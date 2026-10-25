"""Fast recovery contracts: identity, preserved pages, settings and exclusive ownership."""
from pathlib import Path
import json
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


def main():
    from recovery import identity, find_run, validate_checkpoint, JobLock
    from run_storage import RunStore
    (ROOT / '.tmp').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as temporary:
        root = Path(temporary)
        source = root / 'سند.pdf'
        source.write_bytes(b'fixture document bytes')
        key = identity(source, [3, 1], 'base', 8192)
        directory = root / 'outputs/ocr_contract'
        store = RunStore(directory, [3, 1], 'base', job=key)
        store.complete(3, '# Heading', '# Heading\n', .1)
        store.partial(1, 'partial')
        store.finish('cancelled')
        before = (directory / 'page-0003.md').read_bytes()
        assert find_run(root, key) == directory
        assert find_run(root, identity(source, [1, 3], 'base', 8192)) is None
        assert find_run(root, identity(source, [3, 1], 'gundam', 8192)) is None
        assert find_run(root, identity(source, [3, 1], 'base', 4096)) is None
        with JobLock(root, key):
            try:
                with JobLock(root, key):
                    raise AssertionError('Concurrent owner accepted')
            except RuntimeError:
                pass
        resumed = RunStore(directory, [3, 1], 'base', job=key, resume=True)
        assert resumed.meta['completed_pages'] == [3]
        assert resumed.meta['percent'] == 50
        assert (directory / 'page-0003.md').read_bytes() == before
        assert (directory / 'page-0001.partial.md').read_text(encoding='utf-8') == 'partial'
        resumed.complete(1, 'last', 'last\n', .1)
        resumed.finish('completed')
        assert (directory / 'result.md').read_text(encoding='utf-8') == '# Heading\n\n\n---\n\nlast\n'
        assert find_run(root, key) is None
        # A desktop-selected directory must not switch to a newly discovered checkpoint.
        resumed.finish('cancelled')
        import ocr
        from unittest.mock import patch
        fresh = root / 'outputs/ocr_explicit'
        image = source.with_suffix('.png')
        image.write_bytes(source.read_bytes())
        with patch.object(ocr, 'ROOT', root), patch.object(ocr, 'configure_paths'), \
                patch.object(ocr, 'validate_input', return_value=image), \
                patch.object(ocr, 'parse_pages', return_value=[3, 1]), \
                patch.object(ocr, 'check_runtime', side_effect=RuntimeError('controlled CUDA failure')), \
                patch.object(sys, 'argv', ['ocr.py', str(image), '--run-dir', str(fresh)]):
            assert ocr.main() == 1
        assert fresh.is_dir(), 'Explicit desktop run directory was ignored'
        assert (directory / 'page-0003.md').read_bytes() == before
        source.write_bytes(b'different content')
        assert identity(source, [3, 1], 'base', 8192) != key
        (directory / 'page-0003.md').write_text('corrupt', encoding='utf-8')
        try:
            validate_checkpoint(directory, key)
        except ValueError:
            pass
        else:
            raise AssertionError('Corrupt checkpoint accepted')
    print('PASS recovery identity/settings/retention/corruption/exclusive-lock contracts')


if __name__ == '__main__':
    main()
