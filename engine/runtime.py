"""Convert editable Arabic dialogue into game-compatible visual-order text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .fnt6 import DEFAULT_ARABIC_FONT, advance_width
from .shaping import ArabicFont


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
    """Read Unicode coverage from the selected TrueType font."""
    if not font_path.is_file():
        raise TranslationError(f"Arabic font not found: {font_path}")
    try:
        from fontTools.ttLib import TTFont
    except ImportError as error:
        raise TranslationError("Install Python requirements: pip install -r requirements.txt") from error
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


@dataclass
class WordRegistry:
    occupied: set[int]
    font_path: Path = DEFAULT_ARABIC_FONT
    tokens: list[tuple[int, str]] = field(default_factory=list)
    codepoints_by_token: dict[tuple[str, int], int] = field(default_factory=dict)
    offsets: dict[int, int] = field(default_factory=dict)
    story_line_height: int | None = None

    def __post_init__(self) -> None:
        self.supported = font_charset(self.font_path)
        self._pool = (
            cp for first, last in CODEPOINT_RANGES
            for cp in range(first, last + 1)
            if cp not in self.occupied
        )

    def register(self, token: str, offset_x: int = 0) -> str:
        if not token:
            raise TranslationError("Cannot encode an empty Arabic token")
        key = (token, offset_x)
        if key in self.codepoints_by_token:
            return chr(self.codepoints_by_token[key])
        missing = sorted({character for character in token if ord(character) not in self.supported})
        if missing:
            labels = ", ".join(f"{character!r} U+{ord(character):04X}" for character in missing)
            raise TranslationError(f"Arabic font lacks {labels} in {token!r}")
        try:
            codepoint = next(self._pool)
        except StopIteration as error:
            raise TranslationError("No unused Unicode codepoints remain for Arabic tokens") from error
        self.codepoints_by_token[key] = codepoint
        self.tokens.append((codepoint, token))
        if offset_x:
            self.offsets[codepoint] = offset_x
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
        line_height = int.from_bytes(self.original_story_font[24:26], "little") + int.from_bytes(
            self.original_story_font[26:28], "little"
        )
        size = round(96 * line_height / 80)
        self.registry.story_line_height = line_height
        self.font = ArabicFont(self.registry.font_path, size)
        self.space_width = advance_width(self.original_story_font, ord(" "))

    def _convert_content(self, content: str, line_id: str) -> str:
        """Place words right-to-left while retaining left-to-right pen advances.

        The game reveals characters in script order. Each Arabic word is one
        pre-shaped glyph, so script order follows Arabic reading order; a
        per-occurrence signed glyph bearing moves it to its visual position.
        Keeping ordinary positive advances preserves the native reveal timing.
        """
        # Each row contains (kind, value, scale, width) events. Commands stay at
        # their source position, including those between two words on one row.
        rows: list[list[tuple[str, str, float, float]]] = [[]]
        row_width = 0.0
        has_word = False
        pending_space = False
        scale = 1.0

        def trim_pending_space() -> None:
            nonlocal row_width, pending_space
            if pending_space:
                for index in range(len(rows[-1]) - 1, -1, -1):
                    if rows[-1][index][0] == "space":
                        row_width -= rows[-1][index][3]
                        del rows[-1][index]
                        break
            pending_space = False

        for tag, raw in control_stream(content, line_id):
            if tag in RUBY_TAGS:
                raise TranslationError(
                    f"ID {line_id}: flatten ruby tags @b/@</@> before exporting Arabic text"
                )
            if tag == "r":
                trim_pending_space()
                rows.append([])
                row_width = 0.0
                has_word = False
                continue
            if tag != "text":
                rows[-1].append(("tag", raw, scale, 0.0))
                if tag == "z":
                    scale = max(0.01, min(2.0, int(raw[2:-1]) / 100))
                continue
            if not ARABIC.search(raw) and any(
                not character.isspace() and ord(character) not in self.registry.supported
                for character in raw
            ):
                raise TranslationError(
                    f"ID {line_id}: untranslated text remains on an Arabic line; "
                    "translate the whole line before exporting"
                )
            for part in re.findall(r"\s+|\S+", raw):
                if part.isspace():
                    if has_word and not pending_space:
                        gap = self.space_width * scale
                        rows[-1].append(("space", " ", scale, gap))
                        row_width += gap
                        pending_space = True
                    continue
                # Font advances are stored in sixteenth-pixel units in FNT6.
                word_width = round(self.font.getlength(part) * 16) / 16 * scale
                if word_width > self.max_width:
                    raise TranslationError(
                        f"ID {line_id}: {part!r} is wider than one display row; split it"
                    )
                if has_word and row_width + word_width > self.max_width:
                    trim_pending_space()
                    rows.append([])
                    row_width = 0.0
                    has_word = False
                    self.inserted_breaks += 1
                rows[-1].append(("word", part, scale, word_width))
                row_width += word_width
                has_word = True
                pending_space = False

        trim_pending_space()
        output_rows = []
        for row in rows:
            # Mirror within the row's own advance width. The native renderer
            # can center or right-align that row; using max_width here would
            # move short rows outside its measured bounds.
            row_extent = sum(width for _, _, _, width in row)
            pen_x = 0.0
            rendered = []
            for kind, value, word_scale, width in row:
                if kind == "word":
                    desired_x = row_extent - pen_x - width
                    shift = round((desired_x - pen_x) / word_scale)
                    rendered.append(self.registry.register(value, shift))
                    pen_x += width
                elif kind == "space":
                    rendered.append(value)
                    pen_x += width
                else:
                    rendered.append(value)
            output_rows.append("".join(rendered))
        return "@r".join(output_rows)

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
        self.converted_lines += 1
        return speaker + "@r" + self._convert_content(content, line_id)

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
