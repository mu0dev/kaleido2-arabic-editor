# Arabic export engine

This module turns editable Arabic dialogue into a game-ready runtime script and
two FNT6 fonts. It needs the full original `dialogue.txt` from the Kaleido 2
patch project and `newrodin-medium.fnt` / `system.fnt` extracted from the
translator's own game copy. It does not ship game files or keys.

## Python API

```python
from engine import export_patch

result = export_patch(
    edited_dialogue_path="edits.txt",        # all or only changed ID<TAB>text lines
    original_dialogue_path="dialogue.txt",   # complete upstream patch script
    original_story_font_path="newrodin-medium.fnt",
    original_system_font_path="system.fnt",
    output_dir="build",
    max_width=3000,
)
print(result.report)
```

`prepare_runtime` accepts the same source data as strings/bytes for validation
and preview without writing files. `TranslationError` has messages suitable
for display in an editor.

## CLI

Run from the directory containing the `engine` package:

```bat
.venv\Scripts\python.exe -m engine export ^
  --edited edits.txt --original dialogue.txt ^
  --story-font newrodin-medium.fnt --system-font system.fnt ^
  --out build
```

The export writes `build/dialogue.txt` (all original entries with Arabic edits
converted), both patched fonts, `mapping.json`, and `report.json`. Place the
exported dialogue and fonts in the patch builder's source tree, then compile
its `patch.rom`; the export engine does not package the ROM itself.

Optional `--ui-json labels.json` accepts a JSON object of translated UI
strings and emits `ui-runtime.json` with their visual-order glyph references.
It does not inject UI labels into the game: each label still needs a
game-specific asset or script location.

## Text rules

- Keep engine control tags such as `@r`, `@vremo90010.`, and `@z150.`.
  The exporter preserves inline timing and wait commands (including `@k`,
  `@|`, `@x3820.`, `@s20.`, and `@a0.`) around Arabic text. For each edited
  ID, non-ruby commands must match the original in order and value; a missing
  voice or timing command stops export with an ID-specific error. Translators
  may add or move `@r` line breaks for layout.
- Arabic names before the first `@r` are encoded as one glyph each.
- Arabic words after `@r` are baked into font glyphs and reversed within each
  display row. Long rows get explicit `@r` breaks in logical reading order.
- If a translated line has ruby annotations (`@b`, `@<`, `@>`), flatten them
  into ordinary Arabic text. The exporter reports any ruby commands still
  present in an Arabic line.
- The default Arabic font is the bundled Noto Sans Arabic. `fontTools` verifies coverage;
  unsupported characters are reported before font generation.
- The glyph allocator first uses BMP Private Use codepoints, then free Hangul
  and CJK codepoints absent from both original fonts and original script. All
  assigned glyphs are embedded in the exported fonts.

## Runtime behavior

The completed rows read right-to-left and Arabic letters join correctly.
The game's native typewriter animation still reveals baked words from left to
right. The method is proven on the user's Suyu installation for Arabic
dialogue and an Arabic speaker name. UI strings have API and synthetic test
coverage, but still require game-specific injection and screen verification.
