# Persian OCR quality: observed limits

## Result

The original Baidu Unlimited-OCR checkpoint produces Persian Unicode, but is **not reliable for
unattended extraction of the supplied scanned pharmacology book**. This is recognition/layout
quality, not a UTF-8 or font-shaping failure. No alternate model or automatic language correction
was used. Medical terminology, percentages and equations require source comparison.

## Actual local test

2026-10-19, RTX4070Ti, original BF16 safetensors, CUDA13.2, Transformers4.57.6.
Source PDF794pages; source page numbers15,31,32, Gundam mode,200DPI rasterization.
All3completed:2879/2801/2942characters;491.98seconds processing total,7214.4MiB peak allocated VRAM.
Raw text, cleaned text and checkpoints remain in the local run output. Source file was not changed
or uploaded. PDF rendering uses PyMuPDF's CPU raster API; model inference used CUDA.

## Direct visual comparisons

- Page15: routes-of-administration table was merged with adjacent prose; multiple cells/rows repeat.
A source100percent bioavailability value became10percent in output. Therefore numeric fidelity fails.
- Page31: most headings and much prose are recognizable, but left-column content precedes the right,
Greek/Latin symbols and ED50/EC50/Kd relationships are corrupted; stray Latin fragments appear.
- Page32: agonist/efficacy/potency headings are recognizable, but formulas and percentages are wrong,
words are substituted and reading order is mixed.

No character-accuracy percentage is claimed: no complete verified ground-truth transcription was
available. Three pages do not establish coverage of all794pages. Do not use the output as a source
of medication/dosing decisions or as an unreviewed replacement for the original study material.

## Precise RTL mode (0.4)

On2026-10-26 a second, user-supplied five-page scanned document was tested locally with the
same original BF16 checkpoint and CUDA. Oversized PDF point dimensions now rasterize within a
3000pixel long-edge/12million-pixel budget instead of failing the former20million-pixel guard.

The separate `persian` mode reads right-column-first, using contiguous regions whose horizontal
boundaries lie in sparse-ink whitespace. Unlike a brightest-row cut, it does not bisect a photograph
to meet a target crop height. Words and numbers are returned by the model without dictionary repair.
Source files, raster images and recognized private text are not included in this repository.

Exploratory source-page3 runs measured149.0seconds for full-page Base and79.11seconds for
regional reading, but used different expert kernels, so they do not establish a valid speedup.
A subsequent matched-kernel Base attempt kept generating repetitive output and hit the360second
owner ceiling; it was terminated, not counted as completed. The final precise run with the retained
Turbo implementation completed the same page in63.0seconds (6928.5MiB peak allocated VRAM).
This is a bounded success versus a timed-out baseline, not a matched completed-run speed ratio.
Regional reading eliminated the observed
invented English header and duplicate paragraph, read the source1cm/10cm values correctly, and
preserved TSC1/TSC2. This is one page, with different segmentation and output length—not a universal
throughput or accuracy claim. Several Persian words,
figure references and occasional Latin fragments were still wrong. The mode improves this scan;
it does **not** make unattended medical transcription reliable. Compare every important value with
its source. A complete verified transcription is still needed for a defensible character-error rate.

A tested native expert-kernel prototype had inconsistent timing and only short-output parity; it
was not adopted. The existing CUDA Turbo path remains unchanged. Original weights are not quantized,
replaced or fine-tuned, and the Apple reference's263tokens/s has not been reproduced.

## Warnings and cancellation

The attention-mask warning was traced to upstream single-batch generation kwargs. The adapter now
adds an all-ones mask matching non-padded input IDs; no such warning appeared in the three-page run.
The dtype deprecation was removed by current API usage. Upstream JIT and position_ids warnings
remain visible. Neither those remaining warnings nor clean execution proves Persian accuracy.

A separate real GUI-worker test completed page1 of the public paper, requested cancellation during
page2, and verified cancelled status, completed_pages=[1], result retention and50percent progress.
The current page remains explicitly partial; it is not counted as completed. Force-killing a process
preserves the last atomic checkpoint but cannot guarantee final metadata/shutdown on every host.
