"""PDF Forge-compatible ordered, inclusive page selections."""
import re


def parse_pages(expression: str, total: int) -> list[int]:
    if total < 1:
        raise ValueError("Document has no pages.")
    expression = expression.strip().replace("،", ",").replace("–", "-").replace("—", "-")
    if not expression or expression.lower() == "all":
        return list(range(1, total + 1))
    selected: list[int] = []
    seen: set[int] = set()
    for part in expression.split(","):
        match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", part)
        if not match:
            raise ValueError("Use pages such as 1,3,10-20 (no empty entries).")
        first = int(match[1])
        last = int(match[2] or match[1])
        if first < 1 or last > total or first > last:
            raise ValueError(f"Pages must be within 1..{total}; reversed ranges are invalid.")
        for page in range(first, last + 1):
            if page not in seen:
                selected.append(page)
                seen.add(page)
    return selected
