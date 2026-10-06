import json
import math
import os
import shutil
import subprocess

from .storage import write_text


def executable(name):
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"{name} is required on PATH.")
    return found


def run_process(args):
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr[-2000:]}")
    return result.stdout


def probe(path, require_video=True):
    data = json.loads(run_process([executable("ffprobe"), "-v", "error", "-show_format",
                                  "-show_streams", "-of", "json", str(path)]))
    duration = float(data.get("format", {}).get("duration", 0))
    streams = data.get("streams", [])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Could not determine a positive media duration.")
    if require_video and not any(s.get("codec_type") == "video" for s in streams):
        raise ValueError("The input must contain a video stream.")
    if not any(s.get("codec_type") == "audio" for s in streams):
        raise ValueError("The input must contain an audio stream.")
    return {"duration_seconds": duration, "streams": streams,
            "start_time": float(data.get("format", {}).get("start_time", 0))}


def extract_audio(video, destination):
    temp = destination.with_name("audio.partial.m4a")
    run_process([executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                 "-i", str(video), "-map", "0:a:0", "-vn", "-af", "aresample=async=1:first_pts=0",
                 "-ac", "1", "-ar", "16000", "-c:a", "aac", "-b:a", "64k", str(temp)])
    probe(temp, require_video=False)
    os.replace(temp, destination)


def render_clip(video, clip, destination):
    start, end = clip["start_seconds"], clip["end_seconds"]
    temp = destination.with_name(f"{destination.stem}.partial.mp4")
    run_process([executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                 "-ss", f"{start:.3f}", "-i", str(video), "-t", f"{end - start:.3f}",
                 "-map", "0:v:0", "-map", "0:a:0", "-sn", "-dn",
                 "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-preset", "fast",
                 "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                 "-af", "aresample=async=1:first_pts=0", "-movflags", "+faststart", str(temp)])
    info = probe(temp)
    if abs(info["duration_seconds"] - (end - start)) > 0.5:
        raise RuntimeError("Rendered clip duration differs from the requested range by more than 0.5 seconds.")
    os.replace(temp, destination)
    return info["duration_seconds"]


def render_edit(video, segments, destination):
    if len(segments) == 1:
        start, end = segments[0]
        return render_clip(video, {"start_seconds": start, "end_seconds": end}, destination)
    base, source_end = segments[0][0], segments[-1][1]
    count = len(segments)
    temp = destination.with_name(f"{destination.stem}.partial.mp4")
    graph = [f"[0:v]split={count}" + "".join(f"[vs{i}]" for i in range(count)),
             f"[0:a]aresample=async=1:first_pts=0,asplit={count}" + "".join(f"[as{i}]" for i in range(count))]
    for i, (start, end) in enumerate(segments):
        graph.append(f"[vs{i}]trim=start={start-base:.3f}:end={end-base:.3f},setpts=PTS-STARTPTS[v{i}]")
        graph.append(f"[as{i}]atrim=start={start-base:.3f}:end={end-base:.3f},asetpts=PTS-STARTPTS[a{i}]")
    graph.append("".join(f"[v{i}][a{i}]" for i in range(count)) + f"concat=n={count}:v=1:a=1[vc][ac]")
    graph.append("[vc]pad=ceil(iw/2)*2:ceil(ih/2)*2[vout]")
    run_process([executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                 "-ss", f"{base:.3f}", "-t", f"{source_end-base:.3f}", "-i", str(video),
                 "-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "[ac]", "-sn", "-dn",
                 "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(temp)])
    info = probe(temp)
    expected = sum(end - start for start, end in segments)
    if abs(info["duration_seconds"] - expected) > 0.5:
        raise RuntimeError("Rendered edit duration differs from the requested finished duration.")
    os.replace(temp, destination)
    return info["duration_seconds"]


def edit_subtitles(words, segments, destination):
    shifted, elapsed = [], 0
    for start, end in segments:
        for word in words:
            if word["start"] >= start * 1000 - 0.1 and word["end"] <= end * 1000 + 0.1:
                shifted.append({**word, "start": round(word["start"] - start * 1000 + elapsed * 1000),
                                "end": round(word["end"] - start * 1000 + elapsed * 1000)})
        elapsed += end - start
    subtitles(shifted, destination, limit=elapsed)


def timestamp(seconds):
    millis = max(0, round(seconds * 1000))
    hours, remain = divmod(millis, 3600000)
    minutes, remain = divmod(remain, 60000)
    secs, millis = divmod(remain, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def subtitles(words, destination, offset=0, limit=None):
    cues, group = [], []

    def flush():
        if not group:
            return
        start = max(0, group[0]["start"] / 1000 - offset)
        end = max(0, group[-1]["end"] / 1000 - offset)
        if limit is not None:
            end = min(limit, end)
        if end > start:
            cues.append(f"{len(cues) + 1}\n{timestamp(start)} --> {timestamp(end)}\n"
                        + " ".join(w["text"].replace("\n", " ") for w in group) + "\n")
        group.clear()

    for word in words:
        if group and (word.get("speaker") != group[-1].get("speaker") or
                      word["start"] - group[-1]["end"] > 1200):
            flush()
        group.append(word)
        if len(group) >= 12 or word["end"] - group[0]["start"] >= 4500 or word["text"].endswith((".", "?", "!")):
            flush()
    flush()
    write_text(destination, "\n".join(cues))
