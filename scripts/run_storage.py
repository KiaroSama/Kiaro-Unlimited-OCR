"""Crash-safe page checkpoints and local UI event stream; never operational OCR logs."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from uuid import uuid4


def atomic_text(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def new_run(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S_UTC")
    path = root / "outputs" / f"ocr_{stamp}_{uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


class RunStore:
    def __init__(self, directory: Path, pages: list[int], mode: str):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.started = time.monotonic()
        self.meta = {"status": "loading", "selected_pages": pages, "completed_pages": [],
                     "pages": [], "mode": mode, "current_page": None, "percent": 0}
        self.save()

    def save(self) -> None:
        self.meta["seconds"] = round(time.monotonic() - self.started, 2)
        atomic_text(self.directory / "metadata.json", json.dumps(self.meta, ensure_ascii=False, indent=2))

    def event(self, kind: str, **values) -> None:
        with (self.directory / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": kind, **values}, ensure_ascii=False) + "\n")
            handle.flush()

    def begin(self, page: int) -> None:
        self.meta.update(status="processing", current_page=page)
        self.save()
        self.event("page_start", page=page, completed=len(self.meta["completed_pages"]),
                   total=len(self.meta["selected_pages"]))

    def partial(self, page: int, text: str) -> None:
        atomic_text(self.directory / f"page-{page:04d}.partial.md", text)
        self.event("text", page=page, text=text)

    def complete(self, page: int, raw: str, clean: str, seconds: float) -> None:
        atomic_text(self.directory / f"page-{page:04d}.raw.md", raw)
        atomic_text(self.directory / f"page-{page:04d}.md", clean)
        self.meta["completed_pages"].append(page)
        self.meta["pages"].append({"page": page, "characters": len(clean), "seconds": round(seconds, 2)})
        combined = "\n\n---\n\n".join((self.directory / f"page-{p:04d}.md").read_text(encoding="utf-8")
                                           for p in self.meta["completed_pages"])
        atomic_text(self.directory / "result.md", combined)
        done = len(self.meta["completed_pages"])
        total = len(self.meta["selected_pages"])
        self.meta["percent"] = round(done * 100 / total, 1)
        self.save()
        self.event("page_done", page=page, completed=done, total=total, percent=self.meta["percent"])

    def finish(self, status: str) -> None:
        self.meta["status"] = status
        self.save()
        self.event("finished", status=status, completed=len(self.meta["completed_pages"]),
                   total=len(self.meta["selected_pages"]), percent=self.meta["percent"])
