"""Pipeline settings and validation of AssemblyAI word timestamps."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SelectionOptions:
    count: int = 5
    min_seconds: float = 30
    max_seconds: float = 60
    criteria: str = ""
    model: str = "gpt-5-mini"
    reasoning_effort: str = "low"
    max_output_tokens: int = 32768
    project_info: dict = field(default_factory=dict)
    assignment_notes: str = ""
    editorial_prompt: str = ""

    def validate(self):
        if not 1 <= self.count <= 50:
            raise ValueError("Clip count must be between 1 and 50.")
        if not 0 < self.min_seconds <= self.max_seconds <= 3600:
            raise ValueError("Require 0 < min-seconds <= max-seconds <= 3600.")
        if not isinstance(self.project_info, dict):
            raise ValueError("Project information must be a JSON object.")
        if not self.model.strip():
            raise ValueError("A model ID is required.")
        if self.reasoning_effort not in ("low", "medium", "high"):
            raise ValueError("Reasoning effort must be low, medium, or high.")
        if not 4096 <= self.max_output_tokens <= 128000:
            raise ValueError("max-output-tokens must be between 4096 and 128000.")


def validate_words(transcript, duration):
    words = transcript.get("words")
    if not isinstance(words, list) or not words:
        raise ValueError("No timestamped speech found in the transcript.")
    last = -1
    for word in words:
        if not isinstance(word, dict) or not isinstance(word.get("text"), str):
            raise ValueError("Malformed transcript word.")
        start, end = word.get("start"), word.get("end")
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not 0 <= start <= end <= (duration + 0.1) * 1000 or start < last):
            raise ValueError("Transcript word timestamps are invalid or outside the source video.")
        last = start
    return words

