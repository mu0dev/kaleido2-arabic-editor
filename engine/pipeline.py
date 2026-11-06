"""Public export API for the Arabic translator editor."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .fnt6 import DEFAULT_ARABIC_FONT, build_font, mapped_codepoints
from .runtime import (
    CODEPOINT_RANGES,
    RuntimeConverter,
    TranslationError,
    WordRegistry,
    convert_dialogue,
    merge_dialogue,
)


@dataclass
class PreparedRuntime:
    dialogue: str
    ui_strings: dict[str, str]
    registry: WordRegistry
    report: dict[str, object]


@dataclass
class ExportResult:
    dialogue_path: Path
    story_font_path: Path
    system_font_path: Path
    mapping_path: Path
    report_path: Path
    ui_strings_path: Path | None
    report: dict[str, object]


def prepare_runtime(
    original_dialogue: str,
    edited_dialogue: str,
    original_story_font: bytes,
    original_system_font: bytes,
    *,
    ui_strings: Mapping[str, str] | None = None,
    max_width: float = 3000.0,
    arabic_font_path: Path = DEFAULT_ARABIC_FONT,
) -> PreparedRuntime:
    """Validate text and prepare a complete game dialogue plus glyph mapping.

    `edited_dialogue` may contain only changed IDs or the whole script. The
    original dialogue supplies all untouched entries and engine comments.
    """
    if max_width <= 0:
        raise TranslationError("max_width must be positive")
    if ui_strings is not None and (
        not isinstance(ui_strings, Mapping)
        or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in ui_strings.items()
        )
    ):
        raise TranslationError("UI strings must map string keys to string values")
    occupied = mapped_codepoints(original_story_font) | mapped_codepoints(original_system_font)
    occupied.update(map(ord, original_dialogue))
    occupied.update(map(ord, edited_dialogue))
    for ui_value in (ui_strings or {}).values():
        occupied.update(map(ord, ui_value))
    registry = WordRegistry(occupied, Path(arabic_font_path))
    converter = RuntimeConverter(registry, original_story_font, max_width)
    merged, edited_ids = merge_dialogue(original_dialogue, edited_dialogue)
    runtime = convert_dialogue(merged, converter)
    converted_ui = {
        key: converter.convert_ui_text(value)
        for key, value in (ui_strings or {}).items()
    }
    outside_pua = sum(
        not (CODEPOINT_RANGES[0][0] <= codepoint <= CODEPOINT_RANGES[0][1])
        for codepoint, _ in registry.tokens
    )
    report: dict[str, object] = {
        "edited_ids": len(edited_ids),
        "arabic_dialogue_lines": converter.converted_lines,
        "arabic_speaker_names": sorted(converter.translated_speakers),
        "inserted_line_breaks": converter.inserted_breaks,
        "unique_glyph_tokens": len(registry.tokens),
        "tokens_outside_bmp_private_use": outside_pua,
        "ui_strings_prepared": len(converted_ui),
        "ui_strings_need_game_specific_injection": bool(converted_ui),
        "typewriter_note": "Arabic appears one baked word at a time in left-to-right reveal order; completed rows read right-to-left.",
    }
    return PreparedRuntime(runtime, converted_ui, registry, report)


def export_patch(
    edited_dialogue_path: Path | str,
    original_dialogue_path: Path | str,
    original_story_font_path: Path | str,
    original_system_font_path: Path | str,
    output_dir: Path | str,
    *,
    ui_strings_path: Path | str | None = None,
    max_width: float = 3000.0,
    arabic_font_path: Path | str = DEFAULT_ARABIC_FONT,
) -> ExportResult:
    """Export game-ready script/fonts, leaving patch.rom compilation to the caller.

    Original FNT6 game fonts are read from the user's own extraction. They are
    never bundled with this source module. The output directory contains
    derived fonts and must remain local to the game owner.
    """
    edited_dialogue_path = Path(edited_dialogue_path)
    original_dialogue_path = Path(original_dialogue_path)
    original_story_font_path = Path(original_story_font_path)
    original_system_font_path = Path(original_system_font_path)
    output_dir = Path(output_dir)
    ui_data = None
    if ui_strings_path:
        ui_data = json.loads(Path(ui_strings_path).read_text(encoding="utf-8"))
        if not isinstance(ui_data, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in ui_data.items()
        ):
            raise TranslationError("UI strings file must be a JSON object of string keys and values")
    story_font = original_story_font_path.read_bytes()
    system_font = original_system_font_path.read_bytes()
    prepared = prepare_runtime(
        original_dialogue_path.read_text(encoding="utf-8"),
        edited_dialogue_path.read_text(encoding="utf-8"),
        story_font,
        system_font,
        ui_strings=ui_data,
        max_width=max_width,
        arabic_font_path=Path(arabic_font_path),
    )
    # Render both fonts before touching the output directory, so a bad token
    # or FNT6 capacity error cannot leave a half-built export behind.
    patched_story_font = build_font(story_font, prepared.registry.tokens, Path(arabic_font_path))
    patched_system_font = build_font(system_font, prepared.registry.tokens, Path(arabic_font_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    dialogue_path = output_dir / "dialogue.txt"
    story_path = output_dir / "newrodin-medium.fnt"
    system_path = output_dir / "system.fnt"
    mapping_path = output_dir / "mapping.json"
    report_path = output_dir / "report.json"
    ui_path = output_dir / "ui-runtime.json" if ui_data is not None else None
    dialogue_path.write_text(prepared.dialogue, encoding="utf-8")
    story_path.write_bytes(patched_story_font)
    system_path.write_bytes(patched_system_font)
    mapping_path.write_text(
        json.dumps(
            [{"codepoint": f"U+{cp:04X}", "text": token} for cp, token in prepared.registry.tokens],
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(json.dumps(prepared.report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if ui_path:
        ui_path.write_text(json.dumps(prepared.ui_strings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ExportResult(
        dialogue_path, story_path, system_path, mapping_path, report_path, ui_path, prepared.report
    )
