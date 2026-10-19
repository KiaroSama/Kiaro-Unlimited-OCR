# Real upstream fixtures

`upstream-paper.pdf` is the public paper distributed with Unlimited-OCR, unchanged from:
https://huggingface.co/baidu/Unlimited-OCR/blob/8249d20b2822a7d8a4c22c8d8c9069b5ac36bda3/Unlimited-OCR.pdf

`upstream page.png` is page1 rasterized at150DPI with PyMuPDF, not synthetic OCR text.
Expected independently visible title: `Unlimited OCR Works`; abstract starts `Recently, end-to-end
OCR models`. Verification checks title/nonempty body, not perfect character accuracy.
Upstream notice is retained in THIRD_PARTY_NOTICES.md and alongside the separately downloaded model.
Private evaluation documents are never included in this fixture directory or distributed.
