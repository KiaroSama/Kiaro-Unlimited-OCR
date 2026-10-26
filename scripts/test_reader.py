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
    from image_regions import raster_scale, reading_regions, transform_raw
    assert raster_scale(2000, 3000) == 1
    assert raster_scale(600, 800) == 200/72
    for dimensions in ((0, 100), (float('inf'), 100), (-1, 100)):
        try:
            raster_scale(*dimensions)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid page dimensions accepted')
    from image_regions import raster_page
    class Page:
        import types
        rect = types.SimpleNamespace(width=600, height=800)
        def get_pixmap(self, **kwargs): return kwargs
    assert raster_page(Page()) == {'dpi': 200, 'alpha': False}
    assert 'matrix' in raster_page(Page(), bounded=True)
    Page.rect.width, Page.rect.height = 2000, 3000
    assert 'matrix' in raster_page(Page())
    from PIL import Image, ImageDraw
    fixture = Image.new('RGB', (400, 600), 'white')
    draw = ImageDraw.Draw(fixture)
    draw.rectangle((20, 30, 180, 570), fill='black')
    draw.rectangle((220, 30, 380, 570), fill='black')
    regions = reading_regions(fixture)
    assert len(regions) == 2 and regions[0][1][0] > .4
    assert regions[-1][1][0] == 0
    # A solid figure has no safe horizontal gap: do not bisect it to hit a size target.
    assert all(region[1] == 0 and region[3] == 1 for _, region in regions)
    fixture = Image.new('RGB', (400, 900), 'white')
    draw = ImageDraw.Draw(fixture)
    for x in (20, 220):
        draw.rectangle((x, 20, x+160, 300), fill='black')
        for y in range(340, 850, 30):
            draw.rectangle((x, y, x+160, y+10), fill='black')
    regions = reading_regions(fixture)
    assert len(regions) > 2
    for column in (regions[0][1][0], 0):
        bounds = [r for _, r in regions if r[0] == column]
        assert bounds[0][1] == 0 and abs(bounds[-1][1]+bounds[-1][3]-1) < 1e-9
        assert all(abs(a[1]+a[3]-b[1]) < 1e-9 for a, b in zip(bounds, bounds[1:]))
        assert bounds[0][3]*900 > 300, 'A photograph was split before its whitespace boundary'
    mapped = parse_blocks(transform_raw(raw, (.5, .25, .5, .5)))[0]['boxes'][0]
    assert mapped['x'] == .55 and mapped['y'] == .35
    plain = transform_raw('untagged region', (.5, 0, .5, 1))
    tagged = transform_raw(raw, (0, 0, .5, 1))
    assert display_text(plain+'\n'+tagged) == 'untagged region\n\n## # Hello'
    assert display_text(tagged+'\n'+plain) == '## # Hello\n\nuntagged region'
    assert parse_blocks(plain)[0]['boxes'] == []
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
        control.region_prefix, control.region = 'saved region\n', (.5, 0, .5, 1)
        control.tokens = [1]
        control.flush()
        assert (Path(tmp) / 'page-0001.partial.md').read_text(encoding='utf-8').startswith('saved region\n')
        control.reset(1)
        assert control.region is None and not control.region_prefix
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
    # Real region extraction and storage; fake only expensive model inference.
    from unittest.mock import patch
    from image_regions import recognize_regions
    import ocr
    with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as tmp:
        root = Path(tmp)
        source = root / 'region.png'
        fixture.save(source)
        before = source.read_bytes()
        store = RunStore(root / 'result', [1], 'persian')
        control = GenerationControl(Model(), Tokenizer(), store)
        control.monitor.read = lambda: {}
        control.reset(1)
        calls = []
        def infer(*args):
            calls.append(args[2])
            assert args[2] != source
            return f'<|ref|>text<|/ref|><|det|>[[100,100,900,900]]<|/det|>region {len(calls)}'
        with patch.object(ocr, 'infer_image', side_effect=infer):
            result = recognize_regions(source, None, None, store.directory / 'page-0001', control, 4096)
        assert len(calls) == len(regions)
        assert result.count('<|ref|>text') == len(regions)
        assert (store.directory / 'page-0001.partial.md').read_text(encoding='utf-8') == result
        assert store.meta['completed_pages'] == [] and source.read_bytes() == before
        control.reset(1)
        calls.clear()
        def cancel(*args):
            value = infer(*args)
            if len(calls) == 2:
                control.cancelled = True
            return value
        with patch.object(ocr, 'infer_image', side_effect=cancel):
            try:
                recognize_regions(source, None, None, store.directory / 'page-0001', control, 4096)
            except InterruptedError:
                pass
            else:
                raise AssertionError('Regional cancellation was ignored')
        assert 'region 1' in (store.directory / 'page-0001.partial.md').read_text(encoding='utf-8')
        assert store.meta['completed_pages'] == []
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
