"""Bounded, hidden practical verification of the installed Windows CUDA launcher."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def run(arguments: list[str], expected: int = 0, wall: int = 480,
        idle: int = 180, stdin_text: str | None = None,
        command_override: list[str] | None = None) -> dict[str, Any]:
    """Own one launcher process and reap its descendants on timeout or interruption."""
    import psutil
    command = ["pwsh", "-NoLogo", "-NoProfile"]
    if stdin_text is None:
        command.append("-NonInteractive")
    command.extend(["-File", str(ROOT / "run.ps1"), *arguments])
    if command_override is not None:
        command = command_override
    started = time.monotonic()
    events: queue.Queue[str | None] = queue.Queue()
    lines: list[str] = []
    env = os.environ.copy()
    temp = ROOT / ".tmp"
    temp.mkdir(exist_ok=True)
    env.update(TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp), PYTHONUTF8="1",
               OMP_NUM_THREADS="4", HOOKMAKER_MAX_TEST_WORKERS="1")
    process = subprocess.Popen(command, cwd=ROOT / "samples",
                               stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="strict", env=env,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    identity = psutil.Process(process.pid)
    print(f"Owned pid={process.pid} created={identity.create_time()} wall={wall}s idle={idle}s", flush=True)

    def consume() -> None:
        try:
            assert process.stdout is not None
            for line in process.stdout:
                events.put(line)
        finally:
            events.put(None)

    reader = threading.Thread(target=consume, daemon=True)
    reader.start()
    if stdin_text is not None:
        assert process.stdin is not None
        try:
            process.stdin.write(stdin_text)
            process.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            process.stdin.close()
    last_output = started
    last_heartbeat = started
    owned: dict[int, Any] = {}
    try:
        while process.poll() is None or reader.is_alive() or not events.empty():
            now = time.monotonic()
            try:
                for child in identity.children(recursive=True):
                    owned[child.pid] = child
            except psutil.NoSuchProcess:
                pass
            try:
                line = events.get(timeout=0.5)
                if line:
                    lines.append(line)
                    last_output = time.monotonic()
                    print(line, end="", flush=True)
            except queue.Empty:
                pass
            if now - started > wall or now - last_output > idle:
                raise TimeoutError("OCR verification exceeded wall/idle ceiling")
            if now - last_heartbeat >= 15:
                print(f"Heartbeat pid={process.pid} elapsed={now-started:.0f}s", flush=True)
                last_heartbeat = now
        code = process.wait(timeout=5)
        if code != expected:
            raise AssertionError(f"Expected exit {expected}, got {code}")
        return {"pid": process.pid, "exit_code": code,
                "seconds": round(time.monotonic() - started, 2), "output": "".join(lines)}
    finally:
        for child in reversed(list(owned.values())):
            try:
                if child.is_running():
                    child.kill()
            except psutil.NoSuchProcess:
                pass
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        psutil.wait_procs(list(owned.values()), timeout=10)
        reader.join(timeout=5)
        if process.stdout:
            process.stdout.close()
        survivors = [child.pid for child in owned.values()
                     if child.is_running() and child.status() != psutil.STATUS_ZOMBIE]
        if survivors:
            raise RuntimeError(f"Owned process cleanup incomplete: {survivors}")
        print(f"Cleanup pid={process.pid} survivors=0", flush=True)


def inspect_result(before: set[Path]) -> dict[str, Any]:
    """Check newly written output against independently known paper text."""
    created = set((ROOT / "outputs").glob("ocr_*")) - before
    assert len(created) == 1, f"Expected one output directory, got {len(created)}"
    output = created.pop()
    text = (output / "result.md").read_text(encoding="utf-8")
    meta = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert "Unlimited" in text and "OCR" in text and len(text) > 300, text[:200]
    assert meta["device"] == "cuda:0" and meta["status"] == "completed"
    assert meta["peak_vram_mib"] > 5000 and len(meta["pages"]) == 1
    return {"directory": str(output), "characters": len(text),
            "peak_vram_mib": meta["peak_vram_mib"], "ocr_seconds": meta["seconds"]}


def main() -> int:
    """Run the focused smoke or final image/PDF/error acceptance batch."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("local_ocr", ROOT / "scripts" / "ocr.py")
    assert spec is not None and spec.loader is not None
    ocr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ocr)
    assert ocr.clean_text("<|det|>title [0,0,1,1]<|/det|>Hello") == "Hello\n"
    assert ocr.clean_text("سلام دنیا") == "سلام دنیا\n"
    source = ROOT / "samples" / "upstream-paper.pdf"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    before = set((ROOT / "outputs").glob("ocr_*"))
    evidence: list[dict[str, Any]] = []
    if args.smoke:
        evidence.append(run(["-InputPath", str(source), "-Pages", "1", "-MaxLength", "4096"]))
        evidence.append(inspect_result(before))
    else:
        evidence.append(run(["-InputPath", str(ROOT / "samples" / "absent.png")], expected=1, wall=60, idle=45))
        evidence.append(run(["-Check"], wall=150, idle=120))
        image = ROOT / "samples" / "upstream page.png"
        evidence.append(run(["-InputPath", str(image), "-MaxLength", "4096"]))
        evidence.append(inspect_result(before))
        before = set((ROOT / "outputs").glob("ocr_*"))
        evidence.append(run(["-InputPath", str(source), "-Pages", "1", "-MaxLength", "4096"]))
        evidence.append(inspect_result(before))
        before = set((ROOT / "outputs").glob("ocr_*"))
        evidence.append(run(["-InputPath", str(image), "-Mode", "gundam", "-MaxLength", "4096"]))
        evidence.append(inspect_result(before))
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest, "Source changed"
    report = ROOT / "outputs" / ("smoke-verification.json" if args.smoke else "verification.json")
    report.parent.mkdir(exist_ok=True)
    # Captured output is public test-fixture diagnostics only, never private OCR input.
    report.write_text(json.dumps({"status": "passed", "evidence": evidence}, indent=2), encoding="utf-8")
    print(f"PASS: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
