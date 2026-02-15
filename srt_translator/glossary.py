"""Load and apply a terminology glossary from CSV."""

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GlossaryEntry:
    """A single glossary entry mapping Chinese to English."""

    chinese: str
    english: str
    category: str = ""
    notes: str = ""


def load_glossary(path: Path) -> list[GlossaryEntry]:
    """Load glossary from a CSV file.

    Expected CSV columns: Chinese, English, Category (optional), Notes (optional)
    The first row is treated as a header.
    """
    entries = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Support both title-case and lower-case headers
            chinese = (row.get("Chinese") or row.get("chinese", "")).strip()
            english = (row.get("English") or row.get("english", "")).strip()
            category = (row.get("Category") or row.get("category", "")).strip()
            notes = (row.get("Notes") or row.get("notes", "")).strip()
            if chinese and english:
                entries.append(
                    GlossaryEntry(
                        chinese=chinese,
                        english=english,
                        category=category,
                        notes=notes,
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

    # Group by category for clarity
    by_category: dict[str, list[GlossaryEntry]] = {}
    for e in entries:
        cat = e.category or "General"
        by_category.setdefault(cat, []).append(e)

    for cat, cat_entries in by_category.items():
        lines.append(f"### {cat}")
        for e in cat_entries:
            line = f"- {e.chinese} -> {e.english}"
            if e.notes:
                line += f"  ({e.notes})"
            lines.append(line)
        lines.append("")

    return "\n".join(lines)
