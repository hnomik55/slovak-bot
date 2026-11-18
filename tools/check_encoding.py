"""Ищет битые символы (U+FFFD) в исходниках — следы неудачной записи файлов."""

import io
import pathlib

root = pathlib.Path(".")
bad = 0
for path in sorted(root.rglob("*.py")) + sorted(root.rglob("*.md")) + sorted(root.rglob("*.mjs")):
    if "__pycache__" in str(path) or path.name == "check_encoding.py":
        continue
    try:
        text = io.open(path, encoding="utf-8").read()
    except UnicodeDecodeError as exc:
        print("NOT-UTF8", path, exc)
        bad += 1
        continue
    for i, line in enumerate(text.splitlines(), 1):
        if "\ufffd" in line:
            print("%s:%d: %s" % (path, i, line.strip()[:120]))
            bad += 1
print("problems:", bad)
