#!/usr/bin/env python3
"""Flag malformed Thai (doubled or stacked marks) in source files; exit 1 when found."""

import glob
import re
import sys

PAT = re.compile(r"([ัิ-ฺ็-๎])\1|[่-๋][่-๋]|[่-๋][ิ-ื]")
bad = 0
files = [
    *glob.glob("realm/**/*.py", recursive=True),
    *glob.glob("tests/**/*.py", recursive=True),
    *glob.glob("web/**/*.*", recursive=True),
    *glob.glob("realm/config/*.yaml"),
]
for f in files:
    try:
        text = open(f, encoding="utf8").read()
    except (UnicodeDecodeError, IsADirectoryError):
        continue
    for i, line in enumerate(text.splitlines(), 1):
        if PAT.search(line):
            print(f"{f}:{i}: {line.strip()[:100]}")
            bad += 1
sys.exit(1 if bad else 0)
