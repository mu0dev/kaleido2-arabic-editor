"""Convert editable Arabic dialogue into game-compatible visual-order text."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import ImageFont, features

from .fnt6 import DEFAULT_ARABIC_FONT, advance_width


ARABIC = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]")
LINE = re.compile(r"^(\d+)\t(.*)$")

# These are the commands understood by Kaleido's WordWrapLayouter. A command
# is kept byte-for-byte (as Unicode text) at its original point in the line;
# only the ordinary text between commands is converted to Arabic word glyphs.
SIMPLE_TAGS = frozenset("rk>[]{}|yet-b<")
PARAMETER_TAGS = frozenset("vwoazcsxu")
RUBY_TAGS = frozenset("b<>")
NUMERIC_TAGS = frozenset("azsxu")
PARAMETER = re.compile(r"[A-Za-z0-9_+|\-]+")


def control_stream(text: str, line_id: str) -> list[tuple[str, str]]:
    """Split text into ordinary runs and validated, unmodified commands."""
    parts: list[tuple[str, str]] = []
    offset = 0
    while offset < len(text):
        if text[offset] != "@":
            next_tag = text.find("@", offset)
            end = len(text) if next_tag < 0 else next_tag
            parts.append(("text", text[offset:end]))
            offset = end
            continue
        if offset + 1 >= len(text):
            raise TranslationError(f"ID {line_id}: incomplete control tag at end of line")
        tag = text[offset + 1]
        if tag in SIMPLE_TAGS:
            parts.append((tag, text[offset : offset + 2]))
            offset += 2
            continue
        if tag not in PARAMETER_TAGS:
            raise TranslationError(f"ID {line_id}: unknown control tag @{tag}")
        end = text.find(".", offset + 2)
        if end < 0 or "@" in text[offset + 2 : end]:
            raise TranslationError(f"ID {line_id}: @{tag} needs a parameter followed by '.'")
        parameter = text[offset + 2 : end]
        if not PARAMETER.fullmatch(parameter) or (tag in NUMERIC_TAGS and not parameter.isascii()):
            raise TranslationError(f"ID {line_id}: malformed @{tag} parameter {parameter!r}")
        if tag in NUMERIC_TAGS and not parameter.isdecimal():
            raise TranslationError(f"ID {line_id}: @{tag} needs a decimal parameter, got {parameter!r}")
        parts.append((tag, text[offset : end + 1]))
        offset = end + 1
    return parts


def invariant_controls(text: str, line_id: str) -> list[str]:
    """Return commands a translation must retain; line breaks and ruby can change."""
    return [raw for tag, raw in control_stream(text, line_id) if tag not in {"text", "r", *RUBY_TAGS}]

# BMP PUA is first. Later ranges are unused by the supplied game fonts and
# remain single Unicode scalar values. Scan both original fonts before use.
CODEPOINT_RANGES = (
    (0xE000, 0xF8FF),
    (0xAC00, 0xD7A3),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
)


class TranslationError(ValueError):
    """Source text needs a translator edit before it can be exported."""


def font_charset(font_path: Path) -> set[int]:
    """Read Unicode coverage from a TrueType font on Linux or Windows."""
    if not font_path.is_file():
        raise TranslationError(f"Arabic font not found: {font_path}")
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        # Existing Linux installations may have fontconfig rather than the
        # optional Python dependency. Windows users should install the pinned
        # requirements; fc-query is not normally present there.
        if os.name == "nt":
            raise TranslationError("Install Python requirements: pip install -r requirements.txt")
    else:
        try:
            font = TTFont(str(font_path), lazy=True)
            try:
                mapping = font.getBestCmap()
            finally:
                font.close()
        except Exception as error:
            raise TranslationError(f"Cannot inspect Arabic font {font_path}: {error}") from error
        if not mapping:
            raise TranslationError(f"Arabic font has no Unicode character map: {font_path}")
        return set(mapping)
    try:
        specification = subprocess.check_output(
            ["fc-query", "--format", "%{charset}", str(font_path)], text=True
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise TranslationError(f"Cannot inspect Arabic font {font_path}: {error}") from error
    supported: set[int] = set()
    for part in specification.split():
        if "-" in part:
            start, stop = part.split("-", 1)
            supported.update(range(int(start, 16), int(stop, 16) + 1))
        else:
            supported.add(int(part, 16))
    return supported


@dataclass
class WordRegistry:
    occupied: set[int]
    font_path: Path = DEFAULT_ARABIC_FONT
    tokens: list[tuple[int, str]] = field(default_factory=list)
    codepoints_by_token: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.supported = font_charset(self.font_path)
        self._pool = (
            cp for first, last in CODEPOINT_RANGES
            for cp in range(first, last + 1)
            if cp not in self.occupied
        )

    def register(self, token: str) -> str:
        if not token:
            raise TranslationError("Cannot encode an empty Arabic token")
        if token in self.codepoints_by_token:
            return chr(self.codepoints_by_token[token])
        missing = sorted({character for character in token if ord(character) not in self.supported})
        if missing:
            labels = ", ".join(f"{character!r} U+{ord(character):04X}" for character in missing)
            raise TranslationError(f"Arabic font lacks {labels} in {token!r}")
        try:
            codepoint = next(self._pool)
        except StopIteration as error:
            raise TranslationError("No unused Unicode codepoints remain for Arabic tokens") from error
        self.codepoints_by_token[token] = codepoint
        self.tokens.append((codepoint, token))
        return chr(codepoint)


@dataclass
class RuntimeConverter:
    registry: WordRegistry
    original_story_font: bytes
    max_width: float = 3000.0
    converted_lines: int = 0
    inserted_breaks: int = 0
    translated_speakers: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not features.check("raqm"):
            raise TranslationError("Pillow needs libraqm for Arabic shaping")
        line_height = int.from_bytes(self.original_story_font[24:26], "little") + int.from_bytes(
            self.original_story_font[26:28], "little"
        )
        size = round(96 * line_height / 80)
        self.font = ImageFont.truetype(str(self.registry.font_path), size, layout_engine=ImageFont.Layout.RAQM)
        self.space_width = advance_width(self.original_story_font, ord(" "))

    def _convert_text_run(self, text: str, line_id: str, scale: float) -> str:
        if not ARABIC.search(text):
            return text
        tokens = text.split()
        if not tokens:
            return text
        rows: list[list[str]] = []
        current: list[str] = []
        width = 0.0
        limit = self.max_width / scale
        for token in tokens:
            # Even punctuation-only tokens are baked so their display order is
            # controlled by the same registry as Arabic words.
            token_width = self.font.getlength(token, direction="rtl")
            if token_width > limit:
                raise TranslationError(
                    f"ID {line_id}: {token!r} is wider than one display row; split it"
                )
            if current and width + self.space_width + token_width > limit:
                rows.append(current)
                current = []
                width = 0.0
            width += (self.space_width if current else 0.0) + token_width
            current.append(token)
        rows.append(current)
        self.inserted_breaks += len(rows) - 1
        return "@r".join(
            " ".join(self.registry.register(token) for token in reversed(row))
            for row in rows
        )

    def convert_line(self, line_id: str, value: str) -> str:
        if not ARABIC.search(value):
            return value
        speaker, marker, content = value.partition("@r")
        if not marker:
            raise TranslationError(f"ID {line_id}: expected speaker@r or @r dialogue prefix")
        if "@" in speaker:
            raise TranslationError(f"ID {line_id}: unsupported control tag in speaker name")
        if ARABIC.search(speaker):
            self.translated_speakers.add(speaker)
            speaker = self.registry.register(speaker)
        # A global speaker-name translation also touches untranslated Japanese
        # lines. Keep their original ruby annotations and timing untouched.
        if not ARABIC.search(content):
            self.converted_lines += 1
            return speaker + "@r" + content
        scale = 1.0
        output_parts: list[str] = []
        for tag, raw in control_stream(content, line_id):
            if tag in RUBY_TAGS:
                raise TranslationError(
                    f"ID {line_id}: flatten ruby tags @b/@</@> before exporting Arabic text"
                )
            if tag == "z":
                scale = max(0.01, min(2.0, int(raw[2:-1]) / 100))
            output_parts.append(self._convert_text_run(raw, line_id, scale) if tag == "text" else raw)
        self.converted_lines += 1
        return speaker + "@r" + "".join(output_parts)

    def convert_ui_text(self, text: str) -> str:
        """Encode a UI string for a caller that can patch its game location."""
        if not ARABIC.search(text):
            return text
        # UI labels tend to be short. No automatic row breaks are inserted
        # because each UI element has its own unknown geometry.
        words = text.split()
        return " ".join(self.registry.register(word) for word in reversed(words))


def parse_edits(text: str) -> dict[str, str]:
    edits: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = LINE.match(line)
        if not match:
            raise TranslationError(f"Edited dialogue line {number} needs ID<TAB>text")
        line_id, value = match.groups()
        if line_id in edits:
            raise TranslationError(f"Duplicate dialogue ID {line_id}")
        edits[line_id] = value
    return edits


def merge_dialogue(original: str, edited: str) -> tuple[str, list[str]]:
    edits = parse_edits(edited)
    known: set[str] = set()
    lines = []
    for line in original.splitlines(keepends=True):
        match = LINE.match(line.rstrip("\r\n"))
        if not match:
            lines.append(line)
            continue
        line_id, original_value = match.groups()
        known.add(line_id)
        if line_id in edits:
            before = invariant_controls(original_value, line_id)
            after = invariant_controls(edits[line_id], line_id)
            if before != after:
                raise TranslationError(
                    f"ID {line_id}: preserve control tags in order; expected {before!r}, got {after!r}"
                )
            suffix = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            lines.append(line_id + "\t" + edits[line_id] + suffix)
        else:
            lines.append(line)
    unknown = sorted(set(edits) - known)
    if unknown:
        raise TranslationError(f"Edited IDs are absent from original script: {', '.join(unknown[:8])}")
    return "".join(lines), sorted(edits)


def convert_dialogue(merged: str, converter: RuntimeConverter) -> str:
    lines = []
    for line in merged.splitlines(keepends=True):
        match = LINE.match(line.rstrip("\r\n"))
        if not match:
            lines.append(line)
            continue
        line_id, value = match.groups()
        suffix = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        lines.append(line_id + "\t" + converter.convert_line(line_id, value) + suffix)
    return "".join(lines)
