# Maho video clip pipeline

**Video → AssemblyAI transcription → saved transcript → OpenAI editorial analysis → structured JSON → FFmpeg clips.**

Defaults: up to **five clips**, each **30–60 seconds of selected content after internal cuts**,
plus **1.5 seconds before the first word and 1.5 seconds after the last word**. The video,
clip count, duration range, model, project information, and editorial instructions are configurable.

## Mac quick start

### Without Homebrew or administrator access

Download the repository using GitHub's **Code → Download ZIP**, unzip it, and open
Terminal in the resulting `Maho-main` folder. A ZIP download works without Git or
Apple's developer tools. If you already have the clone, update it first with
`git pull --ff-only`.

```bash
bash scripts/setup-mac-no-admin.sh
bash scripts/start-mac.sh
```

This installs [Miniforge](https://github.com/conda-forge/miniforge) under
`~/.maho/miniforge3` and creates Maho's environment inside `.venv`. Python 3.13,
FFmpeg/FFprobe, and Node.js are installed there. **No Homebrew, administrator
password, or `sudo` is used.** Your existing Python 3.9.6 stays installed.
The installer checksum is verified before it runs. Setup needs internet access,
available disk space, and macOS 11 or newer; packages must support your macOS version.

Paste the two API keys into the hidden prompts; they are saved in Mac Keychain.
Next time, run only `bash scripts/start-mac.sh`. To update this installation, update
the repository and rerun `bash scripts/setup-mac-no-admin.sh`.

If setup finds a `.venv` created by the other installation method, rename that
folder and rerun setup. It will preserve `outputs/` and your saved Keychain keys.
No shell activation or changes to your shell profile are needed.

### With Homebrew

Install [Homebrew](https://brew.sh/) first if you do not already have it, then open Terminal:

```bash
git clone https://github.com/Alexiiiine/Maho.git
cd Maho
bash scripts/setup-mac.sh
bash scripts/start-mac.sh
```

The setup script installs Python 3.13, FFmpeg, and Node.js 24 using Homebrew, creates
the local Python environment, installs Maho, and builds the browser interface.
It supports Homebrew's standard Apple Silicon and Intel locations. Homebrew support
for your macOS version still applies; installation can take several minutes.
If `git clone` asks for Apple's Command Line Tools, install them and retry.

During interactive setup, paste your **AssemblyAI** and **OpenAI** keys into the hidden
prompts. They are saved in **macOS Keychain**, not in the project or your shell history.
Allow Python access if macOS shows a Keychain prompt. Setup reuses existing keys and
checks API/model access without submitting a transcription or completion. Actual
processing requires paid API access. If model access fails, check your account or use
`--model` with a model it can access when running the CLI.

The start script opens [Maho](http://127.0.0.1:8765) in your browser. Keep that Terminal
window open; press **Ctrl+C** to stop the server. No environment activation is needed.
In **New run**, enter the video's full Mac path, for example
`/Users/yourname/Movies/interview.mp4`. In Finder, select the video and press
**Option+Command+C** to copy its path. Paste the path without surrounding quotation
marks into the browser form. Videos and outputs stay on that Mac; the audio goes to
AssemblyAI and the transcript goes to the selected LLM provider for processing.

Next time, only run:

```bash
cd /path/to/Maho
bash scripts/start-mac.sh
```

To update a Homebrew installation, stop the server, then run `git pull --ff-only` and
`bash scripts/setup-mac.sh` before starting it again. Rerunning setup rebuilds the
interface and preserves keys and outputs. Clone the repository on each computer;
do not copy a Windows `.venv` to a Mac.

Mac CLI commands are also available without activation:

```bash
.venv/bin/maho doctor
.venv/bin/maho run "/Users/yourname/Movies/interview.mp4"
.venv/bin/maho set-key --service assemblyai
.venv/bin/maho set-key --service openai
bash scripts/start-mac.sh --port 8766
```

To run the tests on a Mac: `.venv/bin/python -m unittest discover -s tests -v`.
Node.js is needed for setup and frontend rebuilds; the running interface uses Python.

## Browser interface

From this project folder, start the local workspace:

```powershell
.\.venv\Scripts\maho.exe serve
```

It opens [Maho](http://127.0.0.1:8765) in your browser. Keep the server running;
press Ctrl+C in its terminal to stop it. The browser interface reads the existing
`outputs/` folders, including runs created from the command line.

- Search previous runs and switch between them.
- Play and seek the input video and each exported clip.
- Download MP4s and SRT subtitles.
- Inspect run settings, the timestamped transcript, structured clip JSON, and live run logs.
- Start a new run with a local video path, maximum clip count, duration range, start/end padding, and editorial instructions.

New browser runs get separate output folders and execute the existing pipeline using the
saved credentials, your editorial prompt, and **GPT-6 Sol with high reasoning effort**.
One browser-started run processes at a time.
Run progress updates every five seconds. Pipeline jobs keep running through a UI-server
restart; the interface detects their operating-system locks and restores live status.
Failed and interrupted runs remain visible;
use the CLI with that run's output folder to resume. Historical CLI runs do not have
recorded live logs. Missing source files and exports that no longer match the current
selection are clearly identified instead of serving a stale clip.

The server binds only to `127.0.0.1`; keys stay on the server. It streams video with
byte-range support. No cloud hosting or account is needed for the interface itself.
Use `--port 8766`, `--runs-dir "C:\path\to\outputs"`, or `--no-open` when needed.

The frontend is React + Vite. It is already built on this computer. After a fresh
checkout or frontend changes, rebuild it before starting `serve`:

```powershell
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
```

For frontend development, run the Python server with `--no-open`, then
`npm.cmd --prefix frontend run dev`. The Vite proxy sends API requests to port 8765.

## First run on this computer

Python dependencies are installed in `.venv`; FFmpeg and FFprobe are on PATH.
Both supplied API keys are already saved in Windows Credential Manager as
`Maho/AssemblyAI` and `Maho/OpenAI`. Run:

```powershell
.\.venv\Scripts\maho.exe doctor
.\.venv\Scripts\maho.exe run "C:\Videos\recording.mp4"
```

Run these commands from this project directory. OpenAI credentials are saved as `Maho/OpenAI`.
No API keys are stored in the source files. Replace a key with `maho set-key --service openai`
or `maho set-key --service assemblyai` using hidden input.

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
and runtime constraints. Runtime applies to selected content after recommended internal removals;
the selected source range may be longer. Export padding adds another three seconds by default.
Use the browser's padding fields or `--lead-seconds` / `--tail-seconds` (0–10 seconds each).
The renderer uses surrounding source footage without including neighboring transcript words;
if another spoken line or the source boundary leaves too little room, it holds the boundary
frame with silence for the remaining padding. Internal edits stay unchanged and subtitles
shift to match the export. These speech boundaries depend on AssemblyAI's timestamp accuracy.

To update existing exports locally without transcription or LLM calls:

```powershell
.\.venv\Scripts\maho.exe cut "C:\Videos\recording.mp4" --output outputs\recording --lead-seconds 1.5 --tail-seconds 1.5
```

Padding is saved separately in `job.json`; rerunning `run` or `cut` reuses those settings.
Changing padding regenerates exports while preserving the transcript and clip selection.

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
validated timestamps. Exact quotations are matched back to the source to ground hook timestamps.
Invalid suggestions receive up to two correction passes with surrounding transcript context and
private word IDs. Those IDs convert directly to original timestamps and are removed from the
delivered JSON. Previously validated clips are retained across corrections. Leading/trailing
removals become source trims before export padding is applied. Candidates that still fail are rejected.

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
| `transcript.txt` | Readable timestamped transcript with speaker labels |
| `transcript.timestamped.txt` | Exact start/end timestamps for every word, matching the AI input |
| `transcript.plain.txt` | Plain transcription without timestamps |
| `transcript.srt` | Full-video subtitles |
| `llm/*.json` | Cached raw model responses, request IDs, and usage |
| `clips.json` | Your exact editorial JSON structure |
| `selection.metadata.json` | Source/transcript/selection fingerprints, settings, and LLM request metadata |
| `clips/clip_01.mp4` | H.264/AAC edited clip; numbering follows editorial priority |
| `clips/clip_01.srt` | Subtitles relative to the edited clip |
| `clips/clip_01.json` | Editorial fields, source/frozen padding, retained segments, render fingerprint, and output paths |
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
`gpt-6-sol` via the Responses API with strict structured output and high reasoning effort.
Override with `--model`, `--reasoning-effort`, and `--max-output-tokens`. The default output/reasoning
budget is 32,768 tokens to leave room for the full editorial JSON.

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
are supported and take precedence over Windows Credential Manager or macOS Keychain. An API account and
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

The supplied 28-minute `long_video_test.mp4` was also processed end to end. Three validated
clips were exported at approximately 40.6, 34.7, and 38.2 seconds; two other proposals failed
verbatim hook validation and were excluded. Timestamped transcripts, the editorial JSON,
MP4s, and SRTs are saved in `outputs/long_video_test/`. A repeat run reused every completed
stage without new API calls. Automated tests also cover configurable render padding, silent
frame holds, caption alignment, and resume without additional provider calls.
