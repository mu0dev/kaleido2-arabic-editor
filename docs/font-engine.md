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
- Arabic words after `@r` are baked into font glyphs in reading order. Each
  word occurrence gets a horizontal glyph offset so the words occupy
  right-to-left positions within the row's native width while retaining
  positive advances for the game's reveal timing. Long rows get explicit
  `@r` breaks in logical reading order.
- Translate an entire dialogue line before export. A line that mixes Arabic
  with an untranslated Japanese run is rejected with its dialogue ID.
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
In a Linux Suyu check of dialogue ID `00007`, the native animation revealed
the rightmost Arabic word first, then a word to its left, and then the complete
line. Reveal is word by word because each word is one baked glyph. This check
covers that sample; other dialogue, control-tag combinations, and Windows
playback still need in-game review. The generated glyph map deduplicates a
word only when its horizontal offset also matches. A large translation can
therefore use substantially more codepoints and FNT6 descriptors than the
earlier one-glyph-per-word method. FNT6 permits fewer than 65,535 descriptors;
full-game capacity has not been measured. UI strings have API and synthetic
test coverage, but still require game-specific injection and screen verification.
