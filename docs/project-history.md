# Maho project history

Snapshot: October 6, 2026. This summarizes the project chats without copying API keys or credentials.

## Implemented pipeline

The **Build video transcription pipeline** chat produced a Python command-line application:

1. Extract audio from a local video while preserving its source timeline.
2. Upload it to AssemblyAI and save the transcription job for resumable polling.
3. Save the transcript as JSON, readable timestamped text, word-level timestamped text, plain text, and SRT.
4. Send the complete timestamped transcript and the supplied editorial prompt to an LLM.
5. Validate the structured selection against transcript words, exact hook wording, source boundaries, internal cuts, and finished runtime.
6. Render clips with FFmpeg, apply internal cuts, and retime subtitle sidecars.

The requested default is up to five clips, each 30–60 seconds after internal removals. Video path, clip count, runtime, model, project context, assignment notes, and editorial criteria are configurable. The supplied editorial prompt is preserved in `maho/prompts/select_clips.txt`; the public result schema is in `schemas/clips.schema.json`.

OpenAI is the default analysis provider through the Responses API. AssemblyAI's LLM Gateway remains optional; the configured account did not have working gateway model access during the initial check. Selection caches depend on the transcript, prompt, settings, and provider. Transcription IDs and completed renders are reused when applicable.

The real-video test exposed incomplete model responses and invalid proposed timestamps. The implementation now exposes reasoning/output budgets and performs bounded correction passes with surrounding transcript context. Corrections can use word IDs, which are converted to exact transcript timestamps before validation; these transport IDs do not change the delivered editorial JSON contract.

The renderer preserves the original composition and source order. Hook reorder flags, graphics markers, and question notes remain editing recommendations. Vertical cropping, burned-in captions, and Premiere integration have not been implemented.

## Verification snapshot

- Twenty-one existing tests passed during repository preparation, including real FFmpeg rendering, audio alignment, internal removals, subtitle offsets, timestamp validation, correction passes, word-ID conversion, API error redaction, and resumable execution with fake APIs.
- The pipeline chat recorded a successful live synthetic-video run: AssemblyAI transcription, OpenAI analysis using the supplied prompt, and a 50.32-second rendered clip.
- A 28-minute 18-second real video was transcribed into 5,418 words across two speakers. Two clips had rendered at this snapshot; further candidate correction and validation were still running in the pipeline chat.

Generated outputs, raw provider responses, uploaded-media URLs, source media, local environments, and credentials are kept outside version control. Test results above describe the October 6 snapshot, not a guarantee for arbitrary footage or future model responses.

## Premiere Pro research

The **Research Premiere Pro API** chat established the intended workflow: one sequence per exported clip, all within a Premiere project. This was research; no plugin has been added or tested in Premiere.

Adobe documents UXP support in Premiere Pro 25.6. Its Project API can create or open a project, import files, create a sequence from media, and save the project. An implementation would import the exports, retrieve and match imported media items, call `createSequenceFromMedia(name, [clip], sequenceBin)` for each clip, and save the project. `importFiles()` returns a boolean, so imported item objects must be retrieved separately. Explicit preset-based creation with `createSequenceWithPresetPath()` requires 26.3.

Sources checked October 6, 2026: [Adobe UXP introduction](https://developer.adobe.com/premiere-pro/uxp/introduction/), [Project API reference](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/project), and the [official sample repository](https://github.com/AdobeDocs/uxp-premiere-pro-samples).

## Mac setup research

The **Check Python installation on Mac** chat established the basic checks:

```sh
python3 --version
which python3
```

The project requires Python 3.11+ and FFmpeg/FFprobe. On non-Windows systems, provide `ASSEMBLYAI_API_KEY` and `OPENAI_API_KEY` through the environment; the Windows `set-key` command uses Windows Credential Manager. Never commit populated environment files or shell commands containing real keys.

See the root README for installation and command examples.
