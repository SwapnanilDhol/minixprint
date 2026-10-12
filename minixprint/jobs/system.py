"""``system.status``: a health slip for the Pi (host, uptime, load, disk, IPs)."""
import os
import platform
import shutil
import socket
import subprocess
import time

from ..render import render_text, rule, stack


def _uptime_seconds():
    try:
        with open("/proc/uptime") as fh:
            return float(fh.read().split()[0])
    except OSError:
        pass
    try:  # macOS / BSD: "{ sec = 1700000000, usec = 0 } ..."
        out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True,
                             text=True, timeout=3).stdout
        sec = int(out.split("sec =")[1].split(",")[0])
        return time.time() - sec
    except Exception:
        return None


def fmt_duration(s):
    if s is None:
        return "?"
    s = int(s)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m = s // 60
    return ("%dd " % d if d else "") + "%dh %02dm" % (h, m)


def local_ip():
    try:  # UDP "connect" picks the outbound interface without sending anything
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def tailscale_ip():
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True,
                             timeout=3)
        return out.stdout.split()[0] if out.returncode == 0 and out.stdout.strip() else None
    except Exception:
        return None


def status_lines(ctx):
    rows = [("host", socket.gethostname()),
            ("os", "%s %s" % (platform.system(), platform.machine())),
            ("time", time.strftime("%Y-%m-%d %H:%M", time.localtime(ctx.now()))),
            ("uptime", fmt_duration(_uptime_seconds()))]
    try:
        rows.append(("load", " ".join("%.2f" % x for x in os.getloadavg())))
    except (OSError, AttributeError):
        pass
    try:
        du = shutil.disk_usage("/")
        rows.append(("disk", "%.1f GB free (%d%%)" % (du.free / 1e9, 100 * du.free // du.total)))
    except OSError:
        pass
    ip = local_ip()
    if ip:
        rows.append(("lan", ip))
    ts = tailscale_ip()
    if ts:
        rows.append(("tailnet", ts))
    return rows


def status(params, ctx):
    rows = status_lines(ctx)
    body = "\n".join("%-8s%s" % (k, v) for k, v in rows)
    return stack(render_text("SYSTEM STATUS", size=26, bold=True, align="center", margin=4),
                 rule("double"), render_text(body, size=18, mono=True, margin=6), gap=2)


JOBS = {"system.status": status}
