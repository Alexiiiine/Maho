"""Real HTTP tests for history, bounded media access, and background jobs."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from maho.storage import job_lock, write_json
from maho.web_server import RunCatalog, WorkspaceServer


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.outputs = self.root / "outputs"
        self.run = self.outputs / "previous"
        (self.run / "clips").mkdir(parents=True)
        self.video = self.root / "input.mp4"
        self.video.write_bytes(b"0123456789abcdefghij")
        self.clip = {"clip_id": "clip_01", "title": "A real clip", "source_start": "00:00:01.000"}
        write_json(self.run / "job.json", {"source_video": str(self.video), "duration_seconds": 20,
                   "created_at": "2026-10-06T00:00:00+00:00", "upload_url": "PRIVATE_UPLOAD_URL"})
        write_json(self.run / "clips.json", {"clips": [self.clip]})
        write_json(self.run / "selection.metadata.json", {"selection_sha256": "fingerprint", "settings": {"count": 5}})
        write_json(self.run / "clips" / "clip_01.json", self.clip)
        (self.run / "clips" / "clip_01.mp4").write_bytes(b"clip-media")
        (self.run / "clips" / "clip_01.srt").write_text("Subtitle", encoding="utf-8")
        (self.run / "transcript.txt").write_text("[00:00:01.000] Hello.", encoding="utf-8")
        write_json(self.run / "render_manifest.json", {"status": "completed", "selection_sha256": "fingerprint",
                   "clips": [{"clip_id": "clip_01", "rendered_duration_seconds": 10}]})
        private = self.run / "superseded-first-pass"
        private.mkdir()
        write_json(private / "job.json", {"source_video": str(self.video)})
        self.web = self.root / "web"
        self.web.mkdir()
        (self.web / "index.html").write_text("<h1>Maho</h1>", encoding="utf-8")
        self.finished = threading.Event()

        def runner(request, directory, log_path):
            log_path.write_text("Transcription completed.\n", encoding="utf-8")
            write_json(directory / "job.json", {"source_video": request["video"], "duration_seconds": 20})
            self.finished.set()
            return 0

        self.catalog = RunCatalog(self.outputs, runner=runner)
        self.server = WorkspaceServer(("127.0.0.1", 0), self.catalog, self.web)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def fetch(self, path, headers=None, data=None):
        req = Request(self.base + path, headers=headers or {}, data=data)
        with urlopen(req) as result:
            return result.status, dict(result.headers), result.read()

    def test_history_and_detail_expose_saved_results_without_private_provider_data(self):
        _, _, body = self.fetch("/api/runs")
        runs = json.loads(body)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "completed")
        _, _, detail = self.fetch("/api/runs/previous")
        self.assertNotIn(b"PRIVATE_UPLOAD_URL", body + detail)
        self.assertTrue(json.loads(detail)["clips"][0]["available"])
        self.assertIn("00:00:01.000", json.loads(detail)["transcript"])

    def test_media_ranges_suffixes_and_unsatisfied_requests(self):
        status, headers, body = self.fetch("/api/runs/previous/files/source", {"Range": "bytes=4-8"})
        self.assertEqual((status, body), (206, b"45678"))
        self.assertEqual(headers["Content-Range"], "bytes 4-8/20")
        _, _, body = self.fetch("/api/runs/previous/files/source", {"Range": "bytes=-3"})
        self.assertEqual(body, b"hij")
        with self.assertRaises(HTTPError) as caught:
            self.fetch("/api/runs/previous/files/source", {"Range": "bytes=20-"})
        self.assertEqual(caught.exception.code, 416)

    def test_stale_renders_are_not_served_after_selection_changes(self):
        write_json(self.run / "clips.json", {"clips": [{**self.clip, "source_start": "00:00:02.000"}]})
        self.assertEqual(self.catalog.list()[0]["status"], "selected")
        self.assertFalse(self.catalog.detail("previous")["clips"][0]["available"])
        with self.assertRaises(HTTPError) as caught:
            self.fetch("/api/runs/previous/files/clip_01.mp4")
        self.assertEqual(caught.exception.code, 404)

    def test_host_origin_csrf_and_path_traversal_guards(self):
        for path, headers in [("/api/runs", {"Host": "attacker.example"}),
                              ("/api/runs", {"Origin": "http://attacker.example"}),
                              ("/api/runs/%2e%2e", {}),
                              ("/api/runs/previous/files/job.json", {}),
                              ("/%2e%2e/input.mp4", {})]:
            with self.assertRaises(HTTPError) as caught:
                self.fetch(path, headers)
            self.assertIn(caught.exception.code, (403, 404))
        with self.assertRaises(HTTPError) as caught:
            self.fetch("/api/runs", data=b"{}")
        self.assertEqual(caught.exception.code, 403)

    def test_new_run_validation_and_background_progress(self):
        _, _, config = self.fetch("/api/config")
        headers = {"Content-Type": "application/json", "X-Maho-Token": json.loads(config)["token"]}
        for settings in ({"video": str(self.video), "count": 0}, {"video": str(self.video), "min_seconds": 61, "max_seconds": 60}, {"video": str(self.root / "missing.mp4")},
                         {"video": str(self.video), "lead_seconds": -1}, {"video": str(self.video), "tail_seconds": "2"}):
            with self.assertRaises(HTTPError) as caught:
                self.fetch("/api/runs", headers, json.dumps(settings).encode())
            self.assertEqual(caught.exception.code, 400)
        self.assertEqual(json.loads(config)["defaults"]["lead_seconds"], 1.5)
        status, _, body = self.fetch("/api/runs", headers, json.dumps({"video": str(self.video), "lead_seconds": 2, "tail_seconds": 1}).encode())
        self.assertEqual(status, 202)
        run_id = json.loads(body)["id"]
        self.assertTrue(self.finished.wait(3))
        deadline = time.monotonic() + 3
        while self.catalog.active and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertIn("Transcription completed", self.catalog.detail(run_id)["log"])
        self.assertEqual(self.catalog.detail(run_id)["settings"]["model"], "gpt-6-sol")
        self.assertEqual(self.catalog.detail(run_id)["settings"]["reasoning_effort"], "high")
        self.assertEqual(self.catalog.detail(run_id)["render_settings"], {"lead_seconds": 2, "tail_seconds": 1})
        self.assertEqual(len(self.catalog.list()), 2)
        self.assertFalse(self.catalog.active)

    def test_missing_source_and_interrupted_jobs_remain_visible(self):
        self.video.unlink()
        self.assertFalse(self.catalog.detail("previous")["source_available"])
        write_json(self.run / ".browser.json", {"status": "running"})
        self.assertEqual(self.catalog.detail("previous")["status"], "interrupted")

    def test_cli_resume_completion_overrides_old_browser_failure(self):
        write_json(self.run / ".browser.json", {"status": "failed", "updated_at": "2026-10-06T01:00:00+00:00",
                                               "error": "Old failure"})
        job = json.loads((self.run / "job.json").read_text(encoding="utf-8"))
        job["render_completed_at"] = "2026-10-06T02:00:00+00:00"
        write_json(self.run / "job.json", job)
        detail = self.catalog.detail("previous")
        self.assertEqual(detail["status"], "completed")
        self.assertIsNone(detail["error"])

    def test_running_pipeline_is_detected_after_browser_server_restart(self):
        write_json(self.run / ".browser.json", {"status": "running"})
        with job_lock(self.run):
            self.assertEqual(self.catalog.detail("previous")["status"], "running")
            with self.assertRaisesRegex(ValueError, "already processing"):
                self.catalog.start({"video": str(self.video)})
        self.assertEqual(self.catalog.detail("previous")["status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
