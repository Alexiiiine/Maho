# Maho video clip pipeline

**Video → AssemblyAI transcription → saved transcript → OpenAI editorial analysis → structured JSON → FFmpeg clips.**

Defaults: up to **five clips**, each **30–60 seconds after internal cuts**. The video,
clip count, duration range, model, project information, and editorial instructions are configurable.

## First run on this computer

Python dependencies are installed in `.venv`; FFmpeg and FFprobe are on PATH.
Both supplied API keys are already saved in Windows Credential Manager as
`Maho/AssemblyAI` and `Maho/OpenAI`. To replace the OpenAI key, use hidden input:

```powershell
.\.venv\Scripts\maho.exe set-key --service openai
.\.venv\Scripts\maho.exe doctor
.\.venv\Scripts\maho.exe run "C:\Videos\recording.mp4"
```

Run these commands from this project directory. OpenAI credentials are saved as `Maho/OpenAI`.
No API keys are stored in the source files.

Customize the settings:

```powershell
.\.venv\Scripts\maho.exe run "C:\Videos\recording.mp4" `
  --count 8 `
  --min-seconds 30 `
  --max-seconds 60 `
  --criteria "Standalone insights for readers of this author" `
  --project-file examples\project.json `
  --output outputs\recording
```

`--count` is a maximum. Fewer clips are returned when fewer moments satisfy the editorial
and runtime constraints. Runtime applies to the finished clip after recommended internal removals;
the selected source range may be longer. No handles are added.

## Your editorial prompt

`maho/prompts/select_clips.txt` is an unchanged copy of the prompt you supplied.
Edit that file, or use `--prompt-file` to select another prompt. The full transcript is sent
in one analysis so the model can compare the entire interview before choosing clips.
Transcript size must fit the selected model's context limit.

`--project-file` accepts JSON containing author, book, campaign, platform, requested topics,
and editorial instructions. `examples/project.json` is an editable starting point.
`--notes-file` accepts a text file with assignment notes or suggested source timestamps.
The configured count and 30–60-second default range are supplied as project instructions,
which override the prompt's general fallback ranges. `--criteria` supplements any editorial
instructions in the project file.

The model returns your exact `project_summary` and `clips` structure, including:

- Exact source timestamps and a complete transcript excerpt.
- Question context and whether to include the question.
- A verbatim hook, its timestamp, and a possible reorder recommendation.
- Internal-cut ranges and reasons, plus graphics/edit markers.
- The six editorial scores, overall score, working title, and priority.

The schema is saved in `schemas/clips.schema.json`. The application checks that source,
cut, hook, and marker timestamps actually exist in AssemblyAI's word-level transcript.
It checks exact hook wording, cut containment, finished runtime, and source overlap.
It reconstructs excerpts from the original transcript words and calculates durations from
validated timestamps. Invalid selections are rejected rather than rendered.

Internal removals are automatically applied with synchronized audio/video trimming and
concatenation. Sidecar subtitles are retimed around each removal. `hook_reorder_candidate`,
question notes, and markers remain editor recommendations: the renderer retains source order
and does not generate graphics, reorder hooks, or remove an interviewer question beyond the
selected source boundary/internal cuts.

The LLM evaluates spoken content; it does not view footage. Scores are editorial judgments.
Exports retain the source composition/aspect ratio. No vertical crop or burned-in captions
are added.

## Saved files

By default, output goes to `outputs/<video-name>-<source-fingerprint>/`.

| File | Contents |
| --- | --- |
| `job.json` | Source fingerprint, transcription settings, upload URL, and resumable job ID |
| `audio.m4a` | Extracted mono audio aligned to the source timeline |
| `transcript.json` | Full AssemblyAI response, including word timestamps and speaker labels |
| `transcript.txt` | Plain transcription |
| `transcript.srt` | Full-video subtitles |
| `llm/*.json` | Cached raw model responses, request IDs, and usage |
| `clips.json` | Your exact editorial JSON structure |
| `selection.metadata.json` | Source/transcript/selection fingerprints, settings, and LLM request metadata |
| `clips/clip_01.mp4` | H.264/AAC edited clip; numbering follows editorial priority |
| `clips/clip_01.srt` | Subtitles relative to the edited clip |
| `clips/clip_01.json` | Editorial fields, retained segments, render fingerprint, and output paths |
| `render_manifest.json` | Render progress and completed output paths |

To return the editorial JSON to another program, add `--json`. Progress goes to stderr:

```powershell
.\.venv\Scripts\maho.exe run "C:\Videos\recording.mp4" --json > result.json
```

## Individual stages and restarts

Use the same video and output directory across stages:

```powershell
.\.venv\Scripts\maho.exe transcribe "C:\Videos\recording.mp4" --output outputs\recording
.\.venv\Scripts\maho.exe select "C:\Videos\recording.mp4" --output outputs\recording --count 5
.\.venv\Scripts\maho.exe cut "C:\Videos\recording.mp4" --output outputs\recording
```

Rerun `run` to resume a saved transcript ID, reuse the transcript and matching LLM analysis,
and skip matching rendered clips. Changing the prompt, project context, notes, criteria,
count, runtime, provider, or model invalidates selection caching without retranscribing.
Changing transcription language or speech models requires a new output directory.
`select` only needs an OpenAI key; `cut` uses local files and requires no keys.

GET requests retry transient errors. Billable POST requests are not automatically retried:
a connection failure may occur after acceptance. There is a small crash window between
submitting a job and saving its returned ID; check the AssemblyAI dashboard if that occurs.
Failed provider transcription jobs are saved for inspection; use a new output directory to
submit a replacement. Default outputs and video/audio files are gitignored. Exclude any custom
output directory from version control as well.

## Providers and installation

Transcription defaults to Universal-3.5 Pro with Universal-2 fallback and automatic language
detection. Use `--language` or `--speech-models` to override. Clip analysis defaults to OpenAI
`gpt-5-mini` via the Responses API with strict structured output; override with `--model`.

AssemblyAI LLM Gateway remains optional with `--llm-provider assemblyai`; its default model
is `gemini-2.5-flash`. The supplied AssemblyAI account rejected gateway model access during
verification, so OpenAI is configured as the default separate provider.

Requires Python 3.11+ and FFmpeg with `libx264`, plus FFprobe on PATH. On another computer:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\maho.exe set-key --service assemblyai
.\.venv\Scripts\maho.exe set-key --service openai
```

On any operating system, `ASSEMBLYAI_API_KEY` and `OPENAI_API_KEY` environment variables
are supported and take precedence over Windows Credential Manager. An API account and
billable service access are required for actual runs. `doctor` checks executables and API/model
authentication without submitting a transcription or LLM completion.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests use fake APIs with real FFmpeg. Coverage includes exact timestamp and quote checks,
JSON schema enforcement, internal-cut durations, subtitle offsets, audio alignment, Responses
API normalization/refusals, error redaction, and restarts without duplicate calls.
Live AssemblyAI transcription was verified on a generated 51-second narration video. OpenAI analysis with your prompt and FFmpeg export also succeeded in the live test,
producing a 50.32-second clip. The complete pipeline is configured.

References: [AssemblyAI transcription](https://www.assemblyai.com/docs/pre-recorded-audio/api-reference/transcripts/submit),
[OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).
