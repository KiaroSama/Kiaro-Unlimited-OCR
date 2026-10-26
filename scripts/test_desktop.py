"""Bounded native desktop verification; one owner, one CUDA worker, hidden WebView."""
import argparse
import json
import hashlib
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from verify import run


def contracts():
    from document_bridge import inspect_document
    info = inspect_document(ROOT / "samples/upstream-paper.pdf")
    assert info["total"] == 14 and info["image"].startswith("data:image/png;base64,")
    for page in (0, 15):
        try:
            inspect_document(ROOT / "samples/upstream-paper.pdf", page)
        except ValueError:
            pass
        else:
            raise AssertionError("Out-of-range preview accepted")
    print("PASS document bridge", flush=True)


def render(gpu=False):
    import subprocess
    import psutil
    import urllib.request
    from playwright.sync_api import sync_playwright
    executable = ROOT / "desktop/target/release/kiaro-unlimited-ocr.exe"
    env = os.environ.copy()
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--remote-debugging-port=19327 --remote-debugging-address=127.0.0.1"
    env["TEMP"] = env["TMP"] = str(ROOT / ".tmp")
    process = subprocess.Popen([str(executable), "--hidden"], cwd=ROOT / "samples", env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW)
    identity = psutil.Process(process.pid)
    owned = {}
    deadline = time.monotonic() + 75
    try:
        while True:
            for child in identity.children(recursive=True):
                owned[child.pid] = child
            if process.poll() is not None:
                raise RuntimeError(f"Desktop exited before readiness: {process.returncode}")
            try:
                with urllib.request.urlopen("http://127.0.0.1:19327/json/version", timeout=1) as response:
                    json.load(response)
                break
            except Exception:
                if time.monotonic() > deadline:
                    raise TimeoutError("Hidden WebView CDP readiness exceeded 75s")
                time.sleep(.2)
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:19327", timeout=15000)
            page = browser.contexts[0].pages[0]
            page.set_default_timeout(15000)
            page.wait_for_selector("#empty-open")
            text_sizes = page.evaluate("""() => Object.fromEntries(
              ['.empty p','.empty kbd','.language-tags span','.live'].map(selector =>
                [selector, parseFloat(getComputedStyle(document.querySelector(selector)).fontSize)]))""")
            print('Native reader text sizes', text_sizes, flush=True)
            assert text_sizes['.empty p'] >= 14, text_sizes
            assert all(size >= 12 for size in text_sizes.values()), text_sizes
            page.screenshot(path=str(ROOT / 'outputs/desktop-empty.png'))
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            invoke = "async ([name,args]) => await window.__TAURI__.core.invoke(name,args)"
            source = ROOT / "samples/upstream-paper.pdf"
            info = page.evaluate(invoke, ["open_document", {"path": str(source)}])
            assert info["total"] == 14
            page.fill('#filename', str(source))
            page.press('#filename', 'Enter')
            try:
                page.wait_for_selector("#preview:not([hidden])")
            except Exception:
                print("UI diagnostic", page.locator('#status').inner_text(), errors, flush=True)
                page.screenshot(path=str(ROOT / "outputs/desktop-failure.png"))
                raise
            page.fill("#selection", "99")
            page.click("#start")
            page.wait_for_function("() => document.querySelector('#state-pill').textContent==='Attention'")
            assert not page.evaluate(invoke, ["poll_run", {}])["active"]
            page.fill("#selection", "۱،۳-۴")
            page.select_option("#mode", "gundam")
            page.dispatch_event("#next", "click")
            page.wait_for_function("() => document.querySelector('#page').value==='2'")
            page.screenshot(path=str(ROOT / "outputs/desktop-source.png"))
            page.fill('#page', '1')
            page.dispatch_event('#page', 'change')
            page.wait_for_function("() => document.querySelector('#source-caption').textContent.includes('page 1 of')")
            if gpu:
                page.fill('#selection', '1-2')
                page.select_option('#mode', 'base')
                page.check('#turbo')
                page.evaluate("async () => await document.querySelector('#start').onclick(new Event('click'))")
                deadline = time.monotonic() + 480
                cancelled = False
                streamed = False
                pause_checked = False
                heartbeat = time.monotonic()
                while True:
                    snapshot = page.evaluate(invoke, ['poll_run', {}])
                    meta = snapshot['metadata']
                    streamed = streamed or bool(snapshot['text'])
                    if streamed and not pause_checked:
                        page.evaluate(invoke, ['pause_run', {'paused':True}])
                        page.wait_for_function("async () => (await window.__TAURI__.core.invoke('poll_run')).document.metrics.paused", timeout=15000)
                        page.wait_for_function("() => document.querySelector('#pause').textContent==='Resume'")
                        paused = page.evaluate(invoke, ['poll_run', {}])['document']['metrics']
                        assert paused['paused'], paused
                        frozen = paused['tokens']
                        stable = page.evaluate(invoke, ['poll_run', {}])['document']['metrics']
                        assert stable['paused'] and stable['tokens'] == frozen, (paused, stable)
                        page.evaluate(invoke, ['pause_run', {'paused':False}])
                        pause_checked = True
                    if len(meta['completed_pages']) >= 1 and not cancelled:
                        page.screenshot(path=str(ROOT / 'outputs/desktop-live.png'))
                        page.dispatch_event('#cancel', 'click')
                        cancelled = True
                    if not snapshot['active']:
                        assert meta['status'] == 'cancelled' and meta['completed_pages'] == [1], meta
                        assert streamed and meta['percent'] == 50
                        assert len((Path(snapshot['output']) / 'result.md').read_text(encoding='utf-8')) > 300
                        (ROOT / 'outputs/rust-worker-verification.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError('Actual GUI CUDA scenario exceeded 480s')
                    if time.monotonic() - heartbeat > 15:
                        print('GUI GPU heartbeat', meta['status'], len(meta['completed_pages']), flush=True)
                        heartbeat = time.monotonic()
                    page.wait_for_timeout(200)
                page.wait_for_function("() => !document.body.classList.contains('busy')")
                directory = Path(snapshot['output'])
                saved = directory / 'page-0001.md'
                saved_hash = hashlib.sha256(saved.read_bytes()).hexdigest()
                page.fill('#filename', str(source))
                page.press('#filename', 'Enter')
                page.wait_for_function("() => document.querySelector('#status').textContent.includes('Document loaded')")
                page.evaluate("async () => await document.querySelector('#start').onclick(new Event('click'))")
                deadline = time.monotonic() + 480
                while True:
                    snapshot = page.evaluate(invoke, ['poll_run', {}])
                    if not snapshot['active']:
                        assert snapshot['metadata']['status'] == 'completed', snapshot['metadata']
                        assert snapshot['output'] == str(directory)
                        assert snapshot['metadata']['completed_pages'] == [1, 2]
                        assert hashlib.sha256(saved.read_bytes()).hexdigest() == saved_hash
                        assert len((directory / 'page-0002.md').read_text(encoding='utf-8')) > 100
                        break
                    assert time.monotonic() < deadline, 'Resume exceeded 480s'
                    if time.monotonic() - heartbeat > 15:
                        print('Resume GPU heartbeat', snapshot['metadata']['status'], flush=True)
                        heartbeat = time.monotonic()
                    page.wait_for_timeout(200)
                page.wait_for_function("() => !document.body.classList.contains('busy')")
                print('PASS real cancel/reopen/resume, completed page hash unchanged', flush=True)
            fixture = '# عنوان فارسی\n\n**پررنگ** و متن خوانا\n\n| Name | Value |\n|---|---|\n| نمونه | 100 |\n\n- First\n- Second\n\n```python\nprint(1)\n```\n\n<img src="https://invalid.example/image" onerror="window.pwned=1"><script>window.pwned=1</script>[bad](javascript:alert(1))'
            page.evaluate("async text => {const {renderMarkdown}=await import('./markdown.js');const target=document.querySelector('#recognized');renderMarkdown(target,text);target.hidden=false;document.querySelector('#text-empty').hidden=true;}", fixture)
            assert page.locator('#recognized h1').inner_text() == 'عنوان فارسی'
            assert page.locator('#recognized strong').inner_text() == 'پررنگ'
            assert page.locator('#recognized table tbody tr').count() == 1
            assert page.locator('#recognized li').count() == 2
            assert page.locator('.source-page').count() == 14
            assert page.locator('#turbo').count() == 1
            assert page.locator('.topbar').evaluate('(e)=>getComputedStyle(e).backgroundColor') == 'rgb(44, 42, 41)'
            page.mouse.move(0,0)
            assert page.locator('#start').evaluate('(e)=>getComputedStyle(e).backgroundColor') == 'rgb(8, 123, 255)'
            page.locator('#monitor summary').dispatch_event('click')
            assert page.locator('#monitor').evaluate('(e)=>e.open')
            page.wait_for_function("() => document.body.classList.contains('monitor-open')")
            assert page.locator('#mode option[value="persian"]').count() == 1
            geometry = page.evaluate("""() => {
              const main=document.querySelector('main').getBoundingClientRect();
              const monitor=document.querySelector('#monitor').getBoundingClientRect();
              const source=document.querySelector('.source-panel').getBoundingClientRect();
              return {width:innerWidth,mainRight:main.right,monitorLeft:monitor.left,ratio:source.width/main.width};
            }""")
            if geometry['width'] >= 1200:
                assert geometry['mainRight'] <= geometry['monitorLeft']+1, geometry
                assert abs(geometry['ratio']-.41) < .01, geometry
            assert page.locator('#recognized pre code').inner_text().strip() == 'print(1)'
            assert page.locator('#recognized img,#recognized script,#recognized a,#recognized [onerror]').count() == 0
            assert not page.evaluate('window.pwned || false')
            page.screenshot(path=str(ROOT / "outputs/desktop-workspace.png"))
            page.set_viewport_size({"width": 900, "height": 700})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert page.locator('.language-tags span').first.evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)') == 12
            assert page.locator('.live').evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)') == 12
            page.screenshot(path=str(ROOT / "outputs/desktop-compact.png"))
            assert not errors, errors
            page.keyboard.press("Tab")
            assert page.evaluate("document.activeElement.tagName") in ("BUTTON", "INPUT", "SELECT", "ARTICLE")
            browser.close()
        print("PASS actual hidden Rust WebView IPC, preview, validation, resize and render", flush=True)
    finally:
        try:
            for child in identity.children(recursive=True):
                owned[child.pid] = child
        except psutil.NoSuchProcess:
            pass
        for child in reversed(list(owned.values())):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        psutil.wait_procs(list(owned.values()), timeout=10)
        survivors = [p for p in owned.values() if p.is_running()]
        for child in survivors:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(survivors, timeout=5)
        assert not [p.pid for p in survivors if p.is_running()]
        print("Desktop cleanup survivors=0", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--gpu", action="store_true")
    args = parser.parse_args()
    contracts()
    if args.render or args.gpu:
        render(gpu=args.gpu)


if __name__ == "__main__":
    main()
