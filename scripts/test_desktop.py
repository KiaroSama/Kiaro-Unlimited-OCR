"""Bounded native desktop verification; one owner, one CUDA worker, hidden WebView."""
import argparse
import json
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
            if gpu:
                page.fill('#selection', '1-2')
                page.select_option('#mode', 'base')
                page.dispatch_event('#start', 'click')
                deadline = time.monotonic() + 480
                cancelled = False
                streamed = False
                heartbeat = time.monotonic()
                while True:
                    snapshot = page.evaluate(invoke, ['poll_run', {}])
                    meta = snapshot['metadata']
                    streamed = streamed or bool(snapshot['text'])
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
            page.screenshot(path=str(ROOT / "outputs/desktop-workspace.png"))
            page.set_viewport_size({"width": 900, "height": 700})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(ROOT / "outputs/desktop-compact.png"))
            assert not errors, errors
            page.keyboard.press("Tab")
            assert page.evaluate("document.activeElement.tagName") in ("BUTTON", "INPUT", "SELECT", "PRE")
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
