"""The dashboard's web app: the live database or a replay's, always seen at one clock (vigil.web.views).

Every /api endpoint takes `replay`, an episode key (absent: live), and `at`, a time with its UTC offset. Live, `at`
defaults to now and may not be after it; in a replay it defaults to the episode's end and must fall inside the
episode. Model text reaches the browser only inside JSON, and the page inserts it as text, never as HTML. Every
page carries the disclaimer and the link to the official agency in its own markup.

    vigil-web --port 8000
"""

# No `from __future__ import annotations`: FastAPI resolves the endpoints' annotations, including the local `Seen`.

import argparse
import html
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from vigil import db
from vigil.agent.bulletin import DISCLAIMER_EN, DISCLAIMER_ES
from vigil.agent.tools import Metric
from vigil.calibration import load_calibration
from vigil.config import ConfigError, load_sources
from vigil.episodes import EPISODES
from vigil.prompts import Target
from vigil.replay import STEP, replay_dir
from vigil.settings import Settings
from vigil.timeutil import parse_utc, to_iso, utcnow
from vigil.web import views
from vigil.web.views import Scene

STATIC = Path(__file__).parent / "static"
LIVE_SPAN = timedelta(hours=24)  # how far back the live strips and series reach by default
MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png"}


def media_file(data_dir: Path, path: str) -> Path | None:
    """A bulletin's evidence overlay or an alert's frame under the data dir (inside a `bulletins` or `alerts`
    folder); None for anything else: frames, databases, pages, or a path that leaves the data dir."""
    root = data_dir.resolve()
    try:
        target = (root / path).resolve()
        if not target.is_relative_to(root) or target.suffix.lower() not in MEDIA_SUFFIXES or not target.is_file():
            return None
    except (OSError, ValueError):  # e.g. a NUL byte in the path
        return None
    folders = target.relative_to(root).parts[:-1]
    return target if "bulletins" in folders or "alerts" in folders else None


def _clock(at: str | None, default: datetime) -> datetime:
    if at is None:
        return default
    try:
        return parse_utc(at)
    except ValueError as exc:
        raise HTTPException(422, f"at: {exc}") from exc


def create_app(settings: Settings | None = None, *, volcano: str = "kilauea",
               now: Callable[[], datetime] = utcnow) -> FastAPI:
    settings = settings or Settings.from_env()
    sources = load_sources(settings.sources_path)
    calibration = load_calibration(settings.calibration_path)
    if volcano not in sources.volcanoes:
        raise ConfigError(f"unknown volcano {volcano!r} in {settings.sources_path}")
    info = sources.volcanoes[volcano]
    live_cameras = tuple(c.id for c in sources.enabled_cameras() if c.volcano == volcano)
    words = {"name": info.name, "agency": info.official_agency, "url": info.official_url}
    disclaimer = {"en": DISCLAIMER_EN.format(**words), "es": DISCLAIMER_ES.format(**words)}
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    for key, value in {"volcano_name": info.name, "official_agency": info.official_agency,
                       "official_url": info.official_url,
                       "notice_lead": DISCLAIMER_EN.split("{agency}")[0].format(name=info.name)}.items():
        page = page.replace("{{" + key + "}}", html.escape(value))

    app = FastAPI(title="Volcano Vigil")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def scene(replay: str | None = None, at: str | None = None) -> Iterator[Scene]:
        if replay is None:
            clock = _clock(at, now())
            if clock > now():
                raise HTTPException(422, f"at {to_iso(clock)} is after now")
            path, cameras, episode = settings.db_path, live_cameras, None
            if not path.is_file():
                raise HTTPException(503, "no live database yet: run vigil-ingest")
        else:
            episode = EPISODES.get(replay)
            if episode is None:
                raise HTTPException(404, f"no episode {replay!r}")
            path, cameras = replay_dir(settings.data_dir, episode) / "vigil.sqlite", episode.cameras
            if not path.is_file():
                raise HTTPException(404, f"episode {episode.key} has not been replayed: run vigil-replay "
                                         f"--episode {episode.key}")
            clock = _clock(at, episode.end)
            if not episode.start <= clock <= episode.end:
                raise HTTPException(422, f"at {to_iso(clock)} is outside episode {episode.key} "
                                         f"({to_iso(episode.start)} to {to_iso(episode.end)})")
        conn = db.connect_readonly(path)
        try:
            yield Scene(conn=conn, clock=clock, data_dir=settings.data_dir, sources=sources, calibration=calibration,
                        volcano=episode.volcano if episode else volcano, cameras=cameras, episode=episode)
        finally:
            conn.close()

    Seen = Annotated[Scene, Depends(scene)]

    def since_or_default(seen: Scene, since: str | None) -> datetime:
        return _clock(since, seen.episode.start if seen.episode else seen.clock - LIVE_SPAN)

    def found(call, *args, **kwargs):
        try:
            return call(*args, **kwargs)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return page

    @app.get("/api/config")
    def config() -> dict:
        vent = calibration.vents.get(volcano)
        replays = []
        for episode in EPISODES.values():
            folder = replay_dir(settings.data_dir, episode)
            if episode.volcano == volcano and (folder / "vigil.sqlite").is_file():
                replays.append({"episode": episode.key, "start": to_iso(episode.start), "end": to_iso(episode.end),
                                "cameras": list(episode.cameras), "step_minutes": STEP / timedelta(minutes=1)})
        return {
            "volcano": {"id": volcano, "name": info.name, "official_agency": info.official_agency,
                        "official_url": info.official_url, "utc_offset_hours": info.utc_offset_hours,
                        "lat": info.lat, "lon": info.lon},
            "vent": None if vent is None else {"lat": vent.lat, "lon": vent.lon, "elev_m": vent.elev_m},
            "disclaimer": disclaimer,
            "live": {"cameras": list(live_cameras), "available": settings.db_path.is_file()},
            "replays": replays, "now": to_iso(now()),
        }

    @app.get("/api/cameras")
    def cameras(seen: Seen) -> dict:
        return {"clock": seen.now, "cameras": views.camera_status(seen)}

    @app.get("/api/frames/latest")  # before /api/frames/{frame_id}, which would take "latest" for an id
    def latest(seen: Seen, camera: str) -> dict:
        return {"clock": seen.now, **found(views.latest_frames, seen, camera)}

    @app.get("/api/frames")
    def strip(seen: Seen, camera: str, since: str | None = None) -> dict:
        start = since_or_default(seen, since)
        return {"clock": seen.now, "camera_id": camera, "since": to_iso(start),
                "frames": found(views.frame_strip, seen, camera, start)}

    @app.get("/api/frames/{frame_id}")
    def one_frame(seen: Seen, frame_id: int) -> dict:
        shown = views.frame(seen, frame_id)
        if shown is None:
            raise HTTPException(404, f"no frame {frame_id} captured by {seen.now}")
        return {"clock": seen.now, "frame": shown}

    @app.get("/api/frames/{frame_id}/image")
    def image(seen: Seen, frame_id: int, overlay: bool = True,
              width: Annotated[int, Query(ge=320, le=1920)] = 1280) -> Response:
        body = found(views.frame_image, seen, frame_id, width=width, overlay=overlay)
        return Response(body, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/api/series")
    def series(seen: Seen, camera: str, target: Target, metric: Metric, since: str | None = None) -> dict:
        start = since_or_default(seen, since)
        return {"clock": seen.now, "since": to_iso(start),
                **found(views.series, seen, camera, target, metric, start)}

    @app.get("/api/bulletins")
    def bulletins(seen: Seen, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> dict:
        return {"clock": seen.now, "bulletins": views.bulletins(seen, limit)}

    @app.get("/api/alerts")
    def alerts(seen: Seen) -> dict:
        return {"clock": seen.now, **views.alerts(seen)}

    @app.get("/api/agent/trace")
    def trace(seen: Seen, run_id: int | None = None) -> dict:
        return {"clock": seen.now, **found(views.agent_trace, seen, run_id)}

    @app.get("/api/replay")
    def replay_state(seen: Seen) -> dict:
        if seen.episode is None:
            raise HTTPException(404, "pass replay=<episode> for a replay's state")
        return {"clock": seen.now, **views.replay_state(seen, replay_dir(settings.data_dir, seen.episode))}

    @app.get("/media/{path:path}")
    def media(path: str) -> FileResponse:
        target = media_file(settings.data_dir, path)
        if target is None:
            raise HTTPException(404, "not a bulletin or alert image")
        return FileResponse(target)

    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Serve the dashboard: live and replayed episodes.")
    parser.add_argument("--host", default="127.0.0.1", help="interface to listen on (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="port (default 8000)")
    args = parser.parse_args(argv)
    uvicorn.run(create_app(), host=args.host, port=args.port)