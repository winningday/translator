"""LLM-based contextual translator using Claude API."""

import json
import re
from dataclasses import dataclass, field

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

3. **Context-aware phase interpretation**: Many terms are ambiguous on their \
own and must be interpreted based on surrounding context:
   - 轮廓 (outline) can appear in BOTH phases — artists outline with pencil \
during sketching AND paint outlines with a brush during the painting phase. \
Use the surrounding context (what tools/materials are being discussed) to \
determine the correct translation.
   - 笔 (pen/brush) could refer to a pencil in the sketch phase or a brush \
in the paint phase. Check what the instructor is doing with it.
   - You will be told the current detected phase in each batch. Trust that \
label as a starting point, but override it if the subtitle content clearly \
belongs to a different phase.

4. **Preserve timestamps**: Return the same index numbers and timestamp ranges. \
Only translate the text content.

5. **Glossary**: When provided, always use the glossary translations for the \
specified Chinese terms. The glossary overrides your own judgment.

6. **Output format**: Return ONLY a valid JSON array. Each element must have \
keys "index" (int) and "text" (string). No markdown fencing, no extra commentary.
"""


@dataclass
class FlaggedSubtitle:
    """A subtitle flagged for human review due to ambiguous phase detection."""

    index: int
    start: str
    end: str
    text: str
    reason: str


@dataclass
class TranslationResult:
    """Result of translating subtitles, including any items flagged for review."""

    subtitles: list[Subtitle]
    flagged: list[FlaggedSubtitle] = field(default_factory=list)
    phase_summary: str = ""


# ---------------------------------------------------------------------------
# Phase detection
# ---------------------------------------------------------------------------

# Strong paint-mode transition signals — explicit statements that the artist
# is switching to color work.  These act as a definitive mode switch.
_PAINT_TRANSITION_PHRASES = re.compile(
    r"开始[用上]颜?色|开始上色|现在[用上]颜?色|开始[画涂]颜色|"
    r"我们[来开]始[上用]色|准备上色|拿[起出]毛笔|换[成用]毛笔|"
    r"开始调[色颜]|我们上色|可以上色|来上色"
)

# Paint-context keywords — these suggest painting but are NOT definitive on
# their own.  They need density (several in a window) to flip the phase.
_PAINT_CONTEXT = re.compile(
    r"颜[料色]|调色|毛笔|水彩|渲染|晕染|上色|涂[抹色]|"
    r"蘸|铺[色底]|叠[加色]|颜色名"
)

# Common color names that strongly imply paint phase when they appear as
# materials being used (not just describing a reference photo, etc.)
_COLOR_NAMES = re.compile(
    r"红[色]?|蓝[色]?|黄[色]?|绿[色]?|紫[色]?|橙[色]?|"
    r"青[色]?|赭石|群青|花青|藤黄|朱[砂磦]|钛白|"
    r"深[红蓝绿黄紫]|浅[红蓝绿黄紫]|淡[红蓝绿黄紫]"
)

# Strong sketch-only keywords — things that ONLY make sense during pencil work.
# Notably, 轮廓 is NOT here because it is used in both phases.
_SKETCH_ONLY = re.compile(
    r"铅笔|橡皮|起[稿形]|草[稿图]|打[底稿]形"
)

# Ambiguous terms — present in both phases, need context to interpret.
_AMBIGUOUS_TERMS = re.compile(
    r"轮廓|勾[勒线]|线[条稿]|构图|比例"
)


def _detect_phase_boundary(
    subtitles: list[Subtitle],
) -> tuple[int, list[FlaggedSubtitle]]:
    """Context-aware phase boundary detection.

    Instead of hard-coding every keyword as sketch or paint, this function:
    1. Looks for explicit paint-transition phrases (definitive switch).
    2. Uses a softer scoring system for contextual keywords.
    3. Flags ambiguous subtitles for human review when confidence is low.

    Returns (boundary_index, flagged_items).
    boundary_index meanings:
      - 0 .. len-1: index in subtitles list where paint phase begins
      - len(subtitles): entire file is sketch phase
      - 0 with no sketch content: entire file is paint phase
    """
    flagged: list[FlaggedSubtitle] = []
    n = len(subtitles)

    # --- Pass 1: look for an explicit paint-transition phrase ---------------
    for i, sub in enumerate(subtitles):
        if _PAINT_TRANSITION_PHRASES.search(sub.text):
            return i, flagged

    # --- Pass 2: contextual scoring -----------------------------------------
    # Each subtitle gets a score:  positive = paint, negative = sketch
    scores: list[float] = []
    for sub in subtitles:
        paint = len(_PAINT_CONTEXT.findall(sub.text))
        colors = len(_COLOR_NAMES.findall(sub.text))
        sketch = len(_SKETCH_ONLY.findall(sub.text))
        ambig = len(_AMBIGUOUS_TERMS.findall(sub.text))

        # Colors mentioned alongside tool/technique words count as paint
        paint_score = paint + (colors * 0.7)
        sketch_score = sketch

        # Ambiguous terms: flag but don't count toward either side
        if ambig and paint == 0 and sketch == 0:
            flagged.append(
                FlaggedSubtitle(
                    index=sub.index,
                    start=sub.start,
                    end=sub.end,
                    text=sub.text,
                    reason=f"Ambiguous term(s) found without clear phase context",
                )
            )

        scores.append(paint_score - sketch_score)

    # Rolling window to find the transition
    window = 8
    for i in range(n - window + 1):
        window_sum = sum(scores[i : i + window])
        if window_sum >= 3:
            return i, flagged

    # --- Pass 3: fallback — check overall paint density ---------------------
    total_paint_subs = sum(
        1 for sub in subtitles if _PAINT_CONTEXT.search(sub.text)
    )
    if total_paint_subs > n * 0.3:
        return 0, flagged  # entire file is paint

    return n, flagged  # entire file is sketch


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

    lines.append(f"## Detected phase: {phase.upper()}")
    lines.append(
        'Translate 画 as "sketch"/"draw" for SKETCH phase or "paint" for PAINT phase. '
        "Use surrounding context (tools, materials, actions being discussed) to "
        "determine the correct interpretation — the phase label is a guide, not "
        "an absolute rule."
    )
    lines.append("")
    lines.append("## Subtitles to translate")
    lines.append("")

    for sub in batch:
        lines.append(f"[{sub.index}]")
        lines.append(sub.text)
        lines.append("")

    lines.append('Return a JSON array: [{"index": N, "text": "..."}]')
    return "\n".join(lines)


def _parse_llm_response(raw: str) -> list[dict]:
    """Parse the LLM's JSON response, handling minor formatting issues."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def format_review_log(flagged: list[FlaggedSubtitle], phase_summary: str) -> str:
    """Format flagged subtitles into a human-readable review log."""
    lines = ["=" * 60, "REVIEW LOG — Phase Detection Summary", "=" * 60, ""]
    lines.append(phase_summary)
    lines.append("")

    if not flagged:
        lines.append("No subtitles flagged for review. All phase assignments")
        lines.append("were made with sufficient context.")
    else:
        lines.append(
            f"{len(flagged)} subtitle(s) flagged for human verification:"
        )
        lines.append("")
        for item in flagged:
            lines.append(f"  [{item.index}] {item.start} --> {item.end}")
            lines.append(f"    Text: {item.text}")
            lines.append(f"    Flag: {item.reason}")
            lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


def translate_subtitles(
    subtitles: list[Subtitle],
    glossary: list[GlossaryEntry] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    model: str = "claude-sonnet-4-20250514",
) -> TranslationResult:
    """Translate a full list of subtitles from Chinese to English.

    Uses batching with overlap for context continuity, context-aware sketch/paint
    phase detection, and glossary enforcement.

    Returns a TranslationResult containing the translated subtitles and any
    items flagged for human review.
    """
    client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var
    glossary_block = format_glossary_for_prompt(glossary) if glossary else ""

    # Detect phase boundary
    boundary, flagged = _detect_phase_boundary(subtitles)

    if boundary == 0:
        phase_summary = "Entire file detected as painting phase."
        print(f"  {phase_summary}")
    elif boundary >= len(subtitles):
        phase_summary = "Entire file detected as sketching phase."
        print(f"  {phase_summary}")
    else:
        phase_summary = (
            f"Phase boundary detected at subtitle ~{subtitles[boundary].index} "
            f"(switching from sketch to paint)."
        )
        print(f"  {phase_summary}")

    if flagged:
        print(
            f"  {len(flagged)} subtitle(s) flagged for human review "
            f"(ambiguous phase context)"
        )

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

    return TranslationResult(
        subtitles=output,
        flagged=flagged,
        phase_summary=phase_summary,
    )
