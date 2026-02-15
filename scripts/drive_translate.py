#!/usr/bin/env python3
"""
Google Drive translation workflow.

Syncs .srt files from a shared Google Drive folder, translates them,
and syncs the results back so the artist can pick them up.

Requires:
  - rclone configured with a Google Drive remote (see SETUP.md)
  - ANTHROPIC_API_KEY environment variable set
  - translate-srt installed (pip install -e .)

Usage:
  python scripts/drive_translate.py              # process all new files
  python scripts/drive_translate.py --once       # process once and exit
  python scripts/drive_translate.py --dry-run    # show what would be processed
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# --- Configuration (edit these to match your setup) ---

# Name of the rclone remote you configured for Google Drive
RCLONE_REMOTE = "gdrive"
# Folder path on Google Drive shared with the artist
DRIVE_FOLDER = "Watercolor Translations"
# Local working directories
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_INPUT = PROJECT_ROOT / "drive_sync" / "input"
LOCAL_OUTPUT = PROJECT_ROOT / "drive_sync" / "output"
# Glossary file
GLOSSARY = PROJECT_ROOT / "watercolor_terminology_zh_en.csv"
# Track which files have already been processed
DONE_MARKER_DIR = PROJECT_ROOT / "drive_sync" / ".processed"


def sync_down():
    """Pull new .srt files from Google Drive to local input folder."""
    LOCAL_INPUT.mkdir(parents=True, exist_ok=True)
    remote_path = f"{RCLONE_REMOTE}:{DRIVE_FOLDER}/input"
    cmd = [
        "rclone", "copy", remote_path, str(LOCAL_INPUT),
        "--include", "*.srt",
        "--verbose",
    ]
    print(f"Syncing from Drive: {remote_path} -> {LOCAL_INPUT}")
    subprocess.run(cmd, check=True)


def sync_up():
    """Push translated files and review logs back to Google Drive."""
    remote_path = f"{RCLONE_REMOTE}:{DRIVE_FOLDER}/output"
    cmd = [
        "rclone", "copy", str(LOCAL_OUTPUT), remote_path,
        "--verbose",
    ]
    print(f"Syncing to Drive: {LOCAL_OUTPUT} -> {remote_path}")
    subprocess.run(cmd, check=True)


def get_new_files() -> list[Path]:
    """Find .srt files that haven't been processed yet."""
    DONE_MARKER_DIR.mkdir(parents=True, exist_ok=True)
    all_srt = sorted(LOCAL_INPUT.glob("*.srt"))
    new_files = []
    for f in all_srt:
        marker = DONE_MARKER_DIR / f"{f.name}.done"
        if not marker.exists():
            new_files.append(f)
    return new_files


def mark_done(srt_file: Path):
    """Mark a file as processed so we don't re-translate it."""
    marker = DONE_MARKER_DIR / f"{srt_file.name}.done"
    marker.write_text(f"Processed: {srt_file.name}\n")


def translate_file(srt_file: Path, dry_run: bool = False):
    """Run translate-srt on a single file."""
    LOCAL_OUTPUT.mkdir(parents=True, exist_ok=True)

    out_file = LOCAL_OUTPUT / srt_file.name.replace(".srt", "_en.srt")
    review_log = LOCAL_OUTPUT / srt_file.name.replace(".srt", "_review.log")

    cmd = [
        "translate-srt",
        str(srt_file),
        "-o", str(out_file),
        "--review-log", str(review_log),
    ]

    if GLOSSARY.exists():
        cmd.extend(["-g", str(GLOSSARY)])

    if dry_run:
        print(f"  [DRY RUN] Would run: {' '.join(cmd)}")
        return

    print(f"\n{'='*60}")
    print(f"Translating: {srt_file.name}")
    print(f"  Output:     {out_file.name}")
    print(f"  Review log: {review_log.name}")
    print(f"{'='*60}\n")

    result = subprocess.run(cmd)

    if result.returncode == 0:
        mark_done(srt_file)
        print(f"\nFinished: {srt_file.name}")
    else:
        print(f"\nERROR translating {srt_file.name} (exit code {result.returncode})")
        print("File will be retried on next run.")


def main():
    parser = argparse.ArgumentParser(
        description="Sync SRT files from Google Drive, translate, and sync back."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be processed without actually translating"
    )
    parser.add_argument(
        "--skip-sync", action="store_true",
        help="Skip Google Drive sync (use files already in drive_sync/input/)"
    )
    parser.add_argument(
        "--reprocess", type=str, default=None,
        help="Re-translate a specific file (by name, e.g., lesson1.srt)"
    )
    args = parser.parse_args()

    # Check API key
    if not args.dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    # Sync down from Drive
    if not args.skip_sync:
        try:
            sync_down()
        except FileNotFoundError:
            print("Error: rclone not found. Install it or use --skip-sync")
            print("  to work with files already in drive_sync/input/")
            sys.exit(1)
        except subprocess.CalledProcessError as e:
            print(f"Error syncing from Drive: {e}")
            sys.exit(1)

    # Handle reprocess flag
    if args.reprocess:
        target = LOCAL_INPUT / args.reprocess
        if not target.exists():
            print(f"Error: file not found: {target}", file=sys.stderr)
            sys.exit(1)
        # Remove done marker to allow reprocessing
        marker = DONE_MARKER_DIR / f"{target.name}.done"
        if marker.exists():
            marker.unlink()
        files = [target]
    else:
        files = get_new_files()

    if not files:
        print("\nNo new .srt files to process.")
        return

    print(f"\nFound {len(files)} file(s) to translate:")
    for f in files:
        print(f"  - {f.name}")

    # Translate each file
    for srt_file in files:
        translate_file(srt_file, dry_run=args.dry_run)

    if args.dry_run:
        print("\n[DRY RUN] No files were translated.")
        return

    # Sync results back to Drive
    if not args.skip_sync:
        try:
            sync_up()
            print("\nResults synced back to Google Drive.")
        except subprocess.CalledProcessError as e:
            print(f"\nWarning: failed to sync results to Drive: {e}")
            print(f"Results are available locally in: {LOCAL_OUTPUT}")
    else:
        print(f"\nResults available in: {LOCAL_OUTPUT}")

    print("\nAll done!")


if __name__ == "__main__":
    main()
