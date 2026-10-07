#!/usr/bin/env python3
"""Flag malformed Thai (doubled or stacked marks) in source files; exit 1 when found."""

import glob
import re
import sys

PAT = re.compile(r"([ัิ-ฺ็-๎])\1|[่-๋][่-๋]|[่-๋][ิ-ื]")
# typos Qwen has produced before
KNOWN_BAD = ("บ่าน", "ท่ี", "น้ี", "อับดับ", "แผนท่ี", "มีย ", "เวลาถิง", "'สุม'", "ตั้บ", "ร่ับ", "ส่่", "ูี", "ีู", "นนี้", "มูี")
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
        if PAT.search(line) or any(w in line for w in KNOWN_BAD):
            print(f"{f}:{i}: {line.strip()[:100]}")
            bad += 1
sys.exit(1 if bad else 0)
