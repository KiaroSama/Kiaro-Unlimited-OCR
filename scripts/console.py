"""Local console wizard; Enter selects OCR, never Exit."""
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ocr import ROOT, configure_paths, start_log, validate_input
from page_selection import parse_pages

PALETTE = {"title": "125;179;255", "label": "110;210;255", "mode": "180;145;255",
           "success": "145;255;95", "warning": "255;215;80", "error": "255;95;120"}


def say(text, role="label"):
    if sys.stdout.isatty():
        print(f"\033[38;2;{PALETTE[role]}m{text}\033[0m")
    else:
        print(text)


def main():
    configure_paths()
    log, _ = start_log()
    try:
        while True:
            say("\n" + "=" * 64, "title")
            say("  Unlimited-OCR  |  NVIDIA CUDA  |  Original BF16", "title")
            say("=" * 64, "title")
            say("  [1] OCR an image or PDF   < Enter default >", "success")
            say("  [2] Run included sample (first page)")
            say("  [3] Check CUDA and model")
            say("  [4] Open visual workspace", "mode")
            say("  [0] Exit", "warning")
            try:
                choice = input("Choose [1]: ").strip() or "1"
            except EOFError:
                return 0
            if choice == "0":
                return 0
            options = []
            try:
                if choice in ("1", "2"):
                    name = str(ROOT / "samples" / "upstream-paper.pdf") if choice == "2" else input("Image/PDF path (empty = back): ").strip().strip('"').strip("'")
                    if not name:
                        continue
                    source = validate_input(Path(name))
                    selection = "1" if choice == "2" else ""
                    if source.suffix.lower() == ".pdf" and choice == "1":
                        import pymupdf
                        with pymupdf.open(source) as document:
                            total = len(document)
                        say(f"Source: {total} pages | Examples: 5 / 1,3 / 10-20,25", "warning")
                        while True:
                            selection = input("Pages to OCR [all]: ").strip()
                            try:
                                selected = parse_pages(selection, total)
                                say(f"Selected: {len(selected)} pages", "success")
                                break
                            except ValueError as error:
                                say(str(error), "error")
                    say("Modes: [1] base (lower VRAM)  [2] gundam (small text / tiled)", "mode")
                    while True:
                        mode_choice = input("Mode [1]: ").strip() or "1"
                        if mode_choice in ("1", "2", "base", "gundam"):
                            break
                        say("Choose 1/base or 2/gundam.", "error")
                    mode = "gundam" if mode_choice in ("2", "gundam") else "base"
                    options = [str(source), "--mode", mode, "--page-selection", selection]
                elif choice == "3":
                    options = ["--check"]
                elif choice == "4":
                    executable = ROOT / "desktop" / "target" / "release" / "kiaro-unlimited-ocr.exe"
                    if not executable.is_file():
                        raise FileNotFoundError("Build the Rust desktop with scripts/build-desktop.ps1 first.")
                    subprocess.run([str(executable)], check=False)
                    continue
                else:
                    say("Invalid choice.", "error")
                    continue
                log.info("Console action=%s", choice)
                say("Processing on CUDA. Ctrl+C requests cancellation; saved pages remain.", "warning")
                child = subprocess.Popen([sys.executable, "-I", "-X", "utf8", "-u", str(ROOT / "scripts" / "ocr.py"), *options])
                while True:
                    try:
                        code = child.wait()
                        break
                    except KeyboardInterrupt:
                        # Both processes receive console Ctrl+C. Worker saves at token boundary.
                        say("Cancellation requested; waiting for saved checkpoints.", "warning")
                say("Operation completed." if code == 0 else f"Operation stopped (exit {code}); saved results retained.",
                    "success" if code == 0 else "warning")
                input("Press Enter to return to menu…")
            except EOFError:
                return 0
            except KeyboardInterrupt:
                say("Back to menu.", "warning")
            except Exception as error:
                log.warning("Console operation failed type=%s", type(error).__name__)
                say(f"Operation failed: {error}", "error")
    finally:
        log.info("Console shutdown")
        for handler in list(log.handlers):
            handler.close()
            log.removeHandler(handler)


if __name__ == "__main__":
    raise SystemExit(main())
