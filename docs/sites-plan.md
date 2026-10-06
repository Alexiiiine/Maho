# Maho on GPT Sites

Deferred on October 6, 2026. Continue with the local Mac app first; the Mac has no administrator access and cannot use Homebrew.

Maho can become a hosted webapp with GPT Sites serving the interface and a separate processing server running the existing Python pipeline and FFmpeg.

The proposed architecture is:

- GPT Sites for video uploads, run settings, progress, transcript inspection, clip previews, and downloads.
- R2 object storage for source videos, audio, transcripts, and exported clips.
- D1 for run metadata and processing status.
- A separate authenticated processing service with a durable job queue for AssemblyAI transcription, OpenAI analysis, and FFmpeg rendering.
- Server-side secret storage for provider credentials.

The local path field must become an upload or cloud-file selector. Uploads should support large files and interruption recovery. Cloud jobs must survive a browser closing, report their progress, and store their results for later access. User identity and access checks must protect each run and its files.

The existing selection, validation, rendering, prompt, and schema can be reused. The loopback Python HTTP server, local output catalog, operating-system credential store, and local-path assumptions require cloud adapters. GPT Sites is not a direct deployment target for the current Python process and FFmpeg subprocesses.

The intended experience is to open Maho in a browser, upload a video, choose options, wait for processing, and preview or download clips without installing Python or FFmpeg on the visitor's computer. Processing-server hosting and existing provider API usage are separate requirements.

Reference: [Official Sites documentation](https://learn.chatgpt.com/docs/sites).

No Site or cloud processing service has been created for this plan.
