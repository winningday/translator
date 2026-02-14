"""SRT file parsing and writing utilities."""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Subtitle:
    """A single subtitle entry."""

    index: int
    start: str  # Timestamp string e.g. "00:01:23,456"
    end: str
    text: str


def parse_srt(content: str) -> list[Subtitle]:
    """Parse SRT content into a list of Subtitle objects."""
    # Normalize line endings
    content = content.replace("\r\n", "\n").strip()
    blocks = re.split(r"\n\n+", content)
    subtitles = []

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue

        try:
            index = int(lines[0].strip())
        except ValueError:
            continue

        timestamp_match = re.match(
            r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})",
            lines[1].strip(),
        )
        if not timestamp_match:
            continue

        start = timestamp_match.group(1)
        end = timestamp_match.group(2)
        text = "\n".join(lines[2:])

        subtitles.append(Subtitle(index=index, start=start, end=end, text=text))

    return subtitles


def write_srt(subtitles: list[Subtitle]) -> str:
    """Write subtitles back to SRT format string."""
    blocks = []
    for i, sub in enumerate(subtitles, 1):
        blocks.append(f"{i}\n{sub.start} --> {sub.end}\n{sub.text}")
    return "\n\n".join(blocks) + "\n"


def read_srt_file(path: Path) -> list[Subtitle]:
    """Read and parse an SRT file. Tries UTF-8 first, falls back to UTF-8-sig and GB18030."""
    for encoding in ["utf-8", "utf-8-sig", "gb18030"]:
        try:
            content = path.read_text(encoding=encoding)
            return parse_srt(content)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"Could not decode {path} with any supported encoding")


def write_srt_file(subtitles: list[Subtitle], path: Path) -> None:
    """Write subtitles to an SRT file."""
    path.write_text(write_srt(subtitles), encoding="utf-8")
