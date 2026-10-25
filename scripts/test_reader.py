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
    print('PASS safe layout/page mapping and stop while paused')


if __name__ == '__main__':
    main()
