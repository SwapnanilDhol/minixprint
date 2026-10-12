"""Small helpers shared by the fun jobs (not a job module: no JOBS)."""
import datetime as _dt
import random


def today(ctx):
    """Today's date in the configured timezone (falls back to local time)."""
    now = _dt.datetime.fromtimestamp(ctx.now())
    tzname = ctx.setting("timezone")
    if tzname:
        try:
            from zoneinfo import ZoneInfo
            now = _dt.datetime.fromtimestamp(ctx.now(), ZoneInfo(tzname))
        except Exception:  # missing tzdata / py3.8: local time is close enough
            pass
    return now.date()


def rng(params, ctx, salt=""):
    """Random generator seeded by params.seed, else by today's date (reproducible)."""
    seed = params.get("seed")
    if seed is None:
        seed = today(ctx).isoformat()
    return random.Random("%s|%s" % (seed, salt))
