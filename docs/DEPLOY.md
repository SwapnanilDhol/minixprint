# Deploy runbook (swap-pi)

URL: https://swap-pi.<tailnet>.ts.net/print/ (tailnet only; never enable Funnel).

## Redeploy

```bash
./deploy/deploy.sh          # from the repo root; rsync + pip install -e . + restart + status check
```

Idempotent. Override the host with `DEPLOY_HOST=...`. History/settings live in
`~/.local/share/minixprint` on the Pi and are not touched.

## Operate

```bash
ssh swap-pi 'journalctl -u minixprint -f'            # logs
ssh swap-pi 'systemctl status minixprint'
ssh swap-pi 'curl -s http://127.0.0.1:8090/api/status'
ssh swap-pi 'tailscale serve status'                 # expect /, /radio, /print
sudo tailscale serve --set-path /print off           # (on the Pi) remove the front door
```

## Switch the printer to the Pi

1. Unplug the USB cable from the Mac, plug it into the Pi (it also charges the printer).
2. `ssh swap-pi 'ls -l /dev/minix /dev/ttyACM*'` — both should exist (udev rule is installed).
   If not: `sudo udevadm trigger`, or replug.
3. `ssh swap-pi 'sudo systemctl restart minixprint'` (the server only detects the printer at start).
4. `curl -s https://swap-pi.<tailnet>.ts.net/print/api/status` → `"fake": false`, `"connected": true`.
5. Print a test from the dashboard. Quit anything on the Mac that still holds the printer.

Going back to the Mac: unplug from the Pi, plug into the Mac, restart the service if you
want it to fall back to fake mode.
