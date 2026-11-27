"""Write docs/flagcov-demo.srt: subtitles timed to the real voiceover in docs/flagcov-demo.mp4.

    python docs/tools/make_subtitles.py

Sentence timings come from the speech service's own sentence boundaries, and each scene is
offset by exactly the scene lengths make_video.py uses, so captions line up with the video.
Upload the .srt to YouTube (Subtitles > Upload file) so viewers can switch captions on.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import make_video as mv  # noqa: E402

ORDER = ["hook", "title", "explain_switch", "explain_split", "green", "reveal", "crash", "selfhosted", "dogfood", "pr", "close"]
OUT = mv.ROOT / "docs" / "flagcov-demo.srt"


def ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


READABLE = {
    "In twenty twelve": "In 2012",
    "four hundred and forty million dollars": "$440 million",
    "forty-five minutes": "45 minutes",
    "Six hundred and ninety": "690",
    "Ten percent": "10%",
    "a hundred shoppers": "100 shoppers",
    "sixty of them": "60 of them",
    "thirty a one-page": "30 a one-page",
    "and ten a brand new": "and 10 a brand new",
    "One in ten": "1 in 10",
    "Flagkov": "FlagCov",
}


def display(text: str) -> str:
    for spoken, shown in READABLE.items():
        text = text.replace(spoken, shown)
    text = text.replace("...", "").replace(" .", ".")
    return re.sub(r"\s+", " ", text).strip()


async def sentences(text: str) -> list[tuple[float, float, str]]:
    import edge_tts

    for attempt in range(6):
        out = []
        try:
            async for chunk in edge_tts.Communicate(text, mv.VOICE, rate="-4%", boundary="SentenceBoundary").stream():
                if chunk["type"] == "SentenceBoundary":
                    start = chunk["offset"] / 10_000_000
                    out.append((start, start + chunk["duration"] / 10_000_000, chunk["text"]))
            if out:
                return out
        except edge_tts.exceptions.NoAudioReceived:
            pass
        await asyncio.sleep(3 + attempt * 3)
    raise RuntimeError("speech service returned no sentence timings")


def scene_length(name: str) -> float:
    text = mv.NARRATION[name]
    cached = mv.CACHE / (hashlib.sha1(f"{mv.VOICE}|{text}".encode()).hexdigest()[:16] + ".mp3")
    if not cached.exists():
        raise SystemExit(f"Run make_video.py first (no cached voiceover for scene '{name}').")
    length = mv.duration(cached) + (2.4 if name == "close" else 0.9)
    return round(length * 30) / 30  # identical to the frame-exact scene length in make_video.py


def main() -> None:
    cues, offset = [], 0.0
    for name in ORDER:
        for start, end, text in asyncio.run(sentences(mv.NARRATION[name])):
            words = display(text)
            if words:
                cues.append((offset + start, offset + end + 0.25, words))
        offset += scene_length(name)
    lines = []
    for i, (start, end, text) in enumerate(cues, 1):
        nxt = cues[i][0] if i < len(cues) else end
        lines += [str(i), f"{ts(start)} --> {ts(min(end, nxt - 0.05))}", "\n".join(textwrap.wrap(text, 62)), ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT} ({len(cues)} captions, ends at {ts(offset)})")


if __name__ == "__main__":
    main()
