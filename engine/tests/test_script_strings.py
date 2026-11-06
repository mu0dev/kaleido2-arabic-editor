from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from engine.runtime import TranslationError
from engine.script_strings import (
    catalog_json,
    export_script_strings,
    extract_script_strings,
    merge_script_strings,
)


SCRIPT = r'''snr.bgm 'GRKS2_ED', %(Track (ver1.0)), 65535
snr.table8_entry 'cg-scene', 0
s.ins SAVEINFO, byte(1), "Chapter one"
s.ins SELECT, ushort(0), ushort(0), ushort(1), 4095, "NCSELECT", "First\u0000Second\u0000"
'''


class ScriptStringTests(unittest.TestCase):
    def test_extract_and_merge_without_changing_resource_ids_or_options(self) -> None:
        entries = extract_script_strings(SCRIPT)
        self.assertEqual(Counter(item.kind for item in entries), {
            "bgm": 1, "gallery_key": 1, "saveinfo": 1, "select_option": 2,
        })
        self.assertFalse(next(item for item in entries if item.kind == "gallery_key").editable)
        edits = {
            "bgm:GRKS2_ED": 'لحن (إصدار ١)',
            "saveinfo:01": 'الفصل "الأول" #{literal}',
            "select:01:option:02": "المرة الثانية",
        }
        merged = merge_script_strings(
            SCRIPT, edits,
            expected_sources={entry.id: entry.source for entry in entries},
        )
        self.assertIn("snr.bgm 'GRKS2_ED'", merged)
        self.assertIn("snr.table8_entry 'cg-scene', 0", merged)
        self.assertEqual(merged.count(r"\u0000"), 2)
        self.assertIn(r'\#{literal}', merged)
        catalog = {entry.id: entry for entry in extract_script_strings(merged)}
        for key, value in edits.items():
            self.assertEqual(catalog[key].source, value)
        self.assertEqual(catalog["select:01:option:01"].source, "First")

    def test_rejects_asset_key_edit_stale_source_and_control_injection(self) -> None:
        with self.assertRaisesRegex(TranslationError, "CG asset key"):
            merge_script_strings(SCRIPT, {"gallery_key:01": "مشهد"})
        with self.assertRaisesRegex(TranslationError, "source changed"):
            merge_script_strings(
                SCRIPT, {"saveinfo:01": "الفصل"},
                expected_sources={"saveinfo:01": "stale title"},
            )
        with self.assertRaisesRegex(TranslationError, "tabs, line breaks"):
            merge_script_strings(SCRIPT, {"saveinfo:01": "two\nlines"})
        with self.assertRaisesRegex(TranslationError, "Unknown script string IDs"):
            merge_script_strings(SCRIPT, {"bgm:missing": "x"})

    def test_json_export_preserves_unedited_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script_path = root / "main.rb"
            catalog_path = root / "catalog.json"
            output_path = root / "out" / "main.rb"
            script_path.write_text(SCRIPT, encoding="utf-8")
            rows = json.loads(catalog_json(SCRIPT))
            next(row for row in rows if row["id"] == "saveinfo:01")["translation"] = "الفصل الأول"
            catalog_path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            export_script_strings(script_path, catalog_path, output_path)
            merged = output_path.read_text(encoding="utf-8")
            self.assertEqual(
                next(item.source for item in extract_script_strings(merged) if item.id == "saveinfo:01"),
                "الفصل الأول",
            )
            self.assertIn("snr.table8_entry 'cg-scene', 0", merged)
            self.assertIn(r'"First\u0000Second\u0000"', merged)


if __name__ == "__main__":
    unittest.main()
