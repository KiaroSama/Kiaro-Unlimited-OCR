"""Local original-checkpoint Unlimited-OCR inference on NVIDIA CUDA."""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Any
from uuid import uuid4

# -I excludes caller/import paths; only this project's authored module directory is added.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_selection import parse_pages
from run_storage import RunStore, new_run
from generation_control import GenerationControl
from recovery import identity, find_run, JobLock

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "Unlimited-OCR"
REVISION = "8249d20b2822a7d8a4c22c8d8c9069b5ac36bda3"
WEIGHT_SHA256 = "2bc48a7a110061ea58fff65d3169367eebe3aee371ca6968dc2219c1b2855fc6"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def configure_paths() -> None:
    """Keep runtime downloads, caches and temporary files inside this project."""
    paths = {
        "HF_HOME": ROOT / ".cache" / "huggingface",
        "HF_HUB_CACHE": ROOT / ".cache" / "huggingface" / "hub",
        "HF_MODULES_CACHE": ROOT / ".cache" / "huggingface" / "modules",
        "HF_XET_CACHE": ROOT / ".cache" / "huggingface" / "xet",
        "TORCH_HOME": ROOT / ".cache" / "torch",
        "MPLCONFIGDIR": ROOT / ".cache" / "matplotlib",
        "CUDA_CACHE_PATH": ROOT / ".cache" / "cuda",
        "TEMP": ROOT / ".tmp", "TMP": ROOT / ".tmp", "TMPDIR": ROOT / ".tmp",
    }
    for key, path in paths.items():
        path.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(path)
    tempfile.tempdir = str(ROOT / ".tmp")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      HF_HUB_DISABLE_TELEMETRY="1", HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
                      TOKENIZERS_PARALLELISM="false")
    os.environ.setdefault("OMP_NUM_THREADS", "4")


def start_log() -> tuple[logging.Logger, Path | None]:
    """Create a collision-safe UTF-8 UTC log with explicit console fallback."""
    log = logging.getLogger("ocr")
    log.setLevel(logging.INFO)
    formatter = logging.Formatter("[%(asctime)s UTC] [%(levelname)s] [OCR] %(message)s",
                                  datefmt="%Y-%m-%d %H:%M:%S")
    formatter.converter = time.gmtime
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    log.addHandler(console)
    path = None
    try:
        (ROOT / "logs").mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S_UTC")
        path = ROOT / "logs" / f"ocr_{stamp}_{uuid4().hex[:8]}.log"
        handler = logging.FileHandler(path, mode="x", encoding="utf-8")
        handler.setFormatter(formatter)
        log.addHandler(handler)
    except OSError:
        log.warning("File logging unavailable; using console only.")
    return log, path


def clean_text(raw: str) -> str:
    """Remove detection markers as text, never evaluate generated expressions."""
    from layout_blocks import display_text
    return display_text(raw) + '\n'


def validate_input(path: Path) -> Path:
    """Reject absent/unsupported inputs before expensive model loading."""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Input file does not exist: {path}")
    if path.suffix.lower() not in IMAGE_EXTENSIONS | {".pdf"}:
        raise ValueError("Supported input: PDF, PNG, JPEG, WebP, BMP, TIFF.")
    if path.stat().st_size == 0:
        raise ValueError("Input file is empty.")
    if path.suffix.lower() == ".pdf":
        import pymupdf
        with pymupdf.open(str(path)) as document:
            if document.needs_pass or document.page_count == 0:
                raise ValueError("PDF must be unlocked and contain at least one page.")
    else:
        from PIL import Image
        with Image.open(path) as image:
            image.verify()
    return path


def check_runtime() -> dict[str, Any]:
    """Validate actual GPU availability and required local model assets."""
    import torch
    import transformers
    for name in ("model.safetensors", "config.json", "tokenizer.json",
                 "modeling_unlimitedocr.py", "modeling_deepseekv2.py",
                 "configuration_deepseek_v2.py", "conversation.py", "deepencoder.py"):
        if not (MODEL / name).is_file():
            raise RuntimeError(f"Missing local model file: {name}")
    if (MODEL / "model.safetensors").stat().st_size != 6672547120:
        raise RuntimeError("Model weight size differs from the original checkpoint.")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU unavailable. Check CUDA-enabled PyTorch and NVIDIA driver; CPU fallback is disabled.")
    if not torch.cuda.is_bf16_supported():
        raise RuntimeError("CUDA device does not support required BF16 inference.")
    torch.set_num_threads(4)
    free, total = torch.cuda.mem_get_info()
    return {"device": "cuda:0", "gpu": torch.cuda.get_device_name(0),
            "cuda_runtime": torch.version.cuda, "torch": torch.__version__,
            "transformers": transformers.__version__, "free_vram_mib": free // 1048576,
            "total_vram_mib": total // 1048576, "model_revision": REVISION,
            "weight_sha256": WEIGHT_SHA256}


def load_model(log: logging.Logger) -> tuple[Any, Any]:
    """Load the original local BF16 checkpoint without CPU offloading."""
    import torch
    from transformers import AutoModel, AutoTokenizer
    log.info("Loading original checkpoint in BF16 on CUDA.")
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL), trust_remote_code=True,
                                             local_files_only=True)
    model = AutoModel.from_pretrained(str(MODEL), trust_remote_code=True,
                                     use_safetensors=True, dtype=torch.bfloat16,
                                     local_files_only=True).eval().cuda()
    if next(model.parameters()).device.type != "cuda":
        raise RuntimeError("Model was not placed on CUDA.")
    # The checkpoint sets max_new_tokens=32768, which otherwise overrides our total limit.
    model.generation_config.max_new_tokens = None
    model.generation_config.pad_token_id = tokenizer.eos_token_id
    log.info("Model ready on CUDA.")
    return tokenizer, model


def infer_image(tokenizer: Any, model: Any, image: Path, output: Path,
                mode: str, max_length: int) -> str:
    """Use returned text, bypassing upstream visualization eval calls."""
    import torch
    with open(os.devnull, "w", encoding="utf-8") as sink:
        with contextlib.redirect_stdout(sink), torch.inference_mode():
            raw = model.infer(tokenizer, prompt="<image>document parsing.",
                              image_file=str(image), output_path=str(output),
                              base_size=1024, image_size=640 if mode == "gundam" else 1024,
                              crop_mode=mode == "gundam", eval_mode=True, save_results=False,
                              max_length=max_length, no_repeat_ngram_size=35,
                              ngram_window=128, temperature=0.0)
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError("Model returned empty or invalid OCR text.")
    return raw


def process_file(source: Path, tokenizer: Any, model: Any, mode: str,
                 pages: int, max_length: int, log: logging.Logger, store: RunStore) -> Path:
    """Process raster input or PDF pages serially into a new local directory."""
    import torch
    from PIL import Image
    output = store.directory
    store.meta.update(check_runtime())
    torch.cuda.reset_peak_memory_stats()
    control = GenerationControl(model, tokenizer, store)

    def run_page(image: Path, number: int, selected_mode: str) -> None:
        page_dir = output / f"page-{number:04d}"
        log.info("Processing page=%d mode=%s", number, selected_mode)
        page_start = time.monotonic()
        store.begin(number)
        control.reset(number)
        raw = infer_image(tokenizer, model, image, page_dir, selected_mode, max_length)
        if control.stop_requested():
            store.partial(number, raw)
            raise InterruptedError("Cancelled; completed and partial pages are saved.")
        text = clean_text(raw)
        store.complete(number, raw, text, time.monotonic() - page_start)
        log.info("Page complete page=%d characters=%d progress=%s%% completed=%d/%d", number,
                 len(text), store.meta["percent"], len(store.meta["completed_pages"]),
                 len(store.meta["selected_pages"]))
        print(f"Progress: {store.meta['percent']}% | {len(store.meta['completed_pages'])}/{len(store.meta['selected_pages'])} pages saved", flush=True)

    try:
        with control:
            if store.meta.get('processing') == 'multi':
                from document_processing import process_chunks
                process_chunks(source, tokenizer, model, store, control, max_length, ROOT,
                               store.meta.get('chunk_size', 2))
            elif source.suffix.lower() == ".pdf":
                import pymupdf
                with pymupdf.open(str(source)) as document:
                    store.meta["source_pages"] = document.page_count
                    with tempfile.TemporaryDirectory(prefix="pdf_", dir=ROOT / ".tmp") as tmp:
                        for number in store.meta["selected_pages"]:
                            if number in store.meta['completed_pages']:
                                continue
                            if control.stop_requested():
                                raise InterruptedError("Cancelled between pages.")
                            page = document[number - 1]
                            if page.rect.width * page.rect.height * (200 / 72) ** 2 > 20000000:
                                raise ValueError("PDF page exceeds 20 million raster pixels at 200 DPI.")
                            image = Path(tmp) / "page.png"
                            pixmap = page.get_pixmap(dpi=200, alpha=False)
                            pixmap.save(str(image))
                            del pixmap
                            run_page(image, number, mode)
            elif 1 not in store.meta['completed_pages']:
                run_page(source, 1, mode)
        store.finish("completed")
        return output
    except (KeyboardInterrupt, InterruptedError):
        store.finish("cancelled")
        raise
    except Exception:
        store.finish("failed")
        raise
    finally:
        store.meta["peak_vram_mib"] = round(torch.cuda.max_memory_allocated() / 1048576, 1)
        store.save()
        log.info("Run status=%s seconds=%s peak_vram_mib=%s output=%s", store.meta["status"],
                 store.meta["seconds"], store.meta["peak_vram_mib"], output)


def main() -> int:
    """Validate arguments, run offline CUDA OCR and propagate failures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, help="Local image or PDF path")
    parser.add_argument("--mode", choices=("base", "gundam"), default="base")
    parser.add_argument("--pages", type=int, default=0, help="PDF page limit; 0 means all")
    parser.add_argument("--max-length", type=int, default=None, help="Total context tokens: default 8192, automatic multi-page 32768")
    parser.add_argument("--check", action="store_true", help="Check local model and CUDA without loading weights")
    parser.add_argument("--page-selection", default="", help="PDF pages, e.g. 1,3,10-20; empty means all")
    parser.add_argument("--run-dir", type=Path, help="New project-local output directory for UI worker")
    parser.add_argument('--resume-dir', type=Path, help='Existing matching job inside project outputs')
    parser.add_argument('--processing', choices=('pagewise', 'multi'), default='pagewise')
    parser.add_argument('--chunk-size', type=int, default=0, choices=range(33), help='Multi-page ceiling: 0 selects context/VRAM-aware groups')
    parser.add_argument('--turbo', action='store_true', help='Runtime CUDA batching without changing model weights')
    parser.add_argument('--fresh', action='store_true', help='Start a new run without replacing saved output')
    args = parser.parse_args()
    if args.max_length is None:
        args.max_length = 32768 if args.processing == 'multi' and args.chunk_size == 0 else 8192
    if args.processing == 'pagewise':
        args.chunk_size = 2
    if args.pages < 0 or not 1024 <= args.max_length <= 32768:
        parser.error("--pages must be >= 0; --max-length must be 1024..32768")
    if not args.input and not args.check:
        parser.print_help()
        return 0
    configure_paths()
    log, log_path = start_log()
    log.info("Startup python=%s log=%s", sys.version.split()[0], log_path)
    store = None
    ownership = None
    try:
        source = validate_input(args.input) if args.input else None
        if args.check:
            info = check_runtime()
            print(json.dumps(info, ensure_ascii=False, indent=2))
            return 0
        assert source is not None
        total = 1
        if source.suffix.lower() == ".pdf":
            import pymupdf
            with pymupdf.open(source) as document:
                total = len(document)
        selected = parse_pages(args.page_selection, total)
        if args.pages:
            selected = selected[:args.pages]
        if args.processing == 'multi' and (args.mode != 'base' or source.suffix.lower() != '.pdf'):
            raise ValueError('Multi-page processing requires a PDF in Base mode.')
        job = identity(source, selected, args.mode, args.max_length)
        if args.processing != 'pagewise' or args.turbo:
            job.update(processing=args.processing, chunk_size=args.chunk_size if args.processing == 'multi' else 2, turbo=args.turbo)
        ownership = JobLock(ROOT, job)
        ownership.__enter__()
        resume = args.resume_dir.resolve() if args.resume_dir and not args.fresh else (None if args.run_dir or args.fresh else find_run(ROOT, job))
        if resume:
            if not resume.is_relative_to((ROOT / 'outputs').resolve()) or not resume.is_dir():
                raise ValueError('Resume directory must be an existing job inside project outputs.')
            output = resume
        elif args.run_dir:
            output = args.run_dir.resolve()
            if not output.is_relative_to(ROOT / "outputs") or output.exists():
                raise ValueError("--run-dir must be a new directory inside project outputs.")
            output.mkdir(parents=True)
        else:
            output = new_run(ROOT)
        store = RunStore(output, selected, args.mode, job=job, resume=bool(resume))
        log.info('Recovery resumed=%s completed=%d', bool(resume), len(store.meta['completed_pages']))
        print(f"Output: {output}", flush=True)
        info = check_runtime()
        log.info("Device=%s gpu=%s CUDA=%s", info['device'], info['gpu'], info['cuda_runtime'])
        load_started = time.monotonic()
        tokenizer, model = load_model(log)
        store.meta['load_seconds'] = round(time.monotonic() - load_started, 3)
        if args.turbo:
            from cuda_fastpath import enable_turbo
            log.info('Turbo CUDA batching enabled layers=%d', enable_turbo(model))
        store.meta.update(processing=args.processing, chunk_size=args.chunk_size, turbo=args.turbo)
        store.save()
        if (output / "cancel.request").exists():
            raise InterruptedError("Cancelled during model loading.")
        output = process_file(source, tokenizer, model, args.mode, args.pages, args.max_length, log, store)
        print(f"Output: {output}")
        return 0
    except (KeyboardInterrupt, InterruptedError):
        if store:
            store.finish("cancelled")
        log.warning("Cancelled; saved pages and partial text are preserved.")
        return 130
    except Exception as error:
        if store and store.meta["status"] not in ("failed", "cancelled"):
            store.finish("failed")
        log.exception("OCR failed (%s). Existing outputs are preserved.", type(error).__name__)
        return 1
    finally:
        if ownership:
            ownership.__exit__(None, None, None)
        log.info("Shutdown")
        for handler in list(log.handlers):
            handler.close()
            log.removeHandler(handler)


if __name__ == "__main__":
    raise SystemExit(main())
