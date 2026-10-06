#!/usr/bin/env python3
"""Delegate one BUILD.md task to a Qwen model through an OpenAI-compatible API.

Usage:
    python3 scripts/delegate.py --ping
    python3 scripts/delegate.py .agents/tasks/T02.json --dry-run
    python3 scripts/delegate.py .agents/tasks/T02.json --max-rounds 3

Standard library only, so it runs before `uv sync`.

Exit codes: 0 pass, 1 checks failed, 2 model/connection/format error, 3 prompt too large.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / ".agents" / "runs"
PROTECTED = {"BUILD.md", "CLAUDE.md", "STATUS.md", "scripts/delegate.py"}
MAX_CONTINUATIONS = 2
FEEDBACK_CHARS = 6000

LANG_BY_SUFFIX = {
    ".py": "python", ".js": "javascript", ".html": "html", ".css": "css", ".md": "markdown",
    ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".toml": "toml", ".sh": "bash",
    ".ini": "ini", ".mako": "mako", ".txt": "text",
}

SYSTEM_PROMPT = """คุณคือนักพัฒนา Python อาวุโสในโปรเจกต์เกม "Realm of Villages"
สเปกหลักคือ BUILD.md ที่แนบมา ทำตามกฎเหล็กหัวข้อ 0 และ contract หัวข้อ 4-10 อย่างเคร่งครัด

รูปแบบคำตอบ (บังคับ):
- ตอบเป็นไฟล์เท่านั้น ไฟล์ละหนึ่งบล็อก:
  ### path/to/file.py
  ```python
  <เนื้อหาเต็มทั้งไฟล์>
  ```
- path เป็น path จาก root ของ repo ห้ามมี backtick หรือคำอื่นในบรรทัด ###
- ส่งเนื้อหาเต็มทุกไฟล์ ห้ามส่ง diff ห้ามเขียน "... เหมือนเดิม ..."
- สร้าง/แก้ได้เฉพาะไฟล์ในรายการที่อนุญาต
- ในไฟล์ .md ห้ามใช้ ``` ข้างใน ให้ใช้ ~~~ แทน
- ต้องส่งไฟล์ docs/handoff/<TASK_ID>.md เสมอ
- ถ้า contract ไม่พอหรือขัดกัน ให้ส่งไฟล์ docs/CHANGES_REQUESTED.md ที่มีคำถามสั้นๆ แล้วทำส่วนที่ทำได้
- ห้ามแต่งฟังก์ชัน ตาราง หรือ endpoint ที่ไม่มีใน contract ห้ามฝังตัวเลข balance ในโค้ด
- ไม่ต้องอธิบายนอกบล็อกไฟล์"""


# ---------------------------------------------------------------- config


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ without overriding existing values."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class ModelConfig:
    base_url: str
    model: str
    api_key: str
    context_tokens: int
    max_tokens: int
    temperature: float
    timeout: int

    @staticmethod
    def from_env() -> ModelConfig:
        model = os.environ.get("QWEN_MODEL", "")
        if not model:
            fail(2, "QWEN_MODEL is not set (put it in .env.agents or the shell)")
        return ModelConfig(
            base_url=os.environ.get("QWEN_BASE_URL", "http://localhost:11434/v1").rstrip("/"),
            model=model,
            api_key=os.environ.get("QWEN_API_KEY", "none"),
            context_tokens=int(os.environ.get("QWEN_CONTEXT_TOKENS", "128000")),
            max_tokens=int(os.environ.get("QWEN_MAX_TOKENS", "16384")),
            temperature=float(os.environ.get("QWEN_TEMPERATURE", "0.2")),
            timeout=int(os.environ.get("QWEN_TIMEOUT", "1800")),
        )


@dataclass
class Task:
    id: str
    title: str
    read: list[str]
    write: list[str]
    test_cmd: str = ""
    notes: str = ""
    extra_allowed: list[str] = field(default_factory=list)

    @staticmethod
    def load(path: Path) -> Task:
        data = json.loads(path.read_text(encoding="utf-8"))
        task = Task(
            id=data["id"],
            title=data.get("title", ""),
            read=list(data.get("read", [])),
            write=list(data["write"]),
            test_cmd=data.get("test_cmd", ""),
            notes=data.get("notes", ""),
        )
        task.extra_allowed = [f"docs/handoff/{task.id}.md", "docs/CHANGES_REQUESTED.md"]
        for p in task.write:
            if p in PROTECTED:
                fail(2, f"task may not write protected file: {p}")
        return task

    @property
    def allowed(self) -> set[str]:
        return set(self.write) | set(self.extra_allowed)


# ---------------------------------------------------------------- helpers


def fail(code: int, message: str) -> None:
    print(json.dumps({"status": "error", "exit_code": code, "message": message}, ensure_ascii=False))
    sys.exit(code)


def estimate_tokens(text: str) -> int:
    """Conservative estimate: Thai and other non-ASCII text costs far more tokens per char."""
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    other = len(text) - ascii_chars
    return int(ascii_chars / 3.2 + other / 1.2) + 1


def fence_lang(path: str) -> str:
    return LANG_BY_SUFFIX.get(Path(path).suffix, "")


def file_block(path: str, content: str) -> str:
    return f"### {path}\n```{fence_lang(path)}\n{content.rstrip()}\n```\n"


def safe_path(rel: str) -> Path | None:
    if rel.startswith("/") or ".." in Path(rel).parts:
        return None
    full = (ROOT / rel).resolve()
    try:
        full.relative_to(ROOT)
    except ValueError:
        return None
    return full


def strip_thinking(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    return re.sub(r"^.*?</think>", "", text, flags=re.S) if "</think>" in text else text


HEADER = re.compile(r"^#{2,4}\s+`?([A-Za-z0-9_./\-]+)`?\s*$")


def parse_files(text: str) -> tuple[dict[str, str], str | None]:
    """Return ({path: content}, truncated_path). A block counts only when its fence closes."""
    files: dict[str, str] = {}
    truncated: str | None = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = HEADER.match(lines[i])
        if m and i + 1 < len(lines) and lines[i + 1].strip().startswith("```"):
            path = m.group(1)
            j = i + 2
            buf: list[str] = []
            while j < len(lines) and lines[j].strip() != "```":
                buf.append(lines[j])
                j += 1
            if j < len(lines):
                files[path] = "\n".join(buf) + "\n"
            else:
                truncated = path
            i = j + 1
            continue
        i += 1
    return files, truncated


def run(cmd: str, timeout: int = 1800) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd, shell=True, cwd=ROOT, capture_output=True, text=True, timeout=timeout
        )
        return p.returncode, (p.stdout + p.stderr)
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s: {cmd}"


# ---------------------------------------------------------------- model API


def chat(cfg: ModelConfig, messages: list[dict]) -> tuple[str, str, dict]:
    body = {
        "model": cfg.model,
        "messages": messages,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
    }
    req = urllib.request.Request(
        f"{cfg.base_url}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg.api_key}"},
    )
    last_err = ""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=cfg.timeout) as resp:
                data = json.load(resp)
            choice = data["choices"][0]
            content = choice.get("message", {}).get("content") or ""
            return content, choice.get("finish_reason") or "", data.get("usage") or {}
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as e:
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(5 * (attempt + 1))
    fail(2, f"model call failed after 3 attempts: {last_err}")
    raise AssertionError  # unreachable


# ---------------------------------------------------------------- prompt


def build_prompt(task: Task, feedback: str) -> str:
    build_md = (ROOT / "BUILD.md").read_text(encoding="utf-8")
    parts = ["# BUILD.md\n", build_md, "\n\n# ไฟล์อ้างอิง (อ่านอย่างเดียว ห้ามแก้)\n"]
    for rel in task.read:
        p = safe_path(rel)
        if p is None or not p.exists():
            parts.append(f"### {rel}\n(ไม่มีไฟล์นี้ใน repo)\n")
            continue
        parts.append(file_block(rel, p.read_text(encoding="utf-8")))

    parts.append("\n# สถานะปัจจุบันของไฟล์ที่คุณต้องสร้าง/แก้\n")
    for rel in task.write:
        p = safe_path(rel)
        if p is not None and p.exists():
            parts.append(file_block(rel, p.read_text(encoding="utf-8")))
        else:
            parts.append(f"### {rel}\n(ยังไม่มี ต้องสร้างใหม่)\n")

    allowed = "\n".join(f"- {p}" for p in sorted(task.allowed))
    parts.append(
        f"\n# งานของคุณ: Task {task.id} · {task.title}\n"
        f"ทำตามหัวข้อ 11 ของ Task {task.id} ใน BUILD.md ทุกข้อ\n\n"
        f"ไฟล์ที่อนุญาตให้สร้าง/แก้:\n{allowed}\n"
    )
    if task.test_cmd:
        parts.append(f"\nคำสั่งที่จะใช้ตรวจงาน: `{task.test_cmd}` และ `ruff check`\n")
    if task.notes:
        parts.append(f"\n## หมายเหตุจากหัวหน้าทีม\n{task.notes}\n")
    if feedback:
        parts.append(
            "\n## ผลตรวจรอบก่อน (ไม่ผ่าน)\n"
            "ไฟล์ในหัวข้อ 'สถานะปัจจุบัน' คือเวอร์ชันที่ไม่ผ่าน แก้ให้ผ่าน "
            "แล้วส่งเนื้อหาเต็มเฉพาะไฟล์ที่ต้องเปลี่ยน\n"
            f"```text\n{feedback}\n```\n"
        )
    return "".join(parts)


# ---------------------------------------------------------------- run one task


@dataclass
class RoundResult:
    written: list[str]
    rejected: list[str]
    missing: list[str]
    check_code: int
    check_output: str


class RunLog:
    def __init__(self, task_id: str) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.dir = RUNS_DIR / task_id / stamp
        self.dir.mkdir(parents=True, exist_ok=True)
        self.task_dir = RUNS_DIR / task_id

    def save(self, name: str, content: str) -> None:
        (self.dir / name).write_text(content, encoding="utf-8")


def write_files(task: Task, files: dict[str, str]) -> tuple[list[str], list[str]]:
    written, rejected = [], []
    for rel, content in files.items():
        p = safe_path(rel)
        if p is None or rel not in task.allowed or rel in PROTECTED:
            rejected.append(rel)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        if rel == "docs/CHANGES_REQUESTED.md":
            with p.open("a", encoding="utf-8") as f:
                f.write(f"\n\n## จาก {task.id} · {datetime.now():%Y-%m-%d %H:%M}\n\n{content}")
        else:
            p.write_text(content, encoding="utf-8")
        written.append(rel)
    return written, rejected


def run_checks(task: Task, written: list[str]) -> tuple[int, str]:
    out: list[str] = []
    code = 0
    py_files = " ".join(f'"{f}"' for f in written if f.endswith(".py"))
    if py_files:
        run(f"uv run ruff format {py_files}")
        run(f"uv run ruff check --fix {py_files}")
        c, o = run(f"uv run ruff check {py_files}")
        if c != 0:
            code = c
            out.append("== ruff check ==\n" + o)
    if task.test_cmd:
        c, o = run(task.test_cmd)
        if c != 0:
            code = code or c
            out.append(f"== {task.test_cmd} ==\n" + o)
    return code, "\n".join(out)


def get_complete_response(cfg: ModelConfig, messages: list[dict], log: RunLog, r: int) -> str:
    """Call the model; if the answer is cut off, ask it to continue (bounded)."""
    combined = ""
    for cont in range(MAX_CONTINUATIONS + 1):
        content, finish, usage = chat(cfg, messages)
        content = strip_thinking(content)
        log.save(f"round{r}_response{cont}.md", content)
        log.save(f"round{r}_usage{cont}.json", json.dumps(usage, indent=2))
        combined += "\n" + content
        _, truncated = parse_files(content)
        if finish != "length" and truncated is None:
            return combined
        messages = messages + [
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": (
                    "คำตอบถูกตัดกลางทาง ส่งต่อเฉพาะไฟล์ที่ยังไม่ได้ส่งหรือส่งไม่ครบ"
                    + (f" เริ่มใหม่ทั้งไฟล์จาก {truncated}" if truncated else "")
                    + " ใช้รูปแบบเดิม ห้ามส่งไฟล์ที่ส่งครบแล้วซ้ำ"
                ),
            },
        ]
    return combined


def delegate(task: Task, cfg: ModelConfig, max_rounds: int) -> int:
    log = RunLog(task.id)
    feedback = ""
    all_written: set[str] = set()
    all_rejected: set[str] = set()
    result: RoundResult | None = None

    for r in range(1, max_rounds + 1):
        prompt = build_prompt(task, feedback)
        tokens = estimate_tokens(SYSTEM_PROMPT + prompt)
        if tokens + cfg.max_tokens > int(cfg.context_tokens * 0.95):
            fail(3, f"prompt ~{tokens} tokens + answer {cfg.max_tokens} exceeds context; split task")
        log.save(f"round{r}_prompt.md", prompt)

        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
        response = get_complete_response(cfg, messages, log, r)
        files, _ = parse_files(response)
        if not files:
            if r == max_rounds:
                fail(2, f"model returned no parsable file blocks; see {log.dir}")
            feedback = "คำตอบรอบก่อนไม่มีบล็อกไฟล์ที่อ่านได้ ต้องใช้รูปแบบ ### path + code fence"
            continue

        written, rejected = write_files(task, files)
        all_written |= set(written)
        all_rejected |= set(rejected)
        missing = [p for p in task.write if not (ROOT / p).exists()]
        code, output = run_checks(task, sorted(all_written))
        result = RoundResult(written, rejected, missing, code, output)
        log.save(f"round{r}_checks.txt", output or "all checks passed")

        problems = []
        if missing:
            problems.append("ยังไม่ได้สร้างไฟล์: " + ", ".join(missing))
        if rejected:
            problems.append("ไฟล์ที่ไม่อนุญาตถูกทิ้ง: " + ", ".join(rejected))
        if code == 0 and not missing:
            return finish_run(task, log, "pass", r, all_written, all_rejected, result)
        feedback = "\n".join(problems) + ("\n" + output[-FEEDBACK_CHARS:] if output else "")

    return finish_run(task, log, "fail", max_rounds, all_written, all_rejected, result)


def finish_run(task: Task, log: RunLog, status: str, rounds: int, written: set[str],
               rejected: set[str], result: RoundResult | None) -> int:
    summary = {
        "task": task.id,
        "status": status if task.test_cmd or status == "fail" else "pass-unverified",
        "rounds": rounds,
        "files_written": sorted(written),
        "files_rejected": sorted(rejected),
        "files_missing": result.missing if result else task.write,
        "last_check_exit": result.check_code if result else None,
        "log_dir": str(log.dir.relative_to(ROOT)),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    }
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    (log.task_dir / "latest.json").write_text(text, encoding="utf-8")
    print(text)
    return 0 if status == "pass" else 1


# ---------------------------------------------------------------- main


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("task_file", nargs="?", help=".agents/tasks/<ID>.json")
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true", help="build prompt and report size only")
    parser.add_argument("--ping", action="store_true", help="check the model endpoint")
    args = parser.parse_args()

    load_env_file(ROOT / ".env.agents")

    if args.ping:
        cfg = ModelConfig.from_env()
        content, finish, usage = chat(cfg, [{"role": "user", "content": "ตอบคำเดียวว่า pong"}])
        print(json.dumps({"status": "ok", "model": cfg.model, "reply": strip_thinking(content).strip(),
                          "finish_reason": finish, "usage": usage}, ensure_ascii=False))
        return

    if not args.task_file:
        parser.error("task_file is required unless --ping")
    task = Task.load(ROOT / args.task_file)

    if args.dry_run:
        prompt = build_prompt(task, "")
        ctx = int(os.environ.get("QWEN_CONTEXT_TOKENS", "128000"))
        max_tok = int(os.environ.get("QWEN_MAX_TOKENS", "16384"))
        tokens = estimate_tokens(SYSTEM_PROMPT + prompt)
        missing_reads = [p for p in task.read if not (ROOT / p).exists()]
        print(json.dumps({
            "task": task.id,
            "prompt_tokens_estimate": tokens,
            "answer_budget": max_tok,
            "context": ctx,
            "fits": tokens + max_tok <= int(ctx * 0.95),
            "missing_read_files": missing_reads,
        }, ensure_ascii=False, indent=2))
        sys.exit(0 if tokens + max_tok <= int(ctx * 0.95) else 3)

    cfg = ModelConfig.from_env()
    sys.exit(delegate(task, cfg, args.max_rounds))


if __name__ == "__main__":
    main()
