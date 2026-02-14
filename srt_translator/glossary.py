"""Load and apply a terminology glossary from CSV."""

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GlossaryEntry:
    """A single glossary entry mapping Chinese to English."""

    chinese: str
    english: str
    notes: str = ""


def load_glossary(path: Path) -> list[GlossaryEntry]:
    """Load glossary from a CSV file.

    Expected CSV columns: chinese, english, notes (optional)
    The first row is treated as a header.
    """
    entries = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entries.append(
                GlossaryEntry(
                    chinese=row["chinese"].strip(),
                    english=row["english"].strip(),
                    notes=row.get("notes", "").strip(),
                )
            )
    return entries


def format_glossary_for_prompt(entries: list[GlossaryEntry]) -> str:
    """Format glossary entries as a readable block for the LLM prompt."""
    if not entries:
        return ""
    lines = ["## Required Terminology Glossary", ""]
    lines.append("Use these exact translations when the Chinese term appears:")
    lines.append("")
    for e in entries:
        line = f"- {e.chinese} -> {e.english}"
        if e.notes:
            line += f"  ({e.notes})"
        lines.append(line)
    return "\n".join(lines)
