#!/usr/bin/env bash
# Run Qwen tasks in parallel: one git worktree + one scratch test database per task.
#
#   scripts/wt.sh new <name>                 create worktree ../rov-worktrees/<name> (branch task/<name> from main) + DB
#   scripts/wt.sh run <name> <task.json> [rounds]   delegate the task inside that worktree (own DB, own .agents/runs)
#   scripts/wt.sh test <name> [pytest args]  run pytest in the worktree against its own DB
#   scripts/wt.sh merge <name>               `git merge --squash task/<name>` into the CURRENT branch of the main checkout
#   scripts/wt.sh rm <name>                  remove worktree, branch and DB
#
# The task JSON must already be committed on main before `new`.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WT_DIR="$(dirname "$ROOT")/rov-worktrees"
DB_CONTAINER="${REALM_TEST_DB_CONTAINER:-realofvillages-db_test-1}"
cmd="${1:-}"
name="${2:?usage: wt.sh <new|run|test|merge|rm> <name> ...}"
db_name="realm_test_$(printf %s "${name//[^a-zA-Z0-9]/_}" | tr A-Z a-z)"  # postgres folds unquoted names to lower case
db_url="postgresql+psycopg://realm_test:realm_test@localhost:5433/${db_name}"

psql_admin() { docker exec "$DB_CONTAINER" psql -U realm_test -d postgres -v ON_ERROR_STOP=1 -q -c "$1"; }

case "$cmd" in
  new)
    git -C "$ROOT" worktree add -q -b "task/$name" "$WT_DIR/$name" main
    psql_admin "create database $db_name"
    (cd "$WT_DIR/$name" && uv sync -q)
    echo "worktree: $WT_DIR/$name"
    echo "database: $db_url"
    ;;
  run)
    task="${3:?task json path (relative to repo root)}"
    (cd "$WT_DIR/$name" && REALM_TEST_DATABASE_URL="$db_url" python3 scripts/delegate_9arm.py "$task" --max-rounds "${4:-3}")
    ;;
  test)
    (cd "$WT_DIR/$name" && REALM_TEST_DATABASE_URL="$db_url" uv run pytest "${@:3}")
    ;;
  merge)
    git -C "$ROOT" merge --squash "task/$name"
    ;;
  rm)
    git -C "$ROOT" worktree remove --force "$WT_DIR/$name"
    git -C "$ROOT" branch -D "task/$name" >/dev/null 2>&1 || true
    psql_admin "drop database if exists $db_name"
    ;;
  *)
    echo "unknown command: $cmd" >&2
    exit 2
    ;;
esac
