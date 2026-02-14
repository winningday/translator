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

## Glossary CSV format

The glossary CSV must have a header row with columns `chinese`, `english`, and optionally `notes`:

```csv
chinese,english,notes
毛笔,brush,
调色盘,palette,
留白,negative space,intentional unpainted area
```

Place your glossary file anywhere and pass it with `-g`.

## How it works

1. **Parses** the SRT file (handles UTF-8, UTF-8 BOM, and GB18030 encodings)
2. **Detects the sketch-to-paint phase boundary** by scanning for contextual clues (pencil/eraser/outline keywords vs. color/brush/wash keywords)
3. **Batches subtitles** (default 35 per batch, with 5-subtitle overlap for context continuity) and sends them to Claude with:
   - A system prompt specialized for watercolor instruction translation
   - The current phase label (SKETCH or PAINT) so 画 is translated correctly
   - The glossary terms to enforce
4. **Reassembles** the translated subtitles with original timestamps intact

## Key design decisions

### Sketch vs. Paint (画)

The word 画 appears throughout but means different things at different stages:
- **Sketch phase**: "sketch," "draw," or "outline" (pencil work before any color)
- **Paint phase**: "paint," "apply," or "brush" (watercolor application)

The system detects the transition automatically using keyword heuristics and labels each batch accordingly. The LLM is instructed to respect the phase label.

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

## Project structure

```
srt_translator/
  __init__.py
  cli.py          # CLI entry point
  parser.py       # SRT parsing and writing
  glossary.py     # CSV glossary loading
  translator.py   # LLM translation with phase detection
input/            # Place Chinese SRT files here
output/           # Translated files go here
glossary.csv      # Your terminology glossary (create from glossary_template.csv)
```
