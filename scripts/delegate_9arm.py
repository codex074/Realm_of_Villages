#!/usr/bin/env python3
"""Delegate one BUILD.md task to Qwen through the headless `claude --settings ~/.claude-9arm.json`.

Usage:
    python3 scripts/delegate_9arm.py .agents/tasks/T02.json --dry-run
    python3 scripts/delegate_9arm.py .agents/tasks/T02.json --max-rounds 3

Task JSON keys: id, title, read[], write[], spec[] ("a-b" line ranges of BUILD.md),
criteria (acceptance text), test_cmd, notes.

Exit codes: 0 checks pass, 1 checks failed after all rounds, 2 Qwen call failed,
3 prompt too large, 4 Qwen touched files outside the allowed list.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / ".agents" / "runs"
MAX_PROMPT_TOKENS = 40_000
CLAUDE_CMD = [
    "claude",
    "--settings",
    str(Path.home() / ".claude-9arm.json"),
    "--model=qwen3.8-27b-fp8",
    "--effort",
    "medium",
    "--bare",
    "--disable-slash-commands",
    "--system-prompt-snapshot",
    "off",
]
TOOLS = ["--allowedTools", "Bash", "Read", "Edit", "Write", "Glob", "Grep"]

RULES = """\
Project rules (iron rules, never break):
1. Create/edit ONLY the files in the WRITE list (plus docs/handoff/<ID>.md).
   Do not touch anything else.
2. Do not change any contract in BUILD.md (function names, signatures, column names, JSON shapes,
   event names). If the contract is insufficient, write the question to docs/CHANGES_REQUESTED.md
   and follow the existing contract meanwhile.
3. realm/core/ must not import realm.db, realm.services, realm.api, realm.engine, realm.bot.
4. Time-dependent functions take `now: datetime` as a parameter; never call datetime.now() (except
   realm/core/clock.py, worker loops, API dependencies). All datetimes are timezone-aware UTC.
5. Type hints on every function; one-line docstring for public functions.
6. No hard-coded game numbers (costs, times, stats): read them from `cfg` (GameConfig).
7. Do not add dependencies. Code/comments/identifiers in English; player-facing text in Thai.
8. Tests must be real: do not assert values computed by the code under test, do not skip tests.
9. Finish by writing docs/handoff/<ID>.md (what was done, files, public functions, limits, TODO).
10. Format with `uv run ruff format <files>` and make `uv run ruff check .` pass."""


def sh(cmd: str, timeout: int = 900) -> tuple[int, str]:
    p = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr)


def changed_files() -> set[str]:
    _, out = sh("git status --porcelain -uall")
    files = set()
    for line in out.splitlines():
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ")[-1]
        files.add(path)
    return files


def build_prompt(task: dict, feedback: str | None) -> str:
    tid = task["id"]
    root = str(ROOT)
    spec = "\n".join(f"  - {root}/BUILD.md lines {r}" for r in task.get("spec", []))
    read = "\n".join(f"  - {root}/{p}" for p in task.get("read", [])) or "  (none)"
    write = "\n".join(f"  - {root}/{p}" for p in task["write"])
    parts = [
        "You are a senior Python developer working on the game 'Realm of Villages'.",
        f"Repository root: {root} (run commands with this as the working directory).",
        f"TASK {tid}: {task['title']}",
        "",
        "Read these spec sections of BUILD.md (use the Read tool with offset/limit; the file is "
        "large, do NOT read all of it):",
        spec,
        "Also read these existing files for context:",
        read,
        "",
        f"WRITE list (the only files you may create or edit, plus docs/handoff/{tid}.md):",
        write,
        "",
        "Acceptance criteria:",
        task.get("criteria", "(see spec)"),
        "",
        RULES.replace("<ID>", tid),
        "",
    ]
    if task.get("notes"):
        parts += ["Extra notes from the lead:", task["notes"], ""]
    if task.get("test_cmd"):
        parts += [
            f"When done, run: {task['test_cmd']} and `uv run ruff check .` and fix every failure.",
            "Reply at the end with a 3-line summary only.",
        ]
    if feedback:
        parts += [
            "",
            "PREVIOUS ATTEMPT FAILED. The files already exist on disk; fix them (do not rewrite "
            "from scratch). Failure output:",
            feedback,
        ]
    return "\n".join(parts)


def clean_env() -> dict[str, str]:
    """Minimal env: host-app ANTHROPIC_*/CLAUDE_* vars break the 9arm gateway auth."""
    keep = ("HOME", "PATH", "LANG", "LC_ALL", "TMPDIR", "USER", "SHELL", "REALM_TEST_DATABASE_URL")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["TERM"] = "dumb"
    return env


def run_qwen(prompt: str, log: Path) -> tuple[int, str]:
    cmd = CLAUDE_CMD + ["-p", prompt] + TOOLS
    try:
        p = subprocess.run(
            cmd, cwd=ROOT, capture_output=True, text=True, timeout=1800, env=clean_env()
        )
    except subprocess.TimeoutExpired:
        log.write_text("TIMEOUT")
        return 2, "timeout"
    log.write_text(p.stdout + "\n--- stderr ---\n" + p.stderr)
    return p.returncode, p.stdout


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("task_file")
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    task = json.loads(Path(args.task_file).read_text(encoding="utf-8"))
    tid = task["id"]
    run_dir = RUNS / tid
    run_dir.mkdir(parents=True, exist_ok=True)

    prompt = build_prompt(task, None)
    est_tokens = len(prompt) // 3
    spec_chars = 0
    lines = (ROOT / "BUILD.md").read_text(encoding="utf-8").splitlines()
    for r in task.get("spec", []):
        a, b = (int(x) for x in r.split("-"))
        spec_chars += sum(len(x) for x in lines[a - 1 : b])
    for p in task.get("read", []):
        spec_chars += (ROOT / p).stat().st_size if (ROOT / p).exists() else 0
    est_tokens += spec_chars // 3
    print(json.dumps({"task": tid, "prompt_chars": len(prompt), "est_total_tokens": est_tokens}))
    if est_tokens > MAX_PROMPT_TOKENS:
        print("too large for Qwen's effective context; split the task", file=sys.stderr)
        sys.exit(3)
    if args.dry_run:
        (run_dir / "dry_prompt.md").write_text(prompt, encoding="utf-8")
        return

    allowed = set(task["write"]) | {f"docs/handoff/{tid}.md", "docs/CHANGES_REQUESTED.md"}
    before = changed_files()
    feedback = None
    summary: dict = {"id": tid, "rounds": []}
    for rnd in range(1, args.max_rounds + 1):
        t0 = time.time()
        code, out = run_qwen(build_prompt(task, feedback), run_dir / f"round{rnd}.log")
        if code != 0:
            summary["status"] = "qwen_error"
            (run_dir / "latest.json").write_text(json.dumps(summary, ensure_ascii=False))
            print(out[-2000:], file=sys.stderr)
            sys.exit(2)
        stray = {
            f for f in changed_files() - before if f not in allowed and not f.startswith(".agents/")
        }
        if stray:
            summary["status"] = "stray_files"
            summary["stray"] = sorted(stray)
            (run_dir / "latest.json").write_text(json.dumps(summary, ensure_ascii=False))
            print("Qwen touched files outside the allowed list:", sorted(stray), file=sys.stderr)
            sys.exit(4)
        fmt = " ".join(p for p in task["write"] if p.endswith(".py") and (ROOT / p).exists())
        if fmt:
            sh(f"uv run ruff format {fmt} && uv run ruff check --fix {fmt}")
        rc_lint, lint = sh("uv run ruff check .")
        rc_test, test = (0, "")
        if task.get("test_cmd"):
            rc_test, test = sh(task["test_cmd"])
        ok = rc_lint == 0 and rc_test == 0
        summary["rounds"].append(
            {
                "round": rnd,
                "seconds": round(time.time() - t0),
                "lint_ok": rc_lint == 0,
                "test_ok": rc_test == 0,
            }
        )
        print(
            f"round {rnd}: lint={'ok' if rc_lint == 0 else 'FAIL'} "
            f"test={'ok' if rc_test == 0 else 'FAIL'}"
        )
        if ok:
            summary["status"] = "pass"
            (run_dir / "latest.json").write_text(json.dumps(summary, ensure_ascii=False))
            return
        feedback = ((lint if rc_lint else "") + "\n" + (test if rc_test else ""))[-6000:]
        (run_dir / f"round{rnd}_feedback.txt").write_text(feedback)
    summary["status"] = "failed"
    (run_dir / "latest.json").write_text(json.dumps(summary, ensure_ascii=False))
    sys.exit(1)


if __name__ == "__main__":
    main()
