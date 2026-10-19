"""Fast deterministic selection and crash-safe output contracts."""
from pathlib import Path
import importlib.util
import sys
import tempfile
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> None:
    from page_selection import parse_pages
    assert parse_pages("۳،۱-۲,۳", 5) == [3, 1, 2]
    assert parse_pages("", 3) == [1, 2, 3]
    for invalid in ("0", "4", "3-1", "1,,2", "a", "1-9"):
        try:
            parse_pages(invalid, 3)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Accepted invalid selection: {invalid}")
    from run_storage import RunStore
    (ROOT / ".tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / ".tmp") as directory:
        store = RunStore(Path(directory), [3, 1], "gundam")
        store.partial(3, "سلام دنیا")
        store.complete(3, "سلام دنیا", "سلام دنیا\n", 1.0)
        store.partial(1, "متن ناتمام")
        store.finish("cancelled")
        meta = json.loads((Path(directory) / "metadata.json").read_text(encoding="utf-8"))
        assert meta["status"] == "cancelled" and meta["completed_pages"] == [3]
        assert "سلام دنیا" in (Path(directory) / "result.md").read_text(encoding="utf-8")
        assert (Path(directory) / "page-0001.partial.md").read_text(encoding="utf-8") == "متن ناتمام"
    print("PASS selection and checkpoint contracts")


if __name__ == "__main__":
    main()
