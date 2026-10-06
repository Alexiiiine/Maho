"""Loopback-only browser workspace for the existing file-backed pipeline."""

import json
import math
import mimetypes
import os
import re
import secrets
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from uuid import uuid4

from .credentials import get_key
from .media import executable
from .selection import SelectionOptions
from .rendering import RenderOptions
from .storage import job_lock, read_json, write_json

WEB_ROOT = Path(__file__).parent / "web"


def optional_json(path):
    try:
        return read_json(path)
    except (OSError, ValueError):
        return {}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def clip_available(directory, clip):
    sidecar = optional_json(directory / "clips" / f"{clip['clip_id']}.json")
    settings = optional_json(directory / "job.json").get("render_settings", {})
    return ((directory / "clips" / f"{clip['clip_id']}.mp4").is_file() and
            all(sidecar.get("padding", {}).get(key) == value for key, value in settings.items()) and
            all(sidecar.get(key) == value for key, value in clip.items()))


def job_running(directory):
    """Recover live CLI/child jobs after a UI-server restart using their OS lock."""
    if not (directory / ".lock").is_file():
        return False
    try:
        with job_lock(directory):
            pass
    except RuntimeError:
        return True
    except OSError:
        return False
    return False


def pipeline_runner(request, directory, log_path):
    # A separate process keeps provider/network and FFmpeg work off HTTP threads.
    args = [sys.executable, "-u", "-m", "maho", "run", request["video"],
            "--output", str(directory), "--count", str(request["count"]),
            "--min-seconds", str(request["min_seconds"]),
            "--max-seconds", str(request["max_seconds"]), "--criteria", request["criteria"],
            "--model", request["model"], "--reasoning-effort", request["reasoning_effort"],
            "--lead-seconds", str(request["lead_seconds"]), "--tail-seconds", str(request["tail_seconds"])]
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                   env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        return process.wait()


class RunCatalog:
    def __init__(self, root, runner=pipeline_runner):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.runner = runner
        self.active = set()
        self.lock = threading.Lock()
        self.thumbnail_lock = threading.Lock()

    def directory(self, run_id):
        if not run_id or run_id in (".", "..") or "/" in run_id or "\\" in run_id:
            raise FileNotFoundError("Unknown run.")
        directory = (self.root / run_id).resolve()
        if (directory.parent != self.root or not directory.is_dir() or
                not any((directory / name).is_file() for name in ("job.json", ".browser.json"))):
            raise FileNotFoundError("Unknown run.")
        return directory

    def summary(self, directory):
        job = optional_json(directory / "job.json")
        browser = optional_json(directory / ".browser.json")
        manifest = optional_json(directory / "render_manifest.json")
        metadata = optional_json(directory / "selection.metadata.json")
        selected = optional_json(directory / "clips.json")
        source = job.get("source_video") or browser.get("request", {}).get("video", "")
        with self.lock:
            active = directory.name in self.active
        active = active or job_running(directory)
        complete = (manifest.get("status") == "completed" and
                    manifest.get("selection_sha256") == metadata.get("selection_sha256") and
                    all(clip_available(directory, c) for c in selected.get("clips", [])))
        resumed = (job.get("render_completed_at", "") > browser.get("updated_at", ""))
        if active:
            status = "running"
        elif complete and (resumed or browser.get("status") not in ("queued", "running", "failed")):
            status = "completed"
        elif browser.get("status") in ("queued", "running"):
            status = "interrupted"
        elif browser.get("status") == "failed":
            status = "failed"
        elif selected:
            status = "selected"
        elif (directory / "transcript.json").exists():
            status = "transcribed"
        else:
            status = "incomplete"
        return {"id": directory.name, "filename": Path(source).name or directory.name,
                "source_video": source, "source_available": Path(source).is_file() if source else False,
                "status": status, "duration_seconds": job.get("duration_seconds", 0),
                "clip_count": len(selected.get("clips", [])),
                "created_at": job.get("created_at") or browser.get("created_at"),
                "updated_at": browser.get("updated_at") or job.get("updated_at")}

    def list(self):
        directories = [p for p in self.root.iterdir() if p.is_dir() and
                       p.resolve().parent == self.root and
                       any((p / name).is_file() for name in ("job.json", ".browser.json"))]
        return sorted((self.summary(p) for p in directories),
                      key=lambda item: item["created_at"] or "", reverse=True)

    def detail(self, run_id):
        directory = self.directory(run_id)
        summary = self.summary(directory)
        metadata = optional_json(directory / "selection.metadata.json")
        selected = optional_json(directory / "clips.json")
        browser = optional_json(directory / ".browser.json")
        manifest = optional_json(directory / "render_manifest.json")
        rendered = {c["clip_id"]: c for c in manifest.get("clips", [])}
        clips = []
        for clip in selected.get("clips", []):
            clip_id = clip.get("clip_id", "")
            if not re.fullmatch(r"clip_\d+", clip_id):
                continue
            record = rendered.get(clip_id, {})
            available = clip_available(directory, clip)
            clips.append({**clip, "available": available,
                          "render_revision": record.get("render_sha256", ""), "padding": record.get("padding"),
                          "rendered_duration_seconds": record.get("rendered_duration_seconds")})
        transcript = directory / "transcript.txt"
        log = directory / ".browser.log"
        # No raw provider responses, upload URLs, or credentials are exposed.
        return {**summary, "output_directory": str(directory), "clips": clips,
                "selection": selected, "settings": metadata.get("settings") or browser.get("request", {}),
                "render_settings": optional_json(directory / "job.json").get("render_settings") or {
                    key: browser.get("request", {}).get(key, 0) for key in ("lead_seconds", "tail_seconds")},
                "editorial_review": metadata.get("editorial_review"),
                "error": browser.get("error") if summary["status"] != "completed" else None,
                "transcript": transcript.read_text(encoding="utf-8") if transcript.exists() else "",
                "log": log.read_text(encoding="utf-8", errors="replace")[-100000:] if log.exists()
                else "This run was created outside the browser. Live logs were not recorded.\n"
                     "Use the Overview, Transcript, and Selection JSON tabs to inspect its saved results."}

    def file(self, run_id, name):
        directory = self.directory(run_id)
        if name == "source":
            source = self.summary(directory)["source_video"]
            path = Path(source) if source else directory / "missing-video"
        else:
            mapping = {"transcript": "transcript.txt", "words": "transcript.timestamped.txt",
                       "transcript-json": "transcript.json", "selection": "clips.json"}
            if name in mapping:
                path = directory / mapping[name]
            elif re.fullmatch(r"clip_\d+\.(mp4|srt|json)", name):
                clip_id = name.rsplit(".", 1)[0]
                selected = optional_json(directory / "clips.json")
                clip = next((c for c in selected.get("clips", []) if c.get("clip_id") == clip_id), None)
                if clip is None:
                    raise FileNotFoundError("Unknown clip.")
                if not clip_available(directory, clip):
                    raise FileNotFoundError("This clip has not been rendered for the current selection.")
                path = directory / "clips" / name
            else:
                raise FileNotFoundError("Unknown file.")
            if not path.resolve().is_relative_to(directory):
                raise FileNotFoundError("Unknown file.")
        if not path.is_file():
            raise FileNotFoundError("File is unavailable on this computer.")
        return path

    def thumbnail(self, run_id, name):
        source = self.file(run_id, "source" if name == "source" else f"{name}.mp4")
        directory = self.directory(run_id) / ".browser-thumbnails"
        directory.mkdir(exist_ok=True)
        target = directory / f"{name}-{source.stat().st_mtime_ns}.jpg"
        with self.thumbnail_lock:
            if not target.exists():
                result = subprocess.run([executable("ffmpeg"), "-v", "error", "-nostdin", "-y",
                                         "-ss", "0.5", "-i", str(source), "-frames:v", "1",
                                         "-vf", "scale=640:-2", "-q:v", "4", str(target)],
                                        capture_output=True, timeout=30,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if result.returncode or not target.exists():
                    raise FileNotFoundError("Preview is unavailable.")
        return target

    def start(self, data):
        if not isinstance(data, dict):
            raise ValueError("Expected run settings.")
        video = Path(str(data.get("video", "")).strip().strip('"')).expanduser().resolve()
        if not video.is_file():
            raise ValueError("Enter the full path to a video file on this computer.")
        count = data.get("count", 5)
        minimum, maximum = data.get("min_seconds", 30), data.get("max_seconds", 60)
        if (type(count) is not int or type(minimum) not in (int, float) or
                type(maximum) not in (int, float) or not all(math.isfinite(x) for x in (minimum, maximum))):
            raise ValueError("Clip count and durations must be valid numbers.")
        criteria = data.get("criteria", "")
        if not isinstance(criteria, str) or len(criteria) > 20000:
            raise ValueError("Editorial instructions must be text under 20,000 characters.")
        SelectionOptions(count=count, min_seconds=minimum, max_seconds=maximum, criteria=criteria).validate()
        rendering = RenderOptions(lead_seconds=data.get("lead_seconds", 1.5), tail_seconds=data.get("tail_seconds", 1.5))
        rendering.validate()
        if self.runner is pipeline_runner:
            get_key("assemblyai")
            get_key("openai")
            executable("ffmpeg")
            executable("ffprobe")
        defaults = SelectionOptions()
        request = {"video": str(video), "count": count, "min_seconds": minimum,
                   "max_seconds": maximum, "criteria": criteria,
                   "model": defaults.model, "reasoning_effort": defaults.reasoning_effort,
                   "lead_seconds": rendering.lead_seconds, "tail_seconds": rendering.tail_seconds}
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", video.stem).strip("-")[:50] or "video"
        run_id = f"{slug}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
        directory = self.root / run_id
        with self.lock:
            if self.active or any(job_running(p) for p in self.root.iterdir() if p.is_dir()):
                raise ValueError("A run is already processing. Wait for it to finish before starting another.")
            directory.mkdir()
            state = {"status": "queued", "created_at": utc_now(), "updated_at": utc_now(), "request": request}
            write_json(directory / ".browser.json", state)
            self.active.add(run_id)
        threading.Thread(target=self._work, args=(directory, state), daemon=True).start()
        return {"id": run_id}

    def _work(self, directory, state):
        try:
            state.update(status="running", updated_at=utc_now())
            write_json(directory / ".browser.json", state)
            result = self.runner(state["request"], directory, directory / ".browser.log")
            state.update(status="completed" if result == 0 else "failed", updated_at=utc_now())
            if result:
                state["error"] = "The pipeline stopped. Open Run log for the error and saved progress."
        except Exception as exc:
            state.update(status="failed", updated_at=utc_now(), error=f"Run failed: {type(exc).__name__}.")
        finally:
            try:
                write_json(directory / ".browser.json", state)
            finally:
                with self.lock:
                    self.active.discard(directory.name)


class WorkspaceServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, catalog, web_root=WEB_ROOT):
        self.catalog = catalog
        self.web_root = Path(web_root).resolve()
        self.token = secrets.token_urlsafe(32)
        super().__init__(address, WorkspaceHandler)


class WorkspaceHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def guard(self, write=False):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if host not in hosts or (origin and origin != f"http://{host}"):
            self.json_response({"error": "This interface is available only on this computer."}, 403)
            return False
        if write and not secrets.compare_digest(self.headers.get("X-Maho-Token", ""), self.server.token):
            self.json_response({"error": "Reload the interface before starting a run."}, 403)
            return False
        return True

    def common_headers(self, status, content_type, length):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; media-src 'self'; "
                         "style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")

    def json_response(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.common_headers(status, "application/json; charset=utf-8", len(body))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.guard():
            return
        url = urlsplit(self.path)
        parts = [unquote(p) for p in url.path.strip("/").split("/") if p]
        try:
            if parts == ["api", "config"]:
                defaults = SelectionOptions()
                return self.json_response({"token": self.server.token, "defaults": {
                    "model": defaults.model, "reasoning_effort": defaults.reasoning_effort,
                    "count": defaults.count, "min_seconds": defaults.min_seconds,
                    "max_seconds": defaults.max_seconds, "lead_seconds": RenderOptions().lead_seconds,
                    "tail_seconds": RenderOptions().tail_seconds}})
            if parts == ["api", "runs"]:
                return self.json_response(self.server.catalog.list())
            if len(parts) == 3 and parts[:2] == ["api", "runs"]:
                return self.json_response(self.server.catalog.detail(parts[2]))
            if len(parts) == 5 and parts[:2] == ["api", "runs"]:
                if parts[3] == "files":
                    return self.send_file(self.server.catalog.file(parts[2], parts[4]),
                                          download="download=1" in url.query)
                if parts[3] == "thumbnails" and re.fullmatch(r"source|clip_\d+", parts[4]):
                    return self.send_file(self.server.catalog.thumbnail(parts[2], parts[4]))
            if parts and parts[0] == "api":
                raise FileNotFoundError("Unknown endpoint.")
            path = (self.server.web_root / (unquote(url.path).lstrip("/") or "index.html")).resolve()
            if not path.is_relative_to(self.server.web_root) or not path.is_file():
                raise FileNotFoundError("Page not found.")
            return self.send_file(path)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self.json_response({"error": str(exc)}, 404)

    def do_POST(self):
        if not self.guard(write=True):
            return
        if urlsplit(self.path).path != "/api/runs":
            return self.json_response({"error": "Unknown endpoint."}, 404)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 100000:
                raise ValueError("Invalid request size.")
            data = json.loads(self.rfile.read(size))
            return self.json_response(self.server.catalog.start(data), 202)
        except (OSError, ValueError, RuntimeError) as exc:
            return self.json_response({"error": str(exc)}, 400)

    def send_file(self, path, download=False):
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        requested = self.headers.get("Range")
        if requested:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
            if not match or not any(match.groups()):
                return self.range_error(size)
            first, last = match.groups()
            if first:
                start = int(first)
                end = min(int(last), end) if last else end
            else:
                start = max(0, size - int(last))
            if start > end or start >= size:
                return self.range_error(size)
            status = 206
        length = max(0, end - start + 1)
        mime = {".js": "text/javascript", ".css": "text/css", ".srt": "text/plain; charset=utf-8"}.get(
            path.suffix.lower(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.common_headers(status, mime, length)
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download:
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(path.name)}")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with path.open("rb") as source:
                source.seek(start)
                remaining = length
                while remaining:
                    chunk = source.read(min(128 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # Browsers cancel byte requests when the viewer seeks or switches clips.

    def range_error(self, size):
        self.send_response(416)
        self.send_header("Content-Range", f"bytes */{size}")
        self.send_header("Content-Length", "0")
        self.end_headers()


def serve(runs_dir="outputs", port=8765, open_browser=True):
    if not (WEB_ROOT / "index.html").is_file():
        raise RuntimeError("Browser interface is not built. Run 'npm --prefix frontend ci' and 'npm --prefix frontend run build'.")
    server = WorkspaceServer(("127.0.0.1", port), RunCatalog(runs_dir))
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Maho browser interface: {url}\nRuns: {server.catalog.root}\nPress Ctrl+C to stop.", flush=True)
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
