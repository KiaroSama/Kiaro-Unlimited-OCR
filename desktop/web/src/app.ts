import { invoke, type DocumentInfo, type Snapshot } from './bridge.js';
import { renderMarkdown } from './markdown.js';
import { updateMonitor } from './monitor.js';
import { loadPages, showPage, updateBoxes } from './source_pages.js';
const element = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const button = (id: string) => element<HTMLButtonElement>(id);
const input = (id: string) => element<HTMLInputElement>(id);
let documentInfo: DocumentInfo | null = null;
let busy = false;
let polling = false;
let currentText = '';
let autoPage = 0;
let previewRequest = 0;
const status = (message: string, error = false) => {
  element('status').textContent = message;
  document.body.classList.toggle('error', error);
  element('state-pill').classList.toggle('error', error);
  if (error) element('state-pill').textContent = 'Attention';
};
const setBusy = (value: boolean) => {
  busy = value;
  document.body.classList.toggle('busy', value);
  for (const id of ['open', 'selection', 'mode', 'filename', 'processing', 'turbo']) (element(id) as HTMLInputElement).disabled = value;
  button('start').disabled = value || !documentInfo;
  button('cancel').disabled = !value;
  element('live').hidden = !value;
};
const displaySource = (value: DocumentInfo) => {
  const changed = documentInfo?.path !== value.path;
  documentInfo = value;
  if (changed) { loadPages(value); displayText(''); }
  else showPage(value.page);
  input('filename').value = value.path;
  input('filename').title = value.path;
  input('page').value = String(value.page);
  input('page').max = String(value.total);
  input('page').disabled = false;
  element('page-total').textContent = `/ ${value.total}`;
  element('source-caption').textContent = `Source page ${value.page} of ${value.total}`;
  button('previous').disabled = value.page <= 1;
  button('next').disabled = value.page >= value.total;
  button('start').disabled = busy;
};
const preview = async (page: number) => {
  if (!documentInfo || !Number.isInteger(page) || page < 1 || page > documentInfo.total) return;
  const request = ++previewRequest;
  if(request === previewRequest) displaySource({...documentInfo,page});
};
const choose = async () => {
  if (busy) return;
  try {
    const value = await invoke<DocumentInfo | null>('choose_document');
    if (value) { displaySource(value); status(`${value.total} source pages · choose pages and start OCR.`); element('state-pill').textContent = 'Ready'; }
  } catch (error) { status(String(error), true); }
};
const displayText = (text: string) => {
  if (currentText === text) return;
  currentText = text;
  const target = element('recognized');
  const follow = target.scrollHeight - target.scrollTop - target.clientHeight < 65;
  renderMarkdown(target, text);
  target.hidden = !text;
  element('text-empty').hidden = !!text;
  element('characters').textContent = `${text.length.toLocaleString()} characters`;
  button('copy').disabled = !text;
  if (follow) target.scrollTop = target.scrollHeight;
};
const update = (value: Snapshot) => {
  setBusy(value.active);
  const meta = value.metadata;
  const count = meta.completed_pages.length;
  const total = meta.selected_pages.length;
  element('done').textContent = `${count}/${total}`;
  element('elapsed').textContent = value.output ? `${value.seconds}s` : '—';
  element('percent').textContent = `${meta.percent}%`;
  const progress = element<HTMLProgressElement>('progress');
  if (value.active && meta.status === 'loading') progress.removeAttribute('value');
  else progress.value = meta.percent;
  element('state-pill').textContent = meta.status.charAt(0).toUpperCase() + meta.status.slice(1);
  if (value.output) {
    status(meta.status === 'loading' ? `${meta.resumed ? 'Resuming saved pages' : 'Loading original CUDA model'} · ${count} pages preserved.` : `${count}/${total} pages saved${meta.current_page ? ` · source page ${meta.current_page}` : ''} · ${meta.status}`, meta.status === 'failed');
    button('results').disabled = false;
    element('text-caption').textContent = meta.current_page ? `Page ${meta.current_page} · ${value.active ? 'live recognition' : meta.status}` : 'Waiting for generation';
  }
  const pages = value.document?.pages || [];
  displayText(pages.length ? pages.map(p => `###### Page ${p.page}\n\n${p.blocks?.length ? p.blocks.map(b=>(b.label==='title'?'## ':b.label==='sub_title'?'### ':'')+b.text).join('\n\n') : p.text}`).join('\n\n---\n\n') : value.text);
  updateBoxes(pages);
  const metrics = value.document?.metrics;
  element('tokens').textContent = String(metrics?.tokens || 0);
  element('rate').textContent = String(metrics?.tokens_per_second || 0);
  button('pause').disabled = !value.active || meta.status === 'loading';
  button('pause').textContent = metrics?.paused ? 'Resume' : 'Pause';
  button('pause').dataset.paused = String(!!metrics?.paused);
  button('restart').disabled = value.active || !documentInfo;
  updateMonitor(value);
  const currentPage = pages.filter(p=>!p.complete).at(-1)?.page || meta.current_page;
  if (currentPage && autoPage !== currentPage) { autoPage = currentPage; void preview(autoPage); }
};
const poll = async () => {
  if (polling) return;
  polling = true;
  try { update(await invoke<Snapshot>('poll_run')); }
  catch (error) { status(String(error), true); }
  finally { polling = false; if (busy) window.setTimeout(() => void poll(), 400); }
};
input('filename').onkeydown = async event => {
  if (event.key !== 'Enter' || busy) return;
  try { displaySource(await invoke<DocumentInfo>('open_document', {path: input('filename').value.trim().replace(/^\"|\"$/g, '')})); status('Document loaded. Choose pages and start OCR.'); }
  catch (error) { status(String(error), true); }
};
if (window.__TAURI__) {
  void window.__TAURI__.event.listen<boolean>('file-hover', event => document.body.classList.toggle('file-hover', event.payload && !busy));
  void window.__TAURI__.event.listen<DocumentInfo>('source-opened', event => {
    if (busy) return;
    displaySource(event.payload); displayText('');
    status(`${event.payload.total} source pages loaded. Matching unfinished work resumes when you start.`);
  });
  void window.__TAURI__.event.listen<string>('source-error', event => status(event.payload, true));
}
element<HTMLDetailsElement>('monitor').ontoggle = () => document.body.classList.toggle('monitor-open', element<HTMLDetailsElement>('monitor').open);
button('open').onclick = choose;
button('empty-open').onclick = choose;
button('previous').onclick = () => void preview(Number(input('page').value) - 1);
button('next').onclick = () => void preview(Number(input('page').value) + 1);
input('page').onchange = () => void preview(Number(input('page').value));
const start = async (fresh = false) => {
  if (busy || !documentInfo) return;
  setBusy(true); autoPage = 0; displayText('');
  status('Checking document identity and saved progress…');
  try {
    update(await invoke<Snapshot>('start_run', {selection: input('selection').value, mode: element<HTMLSelectElement>('mode').value, processing:element<HTMLSelectElement>('processing').value, turbo:input('turbo').checked, fresh}));
    void poll();
  } catch (error) { setBusy(false); status(String(error), true); }
};
button('start').onclick = () => start();
button('restart').onclick = () => start(true);
button('pause').onclick = async () => {
  try { await invoke('pause_run',{paused:button('pause').dataset.paused !== 'true'}); }
  catch(error) { status(String(error),true); }
};
button('cancel').onclick = async () => {
  try { await invoke('cancel_run'); button('cancel').disabled = true; status('Stopping at the next generation boundary · completed and partial text stay saved.'); }
  catch (error) { status(String(error), true); }
};
button('results').onclick = async () => { try { await invoke('open_results'); } catch (error) { status(String(error), true); } };
button('copy').onclick = async () => { try { await navigator.clipboard.writeText(currentText); status('Recognized text copied.'); } catch (error) { status(`Cannot copy: ${error}`, true); } };
document.addEventListener('keydown', event => {
  if (event.ctrlKey && event.key.toLowerCase() === 'o') {event.preventDefault(); void choose();}
  if(['INPUT','SELECT','TEXTAREA'].includes((event.target as HTMLElement).tagName))return;
  if(event.code==='Space' && busy){event.preventDefault();button('pause').click();}
  if(event.key==='Enter' && !busy){event.preventDefault();void start();}
});
