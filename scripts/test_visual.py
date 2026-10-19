"""Bounded real-worker and offscreen native acceptance checks."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def gpu(source: Path, selection: str, mode: str, cancel_after: int):
    import psutil
    output = ROOT / "outputs" / f"ocr_test_{uuid4().hex[:8]}"
    command = [sys.executable, "-I", "-X", "utf8", "-u", str(ROOT / "scripts" / "ocr.py"),
               str(source), "--page-selection", selection, "--mode", mode, "--run-dir", str(output)]
    events = queue.Queue()
    child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, encoding="utf-8", text=True,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    identity = psutil.Process(child.pid)
    owned = {}
    print(f"Owned worker pid={child.pid} created={identity.create_time()}", flush=True)
    def read():
        for line in child.stdout:
            events.put(line)
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    started = last = heartbeat = time.monotonic()
    last_size = 0
    try:
        while child.poll() is None or reader.is_alive() or not events.empty():
            now = time.monotonic()
            try:
                for process in identity.children(recursive=True):
                    owned[process.pid] = process
            except psutil.NoSuchProcess:
                pass
            try:
                line = events.get(timeout=0.3)
                print(line, end="", flush=True)
                last = now
            except queue.Empty:
                pass
            event_file = output / "events.jsonl"
            if event_file.exists():
                size = event_file.stat().st_size
                if size != last_size:
                    last, last_size = now, size
            meta_file = output / "metadata.json"
            if cancel_after and meta_file.exists():
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                if len(meta["completed_pages"]) >= cancel_after:
                    (output / "cancel.request").touch()
            if now - heartbeat > 15:
                print(f"Heartbeat elapsed={now-started:.0f}s event_bytes={last_size}", flush=True)
                heartbeat = now
            if now - started > 1000 or now - last > 240:
                raise TimeoutError("Worker wall/idle ceiling exceeded")
        assert child.wait(timeout=5) == (130 if cancel_after else 0), f"Worker exit {child.returncode}"
        meta = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
        assert meta["device"] == "cuda:0"
        assert meta["status"] == ("cancelled" if cancel_after else "completed")
        assert (output / "result.md").stat().st_size > 0
        print("RESULT", output, "pages", meta["completed_pages"], "peak", meta["peak_vram_mib"], flush=True)
    finally:
        for process in reversed(list(owned.values())):
            try:
                if process.is_running(): process.kill()
            except psutil.NoSuchProcess: pass
        if child.poll() is None: child.kill()
        child.wait(timeout=10)
        psutil.wait_procs(list(owned.values()), timeout=10)
        reader.join(timeout=5)
        child.stdout.close()
        assert not any(process.is_running() for process in owned.values())
        print("Owned worker cleanup: no survivors", flush=True)


def offscreen(real_worker=False):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from gui import Workspace, STYLE, load_system_fonts
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    load_system_fonts(app)
    from PySide6.QtGui import QFontDatabase
    assert QFontDatabase.families(), "Native GUI must have actual renderable fonts"
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = Workspace()
    window.load_source(ROOT / "samples" / "upstream-paper.pdf")
    window.show()
    app.processEvents()
    assert window.page_number.maximum() == 14
    window.ranges.setText("99")
    window.start_run()
    assert "Invalid pages" in window.status.text()
    window.apply_event({"kind":"page_start", "page":2, "completed":0, "total":3})
    window.apply_event({"kind":"text", "text":"آزمایش فارسی و English 123", "page":2})
    window.apply_event({"kind":"page_done", "percent":33.3,"completed":1,"total":3,"page":2})
    assert "فارسی" in window.text.toPlainText() and window.progress.value() == 33
    (ROOT / "outputs").mkdir(exist_ok=True)
    window.grab().save(str(ROOT / "outputs" / "workspace-preview.png"))
    if real_worker:
        from PySide6.QtCore import QProcess
        window.ranges.setText("1-2")
        window.start_run()
        deadline = time.monotonic() + 480
        last_heartbeat = time.monotonic()
        cancelled = False
        try:
            while window.process.state() != QProcess.NotRunning:
                app.processEvents()
                if window.run_dir and (window.run_dir / "metadata.json").exists():
                    meta = json.loads((window.run_dir / "metadata.json").read_text(encoding="utf-8"))
                    if meta["completed_pages"] and not cancelled:
                        window.cancel_run()
                        cancelled = True
                if time.monotonic() - last_heartbeat > 15:
                    print("GUI worker heartbeat", window.status.text(), flush=True)
                    last_heartbeat = time.monotonic()
                if time.monotonic() > deadline:
                    raise TimeoutError("GUI worker deadline")
                time.sleep(0.03)
            app.processEvents()
            window.read_events()
            meta = json.loads((window.run_dir / "metadata.json").read_text(encoding="utf-8"))
            assert cancelled and meta["status"] == "cancelled"
            assert meta["completed_pages"] == [1]
            assert (window.run_dir / "result.md").stat().st_size > 300
            assert window.progress.value() == 50
            print("PASS GUI real CUDA cancellation/checkpoints", window.run_dir, flush=True)
        finally:
            if window.process.state() != QProcess.NotRunning:
                window.process.kill()
                window.process.waitForFinished(10000)
    window.close()
    app.processEvents()
    print("PASS offscreen native preview/ranges/RTL/progress")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--gui-worker", action="store_true")
    parser.add_argument("--selection", default="15,31,32")
    parser.add_argument("--mode", default="gundam")
    parser.add_argument("--cancel-after", type=int, default=0)
    args = parser.parse_args()
    if args.source:
        gpu(args.source, args.selection, args.mode, args.cancel_after)
    else:
        offscreen(args.gui_worker)
