from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import TranslationError, export_patch
from .fnt6 import DEFAULT_ARABIC_FONT


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m engine")
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="Build a complete runtime dialogue and Arabic FNT6 fonts")
    export.add_argument("--edited", required=True, type=Path, help="Translator edits (full or partial ID<TAB>text file)")
    export.add_argument("--original", required=True, type=Path, help="Full original dialogue.txt from patch project")
    export.add_argument("--story-font", required=True, type=Path, help="Extracted original newrodin-medium.fnt")
    export.add_argument("--system-font", required=True, type=Path, help="Extracted original system.fnt")
    export.add_argument("--out", required=True, type=Path, help="Local output directory")
    export.add_argument("--ui-json", type=Path, help="Optional key-to-Arabic UI label JSON for later injection")
    export.add_argument("--arabic-font", type=Path, default=DEFAULT_ARABIC_FONT)
    export.add_argument("--max-width", type=float, default=3000.0)
    args = parser.parse_args()
    try:
        result = export_patch(
            args.edited,
            args.original,
            args.story_font,
            args.system_font,
            args.out,
            ui_strings_path=args.ui_json,
            max_width=args.max_width,
            arabic_font_path=args.arabic_font,
        )
    except (TranslationError, ValueError, OSError) as error:
        parser.exit(2, f"Export failed: {error}\n")
    print(json.dumps({"output": str(args.out), **result.report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
