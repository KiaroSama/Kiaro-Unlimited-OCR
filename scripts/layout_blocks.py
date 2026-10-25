"""Parse untrusted model layout markers without executing generated expressions."""
import json
import math
import re

BLOCK = re.compile(r'<\|ref\|>(.*?)<\|/ref\|>\s*<\|det\|>(.*?)<\|/det\|>(.*?)(?=<\|ref\|>|\Z)', re.S)


def parse_blocks(raw):
    blocks = []
    for match in BLOCK.finditer(raw):
        boxes = []
        try:
            coordinates = json.loads(match[2].replace('(', '[').replace(')', ']'))
            if not isinstance(coordinates, list):
                coordinates = []
            if coordinates and isinstance(coordinates[0], (int, float)):
                coordinates = [coordinates]
            for box in coordinates[:128]:
                if not isinstance(box, list) or len(box) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in box):
                    continue
                x1, y1, x2, y2 = [min(1000, max(0, v)) / 1000 for v in box]
                if x2 > x1 and y2 > y1:
                    boxes.append({'x': x1, 'y': y1, 'width': x2-x1, 'height': y2-y1})
        except (ValueError, TypeError, IndexError):
            pass
        blocks.append({'label': match[1].strip()[:64], 'text': match[3].strip(), 'boxes': boxes})
    if not blocks:
        pattern = r'<\|det\|>\s*([\w -]+?)\s*(\[.*?\])\s*<\|/det\|>(.*?)(?=<\|det\|>|\Z)'
        for match in re.finditer(pattern, raw, re.S):
            canonical = f'<|ref|>{match[1]}<|/ref|><|det|>{match[2]}<|/det|>{match[3]}'
            blocks.extend(parse_blocks(canonical))
    return blocks


def display_text(raw):
    blocks = parse_blocks(raw)
    if blocks:
        return '\n\n'.join(('## ' if b['label'] == 'title' else '### ' if b['label'] == 'sub_title' else '') + b['text'] for b in blocks if b['text'])
    text = re.sub(r'<\|det\|>.*?(?:<\|/det\|>|$)', '', raw, flags=re.S)
    return re.sub(r'<\|[^>]*\|>|<PAGE>|<｜end▁of▁sentence｜>', '', text).strip()


def split_pages(raw, selected):
    parts = raw.split('<PAGE>')
    if len(parts) == 1:
        parts = [raw] if len(selected) == 1 else []
    else:
        parts = parts[1:]
    return [{'page': number, 'raw': part, 'text': display_text(part), 'blocks': parse_blocks(part)}
            for number, part in zip(selected, parts)]
