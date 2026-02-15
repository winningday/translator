"""CLI entry point for SRT translation."""

import argparse
import sys
from pathlib import Path

from .glossary import load_glossary
from .parser import read_srt_file, write_srt_file
from .translator import format_review_log, translate_subtitles


def main():
    parser = argparse.ArgumentParser(
        description="Translate Chinese SRT subtitle files to English using Claude LLM.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Translate a single file
  translate-srt input/lesson1.srt -o output/lesson1_en.srt

  # Translate with a glossary
  translate-srt input/lesson1.srt -g glossary.csv -o output/lesson1_en.srt

  # Translate all .srt files in a directory
  translate-srt input/ -g glossary.csv -o output/

  # Use a specific model
  translate-srt input/lesson1.srt --model claude-sonnet-4-20250514

  # Save a review log for ambiguous phase detections
  translate-srt input/lesson1.srt -o output/lesson1_en.srt --review-log output/review.log
""",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Input SRT file or directory containing SRT files",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output SRT file or directory. Defaults to <input_name>_en.srt",
    )
    parser.add_argument(
        "-g",
        "--glossary",
        type=Path,
        default=None,
        help="Path to glossary CSV file (columns: chinese, english, notes)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="claude-sonnet-4-20250514",
        help="Claude model to use (default: claude-sonnet-4-20250514)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=35,
        help="Number of subtitles per translation batch (default: 35)",
    )
    parser.add_argument(
        "--review-log",
        type=Path,
        default=None,
        help="Path to write a review log of flagged subtitles needing human verification",
    )

    args = parser.parse_args()

    # Load glossary if provided
    glossary = None
    if args.glossary:
        if not args.glossary.exists():
            print(f"Error: glossary file not found: {args.glossary}", file=sys.stderr)
            sys.exit(1)
        glossary = load_glossary(args.glossary)
        print(f"Loaded {len(glossary)} glossary entries from {args.glossary}")

    # Collect input files
    input_path: Path = args.input
    if input_path.is_dir():
        srt_files = sorted(input_path.glob("*.srt"))
        if not srt_files:
            print(f"Error: no .srt files found in {input_path}", file=sys.stderr)
            sys.exit(1)
    elif input_path.is_file():
        srt_files = [input_path]
    else:
        print(f"Error: input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Determine output directory/file
    output_path: Path | None = args.output

    all_flagged = []

    for srt_file in srt_files:
        print(f"\nProcessing: {srt_file.name}")

        # Determine output path for this file
        if output_path is None:
            out_file = srt_file.with_stem(srt_file.stem + "_en")
        elif output_path.suffix == ".srt":
            out_file = output_path
        else:
            # Output is a directory
            output_path.mkdir(parents=True, exist_ok=True)
            out_file = output_path / srt_file.with_stem(srt_file.stem + "_en").name

        subtitles = read_srt_file(srt_file)
        print(f"  Parsed {len(subtitles)} subtitles")

        result = translate_subtitles(
            subtitles,
            glossary=glossary,
            batch_size=args.batch_size,
            model=args.model,
        )

        write_srt_file(result.subtitles, out_file)
        print(f"  Written to: {out_file}")

        if result.flagged:
            all_flagged.extend(result.flagged)

        # Write or print review log if there are flagged items or if requested
        if args.review_log:
            log_content = format_review_log(result.flagged, result.phase_summary)
            if len(srt_files) > 1:
                # For multiple files, append with file header
                mode = "a" if srt_file != srt_files[0] else "w"
                with open(args.review_log, mode, encoding="utf-8") as f:
                    f.write(f"\n--- {srt_file.name} ---\n")
                    f.write(log_content)
                    f.write("\n")
            else:
                args.review_log.parent.mkdir(parents=True, exist_ok=True)
                args.review_log.write_text(log_content, encoding="utf-8")
                print(f"  Review log written to: {args.review_log}")

    # Print summary
    if all_flagged and not args.review_log:
        print(f"\n⚠ {len(all_flagged)} subtitle(s) had ambiguous phase context.")
        print("  Re-run with --review-log <path> to save details for review.")

    print("\nDone.")


if __name__ == "__main__":
    main()
