"""Strict UTF-8/syntax/source-boundary gate for tracked publication inputs."""
import ast
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
files = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z']).decode('utf-8').split('\0')
count = 0
for name in filter(None, files):
    path = ROOT / name
    if path.suffix.lower() in {'.pdf', '.png', '.ico'}:
        continue
    text = path.read_text(encoding='utf-8', errors='strict')
    if path.suffix == '.py':
        ast.parse(text, filename=name)
    if path.suffix in {'.py', '.rs', '.ts', '.ps1'} and len(text.splitlines()) > 800:
        raise AssertionError(f'Source file exceeds 800 lines: {name}')
    count += 1
assert count > 10, 'No meaningful source set discovered'
print(f'PASS strict UTF-8 and source syntax: {count} text files')
