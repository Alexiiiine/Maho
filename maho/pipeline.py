import re
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from . import media
from .selection import SelectionOptions, validate_words
from .editorial import PROMPT_FILE, response_schema, resolve_edit, select_editorial, stamp, timestamped_text
from .storage import data_hash, file_hash, job_lock, read_json, write_json, write_text

DEFAULT_SPEECH_MODELS = ["universal-3-5-pro", "universal-2"]


def now():
    return datetime.now(timezone.utc).isoformat()


class Pipeline:
    def __init__(self, video, output=None, log=print):
        self.video = Path(video).expanduser().resolve()
        if not self.video.is_file():
            raise ValueError(f"Video does not exist: {self.video}")
        log("Reading video metadata and fingerprint.")
        self.info = media.probe(self.video)
        self.fingerprint = file_hash(self.video)
        name = re.sub(r"[^a-zA-Z0-9_-]+", "-", self.video.stem).strip("-")[:70] or "video"
        self.output = Path(output or Path("outputs") / f"{name}-{self.fingerprint[:12]}").resolve()
        self.log = log
        self.state = {}

    def initialize(self):
        path = self.output / "job.json"
        if path.exists():
            self.state = read_json(path)
            if self.state.get("source_sha256") != self.fingerprint:
                raise ValueError("Output directory belongs to a different video. Choose another --output directory.")
        else:
            # Do not attach an existing transcript/selection to an unverified source.
            if any((self.output / name).exists() for name in ("transcript.json", "clips.json")):
                raise ValueError("Existing artifacts lack job.json; use a new output directory.")
            self.state = {"schema_version": 1, "source_sha256": self.fingerprint, "created_at": now()}
        self.state.update({"source_video": str(self.video), "duration_seconds": self.info["duration_seconds"]})
        self.save_state()

    def save_state(self):
        self.state["updated_at"] = now()
        write_json(self.output / "job.json", self.state)

    def transcribe(self, client, language=None, speech_models=None, poll_timeout=7200):
        path = self.output / "transcript.json"
        settings = {"language": language, "speech_models": speech_models or DEFAULT_SPEECH_MODELS}
        previous = self.state.get("transcription_settings")
        if previous is not None and previous != settings:
            raise ValueError("Transcription settings changed. Use a new --output directory to retranscribe.")
        if path.exists():
            transcript = read_json(path)
            if transcript.get("status") == "completed":
                self.log("Reusing saved transcription.")
                self.save_transcript(transcript)
                return transcript
        if not self.state.get("transcript_id"):
            self.state["transcription_settings"] = settings
            self.save_state()
            audio = self.output / "audio.m4a"
            if not self.state.get("upload_url"):
                if not audio.exists():
                    self.log("Extracting audio for transcription.")
                    media.extract_audio(self.video, audio)
                self.log("Uploading extracted audio to AssemblyAI.")
                self.state["upload_url"] = client.upload(audio)
                self.save_state()
            self.log("Submitting transcription.")
            submitted = client.submit(self.state["upload_url"], settings["speech_models"], language)
            self.state["transcript_id"] = submitted["id"]
            self.save_state()
        deadline, last_status = time.monotonic() + poll_timeout, None
        while True:
            transcript = client.transcript(self.state["transcript_id"])
            status = transcript.get("status")
            if status != last_status:
                self.log(f"Transcription: {status}.")
                last_status = status
            if status == "completed":
                self.save_transcript(transcript)
                self.state["transcription_completed_at"] = now()
                self.save_state()
                return transcript
            if status == "error":
                write_json(self.output / "transcript.error.json", transcript)
                raise RuntimeError(f"Transcription failed: {transcript.get('error', 'Unknown error')}. "
                                   "Use a new output directory to submit a replacement job.")
            if status not in ("queued", "processing"):
                raise RuntimeError(f"Unexpected transcription status: {status}.")
            if time.monotonic() >= deadline:
                raise RuntimeError("Transcription wait timed out. Rerun to resume the saved transcript ID.")
            time.sleep(3)

    def save_transcript(self, transcript):
        # Persist the full transcript even when there is no speech for clip selection.
        write_json(self.output / "transcript.json", transcript)
        words = transcript.get("words") or []
        write_text(self.output / "transcript.plain.txt", (transcript.get("text") or "") + "\n")
        write_text(self.output / "transcript.txt", timestamped_text(words))
        write_text(self.output / "transcript.timestamped.txt", "\n".join(
            f"{stamp(w['start'])} --> {stamp(w['end'])} | speaker={w.get('speaker') or '-'} | {w['text']}"
            for w in words) + "\n")
        media.subtitles(transcript.get("words") or [], self.output / "transcript.srt")

    def select(self, client, options):
        transcript = read_json(self.output / "transcript.json")
        validate_words(transcript, self.info["duration_seconds"])
        settings = asdict(options)
        settings["editorial_prompt"] = options.editorial_prompt or PROMPT_FILE.read_text(encoding="utf-8-sig")
        identity = {"source_sha256": self.fingerprint, "transcript_sha256": data_hash(transcript),
                    "editorial_protocol_version": 2,
                    "provider": getattr(client, "cache_identity", "assemblyai"), "settings": settings}
        path = self.output / "clips.json"
        metadata_path = self.output / "selection.metadata.json"
        if path.exists() and metadata_path.exists():
            metadata = read_json(metadata_path)
            if (metadata.get("selection_sha256") == data_hash(identity) and
                    metadata.get("clips_sha256") == data_hash(read_json(path))):
                self.log("Reusing saved clip selection.")
                return read_json(path)
        selected, request = select_editorial(client, transcript, self.info["duration_seconds"], options,
                                            self.output / "llm", self.log)
        metadata = {"schema_version": 1, **identity, "source_video": str(self.video),
                    "transcript_id": transcript.get("id"), "selection_sha256": data_hash(identity),
                    "clips_sha256": data_hash(selected), "llm_request": request, "created_at": now()}
        write_json(path, selected)
        write_json(metadata_path, metadata)
        self.log(f"Selected {len(selected['clips'])} of {options.count} requested clips.")
        return selected

    def cut(self):
        selected = read_json(self.output / "clips.json")
        metadata = read_json(self.output / "selection.metadata.json")
        if metadata.get("source_sha256") != self.fingerprint:
            raise ValueError("Clip selection belongs to a different source video.")
        if metadata.get("clips_sha256") != data_hash(selected):
            raise ValueError("Clip selection changed after validation. Run select again.")
        transcript = read_json(self.output / "transcript.json")
        if metadata.get("transcript_sha256") != data_hash(transcript):
            raise ValueError("Transcript changed after selection. Run select again.")
        options = SelectionOptions(**metadata["settings"])
        options.validate()
        words = validate_words(transcript, self.info["duration_seconds"])
        Draft202012Validator(response_schema()).validate(selected)
        if len(selected["clips"]) > options.count:
            raise ValueError("Saved selection contains an invalid number of clips.")
        plans = []
        for index, saved in enumerate(selected["clips"], 1):
            clip, segments = resolve_edit(saved, words, self.info["duration_seconds"], options)
            if saved != clip or saved["clip_id"] != f"clip_{index:02d}":
                raise ValueError("Saved clip does not match validated transcript timestamps and text.")
            plans.append((clip, segments))
        directory = self.output / "clips"
        directory.mkdir(exist_ok=True)
        rendered = []
        if not plans:
            write_json(self.output / "render_manifest.json", {
                "schema_version": 1, "source_video": str(self.video), "source_sha256": self.fingerprint,
                "selection_sha256": metadata["selection_sha256"], "updated_at": now(),
                "status": "completed", "clips": []})
        for clip, segments in plans:
            path = directory / f"{clip['clip_id']}.mp4"
            sidecar = directory / f"{clip['clip_id']}.json"
            signature = data_hash({"source_sha256": self.fingerprint, "clip": clip, "renderer_version": 2})
            expected = clip["estimated_finished_duration_seconds"]
            if path.exists() and sidecar.exists() and read_json(sidecar).get("render_sha256") == signature:
                actual_duration = media.probe(path)["duration_seconds"]
                if abs(actual_duration - expected) > 0.5:
                    raise ValueError(f"Cached clip {clip['clip_id']} has an unexpected duration.")
                self.log(f"Reusing {clip['clip_id']}.")
            else:
                self.log(f"Rendering {clip['clip_id']}: {clip['title']} ({expected:.2f}s).")
                actual_duration = media.render_edit(self.video, segments, path)
            srt = directory / f"{clip['clip_id']}.srt"
            media.edit_subtitles(words, segments, srt)
            record = {**clip, "output_file": str(path), "subtitles_file": str(srt),
                      "render_sha256": signature, "rendered_duration_seconds": actual_duration,
                      "retained_segments": [{"start_seconds": a, "end_seconds": b} for a, b in segments]}
            write_json(sidecar, record)
            rendered.append(record)
            write_json(self.output / "render_manifest.json", {
                "schema_version": 1, "source_video": str(self.video), "source_sha256": self.fingerprint,
                "selection_sha256": metadata["selection_sha256"], "updated_at": now(),
                "status": "completed" if len(rendered) == len(plans) else "rendering", "clips": rendered})
        self.state["render_completed_at"] = now()
        self.save_state()
        return selected

    def execute(self, stage, client=None, options=None, llm=None, **transcription):
        with job_lock(self.output):
            self.initialize()
            if stage in ("run", "transcribe"):
                result = self.transcribe(client, **transcription)
            if stage in ("run", "select"):
                result = self.select(llm or client, options or SelectionOptions())
            if stage in ("run", "cut"):
                result = self.cut()
            return result
