"""Document metadata/raster adapter for the Rust desktop; no model imports."""
import argparse
import base64
from io import BytesIO
import json
from pathlib import Path


def inspect_document(source: Path, page: int = 1) -> dict:
    source = source.expanduser().resolve(strict=True)
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError("Select a nonempty image or PDF.")
    if source.suffix.lower() == ".pdf":
        import pymupdf
        with pymupdf.open(source) as document:
            if document.needs_pass or not len(document):
                raise ValueError("PDF must be unlocked and contain pages.")
            total = len(document)
            if not 1 <= page <= total:
                raise ValueError("Preview page is outside the document.")
            rect = document[page - 1].rect
            scale = min(1200 / max(rect.width, rect.height), 2)
            pixmap = document[page - 1].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            data = pixmap.tobytes("png")
    else:
        if source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
            raise ValueError("Unsupported document format.")
        from PIL import Image, ImageOps
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((1200, 1200))
            output = BytesIO()
            image.convert("RGB").save(output, format="PNG")
            data = output.getvalue()
        total = 1
        if page != 1:
            raise ValueError("Images contain one preview page.")
    return {"path": str(source), "name": source.name, "total": total, "page": page,
            "image": "data:image/png;base64," + base64.b64encode(data).decode("ascii")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--page", type=int, default=1)
    args = parser.parse_args()
    try:
        print(json.dumps(inspect_document(args.source, args.page), ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
