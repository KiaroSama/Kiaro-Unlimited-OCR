# Kiaro Unlimited-OCR

<div align="center">

[![Source checks](https://github.com/KiaroSama/Kiaro-Unlimited-OCR/actions/workflows/ci.yml/badge.svg?branch=main&event=workflow_dispatch)](https://github.com/KiaroSama/Kiaro-Unlimited-OCR/actions/workflows/ci.yml)
[![License GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue)](LICENSE)
[![Rust](https://img.shields.io/badge/Desktop-Rust-dea584)](desktop/Cargo.toml)
[![Windows 11](https://img.shields.io/badge/Windows-11-0078D4)](#requirements)
[![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB)](#requirements)
[![PowerShell](https://img.shields.io/badge/PowerShell-7-5391FE)](#run)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.14.1-EE4C2C)](#installed-stack)
[![CUDA runtime](https://img.shields.io/badge/CUDA-13.2-76B900)](#installed-stack)
[![Transformers](https://img.shields.io/badge/Transformers-4.57.6-FFD21E)](#installed-stack)
[![Original weights](https://img.shields.io/badge/Weights-original_BF16-blue)](#model)
[![Safetensors](https://img.shields.io/badge/Format-safetensors-blue)](#model)
[![GPU](https://img.shields.io/badge/GPU-RTX_4070_Ti-76B900)](#requirements)
[![Image input](https://img.shields.io/badge/Input-images-blue)](#run)
[![PDF input](https://img.shields.io/badge/Input-PDF-blue)](#run)
[![Local inference](https://img.shields.io/badge/Inference-local-blue)](#privacy-and-limits)
[![Support donations](https://img.shields.io/badge/Support-donations-d04a9a)](#donate)

</div>

Local installation of [Baidu Unlimited-OCR](https://huggingface.co/baidu/Unlimited-OCR).
Uses the requested **original `model.safetensors`**, not GGUF, quantization or another model.
A Rust/Tauri desktop workspace with a TypeScript interface and the original Python/PyTorch CUDA
worker. It is not the upstream SGLang server. All inference remains local.

## Install and build

Prerequisites: Windows x64, NVIDIA GPU/driver with BF16 support and sufficient VRAM, Python3.13,
PowerShell7, Node24, Rust stable MSVC with Microsoft C++ build tools, and WebView2 Runtime.
The tested RTX4070Ti12GB used about6.8–7.1GiB allocated VRAM; this is not a guarantee for every page.

1. Clone this repository and install the Python dependencies described below.
2. Download the pinned original model into `models/Unlimited-OCR` (keep all configuration/custom
   Python/tokenizer files, exclude duplicate weight shard/index):

```powershell
hf download baidu/Unlimited-OCR --revision 8249d20b2822a7d8a4c22c8d8c9069b5ac36bda3 --local-dir models/Unlimited-OCR --exclude model-00001-of-000001.safetensors --exclude model.safetensors.index.json
```

3. Build the Rust desktop. First-time creation of a local, non-publicly-trusted signing identity is
   an explicit action; it does not install a trusted root or export the private key:

```powershell
pwsh -NoProfile -File scripts/build-desktop.ps1 -CreateSigningIdentity
```

Later builds omit `-CreateSigningIdentity`. Cargo/npm retrieve dependencies during build; OCR itself
runs offline. The executable remains under `desktop/target/release` and must stay within this
installation. `run.ps1` does not build, install software or generate certificates automatically.
Self-signed Authenticode identifies the signer and protects integrity, but Windows warnings remain;
this is not a publicly trusted release or an installer. Do not install an unknown certificate as a
trusted root merely to suppress warnings.

[Architecture](docs/architecture.md) · [Persian quality limits](docs/persian-quality.md) ·
[Third-party notices](THIRD_PARTY_NOTICES.md)

## Reader controls (0.3)

The compact reader keeps a continuous source-page stack and cumulative Markdown output. Actual
layout boxes are green, with the latest streamed block blue. Preview images load on demand; only
a small image cache is retained. Page ranges, Base/Gundam and Stop/save remain available.

- **Pause / Resume** holds the current generation in GPU memory; Space toggles it outside inputs.
  Stop also cancels a paused run. Closing/restarting the app resumes by page checkpoint, not token.
- **Restart** explicitly starts a fresh output directory; **Start** may resume matching saved work.
- **Reading** selects page-by-page recovery or Base-only PDF automatic groups. Group size uses
  available VRAM and the total context budget, rather than a fixed two-page cap. Capacity failures
  split a group and retry; an impossible single page fails explicitly. Malformed page markers are
  rejected. Previously committed pages survive cancellation/OOM; this is not unlimited one-shot context.
  Automatic multi-page uses32768total tokens; pagewise keeps8192. Changed settings create a new job;
  older explicit two-page jobs can resume through the Python CLI with `--chunk-size 2 --max-length 8192`.
- **Turbo** batches selected MoE expert operations on CUDA at runtime. Original BF16 weights and
  downloaded model source remain unchanged; this is not quantization or a different checkpoint.
- The collapsible terminal-style monitor shows labeled CPU/GPU/power bars, available clocks and
  RAM/VRAM/swap readings from this Windows system. Hardware samples refresh asynchronously every2s;
  missing sensors display a dash, never a fabricated value. Power bars use the reported device limit.
  Its60-row processing stream separates observed elapsed time, page, block type, excerpt and token
  rate. It follows the bottom only while you are already there; hover reveals a longer excerpt.
  Times/rates describe UI observation, not exact block-completion timestamps. Token throughput
  measures active decode, not model loading or paused time. No Apple-specific core readings are invented.

The reference recording uses a warmed Apple MLX/Core ML implementation, not this Windows BF16
runtime. A short warmed32token comparison measured4.91s baseline versus3.85s Turbo with identical
text; it is not a full-document speed guarantee. A real2page Turbo chunk completed at11.1tokens/s
with6938.7MiB peak allocation. The full public page retained the baseline recognized text;
a few layout coordinates differed by1–2/1000 under BF16 batching. Model load is reported
separately; no263tokens/s claim is made. Automatic grouping was additionally verified on three
actual pages in one CUDA generation:2149tokens,171.8s active decode (12.5tokens/s),7155.7MiB peak.
GPU-indexed packed experts and an incremental repetition-cache candidate were measured and rejected
because they were slower; neither experimental path is shipped.

## Run

**Open `run.ps1` directly** to launch the native graphical workspace. The extra shortcut is
not required. No Windows file association or execution policy is changed.

The visual workspace has source preview/page navigation, local file picker, page selection,
Base/Gundam mode, rendered Markdown/RTL, completed-page progress and Cancel/keep results.
Drop one local PDF/image into the window to load it; multiple files and directories are rejected.
Headings, emphasis, lists, tables and code render in the right pane. Scripts, remote images and
navigable links are removed; Copy retains the original Markdown.
Model loading is shown as busy rather than a fabricated percentage. The percentage is completed
selected pages / total selected pages, not an estimate of remaining tokens in the current page.

For the coloured terminal menu:

```powershell
pwsh -NoProfile -File .\run.ps1 -Console
```

Menu **Enter defaults to 1** (OCR); **2** sample; **3** CUDA check; **4** visual workspace;
**0** exits. Option1 asks for PDF pages and mode before loading the GPU model. Empty path goes
back; EOF exits. Explicit `-InputPath`/`-Check` calls stay noninteractive and preserve exit codes.

From this folder, inspect the installation without loading the weights:

```powershell
pwsh -NoProfile -File .\run.ps1 -Check
```

OCR a local image:

```powershell
pwsh -NoProfile -File .\run.ps1 -InputPath "D:\Documents\scan.png"
```

OCR a PDF (all pages, serially):

```powershell
pwsh -NoProfile -File .\run.ps1 -InputPath "D:\Documents\document.pdf"
```

Try the included real upstream paper, first page only:

```powershell
pwsh -NoProfile -File .\run.ps1 -InputPath ".\samples\upstream-paper.pdf" -Pages 1
```

For small text in images, use `-Mode gundam`. Default `base` uses less GPU memory.
For two-column Persian scans, choose **Persian · precise RTL** or `-Mode persian`.
It reads the right column first in whitespace-bounded regions using the same original model,
then maps layout boxes back to the source page. It does not guess spelling or medical numbers.
Use page-by-page reading; multi-page groups remain Base-only. A page is saved as complete only
when every region finishes; stopping retains the current partial page.
Precise-mode rasterization targets200DPI, capped at3000pixels on the longest edge and12million
pixels. Base/Gundam retain their200DPI input for previously accepted pages; oversized page dimensions
use the bounded fallback instead of failing. This changes image preparation, not the original PDF.
Use `-PageSelection "1,3,10-20"` for inclusive ranges, comma lists and ordered deduplication.
Persian/Arabic digits and Persian commas are accepted; empty selection means all pages.
`-Pages N` additionally caps the selected list; zero means no cap. Original source page numbers
are preserved in output filenames. `-MaxLength 8192` is the default **total context limit**,
including image/prompt tokens; accepted range1024–32768. Low limits can truncate output.
Run without arguments to open the visual workspace; `-Console` selects the terminal wizard.

Input paths resolve from your current directory. The launcher and runtime paths resolve from
this installation, so you can also invoke `run.ps1` by its full path from another directory.

## Outputs and logs

Each run creates a unique directory in `outputs/`:

- `result.md`: combined recognized text, detection tags removed without executing them.
- `page-0001.md`: cleaned page text; corresponding `.raw.md` preserves original model output.
- `metadata.json`: actual device, versions, timing, peak allocated VRAM, pages and status.

Inputs are never modified. Reopening the same content with the same ordered page selection, mode,
context length and model revision automatically resumes a matching unfinished run when Start is
pressed. Completed page hashes are verified and those pages are not regenerated. The unfinished
page starts again from its beginning, not its last token. Changed content/settings create a separate
run; corrupt checkpoints fail explicitly without overwriting them. Old jobs without a stored source
identity cannot be automatically matched. Concurrent writers to the same job are rejected by an
OS-backed lock that releases on crash. Each completed page, combined result and metadata checkpoint
is atomically replaced inside the current run; verified completed pages are preserved on resume. Streaming
current text is saved as `page-NNNN.partial.md` and is never counted as completed.
Cancel in the GUI or Ctrl+C in the console requests a stop at the next token boundary; model
loading/prefill can take longer to respond. Completed pages and current partial text remain saved,
with `status: cancelled`. A hard process kill cannot run shutdown code: the latest atomic checkpoint
remains, but metadata may still say loading/processing. Power-loss/storage failure is not guaranteed.
A failed multi-page run retains completed pages and reports `status: failed`. Markdown can contain untrusted model-generated
links/HTML; inspect it before rendering in a permissive viewer. Bounding-box visualization and
embedded-image extraction are intentionally not enabled.

UTF-8 logs live in `logs/`, named `ocr_YYYY-MM-DD_HH-MM-SS_UTC_<unique>.log`.
Console sessions use the same per-run structured diagnostic logger. Rust desktop logs use
`desktop_YYYY-MM-DD_HH-MM-SS_UTC_<pid>.log` and `[timestamp] [INFO] [DESKTOP] Message`;
worker diagnostic capture is stored separately. Build/sign operations create `build-desktop_*.log`. Old `run_*.log`
files belong to the previous launcher revision and are preserved. Recognized text is stored only
in result/partial files and private `events.jsonl` UI state, not operational logs.
Entries use `[YYYY-MM-DD HH:mm:ss UTC] [LEVEL] [OCR] Message`. INFO records startup, model/device,
page completion, output and shutdown; WARNING/ERROR and tracebacks diagnose failures. No OCR
text, credentials or full request/response payloads are logged. Input/output paths can appear in
local diagnostics. Logging-init failure falls back to console. No debug/verbose switch or automatic
retention/deletion is enabled; review and remove old logs yourself. For support, share only the
relevant log after removing private filenames/paths.

## Requirements

Windows x64, PowerShell (7 recommended), the existing shared Python3.13 installation and
NVIDIA driver are required. This installation targets the detected RTX4070Ti12GB; CPU fallback
is **disabled**. Existing CUDA12.9/13.4 toolkits remain installed and unchanged. Prebuilt PyTorch
ships its own CUDA13.2 runtime and uses the installed NVIDIA driver; it does not need a separate
13.2 toolkit or a compiler/Flash-Attention build.

## Installed stack

| Scope | Components |
| --- | --- |
| Shared Python3.13 | torch2.14.1+cu132, torchvision0.29.1+cu132, Pillow13.0.0 |
| Shared general dependencies | matplotlib3.11.2, einops0.8.2, addict2.4.0, easydict1.13, PyMuPDF2.0, psutil7.2.2, accelerate1.15.0 |
| Project environment | Transformers4.57.6, huggingface-hub0.36.2, tokenizers0.22.2 |

The local environment inherits compatible shared packages. Transformers5.x removed an import
required by the original model, so only its model-specific compatibility stack is local; the
shared Transformers5.x installation is not downgraded. Keep the shared Python installation in
place. `requirements-model.txt` records the three local overrides.

For recovery, with an existing CUDA-enabled shared Python3.13 and `uv`:

```powershell
uv venv --python 3.13 --system-site-packages .venv
uv pip install --python .venv\Scripts\python.exe -r requirements-model.txt
```

General dependencies must also exist in that shared interpreter:

```powershell
py -3.13 -m pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cu132
py -3.13 -m pip install Pillow==13.0.0 matplotlib==3.11.2 einops==0.8.2 addict==2.4.0 easydict==1.13 PyMuPDF==2.0 psutil==7.2.2 accelerate==1.15.0
```

Do not run a plain CPU-only PyTorch install over this setup. Runtime OCR never installs packages or downloads another model.

## Model

`models/Unlimited-OCR/model.safetensors`: **6,672,547,120 bytes**, original BF16 checkpoint.

- Upstream revision: `8249d20b2822a7d8a4c22c8d8c9069b5ac36bda3`.
- SHA256: `2bc48a7a110061ea58fff65d3169367eebe3aee371ca6968dc2219c1b2855fc6`.
- [Exact requested download](https://huggingface.co/baidu/Unlimited-OCR/resolve/main/model.safetensors?download=true).
- Upstream code and license notices are retained next to the weights; downloaded files are unchanged.

The duplicate shard/index were excluded: the loader uses the requested `model.safetensors`.
The local model directory includes custom Python code; `trust_remote_code=True` loads that
reviewed pinned local code, not arbitrary new code fetched during OCR.

## Privacy and limits

Inference uses local files with Hugging Face/Transformers offline mode. Model, custom-code cache,
temporary PDF raster files, CUDA/Matplotlib project caches, logs and outputs stay under this root.
Shared runtimes/packages and their general download caches remain in the existing approved shared
locations. No remote inference API, telemetry upload or public server is configured.

PDF processing is page-by-page: it does not preserve upstream one-shot cross-page context.
Large image crops, multiple concurrent GPU applications or very dense pages can exhaust VRAM.
A page over20million raster pixels is rejected. OCR can misread text, tables, equations and
non-Latin scripts; verify important results. Included public samples do not establish accuracy
on arbitrary private files. Actual local evaluation of three Persian pharmacology pages found
recognizable text but **unacceptable errors for unattended medical/study use**: mixed column order,
malformed table structure, word substitutions and incorrect percentages/symbols. RTL display and
UTF-8 preservation work; they do not repair model recognition quality. No automatic correction or
alternate model is silently substituted. See `docs/persian-quality.md`. The reference video's
macOS MLX one-shot throughput is not a performance promise for this Windows/PyTorch implementation.

## Verification

The bounded verification runner exercises the real launcher from a different working directory,
a filename containing spaces, invalid input and original-checkpoint CUDA image/PDF inference:

```powershell
.\.venv\Scripts\python.exe -I -X utf8 -u .\scripts\verify.py
```

It owns child processes, enforces480s wall/180s idle limits per inference (150s/120s for the
cold CUDA check; 60s/45s for invalid input),
checks recognizable paper text, output metadata and source integrity, then verifies no child
survives. GPU runs are serial. Evidence is written to `outputs/verification.json`; this is local
verification for local-only GPU scenarios. Portable source checks run through the repository's
manually dispatched GitHub workflow; no push/PR/scheduled event starts tests.

Verified on this machine: base image and PDF page each produced1953characters at6928.5MiB
peak allocated VRAM; gundam produced1953characters at7214.4MiB. Measured OCR time was
46.69–55.64seconds per page, excluding model startup. Invalid input and CUDA checks passed.
The current generation adapter supplies a non-padded single-batch attention mask and uses the
current dtype option; the former attention-mask/dtype warnings no longer appeared in the real run.
Upstream JIT deprecation and deterministic position_ids buffer initialization warnings remain
visible in diagnostics. The buffer is constructed by the model's arange, not a learned weight.
No training, checkpoint modification or blanket warning suppression was performed.

Rust-workspace validation: `scripts/test_desktop.py --gpu` tests actual hidden WebView IPC,
preview navigation, range errors, mode selection and original CUDA worker cancellation. CDP is enabled
only in the test-owned process environment. `--render` omits GPU inference.
Markdown DOM/sanitizer and actual CUDA cancel/reopen/resume were verified locally; the completed
page hash remained unchanged. Actual Explorer drops were verified for PDF and Persian filenames;
multiple files and directories reject without replacing the selected source. Legacy Qt rollback
validation: `scripts/test_visual.py --gui-worker` tests real QProcess CUDA OCR,
then cancellation after page1, saved result and50% progress. `scripts/test_workflow.py` checks
ranges/Persian digits/atomic checkpoints; `scripts/test_launcher.py --full` checks console Enter1,
invalid input, EOF and CLI errors. Native GUI rendering is tested offscreen with installed Windows
fonts (no font downloads). Private real-PDF testing is local-only and serial.

## License

Copyright 2026 KiaroSama. Authored application source is licensed under
[GNU GPL-3.0-only](LICENSE). Model assets and third-party components retain their own terms;
see [third-party notices](THIRD_PARTY_NOTICES.md). Weights, personal documents, outputs and
machine-specific signing material are not distributed with the source.

## Sources

- [Official model and inference instructions](https://huggingface.co/baidu/Unlimited-OCR).
- [Official upstream source](https://github.com/baidu/Unlimited-OCR).
- [PyTorch CUDA wheel matrix](https://pytorch.org/get-started/previous-versions/).
- [Transformers4.57.6](https://github.com/huggingface/transformers/releases/tag/v4.57.6).
- [Generation length semantics](https://huggingface.co/docs/transformers/v4.57.1/en/main_classes/text_generation).

## Donate

If this project helps you, donations are appreciated.

| Currency | Network | Address |
| --- | --- | --- |
| Bitcoin (BTC) | Bitcoin | `bc1qmth5m03pu5hujw5xw5jmywam3jj3sqwqupesdt` |
| USDT, BNB, USDC, etc. | BEP20 | `0x0Bd0BA443a8B9cf15922bf7f0Bb0a4b495fD06Ef` |
| USDT, TRX, USDC, etc. | TRC20 | `TWBA3xFTqgZAeAYMxqo85xWnzvty3DcAhw` |
| Ethereum (ETH) | ERC20 | `0x0Bd0BA443a8B9cf15922bf7f0Bb0a4b495fD06Ef` |
| TON | TON | `UQCN8Umo_OfOWqImZetQsrNStPcmLkMAKajFyiCOhso23NDb` |
| Litecoin (LTC) | LTC | `ltc1qntqnnrunadurnw4cshv3qgspywrueyyeyngwuy` |
| Solana (SOL) | Solana | `7B2wkczUjmkDhETwQuknBL8sUsbuV7nErxc317TmQuwR` |
| Polygon (POL) | Polygon | `0x0Bd0BA443a8B9cf15922bf7f0Bb0a4b495fD06Ef` |
