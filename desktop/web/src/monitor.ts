import type { Snapshot } from './bridge.js';
const get = (id:string) => document.getElementById(id)!;
const valid = (value:unknown):value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const number = (value:unknown, digits=1) => valid(value) ? value.toFixed(digits) : '—';
let output:string|null = null;
const rows = new Map<string,HTMLElement>();
const lastBlock = new Map<number,number>();

function resource(key:string, value:unknown, suffix:string, percentage:unknown, detail:string) {
  get(`${key}-value`).textContent = `${number(value)}${valid(value)?suffix:''}`;
  get(`${key}-detail`).textContent = detail;
  const meter = get(`${key}-meter`);
  if (valid(percentage)) {
    const bounded = Math.max(0, Math.min(100,percentage));
    meter.style.setProperty('--load',`${bounded}%`);
    meter.setAttribute('aria-valuenow',String(bounded));
    meter.setAttribute('aria-valuetext',`${number(value)}${suffix}`);
  } else {
    meter.style.setProperty('--load','0%');
    meter.removeAttribute('aria-valuenow');
    meter.setAttribute('aria-valuetext','Unavailable');
  }
}

export function updateMonitor(snapshot:Snapshot) {
  const metrics = snapshot.document?.metrics;
  const hardware = metrics?.monitor || {};
  resource('cpu',hardware.cpu,'%',hardware.cpu,`${number(hardware.cpu_mhz,0)} MHz`);
  resource('gpu',hardware.gpu,'%',hardware.gpu,`${number(hardware.gpu_mhz,0)} MHz`);
  const powerPercent = valid(hardware.power) && valid(hardware.power_limit) && hardware.power_limit > 0 ? hardware.power/hardware.power_limit*100 : null;
  resource('power',hardware.power,' W',powerPercent,`/ ${number(hardware.power_limit,0)} W`);
  get('memory-values').textContent = `RAM ${number(hardware.ram_used)} / ${number(hardware.ram_total)} GB   swap ${number(hardware.swap_used)} / ${number(hardware.swap_total)} GB`;
  get('vram-values').textContent = `VRAM ${number(hardware.vram_used,0)} / ${number(hardware.vram_total,0)} MiB`;
  get('monitor-phase').textContent = metrics?.paused ? 'PAUSED' : snapshot.metadata.status.toUpperCase();
  get('monitor-status').textContent = `[unlimited-ocr] ${metrics?.paused?'paused':snapshot.metadata.status} · ${metrics?.tokens || 0} tokens`;
  const target = get('block-events');
  const follow = target.scrollHeight-target.scrollTop-target.clientHeight < 32;
  if (snapshot.output !== output) { output=snapshot.output; rows.clear();lastBlock.clear();target.replaceChildren(); }
  for (const page of snapshot.document?.pages || []) for (const [index,block] of (page.blocks || []).entries()) {
    const key = `${page.page}:${index}`;
    let row = rows.get(key);
    if (!row) {
      if (index <= (lastBlock.get(page.page) ?? -1)) continue;
      row=document.createElement('div');row.className='monitor-event';
      for (const className of ['event-time','event-page','event-kind','event-text','event-rate']) {
        const cell=document.createElement('span');cell.className=className;row.append(cell);
      }
      row.children[0].textContent=`${snapshot.seconds.toFixed(1)}s`;
      row.children[1].textContent=`p${page.page}`;
      row.children[4].textContent=`${number(metrics?.tokens_per_second)} tok/s`;
      rows.set(key,row);lastBlock.set(page.page,index);target.append(row);
    }
    row.children[2].textContent=block.label;
    row.children[3].textContent=block.text.replace(/\s+/g,' ').slice(0,180);
    row.children[3].setAttribute('dir','auto');
    row.title=`${block.label}: ${block.text.slice(0,500)}`;
  }
  while (rows.size>60) { const key=rows.keys().next().value!;rows.get(key)!.remove();rows.delete(key); }
  get('monitor-empty').hidden=rows.size>0;
  if (follow) target.scrollTop=target.scrollHeight;
}
