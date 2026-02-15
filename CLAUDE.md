# SRT Subtitle Translator

Translates Chinese watercolor class SRT subtitle files into natural American English using Claude as the translation engine.

## Setup

```bash
pip install -e .
```

Requires the `ANTHROPIC_API_KEY` environment variable to be set.

## Usage

### Translate a single file

```bash
translate-srt input/lesson1.srt -o output/lesson1_en.srt
```

### Translate with a glossary

```bash
translate-srt input/lesson1.srt -g glossary.csv -o output/lesson1_en.srt
```

### Translate all SRT files in a directory

```bash
translate-srt input/ -g glossary.csv -o output/
```

### Running as a Python module

```bash
python -m srt_translator.cli input/lesson1.srt -g glossary.csv -o output/
```

### Save a review log for human verification

```bash
translate-srt input/lesson1.srt -o output/lesson1_en.srt --review-log output/review.log
```

## Glossary CSV format

The glossary CSV must have a header row with columns `Chinese`, `English`, `Category` (optional), and `Notes` (optional):

```csv
Chinese,English,Category,Notes
毛笔,brush,Material,Chinese calligraphy/painting brush
调色盘,palette,Material,Surface for mixing paint
留白,preserving whites,Technique,Keeping areas of paper unpainted
晕染,blending / wet blending,Technique,"Intentional soft diffusion of color on wet paper, controlled bleeding"
```

See `watercolor_terminology_zh_en.csv` for the full reference glossary. Place your glossary file anywhere and pass it with `-g`.

## How it works

1. **Parses** the SRT file (handles UTF-8, UTF-8 BOM, and GB18030 encodings)
2. **Detects the sketch-to-paint phase boundary** using context-aware heuristics:
   - **Pass 1**: Looks for explicit transition phrases (e.g., "我们开始用颜色", "拿起毛笔") that definitively mark the switch to painting
   - **Pass 2**: Uses contextual keyword scoring — paint-context terms (颜色, 毛笔, 水彩, color names) score positively, sketch-only terms (铅笔, 橡皮, 起稿) score negatively, and ambiguous terms (轮廓, 构图, 比例) are flagged for review rather than counted
   - **Pass 3**: Falls back to overall paint-keyword density if no clear boundary is found
3. **Flags ambiguous subtitles** where terms like 轮廓 appear without clear phase context, producing a review log with timestamps for human verification
4. **Batches subtitles** (default 35 per batch, with 5-subtitle overlap for context continuity) and sends them to Claude with:
   - A system prompt specialized for watercolor instruction translation
   - The detected phase label as a guide (not an absolute rule)
   - The glossary terms to enforce
5. **Reassembles** the translated subtitles with original timestamps intact

## Key design decisions

### Context-aware phase detection

The system avoids hard-coding terms as belonging to a single phase. Many art terms are inherently ambiguous:

- **轮廓 (outline)**: Used during pencil sketching AND when painting outlines with a brush
- **勾勒/勾线 (delineate/line work)**: Can happen with pencil or brush
- **构图/比例 (composition/proportion)**: Discussed in either phase

Instead of counting these toward sketch or paint scores, they are **flagged for human review** when they appear without surrounding context that clarifies the phase. The LLM translator is also instructed to use surrounding context rather than relying solely on the phase label.

Strong phase signals are:
- **Paint transitions**: Explicit phrases like "我们开始用颜色", "拿起毛笔", "开始调色" — these definitively switch to paint mode
- **Paint context**: 颜色, 毛笔, 水彩, 渲染, 晕染, color names (赭石, 群青, 花青, etc.)
- **Sketch only**: 铅笔, 橡皮, 起稿, 草稿 — terms that only make sense during pencil work

### Review log

When the system encounters ambiguous subtitles, it produces a review log with:
- The flagged subtitle index, timestamp, and original text
- The reason it was flagged
- A summary of the detected phase boundary

Use `--review-log <path>` to save this to a file, or the CLI will print a count and suggest re-running with the flag.

### Sketch vs. Paint (画)

The word 画 appears throughout but means different things at different stages:
- **Sketch phase**: "sketch," "draw," or "outline" (pencil work before any color)
- **Paint phase**: "paint," "apply," or "brush" (watercolor application)

The system detects the transition automatically and labels each batch accordingly. The LLM is instructed to use the label as a guide but to override it when surrounding context clearly indicates otherwise.

### Batching with overlap

Subtitles are sent in batches of ~35 with 5-subtitle overlap between batches. This gives the LLM enough context to produce natural translations while keeping costs reasonable. Overlap ensures continuity at batch boundaries.

## CLI options

| Flag | Description | Default |
|------|-------------|---------|
| `input` | SRT file or directory | (required) |
| `-o`, `--output` | Output file or directory | `<input>_en.srt` |
| `-g`, `--glossary` | Glossary CSV path | none |
| `--model` | Claude model ID | `claude-sonnet-4-20250514` |
| `--batch-size` | Subtitles per batch | 35 |
| `--review-log` | Path for flagged-subtitle review log | none |

## Project structure

```
srt_translator/
  __init__.py
  cli.py          # CLI entry point
  parser.py       # SRT parsing and writing
  glossary.py     # CSV glossary loading
  translator.py   # LLM translation with context-aware phase detection
input/            # Place Chinese SRT files here
output/           # Translated files go here
glossary.csv      # Your terminology glossary (create from glossary_template.csv)
```
