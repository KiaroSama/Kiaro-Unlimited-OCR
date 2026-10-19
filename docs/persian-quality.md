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

## Warnings and cancellation

The attention-mask warning was traced to upstream single-batch generation kwargs. The adapter now
adds an all-ones mask matching non-padded input IDs; no such warning appeared in the three-page run.
The dtype deprecation was removed by current API usage. Upstream JIT and position_ids warnings
remain visible. Neither those remaining warnings nor clean execution proves Persian accuracy.

A separate real GUI-worker test completed page1 of the public paper, requested cancellation during
page2, and verified cancelled status, completed_pages=[1], result retention and50percent progress.
The current page remains explicitly partial; it is not counted as completed. Force-killing a process
preserves the last atomic checkpoint but cannot guarantee final metadata/shutdown on every host.
