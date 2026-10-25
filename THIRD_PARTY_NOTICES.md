# Third-party notices

The authored launcher, Rust desktop and processing adapters are licensed under GPL-3.0-only.
They do not change the licenses of third-party runtimes, model code, weights or documents.

## Baidu Unlimited-OCR

The model and upstream sample are from https://huggingface.co/baidu/Unlimited-OCR at revision
8249d20b2822a7d8a4c22c8d8c9069b5ac36bda3. Model assets are obtained separately and are not included
in the repository. The public paper and its page-one raster are included as attribution-preserving
test fixtures. The upstream repository provides the following MIT notice:

MIT License

Copyright (c) 2026 Baidu

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Markdown renderer

The desktop bundles [Marked 18.1.1](https://github.com/markedjs/marked) (MIT, including its
Markdown/BSD attribution) and [DOMPurify 3.4.17](https://github.com/cure53/DOMPurify)
(Apache-2.0). Their full unmodified license notices are retained in `docs/licenses/`.
Source distributions resolve these components from the committed npm lockfile; binary
redistributions must also retain these notices.

## Runtime dependencies

Tauri and its Rust dependencies retain their individual license notices recorded in Cargo.lock
and the corresponding crate metadata. Python/PyTorch/Transformers, PyMuPDF, Pillow and Windows
WebView2 are separately installed prerequisites. PyMuPDF uses AGPL-3.0 or a commercial license;
review its applicable terms before redistribution. No Windows font files are redistributed.
