"""LLM-based contextual translator using Claude API."""

import json
import re

import anthropic

from .glossary import GlossaryEntry, format_glossary_for_prompt
from .parser import Subtitle

# How many subtitles to send per translation batch. Larger batches give better
# context but cost more tokens. 30-40 is a sweet spot for SRT files.
DEFAULT_BATCH_SIZE = 35
# Overlap between batches so the LLM has continuity context.
BATCH_OVERLAP = 5

SYSTEM_PROMPT = """\
You are an expert Chinese-to-English subtitle translator specializing in \
watercolor painting instruction videos.

## Key rules

1. **Natural American English**: Produce translations that sound natural to an \
American English speaker. You may merge or lightly restructure phrases across \
subtitle lines to achieve natural phrasing, but each subtitle's text must stay \
with its own index/timestamp.

2. **Sketch vs. Paint distinction**: The Chinese character 画 (huà) can mean \
both "sketch/draw" and "paint." In these watercolor class videos:
   - The instructor typically begins with a PENCIL SKETCH phase — outlining \
the composition on paper before applying any color.
   - Later, the instructor transitions to the PAINTING phase — mixing and \
applying watercolor.
   - Use "sketch," "draw," or "outline" when the instructor is still working \
with pencil (no color yet).
   - Switch to "paint," "apply," or "brush" once color/watercolor is being used.
   - Context clues for the sketch phase: mentions of pencil (铅笔), eraser \
(橡皮), light lines (轻轻地), outline (轮廓), composition (构图), proportions (比例).
   - Context clues for the paint phase: mentions of brush (毛笔/笔), water (水), \
pigment/color (颜料/颜色/色), palette (调色盘), wet (湿), dry (干), wash (渲染), \
blending (晕染), layers (层).
   - You will be told the current phase in each batch. Trust that label unless \
the subtitle content clearly contradicts it.

3. **Preserve timestamps**: Return the same index numbers and timestamp ranges. \
Only translate the text content.

4. **Glossary**: When provided, always use the glossary translations for the \
specified Chinese terms. The glossary overrides your own judgment.

5. **Output format**: Return ONLY a valid JSON array. Each element must have \
keys "index" (int) and "text" (string). No markdown fencing, no extra commentary.
"""


def _detect_phase_boundary(subtitles: list[Subtitle]) -> int | None:
    """Heuristic: find the subtitle index where we likely transition from
    sketching to painting. Returns the index (0-based in the list) or None
    if no clear boundary is found (assume sketch throughout or painting
    throughout depending on content)."""
    paint_signals = re.compile(
        r"颜[料色]|调色|[毛]笔|水彩|渲染|晕染|上色|涂[抹色]|湿|干|洗|"
        r"刷|染|调[色和]|蘸|泡|铺[色底]|叠[加色]"
    )
    sketch_signals = re.compile(
        r"铅笔|橡皮|轮廓|构图|比例|线[条稿]|起[稿形]|草[稿图]|勾[勒线]"
    )

    # Score each subtitle
    paint_scores: list[float] = []
    for sub in subtitles:
        p = len(paint_signals.findall(sub.text))
        s = len(sketch_signals.findall(sub.text))
        paint_scores.append(p - s)

    # Use a rolling window to find where cumulative paint signal dominates
    window = 8
    for i in range(len(paint_scores) - window + 1):
        window_sum = sum(paint_scores[i : i + window])
        if window_sum >= 3:
            return i

    return None


def _build_batch_prompt(
    batch: list[Subtitle],
    phase: str,
    glossary_block: str,
) -> str:
    """Build the user message for a translation batch."""
    lines = []
    if glossary_block:
        lines.append(glossary_block)
        lines.append("")

    lines.append(f"## Current phase: {phase.upper()}")
    lines.append(
        'Translate 画 as "sketch"/"draw" for SKETCH phase or "paint" for PAINT phase, '
        "unless context clearly indicates otherwise."
    )
    lines.append("")
    lines.append("## Subtitles to translate")
    lines.append("")

    for sub in batch:
        lines.append(f"[{sub.index}]")
        lines.append(sub.text)
        lines.append("")

    lines.append("Return a JSON array: [{\"index\": N, \"text\": \"...\"}]")
    return "\n".join(lines)


def _parse_llm_response(raw: str) -> list[dict]:
    """Parse the LLM's JSON response, handling minor formatting issues."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def translate_subtitles(
    subtitles: list[Subtitle],
    glossary: list[GlossaryEntry] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    model: str = "claude-sonnet-4-20250514",
) -> list[Subtitle]:
    """Translate a full list of subtitles from Chinese to English.

    Uses batching with overlap for context continuity, automatic sketch/paint
    phase detection, and glossary enforcement.
    """
    client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var
    glossary_block = format_glossary_for_prompt(glossary) if glossary else ""

    # Detect phase boundary
    boundary = _detect_phase_boundary(subtitles)
    if boundary is not None:
        print(
            f"  Phase boundary detected at subtitle ~{subtitles[boundary].index} "
            f"(switching from sketch to paint)"
        )
    else:
        # If no boundary detected, check if the whole file is paint-heavy
        paint_signals = re.compile(r"颜[料色]|调色|水彩|渲染|上色|涂")
        total_paint = sum(
            1 for s in subtitles if paint_signals.search(s.text)
        )
        if total_paint > len(subtitles) * 0.3:
            boundary = 0  # Whole file is painting
            print("  Entire file detected as painting phase")
        else:
            boundary = len(subtitles)  # Whole file is sketching
            print("  Entire file detected as sketching phase")

    translated: dict[int, str] = {}

    # Process in overlapping batches
    start = 0
    batch_num = 0
    while start < len(subtitles):
        batch_num += 1
        end = min(start + batch_size, len(subtitles))
        batch = subtitles[start:end]

        # Determine phase for this batch's midpoint
        mid = start + len(batch) // 2
        phase = "sketch" if mid < boundary else "paint"

        # If batch spans the boundary, note it
        if start < boundary < end:
            phase_note = "sketch transitioning to paint"
        else:
            phase_note = phase

        print(
            f"  Translating batch {batch_num}: subtitles {batch[0].index}-{batch[-1].index} "
            f"(phase: {phase_note})"
        )

        prompt = _build_batch_prompt(batch, phase_note, glossary_block)

        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw_text = response.content[0].text
        results = _parse_llm_response(raw_text)

        for item in results:
            idx = item["index"]
            # Only store if it's in the non-overlap portion, or if we
            # haven't translated it yet (first batch has no overlap)
            if idx not in translated:
                translated[idx] = item["text"]

        # Advance past the non-overlap portion
        if end >= len(subtitles):
            break
        start = end - BATCH_OVERLAP

    # Build final subtitle list
    output = []
    for sub in subtitles:
        output.append(
            Subtitle(
                index=sub.index,
                start=sub.start,
                end=sub.end,
                text=translated.get(sub.index, sub.text),
            )
        )

    return output
