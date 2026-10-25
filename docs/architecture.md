# Desktop architecture

Kiaro Unlimited-OCR uses a **Rust/Tauri desktop host**, a small TypeScript/HTML/CSS interface,
and the original model's Python/PyTorch CUDA runtime. The WebView is a desktop rendering surface,
not a hosted website or remote inference service.

## Boundaries

- `desktop/src/main.rs`: narrow desktop commands and window-close lifecycle.
- `desktop/src/workspace.rs`: selected source, one owned worker, validated ranges/modes,
  checkpoint polling, cooperative cancellation and shutdown cleanup.
- `desktop/src/document.rs`: bounded local preview adapter and installation-relative paths.
- `desktop/web/`: presentation, keyboard navigation, sanitized Markdown/RTL rendering and honest progress.
- `scripts/document_bridge.py`: PDF/image metadata and preview, without loading model dependencies.
- `scripts/ocr.py`, `generation_control.py`, `run_storage.py`: original CUDA model
  adapter, streaming checkpoints, atomic saved pages and cancellation.

The renderer cannot choose arbitrary executables or read arbitrary files: commands expose selected
source previews and the current run only. Arguments are passed directly, never interpolated into a
shell. The CSP blocks remote scripts, frames and object content. Model Markdown is parsed with Marked then sanitized with a strict DOMPurify tag allowlist.
Scripts, attributes, remote media and navigable links are removed; no model HTML executes. Runtime files, diagnostics and WebView state remain inside the installation.

## Reader streaming and acceleration

`generation_control.py` owns token-boundary pause/cancel and phase-specific counters. `layout_blocks.py`
parses generated coordinates as data, never eval. `document_processing.py` calls the original
multi-page API in bounded Base-only chunks and commits verified page boundaries. `cuda_fastpath.py`
replaces only runtime single-token MoE dispatch with selected-expert batching; weights stay BF16.

The Rust dashboard joins completed checkpoint text/layout with the active stream. The frontend
lazily loads source previews, draws normalized boxes and renders cumulative sanitized Markdown.
Hardware readings come from bounded local psutil/NVIDIA calls; no document text enters operational
logs. Native main-window drops route through `WindowEvent::DragDrop`.

## Lifecycle

Open document -> validate preview -> choose pages/mode -> create unique run -> start one Python
worker -> poll atomic metadata/current page -> completed/cancelled/failed. The displayed percentage
is completed selected pages / selected pages. Loading is indeterminate. No estimated token speed
or invented remaining time is displayed.

Stop writes `cancel.request`; generation checks it at token boundaries. If stop occurs before the
worker has created its directory, Rust retains the pending request and delivers it when ready.
Closing during work requests cancellation and defers window exit. Loading/prefill can delay this.
Unexpected worker exit preserves checkpoints and is displayed as failed. Hard OS termination cannot
execute final shutdown logic; existing atomic files survive subject to storage/OS guarantees.

Preview rasterization uses the CPU-only PyMuPDF API. Inference requires CUDA; it never silently
falls back to CPU. The original model, limitations and checkpoints are not replaced by the UI.

## Verification

Portable contracts/format/compile checks run in manually dispatched GitHub CI. Actual CUDA and
hidden WebView scenarios are local-only: they need the original 6.7 GB checkpoint, this GPU and
installed model environment. `scripts/test_desktop.py --gpu` drives the actual Rust WebView through
local CDP, runs the original model, stops after one saved page and checks retained results.
Test-only CDP is enabled by the owner process environment, not in normal application startup.

The legacy Qt workspace remains as a source-level rollback during migration; the default launcher
and console workspace action use the Rust executable. Matching unfinished jobs now resume automatically when Start is pressed. Recovery uses content
SHA256, ordered pages, mode, context length and model revision; complete-page hashes are checked.
A job-level OS lock rejects concurrent writers and releases after a crash. Incomplete pages restart,
not token-level KV state. Native Rust file-drop uses the same validation as the Open action.
