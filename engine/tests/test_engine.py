from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import TranslationError, export_patch, prepare_runtime
from engine import runtime
from engine.fnt6 import advance_width, mapped_codepoints


def tiny_fnt6(line_height: int = 80) -> bytes:
    """Synthetic source with mapped ASCII space and A; no game bytes."""
    pages, count = 1, 2
    start = 32 + pages * 514 + count * 24
    data = bytearray(b"FNT6")
    data.extend(struct.pack("<IIIHH6H", 1, 0, 1, pages, count, 20, 0, line_height - 10, 10, 41, 0))
    data.extend(struct.pack("<H", 0))
    mapping = [0xFFFF] * 256
    mapping[ord(" ")] = 0
    mapping[ord("A")] = 1
    data.extend(struct.pack("<256H", *mapping))
    data.extend(struct.pack("<hhHHHHIII", 0, 0, 8, 8, 440, 440, 1, 0, start))
    data.extend(struct.pack("<hhHHHHIII", 0, 0, 8, 8, 1000, 1000, 2, 0, start + 64))
    data.extend(bytes(128))
    struct.pack_into("<I", data, 8, len(data))
    return bytes(data)


class TranslatorEngineTests(unittest.TestCase):
    def test_export_merges_edits_and_builds_both_fonts(self) -> None:
        original = "# dialogue\n00007\t話者甲@r@vtest00010.仮文甲。\n00008\t話者乙@r@vtest10010.仮文乙。\n"
        edited = "00007\tالمتحدث@r@vtest00010.هذه جملة عربية قصيرة للاختبار.\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "original.txt").write_text(original, encoding="utf-8")
            (root / "edited.txt").write_text(edited, encoding="utf-8")
            (root / "story.fnt").write_bytes(tiny_fnt6())
            (root / "system.fnt").write_bytes(tiny_fnt6(60))
            (root / "ui.json").write_text(json.dumps({"settings": "الإعدادات"}, ensure_ascii=False), encoding="utf-8")
            result = export_patch(
                root / "edited.txt", root / "original.txt", root / "story.fnt",
                root / "system.fnt", root / "out", ui_strings_path=root / "ui.json",
                max_width=600,
            )
            runtime_text = result.dialogue_path.read_text(encoding="utf-8")
            self.assertIn("00008\t話者乙@r@vtest10010.仮文乙。", runtime_text)
            self.assertIn("@vtest00010.", runtime_text)
            self.assertNotIn("هذه", runtime_text)
            self.assertEqual(result.report["edited_ids"], 1)
            self.assertEqual(result.report["arabic_dialogue_lines"], 1)
            self.assertEqual(result.report["arabic_speaker_names"], ["المتحدث"])
            self.assertGreaterEqual(result.report["unique_glyph_tokens"], 6)
            for output in [result.story_font_path, result.system_font_path]:
                patched = output.read_bytes()
                self.assertEqual(patched[:4], b"FNT6")
                self.assertEqual(struct.unpack_from("<I", patched, 8)[0], len(patched))
                self.assertIn(ord("A"), mapped_codepoints(patched))
                self.assertGreater(len(mapped_codepoints(patched)), 2)
                self.assertEqual(advance_width(patched, ord(" ")), 27.5)
            self.assertIn("settings", json.loads(result.ui_strings_path.read_text(encoding="utf-8")))

    def test_game_control_tags_survive_arabic_text_around_them(self) -> None:
        original = (
            "00235\t@r仮文甲。@k@|仮文乙。\n"
            "00473\t話者甲@r@vtest20010.仮文甲。@k@|@x3820.仮文乙。@k@x7860.仮文丙。\n"
            "01714\t話者乙@r@vtest30010.例語は@bかり.@<仮@>です。\n"
            "05922\t@r@s20.@a0.仮文終。\n"
        )
        edited = (
            "00235\t@rنجحت البطاقة الأولى.@k@|نجحت الثانية.\n"
            "00473\tالمتحدث@r@vtest20010.هيا نبدأ.@k@|@x3820.نجحت الأولى.@k@x7860.نجحت الثانية.\n"
            "01714\tالمتحدثة@r@vtest30010.هذا نص تجريبي.\n"
            "05922\t@r@s20.@a0.إغلاق البرنامج.\n"
        )
        result = prepare_runtime(original, edited, tiny_fnt6(), tiny_fnt6())
        lines = dict(line.split("\t", 1) for line in result.dialogue.splitlines())
        for line_id, edited_value in runtime.parse_edits(edited).items():
            self.assertEqual(
                runtime.invariant_controls(edited_value, line_id),
                runtime.invariant_controls(lines[line_id], line_id),
            )
        self.assertIn("@k@|", lines["00235"])
        self.assertIn("@vtest20010.", lines["00473"])
        self.assertIn("@k@|@x3820.", lines["00473"])
        self.assertIn("@k@x7860.", lines["00473"])
        self.assertIn("@vtest30010.", lines["01714"])
        self.assertNotIn("@b", lines["01714"])
        self.assertIn("@s20.@a0.", lines["05922"])
        self.assertNotRegex(result.dialogue, runtime.ARABIC)
        self.assertEqual(result.report["arabic_dialogue_lines"], 4)

    def test_global_arabic_speaker_keeps_untouched_japanese_ruby(self) -> None:
        original = "01714\t話者乙@r@vtest30010.例語は@bかり.@<仮@>です。\n"
        edited = "01714\tالمتحدثة@r@vtest30010.例語は@bかり.@<仮@>です。\n"
        result = prepare_runtime(original, edited, tiny_fnt6(), tiny_fnt6())
        line = result.dialogue.splitlines()[0]
        self.assertIn("@r@vtest30010.例語は@bかり.@<仮@>です。", line)
        self.assertNotIn("المتحدثة", line)
        self.assertEqual(result.report["arabic_speaker_names"], ["المتحدثة"])

    def test_missing_or_changed_control_tags_are_rejected(self) -> None:
        base = "00473\t話者甲@r@vtest20010.仮文甲。@k@x3820.仮文乙。\n"
        for edited in (
            "00473\tالمتحدث@r@vtest20010.مرحبا.@x3820.ثانية.\n",
            "00473\tالمتحدث@r@vtest20010.مرحبا.@k@x3821.ثانية.\n",
            "00473\tالمتحدث@rمرحبا.@k@x3820.ثانية.\n",
        ):
            with self.subTest(edited=edited), self.assertRaisesRegex(TranslationError, "preserve control tags"):
                prepare_runtime(base, edited, tiny_fnt6(), tiny_fnt6())

    def test_unknown_or_malformed_control_tags_are_rejected(self) -> None:
        base = "00235\t@r仮文甲。\n"
        for tag in ("@q", "@xfoo.", "@x", "@z100"):
            with self.subTest(tag=tag), self.assertRaisesRegex(TranslationError, "control tag|parameter"):
                prepare_runtime(base, f"00235\t@rمرحبا{tag}عالم\n", tiny_fnt6(), tiny_fnt6())
        self.assertEqual(
            runtime.invariant_controls("@r@vtest00010|test10010.مرحبا", "01561"),
            ["@vtest00010|test10010."],
        )

    def test_ruby_tags_and_missing_font_glyph_are_actionable_errors(self) -> None:
        base = "00007\t話者甲@r仮文甲。\n"
        font = tiny_fnt6()
        with self.assertRaisesRegex(TranslationError, "flatten ruby tags"):
            prepare_runtime(base, "00007\t話者甲@rمرحبا@bعالم\n", font, font)
        with self.assertRaisesRegex(TranslationError, "font lacks"):
            prepare_runtime(base, "00007\t話者甲@rمرحبا*\n", font, font)

    def test_allocator_uses_next_safe_bmp_range_when_pua_is_full(self) -> None:
        with patch.object(runtime, "CODEPOINT_RANGES", ((0xE000, 0xE000), (0xAC00, 0xAC01))):
            registry = runtime.WordRegistry(set())
            self.assertEqual(ord(registry.register("مرحبا")), 0xE000)
            self.assertEqual(ord(registry.register("عالم")), 0xAC00)
            self.assertEqual(ord(registry.register("أهلا")), 0xAC01)
            with self.assertRaisesRegex(TranslationError, "No unused Unicode"):
                registry.register("كلمة")


if __name__ == "__main__":
    unittest.main()
