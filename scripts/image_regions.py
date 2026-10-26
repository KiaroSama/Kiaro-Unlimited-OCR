"""Bounded PDF rasterization and source-grounded right-to-left reading regions."""
import json
import math
from PIL import Image, ImageStat


def raster_scale(width, height, dpi=200):
    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
        raise ValueError('Page dimensions must be finite and positive.')
    return min(dpi / 72, 3000 / max(width, height), math.sqrt(12000000 / (width * height)))


def raster_page(page, bounded=False):
    import pymupdf
    width, height = page.rect.width, page.rect.height
    scale = raster_scale(width, height)
    # Preserve accepted legacy Base/Gundam checkpoint inputs; only oversized pages need fallback.
    if not bounded and width*height*(200/72)**2 <= 20000000:
        return page.get_pixmap(dpi=200, alpha=False)
    return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)


def reading_regions(image):
    """Two columns, right first; cut near whitespace rather than through printed lines."""
    width, height = image.size
    if width < 100 or height < 100:
        raise ValueError('Precise reading requires an image at least 100 pixels per side.')
    gray = image.convert('L')
    sample = gray.crop((0, int(height * .12), width, int(height * .94)))
    lo, hi = int(width * .46), int(width * .54)
    gutter = max(range(lo, hi + 1), key=lambda x: ImageStat.Stat(sample.crop((x, 0, x+1, sample.height))).mean[0])
    regions = []
    for left, right in ((gutter, width), (0, gutter)):
        # Printed lines have sparse dark pixels; a photograph is not a whitespace cut.
        margin = max(1, (right-left)//12)
        column = gray.crop((left+margin, 0, right-margin, height)).point(lambda v: 255 if v < 150 else 0)
        gaps, start = [], None
        for y in range(height+1):
            blank = y < height and ImageStat.Stat(column.crop((0, y, column.width, y+1))).mean[0] < 255*.006
            if blank and start is None:
                start = y
            elif not blank and start is not None:
                if y-start >= max(4, height//500):
                    gaps.append((start, y))
                start = None
        top, target = 0, round((right-left)*.9)
        while top < height:
            candidates = [(a+b)//2 for a, b in gaps if top+target*.55 < (a+b)//2 <= top+target*1.35]
            if candidates:
                bottom = min(candidates, key=lambda y: abs(y-top-target))
            else:
                # Never cut a figure or printed line just to meet a preferred size.
                bottom = next(((a+b)//2 for a, b in gaps if (a+b)//2 > top+target), height)
            if height-bottom < target*.3:
                bottom = height
            crop = image.crop((left, top, right, bottom))
            extrema = crop.convert('L').getextrema()
            if extrema[1] - extrema[0] > 12:
                regions.append((crop, (left/width, top/height, (right-left)/width, (bottom-top)/height)))
            top = bottom
    return regions


def transform_raw(raw, region):
    """Re-encode validated boxes in original-page coordinates; retain recognized words."""
    from layout_blocks import parse_blocks
    x, y, width, height = region
    blocks = parse_blocks(raw)
    if not blocks:
        # Keep an untagged region distinct when adjacent regions have layout markers.
        return f'<|ref|>text<|/ref|><|det|>[]<|/det|>{raw}' if raw.strip() else ''
    parts = []
    for block in blocks:
        boxes = [[round((x+b['x']*width)*1000), round((y+b['y']*height)*1000),
                  round((x+(b['x']+b['width'])*width)*1000), round((y+(b['y']+b['height'])*height)*1000)]
                 for b in block['boxes']]
        parts.append(f"<|ref|>{block['label']}<|/ref|><|det|>{json.dumps(boxes)}<|/det|>{block['text']}")
    return '\n'.join(parts)


def recognize_regions(image_path, tokenizer, model, output, control, max_length):
    from pathlib import Path
    import logging
    from ocr import infer_image
    log = logging.getLogger('ocr')
    with Image.open(image_path) as image:
        regions = reading_regions(image.convert('RGB'))
    if not regions:
        raise ValueError('No readable regions; page has not been marked complete.')
    accumulated = ''
    for index, (image, region) in enumerate(regions):
        if control.boundary():
            raise InterruptedError('Cancelled between reading regions; page remains partial.')
        path = Path(output) / 'region.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        control.region_prefix, control.region = accumulated, region
        log.info('Reading region=%d/%d page=%d', index+1, len(regions), control.page)
        control.reset(control.page, keep_regions=True)
        raw = infer_image(tokenizer, model, path, output, 'base', max_length)
        if control.stop_requested():
            raise InterruptedError('Cancelled during a reading region; page remains partial.')
        accumulated += transform_raw(raw, region) + '\n'
    control.region_prefix, control.region = accumulated, (0, 0, 1, 1)
    control.reset(control.page, keep_regions=True)
    return accumulated
