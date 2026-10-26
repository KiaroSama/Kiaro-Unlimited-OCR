"""Content-bound page recovery and crash-released exclusive job ownership."""
import hashlib
import json
import os
from pathlib import Path

MODEL_REVISION = '8249d20b2822a7d8a4c22c8d8c9069b5ac36bda3'


def file_hash(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def identity(source: Path, pages: list[int], mode: str, max_length: int) -> dict:
    before = source.stat()
    digest = file_hash(source)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Source changed while computing its recovery identity.')
    key = {'sha256': digest, 'bytes': after.st_size, 'selected_pages': pages,
           'mode': mode, 'max_length': max_length, 'model_revision': MODEL_REVISION,
           'raster_dpi': 200, 'schema': 1}
    if mode == 'persian':
        key['region_schema'] = 1
    return key


def validate_checkpoint(directory: Path, job: dict) -> dict:
    meta = json.loads((directory / 'metadata.json').read_text(encoding='utf-8'))
    if meta.get('job') != job:
        raise ValueError('Saved run does not match this document and settings.')
    completed = meta.get('completed_pages', [])
    if not isinstance(completed, list) or completed != job['selected_pages'][:len(completed)]:
        raise ValueError('Saved completed-page order is invalid.')
    records = {item['page']: item for item in meta.get('pages', [])}
    for number in completed:
        path = directory / f'page-{number:04d}.md'
        if path.is_symlink() or not path.is_file() or not path.stat().st_size:
            raise ValueError(f'Saved page {number} is missing or invalid; existing output preserved.')
        expected = records.get(number, {}).get('sha256')
        if not expected or file_hash(path) != expected:
            raise ValueError(f'Saved page {number} failed integrity verification; existing output preserved.')
    return meta


def find_run(root: Path, job: dict) -> Path | None:
    candidates = []
    for path in (root / 'outputs').glob('ocr_*/metadata.json'):
        if path.parent.is_symlink():
            continue
        try:
            meta = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if meta.get('job') == job and meta.get('status') != 'completed':
            validate_checkpoint(path.parent, job)
            candidates.append(path)
    return max(candidates, key=lambda path: path.stat().st_mtime_ns).parent if candidates else None


class JobLock:
    """OS lock, not a PID sentinel: a crash releases ownership without deleting state."""
    def __init__(self, root: Path, job: dict):
        key = hashlib.sha256(json.dumps(job, sort_keys=True).encode('utf-8')).hexdigest()
        folder = root / 'outputs/.locks'
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / f'{key}.lock'
        self.handle = None

    def __enter__(self):
        self.handle = self.path.open('a+b')
        self.handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.handle.close()
            self.handle = None
            raise RuntimeError('This document and settings are already being processed.') from error
        return self

    def __exit__(self, *args):
        if self.handle:
            try:
                self.handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            finally:
                self.handle.close()
                self.handle = None
