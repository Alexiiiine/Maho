import argparse
import getpass
import json
import sys

from jsonschema.exceptions import ValidationError

from .api import AssemblyAI, STT_URL
from .credentials import get_key, save_key, key_storage_name
from .media import executable
from .pipeline import DEFAULT_SPEECH_MODELS, Pipeline
from .llm import OpenAILLM
from .editorial import PROMPT_FILE
from .selection import SelectionOptions
from .rendering import RenderOptions
from .storage import read_json
from pathlib import Path


def parser():
    root = argparse.ArgumentParser(description="Transcribe a video, select the best spoken moments, and export MP4 clips.")
    commands = root.add_subparsers(dest="command", required=True)
    key = commands.add_parser("set-key", help="Save an API key in the system credential store (hidden input).")
    key.add_argument("--service", choices=["assemblyai", "openai"], default="assemblyai")
    doctor = commands.add_parser("doctor", help="Check FFmpeg, API authentication, and model availability.")
    doctor.add_argument("--model")
    doctor.add_argument("--llm-provider", choices=["openai", "assemblyai"], default="openai")
    browser = commands.add_parser("serve", help="Open the local browser interface for run history, videos, and new runs.")
    browser.add_argument("--port", type=int, default=8765)
    browser.add_argument("--runs-dir", default="outputs", help="Directory containing previous run folders.")
    browser.add_argument("--no-open", action="store_true", help="Start the server without opening a browser.")
    for name in ("run", "transcribe", "select", "cut"):
        command = commands.add_parser(name, help={
            "run": "Run the complete pipeline.", "transcribe": "Upload and save the transcript only.",
            "select": "Choose clips from a saved transcript.", "cut": "Render saved clips.json without calling any API."
        }[name])
        command.add_argument("video", help="Local video file path.")
        command.add_argument("--output", help="Output directory; default outputs/<video-name>-<fingerprint>.")
        command.add_argument("--json", action="store_true", help="Print the structured result to stdout.")
        if name in ("run", "cut"):
            command.add_argument("--lead-seconds", type=float, help="Time before the first word (default: 1.5; saved settings reused).")
            command.add_argument("--tail-seconds", type=float, help="Time after the last word (default: 1.5; saved settings reused).")
        if name in ("run", "select"):
            defaults = SelectionOptions()
            command.add_argument("--count", type=int, default=defaults.count, help="Maximum clips (default: 5).")
            command.add_argument("--min-seconds", type=float, default=defaults.min_seconds, help="Minimum length (default: 30).")
            command.add_argument("--max-seconds", type=float, default=defaults.max_seconds, help="Maximum length (default: 60).")
            command.add_argument("--criteria", default=defaults.criteria, help="Audience or editorial selection preferences.")
            command.add_argument("--model", help=f"LLM model ID; default {defaults.model} for OpenAI.")
            command.add_argument("--reasoning-effort", choices=["low", "medium", "high"], default=defaults.reasoning_effort)
            command.add_argument("--max-output-tokens", type=int, default=32768, help="OpenAI output/reasoning budget (default: 32768).")
            command.add_argument("--llm-provider", choices=["openai", "assemblyai"], default="openai")
            command.add_argument("--project-file", help="JSON with author, book, campaign, platform, or other project context.")
            command.add_argument("--notes-file", help="Text file with assignment notes or suggested source timestamps.")
            command.add_argument("--prompt-file", default=str(PROMPT_FILE), help="Editable editorial prompt text file.")
        if name in ("run", "transcribe"):
            command.add_argument("--language", help="Language code; default automatic detection.")
            command.add_argument("--speech-models", nargs="+", default=DEFAULT_SPEECH_MODELS)
            command.add_argument("--poll-timeout", type=float, default=7200, help="Seconds to wait; rerunning resumes the same job.")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "serve":
            from .web_server import serve
            serve(args.runs_dir, args.port, not args.no_open)
            return 0
        if args.command == "set-key":
            save_key(getpass.getpass(f"{args.service} API key: "), args.service)
            print(f"API key saved in {key_storage_name()} for {args.service}.")
            return 0
        if args.command == "doctor":
            for name in ("ffmpeg", "ffprobe"):
                print(f"{name}: {executable(name)}")
            client = AssemblyAI(get_key())
            # /models is public; an authenticated STT request separately verifies the key.
            client.request("GET", f"{STT_URL}/transcript", params={"limit": 1})
            print("AssemblyAI authentication: OK")
            model = args.model or (SelectionOptions().model if args.llm_provider == "openai" else "gemini-2.5-flash")
            if args.llm_provider == "openai":
                OpenAILLM(get_key("openai")).check_model(model)
                print(f"OpenAI authentication and model access: OK ({model})")
            else:
                models = client.models().get("data", [])
                match = next((m for m in models if m.get("id") == model), None)
                if not match or "response_format" not in match.get("supported_parameters", []):
                    raise ValueError(f"Model {model} is unavailable or does not advertise structured outputs.")
                print(f"LLM catalog model: {model}; catalog availability does not verify account access.")
            print("This check does not submit a transcription or LLM completion.")
            return 0
        options = None
        llm = None
        render_options = {}
        if args.command in ("run", "cut"):
            render_options = {field: getattr(args, field) for field in ("lead_seconds", "tail_seconds") if getattr(args, field) is not None}
            RenderOptions(**render_options).validate()
        if args.command in ("run", "select"):
            args.model = args.model or (SelectionOptions().model if args.llm_provider == "openai" else "gemini-2.5-flash")
            options = SelectionOptions(**{field: getattr(args, field) for field in (
                "count", "min_seconds", "max_seconds", "criteria", "model", "reasoning_effort", "max_output_tokens")},
                project_info=read_json(args.project_file) if args.project_file else {},
                assignment_notes=Path(args.notes_file).read_text(encoding="utf-8-sig") if args.notes_file else "",
                editorial_prompt=Path(args.prompt_file).read_text(encoding="utf-8-sig"))
            options.validate()
            if not isinstance(options.project_info, dict):
                raise ValueError("Project file must contain a JSON object.")
            llm = OpenAILLM(get_key("openai")) if args.llm_provider == "openai" else AssemblyAI(get_key())
        transcription = {}
        if args.command in ("run", "transcribe"):
            if args.poll_timeout <= 0:
                raise ValueError("poll-timeout must be positive.")
            transcription = {field: getattr(args, field) for field in ("language", "speech_models", "poll_timeout")}
        pipeline = Pipeline(args.video, args.output, log=lambda msg: print(msg, file=sys.stderr))
        client = AssemblyAI(get_key()) if args.command in ("run", "transcribe") else None
        result = pipeline.execute(args.command, client, options, llm=llm, render_options=render_options, **transcription)
        if args.json:
            # ASCII escapes preserve every character across Windows shell encodings.
            print(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False))
        else:
            print(f"Saved to: {pipeline.output}")
            if "clips" in result:
                for clip in result["clips"]:
                    print(f"  {clip['clip_id']}: {clip['title']} ({clip['estimated_finished_duration_seconds']:.2f}s)")
        return 0
    except (RuntimeError, ValueError, OSError, KeyError, TypeError, ValidationError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Rerun the same command to resume saved work.", file=sys.stderr)
        return 130
