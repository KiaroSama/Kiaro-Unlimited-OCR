"""Token-boundary pause/cancel and bounded live document telemetry."""
import json
import signal
import time

from layout_blocks import split_pages
from run_storage import atomic_text


class TokenLimitError(RuntimeError):
    """Generation exhausted context without completing the document."""


class GenerationControl:
    def __init__(self, model, tokenizer, store):
        self.model, self.tokenizer, self.store = model, tokenizer, store
        self.original = model.generate
        self.cancelled = False
        self.page = 0
        self.region_prefix, self.region = '', None
        self.pages = []
        self.tokens = []
        self.first = True
        self.last_write = 0.0
        self.last_progress = time.monotonic()
        self.old_handler = None
        self.decode_started = None
        self.paused_seconds = 0.0
        self.prior_tokens = 0
        self.prior_decode = 0.0
        self.paused = False
        self.decode_finished = None
        from runtime_metrics import Monitor
        self.monitor = Monitor()

    def stop_requested(self):
        return self.cancelled or (self.store.directory / 'cancel.request').exists()

    def boundary(self):
        pause = self.store.directory / 'pause.request'
        if pause.exists() and not self.stop_requested():
            start = time.monotonic()
            self.paused_at = start
            self.paused = True
            self.flush()
            while pause.exists() and not self.stop_requested():
                time.sleep(0.05)
            self.paused_seconds += time.monotonic() - start
            self.paused = False
            self.flush()
        return self.stop_requested()

    def put(self, value):
        if self.first:
            self.first = False
            return
        if self.decode_started is None:
            self.decode_started = time.monotonic()
        self.tokens.extend(value.reshape(-1).tolist())
        now = time.monotonic()
        if now - self.last_progress >= 15:
            import logging
            logging.getLogger('ocr').info('Generation page=%d tokens=%d', self.page, len(self.tokens))
            self.last_progress = now
        if now - self.last_write >= 0.4:
            self.flush()
            self.last_write = now

    def statistics(self):
        now = self.paused_at if self.paused else (self.decode_finished or time.monotonic())
        seconds = max(0, now - self.decode_started - self.paused_seconds) if self.decode_started else 0
        count = self.prior_tokens + len(self.tokens)
        elapsed = self.prior_decode + seconds
        return {'tokens': count, 'decode_seconds': round(elapsed, 3),
                'tokens_per_second': round(count / elapsed, 1) if elapsed else 0,
                'paused': self.paused, 'phase': 'paused' if self.paused else 'reading'}

    def flush(self):
        if not self.pages:
            return
        raw = self.tokenizer.decode(self.tokens, skip_special_tokens=False) if self.tokens else ''
        if self.region is not None:
            from image_regions import transform_raw
            raw = self.region_prefix + transform_raw(raw, self.region)
        pages = split_pages(raw, self.pages)
        if len(self.pages) == 1:
            self.store.partial(self.page, raw)
        data = {**self.statistics(), 'pages': pages, 'monitor': self.monitor.read()}
        atomic_text(self.store.directory / 'stream.json', json.dumps(data, ensure_ascii=False))

    def end(self):
        self.decode_finished = time.monotonic()
        self.flush()

    def __enter__(self):
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList
        owner = self

        class Stop(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return owner.boundary()

        def generate(*args, **kwargs):
            kwargs['attention_mask'] = torch.ones_like(kwargs['input_ids'])
            kwargs['streamer'] = owner
            criteria = list(kwargs.get('stopping_criteria') or [])
            kwargs['stopping_criteria'] = StoppingCriteriaList(criteria + [Stop()])
            result = owner.original(*args, **kwargs)
            if not owner.stop_requested() and int(result[0, -1]) != owner.tokenizer.eos_token_id:
                raise TokenLimitError('Generation reached its token limit without EOS; partial output preserved, page not complete.')
            return result

        self.model.generate = generate
        self.old_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, lambda *_: setattr(self, 'cancelled', True))
        return self

    def reset(self, page, keep_regions=False):
        if not keep_regions:
            self.region_prefix, self.region = '', None
        stats = self.statistics()
        self.prior_tokens, self.prior_decode = stats['tokens'], stats['decode_seconds']
        self.pages = page if isinstance(page, list) else [page]
        self.page = self.pages[0]
        self.tokens, self.first, self.last_write = [], True, 0.0
        self.decode_started, self.paused_seconds, self.decode_finished = None, 0.0, None
        self.flush()

    def __exit__(self, *_):
        self.model.generate = self.original
        signal.signal(signal.SIGINT, self.old_handler)
        self.monitor.close()
        self.flush()
