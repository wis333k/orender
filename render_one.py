#!/usr/bin/env python
"""Render one comeback video inside GitHub Actions.

Input:  work/w_<yid>/ containing:
          script.json   - list of Vietnamese narration sentences
          s00.mp3 ...   - CapCut TTS per sentence
          sil.wav       - 0.45s silence
          src.mp4       - source clip trimmed to narration length
Output: <out>/<yid>.mp4

The source clip is produced on the PC (runner IPs are blocked by YouTube).
This script builds the narration wav, authors ASS subtitles, then ffmpeg.
"""
import json
import os
import subprocess
import sys

GAP = 0.45

ASS_HEAD = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, BackColour, "
            "Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginV\n"
            "Style: TikTok,Verdana,40,&H00FFFFFF,&H99000000,0,0,1,3,1,2,80\n[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")


def dur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", p],
                       capture_output=True, text=True)
    try:
        return float((r.stdout or "0").strip())
    except Exception:
        return 0.0


def ts(s):
    s = max(0, s)
    h, m = int(s // 3600), int(s % 3600 // 60)
    sec = s % 60
    ss = int(sec)
    cs = min(99, int((sec - ss) * 100))
    return f"{h}:{m:02d}:{ss:02d}.{cs:02d}"


def wrap(text):
    return " ".join(text.split())


def download(yid, dst):
    mm = "%02d:%02d" % (START // 60, START % 60)
    ee = "%02d:%02d" % ((START + SECLEN) // 60, (START + SECLEN) % 60)
    for fmt in (FMT, "best[height<=720]"):
        r = subprocess.run(["yt-dlp", "--no-playlist",
                            "--js-runtimes", "node",
                            "--download-sections", f"*{mm}-{ee}",
                            "-f", fmt, "--merge-output-format", "mp4",
                            "-o", dst, f"https://www.youtube.com/watch?v={yid}"],
                           capture_output=True, text=True)
        if dur(dst) >= 30:
            return True
        print("  yt-dlp:", (r.stderr or "")[-400:], flush=True)
        if os.path.exists(dst):
            os.remove(dst)
    return False


def main():
    yid = sys.argv[1]
    work = sys.argv[2] if len(sys.argv) > 2 else "."
    out = sys.argv[3] if len(sys.argv) > 3 else work
    wd = os.path.join(work, "w_" + yid)
    os.makedirs(wd, exist_ok=True)
    os.makedirs(out, exist_ok=True)
    out = os.path.abspath(out)
    wd = os.path.abspath(wd)
    src = os.path.join(wd, "src.mp4")
    if dur(src) < 30:
        print(f"{yid} NO-SOURCE", flush=True)
        sys.exit(2)

    sents = json.load(open(os.path.join(wd, "script.json"), encoding="utf-8"))
    os.chdir(wd)

    parts, marks, t = [], [], 0.0
    for i, s in enumerate(sents):
        mp3 = f"s{i:02d}.mp3"
        wav = f"s{i:02d}.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", mp3,
                        "-ar", "24000", "-ac", "1", wav], check=True)
        d = dur(wav)
        marks.append((t, t + d, s))
        t += d + GAP
        parts.append(wav)

    with open("lst.txt", "w") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
            f.write("file 'sil.wav'\n")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", "lst.txt", "-c:a", "pcm_s16le", "n.wav"], check=True)

    Tvid = dur("n.wav") + 1.0
    srcv = "src.mp4"
    loops = 0
    if dur("src.mp4") < Tvid + 2:
        # source shorter than narration -> loop it seamlessly instead of failing
        loops = int((Tvid + 2) // max(1.0, dur("src.mp4"))) + 1
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                        "-i", "color=c=black:s=1280x720:r=30",
                        "-i", "src.mp4"], capture_output=True)  # noop warm-up
        subprocess.run(["ffmpeg", "-y", "-v", "error",
                        "-stream_loop", str(loops), "-i", "src.mp4",
                        "-c", "copy", "src_loop.mp4"], check=True)
        srcv = "src_loop.mp4"

    body = ""
    for a, b, s in marks:
        if a >= Tvid + 2:
            break
        body += (f"Dialogue: 0,{ts(a - 0.05)},{ts(min(b + 0.12, Tvid + 2))},"
                 f"TikTok,,0,0,0,,{wrap(s)}\n")
    open("k.ass", "w", encoding="utf-8").write(ASS_HEAD + body)

    DD = str(int(Tvid) + 2)
    fc = (f"[0:v]scale=1280:720:flags=lanczos,setsar=1,eq=saturation=0.72,"
          f"vignette=PI/4.6,noise=alls=5:allf=t+u,ass=k.ass,"
          "drawtext=font='DejaVu Sans':"
          "text='OStudio Review':fontsize=28:fontcolor=white:"
          "borderw=2:bordercolor=black:x=30:y=40,"
          "unsharp=5:5:0.4:5:5:0.0[v];"
          f"sine=frequency=55:duration={DD},volume=0.06[dr];"
          f"anoisesrc=color=brown:duration={DD}:seed=7,lowpass=f=160,"
          "volume=0.09,tremolo=f=0.15:d=0.8[no];"
          "[dr][no]amix=inputs=2:duration=longest:normalize=0[bed];"
          "[0:a]volume=0.08[ab];[1:a]volume=2.4[an];"
          "[ab][an][bed]amix=inputs=3:duration=first:normalize=0,"
          "loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    final = os.path.join(out, yid + ".mp4")
    subprocess.run(["ffmpeg", "-y", "-ss", "0", "-t", str(Tvid),
                    "-i", srcv, "-i", "n.wav", "-filter_complex", fc,
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
                    "-preset", "medium", "-crf", "20", "-c:a", "aac",
                    "-shortest", final], check=True)
    print(f"{yid} OK {dur(final):.0f}s", flush=True)


if __name__ == "__main__":
    main()
