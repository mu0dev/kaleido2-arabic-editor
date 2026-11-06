"""Asset-free checks for the local editor's Windows build paths."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import Project
from engine.fnt6 import DEFAULT_ARABIC_FONT
from engine.images import _run
from engine.tests.test_engine import tiny_fnt6


class WindowsApplicationTests(unittest.TestCase):
    def test_subprocess_text_keeps_utf8_archive_names(self) -> None:
        # sdu's archive listing includes Japanese paths; Windows process text
        # decoding must not use the machine's ANSI code page.
        with patch.dict(os.environ, {"PYTHONIOENCODING": "utf-8"}):
            result = _run([sys.executable, "-c", "print('FILE /picture/日本語.pic')"])
        self.assertEqual(result.stdout.strip(), "FILE /picture/日本語.pic")

    def test_export_builds_with_unicode_and_space_filled_windows_paths(self) -> None:
        self.assertTrue(DEFAULT_ARABIC_FONT.is_file(), DEFAULT_ARABIC_FONT)
        with tempfile.TemporaryDirectory(prefix="kaleido Arabic 日本語 ") as directory:
            root = Path(directory)
            game = root / "owned game 日本語"
            game.mkdir()
            (game / "dialogue.txt").write_text("00007\t話者甲@rこんにちは。\n", encoding="utf-8")
            (game / "main.rb").write_text("", encoding="utf-8")
            (game / "story.fnt").write_bytes(tiny_fnt6())
            (game / "system.fnt").write_bytes(tiny_fnt6())
            (game / "data.rom").write_bytes(b"synthetic test marker")

            patch_source = root / "patch source 日本語"
            (patch_source / "base").mkdir(parents=True)
            (patch_source / "rom_source").mkdir()
            (patch_source / "base" / "main.rb").write_text("", encoding="utf-8")
            (patch_source / "compile.rb").write_text(
                "'''\nrequire 'fileutils'\nkaleido_cmd = ['ruby', 'kal_tl.rb',\n'''\n"
                "from pathlib import Path\nimport sys\n"
                "Path(sys.argv[1]).write_bytes(b'synthetic patch')\n",
                encoding="utf-8",
            )

            kaleido = root / "Kaleido compiler 日本語" / "rom-repack"
            kaleido.mkdir(parents=True)
            (kaleido / "toolkit.rb").write_text("File.read(entry_path)\n", encoding="utf-8")
            (kaleido / "scenario.rb").write_text("File.write(file, data)\n", encoding="utf-8")
            (kaleido / "kal_tl.rb").write_text("File.read(e).lines\n", encoding="utf-8")

            config = root / "editor config 日本語.json"
            config.write_text(json.dumps({
                "project_dir": (root / "translation project 日本語").as_posix(),
                "original_dialogue": (game / "dialogue.txt").as_posix(),
                "original_script": (game / "main.rb").as_posix(),
                "original_story_font": (game / "story.fnt").as_posix(),
                "original_system_font": (game / "system.fnt").as_posix(),
                "arabic_font_path": DEFAULT_ARABIC_FONT.as_posix(),
                "data_rom": (game / "data.rom").as_posix(),
                "patch_source": patch_source.as_posix(),
                "kaleido_path": kaleido.parent.as_posix(),
                "ruby_bin": Path(sys.executable).as_posix(),
                "suyu_load_dir": (root / "Suyu load 日本語").as_posix(),
                "title_id": "0100451020714000",
                "mod_name": "Arabic Editor",
            }, ensure_ascii=False), encoding="utf-8")

            project = Project(config)
            self.assertTrue(project.status()["ready"])
            project.save_dialogue("00007", "مرحبا يا صديقي.")
            result = project.export()
            patch = Path(result["path"])
            self.assertEqual(patch.read_bytes(), b"synthetic patch")
            self.assertEqual(result["dialogue_translated"], 1)
            self.assertGreater(result["font_tokens"], 0)
            copied = project.root / "build" / "workspace" / "kaleido" / "rom-repack"
            self.assertIn("File.binread(entry_path)", (copied / "toolkit.rb").read_text(encoding="utf-8"))
            self.assertIn("File.read(entry_path)", (kaleido / "toolkit.rb").read_text(encoding="utf-8"))

            installed = project.install()
            self.assertEqual(Path(installed["path"]).read_bytes(), b"synthetic patch")

if __name__ == "__main__":
    unittest.main()
