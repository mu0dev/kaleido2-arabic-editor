"""The image converter must see ASCII file arguments on Windows."""

from __future__ import annotations

import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import images


PNG = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 16, 16) + bytes(8)
TXA = b"TXA4" + bytes(12)
PIC = b"PIC4" + bytes(12)


class WindowsImagePathsTests(unittest.TestCase):
    def test_unicode_project_and_archive_names_use_ascii_extractor_arguments(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kaleido 日本語 ") as directory:
            root = Path(directory)
            rom = root / "game 日本語" / "data.rom"
            rom.parent.mkdir()
            rom.write_bytes(b"synthetic")
            project = root / "project 日本語"
            calls: list[list[str]] = []

            def run(args: list[str]) -> subprocess.CompletedProcess[str]:
                if args[1:3] == ["rom", "extract-one"]:
                    Path(args[-1]).parent.mkdir(parents=True, exist_ok=True)
                    Path(args[-1]).write_bytes(TXA)
                else:
                    calls.append(args)
                    self.assertTrue(all(arg.isascii() for arg in args[1:]), args)
                    if "-replace" in args:
                        replacement = Path(args[-1]).parent / "preview_label.png"
                        self.assertTrue(replacement.is_file())
                        Path(args[2]).write_bytes(TXA)
                    else:
                        Path(args[2]).with_name("preview_label.png").write_bytes(PNG)
                return subprocess.CompletedProcess(args, 0, "", "")

            asset = {"rom_path": "menu/日本語.txa", "kind": "txa", "group": "menu"}
            with patch.object(images, "list_image_assets", return_value=[asset]), \
                 patch.object(images, "_binary", return_value="converter"), \
                 patch.object(images, "_run", side_effect=run):
                manifest = images.export_images(rom, project, "sdu", "EnterExtractor")
                png = project / "images" / manifest["assets"][asset["rom_path"]]["images"][0]["path"]
                self.assertEqual(png.name, "日本語_label.png")
                png.write_bytes(PNG + b"changed")
                result = images.import_images(project, project / "patch", "EnterExtractor")

            self.assertEqual(len(calls), 2)
            self.assertEqual(result["changed_assets"], [asset["rom_path"]])
            self.assertEqual((project / "patch" / asset["rom_path"]).read_bytes(), TXA)

    def test_pic_conversion_uses_ascii_paths_too(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kaleido 日本語 ") as directory:
            root = Path(directory)
            rom = root / "data.rom"
            rom.write_bytes(b"synthetic")
            project = root / "project 日本語"
            converted = []

            def run(args: list[str]) -> subprocess.CompletedProcess[str]:
                if args[1:3] == ["rom", "extract-one"]:
                    Path(args[-1]).parent.mkdir(parents=True, exist_ok=True)
                    Path(args[-1]).write_bytes(PIC)
                else:
                    converted.append(args)
                    self.assertTrue(all(arg.isascii() for arg in args[1:]), args)
                    Path(args[2]).write_bytes(PIC if "-replace" in args else PNG)
                return subprocess.CompletedProcess(args, 0, "", "")

            asset = {"rom_path": "picture/日本語.pic", "kind": "pic", "group": "picture"}
            with patch.object(images, "list_image_assets", return_value=[asset]), \
                 patch.object(images, "_binary", return_value="converter"), \
                 patch.object(images, "_run", side_effect=run):
                manifest = images.export_images(rom, project, "sdu", "EnterExtractor", selected=[asset["rom_path"]])
                png = project / "images" / manifest["assets"][asset["rom_path"]]["images"][0]["path"]
                png.write_bytes(PNG + b"changed")
                result = images.import_images(project, project / "patch", "EnterExtractor")

            self.assertEqual(len(converted), 2)
            self.assertEqual(result["changed_assets"], [asset["rom_path"]])
            self.assertEqual((project / "patch" / asset["rom_path"]).read_bytes(), PIC)


if __name__ == "__main__":
    unittest.main()
