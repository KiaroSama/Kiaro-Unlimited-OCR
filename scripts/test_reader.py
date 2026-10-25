"""Reader contracts: safe markers, page mapping and stop while paused."""
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


def main():
    from layout_blocks import parse_blocks, split_pages
    raw = '<|ref|>title<|/ref|><|det|>[[100,200,500,600]]<|/det|># Hello'
    boxes = parse_blocks(raw)[0]['boxes']
    assert len(boxes) == 1 and boxes[0]['x'] == .1 and abs(boxes[0]['height']-.4) < 1e-9
    assert split_pages('<PAGE>'+raw+'<PAGE>world', [3, 8])[1]['page'] == 8
    assert split_pages('missing markers', [1, 2]) == []
    from layout_blocks import display_text
    assert display_text('<|det|>title [100,200,500,600]<|/det|>Hello') == '## Hello'
    assert parse_blocks('<|det|>text [100,200,500,600]<|/det|>Hello')[0]['boxes'][0]['x'] == .1
    assert parse_blocks(raw.replace('[[100,200,500,600]]', '__import__("os")'))[0]['boxes'] == []
    from document_processing import chunk_limit
    assert chunk_limit(14, 32768, 8 * 1024**3) > 2
    assert chunk_limit(100, 8192, 8 * 1024**3) == 3
    assert chunk_limit(14, 32768, 200 * 1024**2) == 1
    from generation_control import GenerationControl
    from run_storage import RunStore
    class Model:
        generate = None
    class Tokenizer:
        def decode(self, tokens, **kwargs):
            return 'text'
    (ROOT / '.tmp').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as tmp:
        store = RunStore(Path(tmp), [1], 'base')
        control = GenerationControl(Model(), Tokenizer(), store)
        control.monitor.read = lambda: {}
        control.reset(1)
        (Path(tmp) / 'pause.request').touch()
        thread = threading.Thread(target=control.boundary)
        thread.start()
        deadline = time.monotonic()+3
        while not control.paused and time.monotonic() < deadline:
            time.sleep(.01)
        assert control.paused
        (Path(tmp) / 'cancel.request').touch()
        thread.join(timeout=3)
        assert not thread.is_alive() and control.stop_requested()
    # Exercise real page storage/rasterization; fake only the expensive GPU boundary.
    import contextlib
    import types
    from unittest.mock import patch
    from document_processing import process_chunks
    class OutOfMemoryError(RuntimeError):
        pass
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(mem_get_info=lambda: (8*1024**3, 12*1024**3),
                                   OutOfMemoryError=OutOfMemoryError, empty_cache=lambda: None),
        inference_mode=contextlib.nullcontext)
    class ChunkModel:
        config = types.SimpleNamespace(sliding_window=128)
        def __init__(self, failure):
            self.failure, self.attempts = failure, []
        def infer_multi(self, tokenizer, **kwargs):
            size = len(kwargs['image_files'])
            self.attempts.append(size)
            if size > 1:
                self.config.sliding_window = None
                raise self.failure('Controlled capacity failure')
            assert self.config.sliding_window == 128
            return '<PAGE>verified text', 2
    class Control:
        def boundary(self): return False
        def reset(self, pages): pass
        def stop_requested(self): return False
    from generation_control import TokenLimitError
    for failure in (OutOfMemoryError, TokenLimitError):
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as tmp:
            store = RunStore(Path(tmp), [1, 2, 3], 'base')
            model = ChunkModel(failure)
            with patch.dict(sys.modules, {'torch': fake_torch}):
                process_chunks(ROOT / 'samples/upstream-paper.pdf', None, model, store,
                               Control(), 32768, ROOT, 0)
            assert model.attempts == [3, 1, 1, 1], model.attempts
            assert store.meta['completed_pages'] == [1, 2, 3]
            assert model.config.sliding_window == 128
    print('PASS safe layout/page mapping, adaptive capacity fallback and stop while paused')


if __name__ == '__main__':
    main()
