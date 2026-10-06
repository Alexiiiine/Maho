import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator, ValidationError

from maho import media
from maho.api import AssemblyAI
from maho.pipeline import Pipeline
from maho.selection import SelectionOptions, validate_words
from maho.storage import read_json, write_json
from maho.editorial import (SCORE_NAMES, resolve_edit, response_schema as editorial_schema, timestamped_text,
                            ground_hook_timestamp, correction_schema, ground_correction, select_editorial)
from maho.llm import OpenAILLM


def words(count=60):
    return [{"text": f"word{i}.", "start": i * 1000, "end": (i + 1) * 1000, "speaker": "A"}
            for i in range(count)]




def editorial_candidate(first=5, last=12):
    from maho.editorial import stamp
    return {"clip_id": "clip_01", "priority": 1, "title": "A useful idea",
            "source_start": stamp(first * 200), "source_end": stamp((last + 1) * 200),
            "estimated_source_duration_seconds": (last + 1 - first) * 0.2,
            "estimated_finished_duration_seconds": (last + 1 - first) * 0.2,
            "question_context": "What is the idea?", "include_question": False,
            "hook": f"Word{first}.", "hook_timestamp": stamp(first * 200), "hook_reorder_candidate": False,
            "transcript_excerpt": " ".join(f"Word{i}." for i in range(first, last + 1)),
            "editorial_reason": "A complete useful idea.", "internal_cuts": [], "markers": [],
            "scores": {name: 8 for name in SCORE_NAMES}}


class SelectionTests(unittest.TestCase):
    def test_default_lengths_are_30_to_60_and_configurable(self):
        self.assertEqual((SelectionOptions().min_seconds, SelectionOptions().max_seconds), (30, 60))
        SelectionOptions(min_seconds=5, max_seconds=10).validate()
        with self.assertRaises(ValueError):
            SelectionOptions(min_seconds=61, max_seconds=60).validate()




    def test_invalid_transcript_and_no_speech_fail(self):
        for transcript in [{"words": []}, {"words": [{"text": "x", "start": 0, "end": 999999}]},
                           {"words": [{"text": "x", "start": float("nan"), "end": 1}]}]:
            with self.assertRaises(ValueError):
                validate_words(transcript, 60)



    def test_caption_timestamps_are_relative_to_clip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "clip.srt"
            media.subtitles(words()[5:7], path, offset=4.85, limit=2.3)
            text = path.read_text()
            self.assertIn("00:00:00,150 --> 00:00:01,150", text)
            self.assertNotIn("00:00:05,000", text)

    def test_post_connection_failure_is_not_retried(self):
        import requests
        client = AssemblyAI("dummy-key")
        with patch.object(client.session, "request", side_effect=requests.ConnectionError()) as call:
            with self.assertRaises(RuntimeError):
                client.complete({})
            self.assertEqual(call.call_count, 1)

    def test_api_error_redacts_key(self):
        client = AssemblyAI("dummy-secret")
        response = unittest.mock.Mock(ok=False, status_code=401, headers={})
        response.json.return_value = {"error": "Rejected dummy-secret"}
        with patch.object(client.session, "request", return_value=response):
            with self.assertRaises(RuntimeError) as caught:
                client.models()
        self.assertNotIn("dummy-secret", str(caught.exception))


class FakeClient:
    def __init__(self):
        self.uploads = self.submissions = self.completions = 0
        self.polls = 0
        self.transcript_result = {"id": "test-transcript", "status": "completed", "text": "Test speech.",
                                  "words": [{"text": f"Word{i}.", "start": i * 200, "end": (i + 1) * 200,
                                             "speaker": "A"} for i in range(20)]}

    def upload(self, path):
        assert path.is_file()
        self.uploads += 1
        return "https://example.invalid/audio"

    def submit(self, *args):
        self.submissions += 1
        return {"id": "test-transcript"}

    def transcript(self, transcript_id):
        self.polls += 1
        return self.transcript_result

    def complete(self, body):
        self.completions += 1
        return {"request_id": "test-request", "usage": {"total_tokens": 50},
                "choices": [{"finish_reason": "stop", "message": {
                    "content": json.dumps({"project_summary": {"primary_subject": "Test", "main_topics": ["Idea"], "recommended_clip_count": 1}, "clips": [editorial_candidate()]})}}]}


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class FFmpegPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.video = self.root / "source with spaces.mp4"
        media.run_process([media.executable("ffmpeg"), "-v", "error", "-y", "-f", "lavfi",
                           "-i", "testsrc2=size=320x180:rate=25:duration=4", "-f", "lavfi",
                           "-i", "sine=frequency=440:duration=4", "-c:v", "libx264", "-g", "100",
                           "-c:a", "aac", "-shortest", str(self.video)])
        self.output = self.root / "result"
        self.options = SelectionOptions(count=1, min_seconds=1, max_seconds=3)
        self.client = FakeClient()

    def tearDown(self):
        self.temp.cleanup()

    def pipeline(self):
        return Pipeline(self.video, self.output, log=lambda msg: None)

    def test_complete_pipeline_then_resume_without_paid_api_calls(self):
        result = self.pipeline().execute("run", self.client, self.options)
        clip = read_json(self.output / "render_manifest.json")["clips"][0]
        self.assertEqual(read_json(self.output / "render_manifest.json")["status"], "completed")
        self.assertAlmostEqual(media.probe(Path(clip["output_file"]))["duration_seconds"], 1.6, delta=0.12)
        self.assertEqual(clip["source_start"], "00:00:01.000")
        self.assertTrue((self.output / "transcript.txt").exists())
        self.assertTrue((self.output / "transcript.srt").exists())
        self.assertIn("00:00:00,000", Path(clip["subtitles_file"]).read_text())
        self.pipeline().execute("run", self.client, self.options)
        self.assertEqual((self.client.uploads, self.client.submissions, self.client.completions), (1, 1, 1))

    def test_poll_timeout_resume_reuses_transcript_id(self):
        completed = self.client.transcript_result
        self.client.transcript_result = {"status": "processing"}
        with self.assertRaises(RuntimeError):
            self.pipeline().execute("transcribe", self.client, poll_timeout=0)
        self.assertEqual(read_json(self.output / "job.json")["transcript_id"], "test-transcript")
        self.client.transcript_result = completed
        self.pipeline().execute("transcribe", self.client)
        self.assertEqual((self.client.uploads, self.client.submissions), (1, 1))

    def test_tampered_timestamps_are_rejected_before_cutting(self):
        self.pipeline().execute("run", self.client, self.options)
        path = self.output / "clips.json"
        selected = read_json(path)
        selected["clips"][0]["source_start"] = "00:00:00.999"
        write_json(path, selected)
        with patch("maho.media.render_edit") as render, self.assertRaises(ValueError):
            self.pipeline().execute("cut")
        render.assert_not_called()

    def test_changed_preferences_reuse_transcript_and_reselect(self):
        self.pipeline().execute("run", self.client, self.options)
        altered = SelectionOptions(count=1, min_seconds=1, max_seconds=3, criteria="Educational insights")
        self.pipeline().execute("run", self.client, altered)
        self.assertEqual((self.client.uploads, self.client.submissions, self.client.completions), (1, 1, 2))

    def test_audio_extraction_preserves_delayed_audio_timeline(self):
        delayed = self.root / "delayed.mp4"
        media.run_process([media.executable("ffmpeg"), "-v", "error", "-y", "-f", "lavfi",
                           "-i", "color=c=blue:s=320x180:r=25:d=4", "-itsoffset", "2", "-f", "lavfi",
                           "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-c:a", "aac", str(delayed)])
        audio = self.root / "audio.m4a"
        media.extract_audio(delayed, audio)
        self.assertAlmostEqual(media.probe(audio, require_video=False)["duration_seconds"], 4, delta=0.2)
        result = subprocess.run([media.executable("ffmpeg"), "-i", str(audio), "-af",
                                 "silencedetect=noise=-35dB:d=1", "-f", "null", "-"], capture_output=True, text=True)
        self.assertIn("silence_start: 0", result.stderr)
        self.assertIn("silence_end: 1.9", result.stderr)


class EditorialAndOpenAITests(unittest.TestCase):
    def setUp(self):
        self.words = FakeClient().transcript_result["words"]
        self.options = SelectionOptions(count=1, min_seconds=1, max_seconds=3)

    def test_exact_user_schema_and_transcript_boundaries(self):
        schema = editorial_schema()
        selected = {"project_summary": {"primary_subject": "Test", "main_topics": [], "recommended_clip_count": 1},
                    "clips": [editorial_candidate()]}
        Draft202012Validator(schema).validate(selected)
        clip, segments = resolve_edit(selected["clips"][0], self.words, 4, self.options)
        self.assertEqual(segments, [(1, 2.6)])
        self.assertEqual(clip["estimated_finished_duration_seconds"], 1.6)
        bad = {**clip, "source_start": "00:00:01.001"}
        with self.assertRaises(ValueError):
            resolve_edit(bad, self.words, 4, self.options)

    def test_readable_transcript_preserves_timestamps_and_speakers(self):
        text = timestamped_text(self.words[:2])
        self.assertIn("[00:00:00.000 --> 00:00:00.200] Speaker A: Word0.", text)
        self.assertIn("[00:00:00.200 --> 00:00:00.400] Speaker A: Word1.", text)

    def test_hook_timestamp_is_grounded_by_exact_quotation(self):
        clip = {**editorial_candidate(), "hook_timestamp": "00:00:01.999"}
        grounded = ground_hook_timestamp(clip, self.words)
        self.assertEqual(grounded["hook_timestamp"], "00:00:01.000")
        self.assertEqual(grounded["hook"], clip["hook"])
        hallucinated = {**clip, "hook": "An invented quote"}
        self.assertEqual(ground_hook_timestamp(hallucinated, self.words), hallucinated)

    def test_private_word_ids_ground_correction_without_changing_output_contract(self):
        wire = {"project_summary": {"primary_subject": "Test", "main_topics": [], "recommended_clip_count": 1},
                "clips": [{**editorial_candidate(), "source_start": "00:00:01.001",
                           "source_end": "00:00:02.601", "source_start_word": 5, "source_end_word": 12, "hook_word": 5}]}
        Draft202012Validator(correction_schema(len(self.words))).validate(wire)
        actual = ground_correction(wire, self.words)
        Draft202012Validator(editorial_schema()).validate(actual)
        self.assertEqual(actual["clips"][0]["source_start"], "00:00:01.000")
        self.assertEqual(actual["clips"][0]["source_end"], "00:00:02.600")
        self.assertNotIn("source_start_word", actual["clips"][0])

    def test_invalid_selection_is_corrected_and_both_api_responses_are_cached(self):
        class RepairClient:
            cache_identity = "test-repair"

            def __init__(self):
                self.calls = 0

            def complete(self, body):
                self.calls += 1
                clip = {**editorial_candidate(), "source_end": "00:00:02.601"}
                if self.calls == 2:
                    clip.update(source_start_word=5, source_end_word=12, hook_word=5)
                selected = {"project_summary": {"primary_subject": "Test", "main_topics": [], "recommended_clip_count": 1},
                            "clips": [clip]}
                return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(selected)}}]}

        client = RepairClient()
        with tempfile.TemporaryDirectory() as temp:
            for _ in range(2):
                selected, metadata = select_editorial(client, {"words": self.words}, 4, self.options,
                                                     Path(temp), log=lambda msg: None)
                self.assertEqual(selected["clips"][0]["source_end"], "00:00:02.600")
                self.assertEqual(len(metadata["requests"]), 2)
        self.assertEqual(client.calls, 2)

    def test_internal_cuts_compute_finished_length_and_shift_captions(self):
        clip = editorial_candidate(0, 19)
        clip["internal_cuts"] = [{"cut_start": "00:00:01.000", "cut_end": "00:00:02.000", "reason": "Repetition"}]
        canonical, segments = resolve_edit(clip, self.words, 4, self.options)
        self.assertEqual(canonical["estimated_source_duration_seconds"], 4)
        self.assertEqual(canonical["estimated_finished_duration_seconds"], 3)
        self.assertEqual(segments, [(0, 1), (2, 4)])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "clip.srt"
            media.edit_subtitles(self.words, segments, path)
            text = path.read_text()
            self.assertNotIn("Word5.", text)
            self.assertNotIn("Word9.", text)
            self.assertIn("00:00:01,000 --> 00:00:01,200", text)
            self.assertIn("Word10.", text)

    def test_exact_hook_and_markers_are_validated(self):
        clip = editorial_candidate()
        for change in [{"hook": "Rewritten quote"}, {"hook_timestamp": "00:00:01.001"},
                       {"markers": [{"timestamp": "00:00:01.001", "type": "strong_quote", "text": "x", "reason": "x"}]}]:
            with self.assertRaises(ValueError):
                resolve_edit({**clip, **change}, self.words, 4, self.options)

    def test_internal_cut_cannot_remove_any_part_of_the_hook(self):
        clip = editorial_candidate(0, 19)
        clip["hook"] = "Word0. Word1. Word2. Word3. Word4. Word5."
        clip["internal_cuts"] = [{"cut_start": "00:00:01.000", "cut_end": "00:00:02.000", "reason": "Repetition"}]
        with self.assertRaises(ValueError):
            resolve_edit(clip, self.words, 4, self.options)

    def test_openai_responses_request_and_normalization(self):
        client = OpenAILLM("test-openai-key")
        self.assertEqual(client.session.headers["authorization"], "Bearer test-openai-key")
        response = {"id": "resp_test", "request_id": "req_test", "status": "completed", "usage": {},
                    "output": [{"type": "reasoning"}, {"type": "message", "content": [{"type": "output_text", "text": "{}"}]}]}
        with patch.object(client, "request", return_value=response) as call:
            result = client.complete({"model": "gpt-5-mini", "messages": [{"role": "user", "content": "Test"}],
                                      "max_tokens": 4096, "response_format": {"json_schema": {"name": "test", "schema": editorial_schema()}}})
        self.assertEqual(result["choices"][0]["message"]["content"], "{}")
        self.assertEqual(result["choices"][0]["finish_reason"], "stop")
        self.assertEqual(call.call_args.args, ("POST", "https://api.openai.com/v1/responses"))
        body = call.call_args.kwargs["json"]
        self.assertFalse(body["store"])
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertNotIn("post_processing_steps", body)
        self.assertNotIn("max_tokens", body)
        self.assertEqual(body["reasoning"], {"effort": "low"})
        self.assertGreaterEqual(body["max_output_tokens"], 32768)

    def test_openai_refusal_and_incomplete_responses_are_not_success(self):
        client = OpenAILLM("test-key")
        body = {"model": "gpt-5-mini", "messages": [], "max_tokens": 4096,
                "response_format": {"json_schema": {"name": "test", "schema": editorial_schema()}}}
        for response in [{"status": "incomplete", "output": []},
                         {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "No"}]}]}]:
            with patch.object(client, "request", return_value=response):
                self.assertNotEqual(client.complete(body)["choices"][0]["finish_reason"], "stop")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class InternalCutRenderTests(unittest.TestCase):
    def test_real_ffmpeg_removes_middle_segment(self):
        with tempfile.TemporaryDirectory() as temp:
            source, target = Path(temp) / "source.mp4", Path(temp) / "clip.mp4"
            media.run_process([media.executable("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i",
                               "testsrc2=size=320x180:rate=25:duration=4", "-f", "lavfi", "-i",
                               "sine=frequency=440:duration=4", "-c:v", "libx264", "-c:a", "aac", str(source)])
            duration = media.render_edit(source, [(0, 1), (2, 4)], target)
            self.assertAlmostEqual(duration, 3, delta=0.15)


if __name__ == "__main__":
    unittest.main()
