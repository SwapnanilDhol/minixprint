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

## Mac as print host

With the printer on the Mac's USB port, run the server as a launchd user agent so it
starts at login and is restarted if it dies (the Pi uses systemd for the same job).

```bash
./deploy/macos/install.sh   # from the repo root; needs .venv with `pip install -e .`
launchctl list | grep minixprint
curl -s http://127.0.0.1:8090/api/status      # "connected": true
tail -f ~/Library/Logs/minixprint/server.log
```

The agent runs `.venv/bin/minixprint serve --host 127.0.0.1 --port 8090` with
`RunAtLoad` and `KeepAlive`. If the USB device disappears or re-enumerates the server
keeps answering HTTP, reports `"connected": false` with the error, holds queued jobs, and
retries the connection every 2 s backing off to 30 s; a job that was mid-print is marked
failed. Re-run the script after moving the repo or recreating the venv.

Moving the printer to the Pi: either leave the Mac agent (it falls back to fake mode when
no printer is attached) or remove it:

```bash
launchctl bootout gui/$UID/com.minixprint.server
rm ~/Library/LaunchAgents/com.minixprint.server.plist
```
