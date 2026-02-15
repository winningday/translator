# Translation Workflow Setup

This guide explains how to set up the automated Google Drive translation workflow so your artist can simply drop `.srt` files into a shared folder and get translations back.

## How it works

```
Artist drops .srt file        You (or Claude Code)         Artist picks up results
into shared Drive folder  -->  runs the translation   -->  from the output folder
     "input/"                                                  "output/"
```

The artist sees two folders:
- **input/** — they drop their `.srt` subtitle files here
- **output/** — translated `_en.srt` files and `_review.log` files appear here

---

## One-time setup (your machine)

### 1. Install the translator

```bash
cd /path/to/translator
pip install -e .
```

### 2. Set your Anthropic API key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Add this to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.) so it persists.

### 3. Install rclone (for Google Drive sync)

**macOS:**
```bash
brew install rclone
```

**Linux:**
```bash
curl https://rclone.org/install.sh | sudo bash
```

**Windows:**
```
Download from https://rclone.org/downloads/
```

### 4. Configure rclone for Google Drive

```bash
rclone config
```

Follow the prompts:
1. Choose `n` for new remote
2. Name it `gdrive` (this matches the script's default)
3. Choose `drive` (Google Drive)
4. For client_id and client_secret, leave blank (uses rclone's defaults)
5. For scope, choose `1` (full access)
6. Follow the browser auth flow to grant access
7. Choose `n` for shared drive (unless using one)
8. Confirm with `y`

Test it works:
```bash
rclone lsd gdrive:
```
You should see your Google Drive folders listed.

### 5. Create the shared Drive folder

Create a folder on Google Drive called **"Watercolor Translations"** with two subfolders:

```
Watercolor Translations/
  input/
  output/
```

Share this folder with your artist's Google account (or generate a share link).

> **Tip:** If you want a different folder name, edit `DRIVE_FOLDER` at the top of `scripts/drive_translate.py`.

---

## Running the workflow

### Standard run (sync + translate + sync back)

```bash
python scripts/drive_translate.py
```

This will:
1. Download any new `.srt` files from Drive's `input/` folder
2. Translate each one (using the glossary automatically)
3. Upload the translated `.srt` + review log back to Drive's `output/` folder

### Check what's pending without translating

```bash
python scripts/drive_translate.py --dry-run
```

### Re-translate a specific file

```bash
python scripts/drive_translate.py --reprocess lesson5.srt
```

### Work without Drive sync (local files only)

If you already have the `.srt` file locally:
```bash
# Drop the file into drive_sync/input/ manually, then:
python scripts/drive_translate.py --skip-sync
```

Or use the CLI directly:
```bash
translate-srt myfile.srt -g watercolor_terminology_zh_en.csv -o output/myfile_en.srt --review-log output/myfile_review.log
```

---

## Using with Claude Code

You can also just tell Claude Code to do it:

> "Translate the new SRT file the artist uploaded"

or

> "Run the translation workflow"

Claude Code can run `python scripts/drive_translate.py` for you, or run `translate-srt` directly on files.

---

## What the artist gets back

For each uploaded file (e.g., `lesson5.srt`), two files appear in the `output/` folder:

| File | What it is |
|------|-----------|
| `lesson5_en.srt` | The translated English subtitle file, ready to use |
| `lesson5_review.log` | Notes on any subtitles that may need a manual check (ambiguous sketch/paint phase) |

The review log flags specific timestamps where a term like "outline" could mean pencil sketching OR brush painting, so you can verify the translator picked the right one.
