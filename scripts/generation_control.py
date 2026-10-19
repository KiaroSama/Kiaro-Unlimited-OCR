"""Narrow runtime generation adapter: live text, cancellation and valid single-batch mask."""
import signal
import time
from pathlib import Path


class GenerationControl:
    def __init__(self, model, tokenizer, store):
        self.model, self.tokenizer, self.store = model, tokenizer, store
        self.original = model.generate
        self.cancelled = False
        self.page = 0
        self.tokens: list[int] = []
        self.first = True
        self.last_write = 0.0
        self.old_handler = None

    def stop_requested(self) -> bool:
        return self.cancelled or (self.store.directory / "cancel.request").exists()

    def put(self, value) -> None:
        if self.first:
            self.first = False
            return
        self.tokens.extend(value.reshape(-1).tolist())
        now = time.monotonic()
        if now - self.last_write >= 0.4:
            self.flush()
            self.last_write = now

    def flush(self) -> None:
        if self.tokens:
            text = self.tokenizer.decode(self.tokens, skip_special_tokens=False)
            self.store.partial(self.page, text)

    def end(self) -> None:
        self.flush()

    def __enter__(self):
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList
        owner = self

        class Stop(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return owner.stop_requested()

        def generate(*args, **kwargs):
            kwargs["attention_mask"] = torch.ones_like(kwargs["input_ids"])
            kwargs["streamer"] = owner
            criteria = list(kwargs.get("stopping_criteria") or [])
            kwargs["stopping_criteria"] = StoppingCriteriaList(criteria + [Stop()])
            return owner.original(*args, **kwargs)

        self.model.generate = generate
        self.old_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "cancelled", True))
        return self

    def reset(self, page: int) -> None:
        self.page, self.tokens, self.first, self.last_write = page, [], True, 0.0

    def __exit__(self, *_):
        self.model.generate = self.original
        signal.signal(signal.SIGINT, self.old_handler)
        self.flush()
