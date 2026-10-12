# Publishing over Tailscale

The server binds to loopback only; `tailscale serve` is the front door (HTTPS, tailnet-only).

```bash
sudo systemctl enable --now minixprint        # unit in deploy/minixprint.service
curl http://127.0.0.1:8090/api/status         # sanity check

# the aviation bot already owns / (:8070) and /radio (:8888); add /print
sudo tailscale serve --bg --set-path /print http://127.0.0.1:8090
tailscale serve status
```

→ `https://swap-pi.<tailnet>.ts.net/print/` (dashboard) and `…/print/api/...` (API).

Notes:

- Tailscale strips `/print` before proxying; the unit passes `--root-path /print` so OpenAPI docs
  (`/print/docs`) point at the right URLs. The dashboard uses relative URLs and needs the trailing slash.
- Requests carry `Tailscale-User-Login` and `Tailscale-User-Name`; the server stores the name with each job
  and shows it in the status bar. There is no other auth — it is the tailnet that gates access.
- **Never enable Funnel** (`tailscale funnel`) for this path: anyone on the internet could print.
- Remove with `sudo tailscale serve --set-path /print off`.
