"""Bounded multi-page generation with verified page-boundary checkpoints."""
import contextlib
import gc
import logging
import os
import tempfile
import time
from pathlib import Path

from generation_control import TokenLimitError
from layout_blocks import split_pages
from run_storage import atomic_text


def chunk_limit(remaining, max_length, free_bytes):
    """Conservative estimate; actual capacity failures still split the group."""
    limit = min(remaining, max(1, (max_length - 64) // (273 + 2048)), 32)
    budget = max(0, free_bytes - 512 * 1024**2)
    while limit > 1:
        prefix = 273 * limit + 64
        # Eager BF16 attention also materializes FP32 softmax; leave vision headroom.
        estimate = 10 * prefix**2 * 8 + limit * 128 * 1024**2
        if estimate <= budget:
            break
        limit -= 1
    return max(1, limit)


def process_chunks(source, tokenizer, model, store, control, max_length, root, chunk_size=2):
    import pymupdf
    import torch
    log = logging.getLogger('ocr')
    remaining = [n for n in store.meta['selected_pages'] if n not in store.meta['completed_pages']]
    offset, ceiling = 0, chunk_size or 32
    with pymupdf.open(source) as document, tempfile.TemporaryDirectory(dir=root / '.tmp', prefix='multi_') as tmp:
        while offset < len(remaining):
            if control.boundary():
                raise InterruptedError('Cancelled between page chunks.')
            free, _ = torch.cuda.mem_get_info()
            count = min(ceiling, chunk_limit(len(remaining)-offset, max_length, free))
            selected = remaining[offset:offset + count]
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
            log.info('Multi-page chunk pages=%d first=%d context=%d', count, selected[0], max_length)
            retry = False
            sliding_window = getattr(model.config, 'sliding_window', None)
            try:
                with open(os.devnull, 'w', encoding='utf-8') as sink, contextlib.redirect_stdout(sink), torch.inference_mode():
                    raw, _ = model.infer_multi(tokenizer, prompt='<image>Multi page parsing.',
                        image_files=images, output_path=str(Path(tmp) / 'model'), image_size=1024,
                        save_results=False, max_length=max_length, no_repeat_ngram_size=35,
                        ngram_window=1024, temperature=0.0)
            except (torch.cuda.OutOfMemoryError, TokenLimitError) as error:
                if count == 1:
                    raise
                log.warning('Chunk capacity exceeded type=%s pages=%d; retrying smaller group', type(error).__name__, count)
                ceiling = max(1, count // 2)
                retry = True
            finally:
                # Upstream restores this only after successful generate, not on failure.
                model.config.sliding_window = sliding_window
            if retry:
                gc.collect()
                torch.cuda.empty_cache()
                continue
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
            offset += count
