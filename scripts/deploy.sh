#!/usr/bin/env bash
# Deploy to the pve1 docker LXC: back up the DB, ship the code, rebuild, migrate, health-check.
#
#   scripts/deploy.sh            deploy the current working tree
#
# Overrides: DEPLOY_SSH (default root@100.85.149.32), DEPLOY_LXC (103), DEPLOY_DIR, DEPLOY_URL.
# The server keeps its own .env and cloudflared.env (never overwritten, never in git).
set -euo pipefail
cd "$(dirname "$0")/.."

SSH_TARGET="${DEPLOY_SSH:-root@100.85.149.32}"
LXC="${DEPLOY_LXC:-103}"
DIR="${DEPLOY_DIR:-/opt/realm-of-villages}"
URL="${DEPLOY_URL:-https://rov.codex074.com}"
in_lxc() { ssh "$SSH_TARGET" "lxc-attach -n $LXC -- sh -c '$1'"; }

echo "==> backup before deploy"
in_lxc "cd $DIR && mkdir -p backups && docker compose exec -T db pg_dump -U realm realm | gzip > backups/pre-deploy-\$(date +%Y%m%d-%H%M).sql.gz && ls -1t backups | head -3"

echo "==> ship code"
# COPYFILE_DISABLE stops macOS tar adding ._* files (they break alembic's migration loader)
COPYFILE_DISABLE=1 tar czf - --no-xattrs --exclude=.venv --exclude=.git --exclude=__pycache__ \
  --exclude=.pytest_cache --exclude=.ruff_cache --exclude=backups --exclude=.agents/runs \
  --exclude=.env --exclude=.env.agents --exclude=cloudflared.env --exclude=.claude --exclude='._*' . \
  | ssh "$SSH_TARGET" "lxc-attach -n $LXC -- sh -c 'mkdir -p $DIR && tar xzf - -C $DIR && find $DIR -name \"._*\" -delete'"

echo "==> build + start"
in_lxc "cd $DIR && docker compose --profile tunnel up -d --build 2>&1 | tail -15"

echo "==> health check"
ok=""
for i in 1 2 3 4 5 6; do
  if in_lxc "curl -sf -m 10 localhost:8080/api/auth/me >/dev/null"; then ok=1; break; fi
  sleep 5
done
[ -n "$ok" ] || { echo "FAILED: the game does not answer inside the LXC" >&2; exit 1; }
echo "OK inside the LXC (localhost:8080)"
code=$(curl -s -m 15 -o /dev/null -w '%{http_code}' "$URL/api/auth/me" || true)
if [ "$code" = "200" ]; then echo "OK public $URL"; else echo "note: public check returned '$code' (local DNS cache or tunnel); check $URL in a browser"; fi
