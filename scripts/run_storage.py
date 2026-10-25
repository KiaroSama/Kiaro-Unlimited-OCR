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
    # Windows readers/antivirus may briefly hold the destination without delete sharing.
    deadline = time.monotonic() + 2
    while True:
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.02)


def new_run(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S_UTC")
    path = root / "outputs" / f"ocr_{stamp}_{uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


class RunStore:
    def __init__(self, directory: Path, pages: list[int], mode: str, job=None, resume=False):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.started = time.monotonic()
        self.prior_seconds = 0
        if resume:
            from recovery import validate_checkpoint
            self.meta = validate_checkpoint(directory, job)
            self.prior_seconds = self.meta.get('seconds', 0)
            self.meta.update(status='loading', current_page=None, resumed=True)
            (directory / 'cancel.request').unlink(missing_ok=True)
            self.rebuild_result()
        else:
            self.meta = {"status": "loading", "selected_pages": pages, "completed_pages": [],
                         "pages": [], "mode": mode, "current_page": None, "percent": 0}
            if job is not None:
                self.meta['job'] = job
        self.save()

    def rebuild_result(self):
        completed = self.meta['completed_pages']
        combined = '\n\n---\n\n'.join((self.directory / f'page-{p:04d}.md').read_text(encoding='utf-8') for p in completed)
        atomic_text(self.directory / 'result.md', combined)
        self.meta['percent'] = round(len(completed) * 100 / len(self.meta['selected_pages']), 1)

    def save(self) -> None:
        self.meta["seconds"] = round(self.prior_seconds + time.monotonic() - self.started, 2)
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
        from recovery import file_hash
        self.meta["pages"].append({"page": page, "characters": len(clean), "seconds": round(seconds, 2),
                                   "sha256": file_hash(self.directory / f'page-{page:04d}.md')})
        self.rebuild_result()
        done = len(self.meta["completed_pages"])
        total = len(self.meta["selected_pages"])
        self.save()
        self.event("page_done", page=page, completed=done, total=total, percent=self.meta["percent"])

    def finish(self, status: str) -> None:
        self.meta["status"] = status
        self.save()
        self.event("finished", status=status, completed=len(self.meta["completed_pages"]),
                   total=len(self.meta["selected_pages"]), percent=self.meta["percent"])
