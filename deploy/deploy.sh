#!/usr/bin/env bash
# Idempotent deploy to the Pi. Run from the repo root: ./deploy/deploy.sh
set -euo pipefail
HOST="${DEPLOY_HOST:-swap-pi}"
cd "$(dirname "$0")/.."

rsync -az --delete \
  --exclude .git --exclude .venv --exclude .claude --exclude __pycache__ \
  --exclude '*.egg-info' --exclude .pytest_cache \
  ./ "$HOST:minixprint/"

ssh "$HOST" 'bash -s' <<'REMOTE'
set -euo pipefail
cd ~/minixprint
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -e .

# systemd unit with this host's user/home substituted
sed -e "s|^User=.*|User=$(id -un)|" \
    -e "s|/home/swapnanildhol|$HOME|g" deploy/minixprint.service \
  | sudo tee /etc/systemd/system/minixprint.service >/dev/null

# printer access: stable /dev/minix name + dialout membership
sudo install -m 644 deploy/udev/99-minix.rules /etc/udev/rules.d/99-minix.rules
sudo udevadm control --reload-rules
id -nG | tr ' ' '\n' | grep -qx dialout || sudo usermod -aG dialout "$(id -un)"

sudo systemctl daemon-reload
sudo systemctl enable minixprint >/dev/null 2>&1
sudo systemctl restart minixprint
for _ in $(seq 1 20); do
  curl -sf http://127.0.0.1:8090/api/status && { echo; exit 0; }
  sleep 1
done
echo "service did not come up:" >&2
sudo journalctl -u minixprint -n 30 --no-pager >&2
exit 1
REMOTE
