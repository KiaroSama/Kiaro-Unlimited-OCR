"""Hidden bounded tests of the real interactive launcher and its existing CLI."""
from pathlib import Path
import argparse
import importlib.util
import json

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify", ROOT / "scripts" / "verify.py")
assert spec and spec.loader
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    result = verify.run(["-Console"], stdin_text="0\n", wall=60, idle=45)
    assert "Enter default" in result["output"], "Console must show default OCR action"
    if args.full:
        invalid = verify.run(["-Console"], stdin_text="9\n\nmissing image.png\n0\n", wall=90, idle=60)
        assert "Invalid choice" in invalid["output"]
        assert "Operation failed" in invalid["output"]
        assert invalid["output"].count("Original BF16") >= 3
        verify.run(["-Console"], stdin_text="", wall=60, idle=45)
        verify.run(["-InputPath", "missing.png"], expected=1, wall=60, idle=45)
        (ROOT / "outputs").mkdir(exist_ok=True)
        (ROOT / "outputs" / "launcher-verification.json").write_text(
            json.dumps({"status": "passed", "coverage": "console default/invalid/EOF/CLI"}, indent=2), encoding="utf-8")
    print("PASS launcher menu")


if __name__ == "__main__":
    main()
