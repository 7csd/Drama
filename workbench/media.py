import asyncio
import json
import shutil
import wave
import zipfile
from pathlib import Path

import imageio_ffmpeg


async def ffmpeg(args, cwd=None):
    proc = await asyncio.create_subprocess_exec(
        imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *map(str, args),
        cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        _, error = await asyncio.wait_for(proc.communicate(), 300)
    except BaseException:
        proc.kill()
        await proc.wait()
        raise
    if proc.returncode:
        raise ValueError("媒体处理失败：" + error.decode(errors="replace")[-1500:])


def dimensions(aspect):
    return (720, 1280) if aspect == "9:16" else (1280, 720)


def wav_duration(path):
    with wave.open(str(path), "rb") as audio:
        return audio.getnframes() / audio.getframerate()


def pad_voice(source, destination, duration):
    """Pad silence, never repeat or stretch a character's line."""
    with wave.open(str(source), "rb") as original:
        params = original.getparams()
        frames = original.readframes(original.getnframes())
        missing = max(0, round(duration * original.getframerate()) - original.getnframes())
        silence = b"\0" * (missing * original.getnchannels() * original.getsampwidth())
    with wave.open(str(destination), "wb") as padded:
        padded.setparams(params)
        padded.writeframes(frames + silence)


def srt_time(seconds):
    ms = round(seconds * 1000)
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    seconds, ms = divmod(ms, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"


def write_srt(path, shots):
    entries, offset = [], 0.0
    for shot in shots:
        duration = shot["duration"]
        if shot.get("dialogue"):
            text = shot["dialogue"].replace("\r", " ").replace("\n", " ").replace("-->", "→")
            # Wrap Chinese subtitles without relying on spaces between words.
            text = "\n".join(text[i:i + 22] for i in range(0, len(text), 22))
            subtitle_duration = min(duration, shot.get("speech_duration", duration))
            entries.append(f"{len(entries) + 1}\n{srt_time(offset)} --> {srt_time(offset + subtitle_duration)}\n{text}\n")
        offset += duration
    path.write_text("\n".join(entries), encoding="utf-8")
    return offset


async def compose(store, job, payload):
    folder = store.media_path(job["id"])
    folder.mkdir(exist_ok=True)
    width, height = dimensions(payload["aspect"])
    clips, shot_data = [], []
    for idx, shot in enumerate(payload["shots"]):
        output = folder / f"clip_{idx:03}.mp4"
        video = store.media_path(shot["video"])
        audio = store.media_path(shot["audio"])
        duration = shot["duration"]
        args = ["-i", video, "-i", audio, "-map", "0:v:0", "-map", "1:a:0", "-t", duration,
                "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,tpad=stop_mode=clone:stop_duration=30",
                "-af", "apad,loudnorm=I=-16:TP=-1.5:LRA=11", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "24000", "-ac", "1", output]
        await ffmpeg(args)
        clips.append(output)
        shot_data.append(shot)
    (folder / "concat.txt").write_text("\n".join(f"file '{clip.name}'" for clip in clips), encoding="utf-8")
    duration = write_srt(folder / "subtitles.srt", shot_data)
    await ffmpeg(["-f", "concat", "-safe", "0", "-i", "concat.txt", "-vf",
                  "subtitles=subtitles.srt:force_style='FontName=Microsoft YaHei,FontSize=18,MarginV=36'",
                  "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-c:a", "aac", "-movflags", "+faststart", "final.mp4"], cwd=folder)
    return {"path": f"{job['id']}/final.mp4", "subtitles": f"{job['id']}/subtitles.srt",
            "duration": duration, "simulated": payload["simulated"]}


def bundle(store, project, episode, assets, shots, jobs, reviews, result):
    folder = store.media_path(Path(result["path"]).parent)
    manifest = {"schema_version": 1, "project": project, "episode": episode, "assets": assets,
                "shots": shots, "jobs": jobs, "reviews": reviews, "output": result}
    manifest_path = folder / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    archive_path = folder / "delivery.zip"
    paths = {result["path"], result["subtitles"], manifest_path.relative_to(store.root / "media").as_posix()}
    for item in assets:
        if item.get("image"):
            paths.add(item["image"])
    for job in jobs:
        if job.get("result", {}).get("path"):
            paths.add(job["result"]["path"])
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            source = store.media_path(path)
            if source.is_file():
                archive.write(source, path)
    return archive_path.relative_to(store.root / "media").as_posix()
