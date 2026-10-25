"""Bounded multi-page generation with verified page-boundary checkpoints."""
import contextlib
import os
import tempfile
import time
from pathlib import Path

from layout_blocks import split_pages
from run_storage import atomic_text


def process_chunks(source, tokenizer, model, store, control, max_length, root, chunk_size=2):
    import pymupdf
    import torch
    remaining = [n for n in store.meta['selected_pages'] if n not in store.meta['completed_pages']]
    with pymupdf.open(source) as document, tempfile.TemporaryDirectory(dir=root / '.tmp', prefix='multi_') as tmp:
        for offset in range(0, len(remaining), chunk_size):
            if control.boundary():
                raise InterruptedError('Cancelled between page chunks.')
            selected = remaining[offset:offset + chunk_size]
            images = []
            for number in selected:
                page = document[number-1]
                if page.rect.width * page.rect.height * (200/72)**2 > 20000000:
                    raise ValueError('PDF page exceeds 20 million raster pixels at 200 DPI.')
                path = Path(tmp) / f'page-{number}.png'
                page.get_pixmap(dpi=200, alpha=False).save(path)
                images.append(str(path))
            store.begin(selected[0])
            control.reset(selected)
            started = time.monotonic()
            with open(os.devnull, 'w', encoding='utf-8') as sink, contextlib.redirect_stdout(sink), torch.inference_mode():
                raw, _ = model.infer_multi(tokenizer, prompt='<image>Multi page parsing.',
                    image_files=images, output_path=str(Path(tmp) / 'model'), image_size=1024,
                    save_results=False, max_length=max_length, no_repeat_ngram_size=35,
                    ngram_window=1024, temperature=0.0)
            atomic_text(store.directory / 'chunk.partial.md', raw)
            pages = split_pages(raw, selected)
            cancelled = control.stop_requested()
            valid = pages[:-1] if cancelled else pages
            if not cancelled and (raw.count('<PAGE>') != len(selected) or len(pages) != len(selected) or any(not p['text'] for p in pages)):
                raise ValueError('Multi-page output did not contain every selected page; partial output preserved.')
            for page in valid:
                if not page['text']:
                    raise ValueError('Empty multi-page result; existing output preserved.')
                store.complete(page['page'], page['raw'], page['text']+'\n',
                               (time.monotonic()-started)/len(selected))
            if cancelled:
                raise InterruptedError('Cancelled; complete page boundaries retained, last page restarts.')
