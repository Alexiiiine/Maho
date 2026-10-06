"""Render-only handles; editorial timestamps and paid selection stay unchanged."""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RenderOptions:
    lead_seconds: float = 1.5
    tail_seconds: float = 1.5

    def validate(self):
        for name in ("lead_seconds", "tail_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 10:
                raise ValueError(f"{name} must be between 0 and 10 seconds.")


def padded_edit(segments, words, duration, options):
    options.validate()
    first, last = segments[0][0], segments[-1][1]
    # Keep a small clearance from neighboring speech rather than exporting a
    # fragment of the preceding/next sentence. Fill unavailable time silently.
    previous = [w["end"] / 1000 for w in words if w["start"] / 1000 < first - 0.0001]
    following = [w["start"] / 1000 for w in words if w["end"] / 1000 > last + 0.0001]
    lower = min(first, max(previous) + 0.08) if previous else 0
    upper = max(last, min(following) - 0.08) if following else duration
    start = max(0, lower, first - options.lead_seconds)
    end = min(duration, upper, last + options.tail_seconds)
    source_lead, source_tail = first - start, end - last
    padded = list(segments)
    padded[0] = (round(start, 6), padded[0][1])
    padded[-1] = (padded[-1][0], round(end, 6))
    padding = {
        "lead_seconds": options.lead_seconds, "tail_seconds": options.tail_seconds,
        "source_lead_seconds": round(source_lead, 6), "source_tail_seconds": round(source_tail, 6),
        "freeze_lead_seconds": round(max(0, options.lead_seconds - source_lead), 6),
        "freeze_tail_seconds": round(max(0, options.tail_seconds - source_tail), 6),
    }
    return padded, padding
