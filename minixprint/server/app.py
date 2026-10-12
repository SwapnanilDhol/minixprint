"""FastAPI app: REST under /api, dashboard at /. See docs/API.md."""
import io
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from .. import feeds as feed_kinds
from .. import jobs, render
from ..render import WIDTH
from .feeds import FeedError, FeedManager
from .queue import PrintQueue
from .scheduler import Scheduler, SpecError, parse_spec
from .store import Store

log = logging.getLogger("minixprint.server")
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

SERVER_DEFAULTS = {"density": 2, "max_height_px": 4000, "transport": "auto"}
PNG = "image/png"


class TextBody(BaseModel):
    text: str
    size: int = Field(28, ge=8, le=200)
    align: str = Field("left", pattern="^(left|center|right)$")
    bold: bool = False
    mono: bool = False
    density: Optional[int] = Field(None, ge=0, le=2)


class MarkdownBody(BaseModel):
    markdown: str
    size: int = Field(24, ge=8, le=200)
    density: Optional[int] = Field(None, ge=0, le=2)


class QrBody(BaseModel):
    data: str
    caption: Optional[str] = None
    density: Optional[int] = Field(None, ge=0, le=2)


class FeedBody(BaseModel):
    dots: int = Field(80, ge=1, le=2000)


class ScheduleBody(BaseModel):
    spec: str
    job: str
    params: Dict[str, Any] = {}
    enabled: bool = True


class SchedulePatch(BaseModel):
    enabled: Optional[bool] = None
    spec: Optional[str] = None
    params: Optional[Dict[str, Any]] = None


class FeedCreate(BaseModel):
    kind: str
    params: Dict[str, Any] = {}
    interval_s: Optional[int] = Field(None, ge=1, le=86400)
    enabled: bool = False


class SettingsBody(BaseModel):
    home_airport: Optional[str] = None
    airports: Optional[List[str]] = None
    density: Optional[int] = Field(None, ge=0, le=2)
    timezone: Optional[str] = None
    max_height_px: Optional[int] = Field(None, ge=100, le=100000)
    aircraft_json: Optional[str] = None
    aviation_bot_url: Optional[str] = None
    home_lat: Optional[float] = Field(None, ge=-90, le=90)
    home_lon: Optional[float] = Field(None, ge=-180, le=180)


def who(request: Request) -> str:
    h = request.headers
    return h.get("tailscale-user-name") or h.get("tailscale-user-login") or "local"


def _describe(fn) -> str:
    doc = (fn.__doc__ or "").strip() or (importlib_doc(fn) or "")
    return doc.splitlines()[0].replace("`", "").strip() if doc else ""


def importlib_doc(fn) -> str:
    import sys
    mod = sys.modules.get(getattr(fn, "__module__", ""))
    return ((mod.__doc__ if mod else "") or "").strip()


def create_app(data_dir: Optional[str] = None, fake: bool = False, root_path: Optional[str] = None,
               connect_fn=None, scheduler: bool = True) -> FastAPI:
    store = Store(data_dir)
    root = root_path if root_path is not None else os.environ.get("MINIXPRINT_ROOT_PATH", "")

    def settings() -> Dict[str, Any]:
        s = dict(jobs.DEFAULT_SETTINGS)
        s.update(SERVER_DEFAULTS)
        s.update(store.stored_settings())
        return s

    def tz() -> ZoneInfo:
        try:
            return ZoneInfo(settings()["timezone"])
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    queue = PrintQueue(store, settings, fake=fake, connect_fn=connect_fn)

    def ctx() -> jobs.JobContext:
        return jobs.JobContext(settings=settings())

    def run_scheduled(name: str, params: dict) -> None:
        try:
            img = jobs.run(name, params, ctx())
            queue.submit("job:" + name, img, "schedule: %s" % name, "scheduler", settings()["density"])
        except Exception as e:
            queue.record_failure("job:" + name, "schedule: %s" % name, "scheduler",
                                 "%s: %s" % (type(e).__name__, e))

    sched = Scheduler(store, run_scheduled, tz)
    feeds = FeedManager(store, queue, settings)

    @asynccontextmanager
    async def lifespan(app):
        queue.start()
        if scheduler:
            sched.start()
            feeds.start()
        yield
        feeds.stop()
        sched.stop()
        queue.stop()

    app = FastAPI(title="minixprint", root_path=root, lifespan=lifespan)
    app.state.queue, app.state.store, app.state.scheduler = queue, store, sched
    app.state.feeds = feeds

    # --- helpers -----------------------------------------------------------
    def finish(request: Request, img: Image.Image, kind: str, summary: str,
               density: Optional[int], dedupe: Optional[str] = None):
        """Preview routes return the PNG; print routes enqueue it."""
        cap = settings()["max_height_px"]
        if img.height > cap:
            raise HTTPException(413, "rendered height %d px exceeds max_height_px %d" % (img.height, cap))
        if request.scope["route"].path.startswith("/api/preview"):
            buf = io.BytesIO()
            img.save(buf, "PNG")
            return Response(buf.getvalue(), media_type=PNG, headers={"X-Height-Px": str(img.height)})
        d = settings()["density"] if density is None else density
        job = queue.submit(kind, img, summary, who(request), d, dedupe)
        return _job_out(job, queue.store.depth())

    def _job_out(job: Dict[str, Any], depth: int) -> Dict[str, Any]:
        return {"id": job["id"], "status": job["status"], "height_px": job["height"],
                "queue_depth": depth, "skipped_of": job.get("skipped_of")}

    def _hist(r: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": r["id"], "ts": r["ts"], "kind": r["kind"], "summary": r["summary"],
                "user": r["user"], "height_px": r["height"], "status": r["status"], "error": r["error"]}

    def render_guard(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(422, "%s: %s" % (type(e).__name__, e))

    def both(path: str, **kw):
        """Register one handler under /api/print/<path> and /api/preview/<path>."""
        def deco(fn):
            app.post("/api/print/" + path, **kw)(fn)
            app.post("/api/preview/" + path, **kw)(fn)
            return fn
        return deco

    # --- print / preview ---------------------------------------------------
    @both("text")
    def p_text(request: Request, b: TextBody):
        img = render_guard(render.render_text, b.text, size=b.size, align=b.align, bold=b.bold, mono=b.mono)
        return finish(request, img, "text", b.text.strip()[:60], b.density)

    @both("markdown")
    def p_markdown(request: Request, b: MarkdownBody):
        img = render_guard(render.render_markdown, b.markdown, size=b.size)
        return finish(request, img, "markdown", b.markdown.strip()[:60], b.density)

    @both("receipt")
    def p_receipt(request: Request, data: Dict[str, Any] = Body(...), density: Optional[int] = Query(None, ge=0, le=2)):
        img = render_guard(render.render_receipt, data)
        return finish(request, img, "receipt", str(data.get("title", "receipt"))[:60], density)

    @both("qr")
    def p_qr(request: Request, b: QrBody):
        img = render_guard(render.render_qr, b.data, caption=b.caption)
        return finish(request, img, "qr", b.data[:60], b.density)

    def _open(upload: UploadFile) -> Image.Image:
        try:
            img = Image.open(io.BytesIO(upload.file.read()))
            img.load()
            return img
        except (UnidentifiedImageError, OSError):
            raise HTTPException(415, "not a readable image")

    @both("image")
    def p_image(request: Request, file: UploadFile = File(...), dither: str = Query("fs", pattern="^(fs|atkinson|none)$"),
                gamma: float = Query(1.0, gt=0, le=5), invert: bool = False,
                density: Optional[int] = Query(None, ge=0, le=2)):
        img = render_guard(render.render_image, _open(file), dither=dither, gamma=gamma, invert=invert)
        return finish(request, img, "image", file.filename or "image", density)

    @both("raw")
    def p_raw(request: Request, file: UploadFile = File(...), density: Optional[int] = Query(None, ge=0, le=2)):
        img = _open(file)
        if img.width != WIDTH:
            raise HTTPException(400, "raw images must be exactly %d px wide (got %d)" % (WIDTH, img.width))
        if img.mode != "1":
            img = img.convert("L").point(lambda v: 255 if v >= 128 else 0).convert("1")
        return finish(request, img, "raw", file.filename or "raw", density)

    # --- jobs --------------------------------------------------------------
    @app.get("/api/jobs")
    def list_jobs():
        return [{"name": n, "description": _describe(fn)} for n, fn in sorted(jobs.discover().items())]

    @app.post("/api/jobs/{name}/run")
    @app.post("/api/preview/jobs/{name}")
    def run_job(request: Request, name: str, params: Dict[str, Any] = Body(default={}),
                dedupe: Optional[str] = None, density: Optional[int] = Query(None, ge=0, le=2)):
        if name not in jobs.discover():
            raise HTTPException(404, "unknown job %r" % name)
        try:
            img = jobs.run(name, params, ctx())
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500 if not isinstance(e, ValueError) else 422,
                                "job %s failed: %s: %s" % (name, type(e).__name__, e))
        return finish(request, img, "job:" + name, name, density, dedupe)

    # --- misc --------------------------------------------------------------
    @app.get("/api/status")
    def status(request: Request):
        return dict(queue.status(), user=who(request), timezone=settings()["timezone"])

    @app.post("/api/feed")
    def feed(request: Request, b: FeedBody):
        job = queue.submit_feed(b.dots, who(request))
        return _job_out(job, queue.store.depth())

    @app.get("/api/history")
    def history(limit: int = Query(30, ge=1, le=500)):
        return [_hist(r) for r in store.history(limit)]

    @app.get("/api/history/{job_id}.png")
    def history_png(job_id: int):
        path = store.png_path(job_id)
        if not os.path.exists(path):
            raise HTTPException(404, "no image for job %d" % job_id)
        return FileResponse(path, media_type=PNG)

    # --- schedules ---------------------------------------------------------
    def _check_sched(spec: str, job: Optional[str]) -> None:
        try:
            parse_spec(spec)
        except SpecError as e:
            raise HTTPException(422, str(e))
        if job is not None and job not in jobs.discover():
            raise HTTPException(404, "unknown job %r" % job)

    @app.get("/api/schedules")
    def get_schedules():
        return store.schedules()

    @app.post("/api/schedules", status_code=201)
    def add_schedule(b: ScheduleBody):
        _check_sched(b.spec, b.job)
        return store.add_schedule(b.spec.strip(), b.job, b.params, b.enabled)

    @app.patch("/api/schedules/{sid}")
    def patch_schedule(sid: int, b: SchedulePatch):
        if not store.schedule(sid):
            raise HTTPException(404, "no such schedule")
        fields = {k: v for k, v in b.model_dump().items() if v is not None}
        if "spec" in fields:
            _check_sched(fields["spec"], None)
        if "params" in fields:
            import json
            fields["params"] = json.dumps(fields["params"])
        if fields:
            store.update_schedule(sid, **fields)
        return store.schedule(sid)

    @app.delete("/api/schedules/{sid}", status_code=204)
    def del_schedule(sid: int):
        if not store.delete_schedule(sid):
            raise HTTPException(404, "no such schedule")
        return Response(status_code=204)

    # --- feeds -------------------------------------------------------------
    def _feed_or_404(fid: int) -> Dict[str, Any]:
        f = store.feed(fid)
        if not f:
            raise HTTPException(404, "no such feed")
        return f

    @app.get("/api/feeds/kinds")
    def feed_kinds_list():
        return [{"kind": k, "description": getattr(m, "DESCRIPTION", ""), "params": m.PARAMS,
                 "default_interval_s": m.DEFAULT_INTERVAL_S}
                for k, m in sorted(feed_kinds.discover().items())]

    @app.get("/api/feeds")
    def list_feeds():
        return [feeds.view(f) for f in store.feeds()]

    @app.post("/api/feeds", status_code=201)
    def add_feed(b: FeedCreate):
        try:
            return feeds.view(feeds.create(b.kind, b.params, b.interval_s, b.enabled))
        except FeedError as e:
            raise HTTPException(422, str(e))

    @app.post("/api/feeds/{fid}/start")
    def start_feed(fid: int):
        _feed_or_404(fid)
        store.update_feed(fid, enabled=True)
        return feeds.view(store.feed(fid))

    @app.post("/api/feeds/{fid}/stop")
    def stop_feed(fid: int):
        _feed_or_404(fid)
        store.update_feed(fid, enabled=False)
        return feeds.view(store.feed(fid))

    @app.delete("/api/feeds/{fid}", status_code=204)
    def del_feed(fid: int):
        if not store.delete_feed(fid):
            raise HTTPException(404, "no such feed")
        return Response(status_code=204)

    @app.post("/api/feeds/{fid}/poll")
    def poll_feed(fid: int):
        _feed_or_404(fid)
        return feeds.view(feeds.poll(fid))

    @app.get("/api/feeds/{fid}/preview")
    def preview_feed(fid: int):
        _feed_or_404(fid)
        try:
            img = feeds.preview(fid)
        except Exception as e:
            raise HTTPException(502, "%s: %s" % (type(e).__name__, e))
        if img is None:
            raise HTTPException(404, "nothing to preview yet")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return Response(buf.getvalue(), media_type=PNG, headers={"X-Height-Px": str(img.height)})

    # --- settings ----------------------------------------------------------
    @app.get("/api/settings")
    def get_settings():
        s = settings()
        keys = ("home_airport", "airports", "density", "timezone", "max_height_px",
                "aircraft_json", "aviation_bot_url", "home_lat", "home_lon")
        return {k: s[k] for k in keys}

    @app.put("/api/settings")
    def put_settings(b: SettingsBody):
        vals = {k: v for k, v in b.model_dump().items() if v is not None}
        if "timezone" in vals:
            try:
                ZoneInfo(vals["timezone"])
            except (ZoneInfoNotFoundError, ValueError):
                raise HTTPException(422, "unknown timezone %r" % vals["timezone"])
        if "airports" in vals:
            vals["airports"] = [a.strip().upper() for a in vals["airports"] if a.strip()]
        if "home_airport" in vals:
            vals["home_airport"] = vals["home_airport"].strip().upper()
        store.put_settings(vals)
        return get_settings()

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app
