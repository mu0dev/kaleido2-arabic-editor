"""Catalog and safely replace text literals outside the game's dialogue file.

The game-specific ``base/main.rb`` is a compiled script description. This
module changes only known string literal spans; it never evaluates Ruby or
rewrites instructions, asset paths, numeric arguments, or branching.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

from .runtime import TranslationError


@dataclass(frozen=True)
class ScriptString:
    id: str
    kind: str
    source: str
    line: int
    context: str
    editable: bool = True


@dataclass(frozen=True)
class _Literal:
    kind: str
    key: str
    source: str
    start: int
    end: int
    line: int
    options: tuple[str, ...] = ()


_SAVE = re.compile(r'^\s*s\.ins\s+SAVEINFO,\s*byte\([^)]*\),\s*(?P<value>"(?:\\.|[^"\\])*")')
_SELECT = re.compile(r'^\s*s\.ins\s+SELECT,.*?"NCSELECT",\s*(?P<value>"(?:\\.|[^"\\])*")')
_BGM = re.compile(r"^\s*snr\.bgm\s+'(?P<key>(?:\\.|[^'\\])*)'\s*,\s*")
_GALLERY = re.compile(r"^\s*snr\.table8_entry\s+(?P<value>'(?:\\.|[^'\\])*')")
_CONTROL = re.compile(r"[\x00-\x1f\x7f\u2028\u2029]")
_OPTION_SEPARATOR = r"\u0000"


def _decode_quoted(literal: str) -> str:
    """Decode only escapes used by these source fields, preserving all others."""
    if len(literal) < 2 or literal[0] not in ('"', "'") or literal[-1] != literal[0]:
        raise TranslationError("Unexpected Ruby string literal")
    quote = literal[0]
    body = literal[1:-1]
    output: list[str] = []
    i = 0
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body) and body[i + 1] in (quote, "\\", "#"):
            output.append(body[i + 1])
            i += 2
        else:
            output.append(body[i])
            i += 1
    return "".join(output)


def _read_literal(line: str, start: int) -> tuple[str, int]:
    """Read a Ruby %(...) or quoted literal and return its text and end."""
    if line.startswith("%(", start):
        depth = 1
        i = start + 2
        while i < len(line):
            char = line[i]
            if char == "\\":
                i += 2
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return line[start + 2 : i], i + 1
            i += 1
        raise TranslationError("Unterminated Ruby percent string in BGM title")
    if start < len(line) and line[start] in ('"', "'"):
        quote = line[start]
        i = start + 1
        while i < len(line):
            if line[i] == "\\":
                i += 2
            elif line[i] == quote:
                return _decode_quoted(line[start : i + 1]), i + 1
            else:
                i += 1
        raise TranslationError("Unterminated quoted BGM title")
    raise TranslationError("Unexpected BGM title expression")


def _scan(source: str) -> list[_Literal]:
    results: list[_Literal] = []
    counts = {"saveinfo": 0, "select": 0, "gallery_key": 0}
    offset = 0
    for line_number, line in enumerate(source.splitlines(keepends=True), 1):
        match = _SAVE.match(line)
        if match:
            counts["saveinfo"] += 1
            literal = match.group("value")
            results.append(
                _Literal(
                    "saveinfo", f"saveinfo:{counts['saveinfo']:02d}",
                    _decode_quoted(literal), offset + match.start("value"),
                    offset + match.end("value"), line_number,
                )
            )
        match = _SELECT.match(line)
        if match:
            counts["select"] += 1
            literal = match.group("value")
            raw = literal[1:-1]
            if not raw.endswith(_OPTION_SEPARATOR):
                raise TranslationError(f"SELECT at line {line_number} lacks a NUL terminator")
            options = tuple(
                _decode_quoted('"' + option + '"')
                for option in raw[: -len(_OPTION_SEPARATOR)].split(_OPTION_SEPARATOR)
            )
            results.append(
                _Literal(
                    "select", f"select:{counts['select']:02d}", "",
                    offset + match.start("value"), offset + match.end("value"),
                    line_number, options,
                )
            )
        match = _BGM.match(line)
        if match:
            key = match.group("key")
            title, end = _read_literal(line, match.end())
            results.append(
                _Literal(
                    "bgm", f"bgm:{key}", title,
                    offset + match.end(), offset + end, line_number,
                )
            )
        match = _GALLERY.match(line)
        if match:
            counts["gallery_key"] += 1
            literal = match.group("value")
            results.append(
                _Literal(
                    "gallery_key", f"gallery_key:{counts['gallery_key']:02d}",
                    _decode_quoted(literal), offset + match.start("value"),
                    offset + match.end("value"), line_number,
                )
            )
        offset += len(line)
    keys = [item.key for item in results]
    if len(keys) != len(set(keys)):
        raise TranslationError("Duplicate non-dialogue text ID in Ruby script")
    return results


def extract_script_strings(source: str) -> list[ScriptString]:
    """Return stable, game-specific IDs for text outside ``dialogue.txt``.

    Gallery strings are asset keys shared with CG artwork/texture names; they
    are included for review but are not safe to edit independently.
    """
    output: list[ScriptString] = []
    for item in _scan(source):
        if item.kind == "select":
            for number, option in enumerate(item.options, 1):
                output.append(
                    ScriptString(
                        f"{item.key}:option:{number:02d}", "select_option", option,
                        item.line, f"SELECT instruction {item.key.split(':')[1]}",
                    )
                )
        else:
            output.append(
                ScriptString(
                    item.key, item.kind, item.source, item.line,
                    "Internal gallery thumbnail key; edit visible gallery text in Images" if item.kind == "gallery_key"
                    else "BGM display title" if item.kind == "bgm"
                    else "Save/autosave chapter title",
                    item.kind != "gallery_key",
                )
            )
    return output


def _validate_translation(key: str, value: str) -> None:
    if not isinstance(value, str):
        raise TranslationError(f"{key}: translation must be text")
    if not value:
        raise TranslationError(f"{key}: translation cannot be empty")
    if _CONTROL.search(value):
        raise TranslationError(f"{key}: translation cannot contain tabs, line breaks, or controls")
    if _OPTION_SEPARATOR in value or "\\u0000" in value:
        raise TranslationError(f"{key}: translation cannot contain a SELECT separator")


def _ruby_double(value: str) -> str:
    # Escape interpolation as well as quote and backslash. The Ruby compiler
    # must receive exactly the supplied text, never executable interpolation.
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("#{", "\\#{")
    return '"' + escaped + '"'


def merge_script_strings(
    source: str,
    edits: Mapping[str, str],
    *,
    expected_sources: Mapping[str, str] | None = None,
) -> str:
    """Merge text edits into exact Ruby literal spans.

    ``expected_sources`` provides optimistic concurrency protection for an
    editor catalog made from an older ``base/main.rb``. Gallery keys are locked
    because they match texture/CG identifiers.
    """
    catalog = {entry.id: entry for entry in extract_script_strings(source)}
    unknown = sorted(set(edits) - set(catalog))
    if unknown:
        raise TranslationError(f"Unknown script string IDs: {', '.join(unknown[:8])}")
    if expected_sources is not None:
        for key in edits:
            if key not in expected_sources or expected_sources[key] != catalog[key].source:
                raise TranslationError(f"{key}: source changed since catalog extraction")
    for key, value in edits.items():
        _validate_translation(key, value)
        entry = catalog[key]
        if not entry.editable and value != entry.source:
            raise TranslationError(
                f"{key}: this is a CG asset key; changing it requires matching asset renames"
            )

    replacements: list[tuple[int, int, str]] = []
    for item in _scan(source):
        if item.kind == "select":
            options = [
                edits.get(f"{item.key}:option:{number:02d}", option)
                for number, option in enumerate(item.options, 1)
            ]
            if options != list(item.options):
                # Keep exactly the same option count and NUL delimiters.
                body = _OPTION_SEPARATOR.join(_ruby_double(option)[1:-1] for option in options)
                replacements.append((item.start, item.end, '"' + body + _OPTION_SEPARATOR + '"'))
        elif item.key in edits and edits[item.key] != item.source:
            replacements.append((item.start, item.end, _ruby_double(edits[item.key])))
    merged = source
    for start, end, value in sorted(replacements, reverse=True):
        merged = merged[:start] + value + merged[end:]
    # Reparse after edits to catch syntax/option-count damage before export.
    reread = {entry.id: entry for entry in extract_script_strings(merged)}
    if set(reread) != set(catalog):
        raise TranslationError("Ruby script text IDs changed during merge")
    for key, value in edits.items():
        if reread[key].source != value:
            raise TranslationError(f"{key}: merged Ruby literal did not retain exact text")
    return merged


def export_script_strings(
    original_script_path: Path | str,
    catalog_path: Path | str,
    output_script_path: Path | str,
) -> Path:
    """Export a merged ``main.rb`` from a JSON editor catalog.

    JSON is a list of objects with ``id``, ``source``, and ``translation``.
    Blank translations mean unchanged. The source check rejects stale edits.
    """
    source = Path(original_script_path).read_text(encoding="utf-8")
    rows = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise TranslationError("Script catalog must be a list")
    edits: dict[str, str] = {}
    expected: dict[str, str] = {}
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ("id", "source", "translation")):
            raise TranslationError(f"Script catalog item {index} needs id, source, translation text")
        key = row["id"]
        if key in expected:
            raise TranslationError(f"Duplicate script catalog ID {key}")
        expected[key] = row["source"]
        if row["translation"]:
            edits[key] = row["translation"]
    merged = merge_script_strings(source, edits, expected_sources=expected)
    output = Path(output_script_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(merged, encoding="utf-8")
    return output


def catalog_json(source: str) -> str:
    """Return the editor's initial JSON catalog with blank translations."""
    return json.dumps(
        [{**asdict(entry), "translation": ""} for entry in extract_script_strings(source)],
        ensure_ascii=False, indent=2,
    ) + "\n"
