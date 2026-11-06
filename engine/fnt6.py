"""Append pre-shaped Arabic token glyphs to the game's FNT6 fonts.

The existing glyph descriptors and bitmap payloads are preserved verbatim.
Each generated token maps to one otherwise-unused Unicode codepoint.
"""

from __future__ import annotations

import math
import os
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, features


DEFAULT_ARABIC_FONT = Path(
    os.environ.get("KALEIDO_ARABIC_FONT", "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf")
)
PAGE_BYTES = 514
DESC_BYTES = 24
HEADER_BYTES = 32
MAX_DISTANCE = 1_000_000_000.0


def u16(data: bytes, at: int) -> int:
    return struct.unpack_from("<H", data, at)[0]


def u32(data: bytes, at: int) -> int:
    return struct.unpack_from("<I", data, at)[0]


def round_up(value: int, multiple: int) -> int:
    return ((value + multiple - 1) // multiple) * multiple


def distance_transform_1d(values: list[float]) -> list[float]:
    """Exact squared Euclidean distance transform, Felzenszwalb-Huttenlocher."""
    finite = [i for i, value in enumerate(values) if value < MAX_DISTANCE]
    if not finite:
        return [MAX_DISTANCE] * len(values)
    envelope = [finite[0]]
    boundaries = [-float("inf")]
    for q in finite[1:]:
        while True:
            p = envelope[-1]
            crossing = ((values[q] + q * q) - (values[p] + p * p)) / (2 * (q - p))
            if crossing > boundaries[-1]:
                break
            envelope.pop()
            boundaries.pop()
        envelope.append(q)
        boundaries.append(crossing)
    result = []
    k = 0
    for q in range(len(values)):
        while k + 1 < len(envelope) and boundaries[k + 1] <= q:
            k += 1
        p = envelope[k]
        result.append((q - p) ** 2 + values[p])
    return result


def distance_to(mask: list[bool], width: int, height: int, site: bool) -> list[float]:
    temp = [0.0] * (width * height)
    for x in range(width):
        column = [0.0 if mask[y * width + x] == site else MAX_DISTANCE for y in range(height)]
        transformed = distance_transform_1d(column)
        for y, value in enumerate(transformed):
            temp[y * width + x] = value
    output = [0.0] * (width * height)
    for y in range(height):
        row = distance_transform_1d(temp[y * width : (y + 1) * width])
        output[y * width : (y + 1) * width] = row
    return output


def signed_distance(mask: Image.Image) -> list[float]:
    width, height = mask.size
    coverage = list(mask.getdata())
    inside = [value >= 128 for value in coverage]
    to_inside = distance_to(inside, width, height, True)
    to_outside = distance_to(inside, width, height, False)
    field = []
    for value, is_inside, dist_in, dist_out in zip(coverage, inside, to_inside, to_outside):
        if 0 < value < 255:
            field.append(value / 255.0 - 0.5)
        elif is_inside:
            field.append(math.sqrt(dist_out) - 0.5)
        else:
            field.append(0.5 - math.sqrt(dist_in))
    return field


def encode_snorm(value: float, spread: int) -> int:
    return round(max(-1.0, min(1.0, value / spread)) * 127) & 0xFF


def delta_encode(pixels: list[int], width: int) -> bytes:
    result = bytearray(len(pixels))
    result[0] = (pixels[0] + 127) & 0xFF
    for x in range(1, width):
        result[x] = (pixels[x] - pixels[x - 1]) & 0xFF
    for index in range(width, len(pixels)):
        result[index] = (pixels[index] - pixels[index - width]) & 0xFF
    return bytes(result)


def render_word(word: str, font: ImageFont.FreeTypeFont, spread: int, mip_count: int):
    bbox = font.getbbox(word, direction="rtl", anchor="ls")
    advance = font.getlength(word, direction="rtl")
    if round(advance * 16) > 0xFFFF:
        raise ValueError(f"Token is too wide for FNT6 advance field: {word!r}")
    margin = 10
    width = round_up(max(math.ceil(advance), bbox[2] - bbox[0]) + margin * 2, 1 << (mip_count - 1))
    height = round_up(bbox[3] - bbox[1] + margin * 2, 1 << (mip_count - 1))
    baseline = margin - bbox[1]
    image = Image.new("L", (width, height), 0)
    ImageDraw.Draw(image).text((margin - bbox[0], baseline), word, font=font, fill=255, direction="rtl", anchor="ls")
    field = signed_distance(image)
    mip_data = bytearray()
    current_width, current_height = width, height
    for level in range(mip_count):
        pixels = [encode_snorm(value, spread) for value in field]
        mip_data.extend(delta_encode(pixels, current_width))
        if level + 1 == mip_count:
            break
        next_width, next_height = current_width // 2, current_height // 2
        next_field = []
        for y in range(next_height):
            for x in range(next_width):
                at = y * 2 * current_width + x * 2
                next_field.append((field[at] + field[at + 1] + field[at + current_width] + field[at + current_width + 1]) / 4)
        field = next_field
        current_width, current_height = next_width, next_height
    return {
        "bbox": bbox,
        "bearing_x": -margin,
        "bearing_y": baseline,
        "width": width,
        "height": height,
        "advance_16": round(advance * 16),
        "payload": bytes(mip_data),
        "preview": image,
    }


def append_glyphs(reference: bytes, glyphs: list[tuple[int, dict]]) -> bytes:
    if reference[:4] != b"FNT6" or u32(reference, 4) != 1:
        raise ValueError("Expected an FNT6 version 1 reference font")
    if u32(reference, 8) != len(reference):
        raise ValueError("Reference font size field is incorrect")
    old_pages = u16(reference, 16)
    old_count = u16(reference, 18)
    old_desc = HEADER_BYTES + old_pages * PAGE_BYTES
    old_data = old_desc + old_count * DESC_BYTES
    if old_data > len(reference):
        raise ValueError("Truncated reference font tables")
    pages = {}
    for index in range(old_pages):
        at = HEADER_BYTES + index * PAGE_BYTES
        tag = u16(reference, at)
        if tag in pages:
            raise ValueError("Duplicate Unicode page")
        pages[tag] = list(struct.unpack_from("<256H", reference, at + 2))
    descriptors = [bytearray(reference[old_desc + i * DESC_BYTES : old_desc + (i + 1) * DESC_BYTES]) for i in range(old_count)]
    existing_ids = {u32(desc, 12) for desc in descriptors}
    next_identity = 0xA11B0000
    for index, (codepoint, glyph) in enumerate(glyphs):
        tag, low = codepoint >> 8, codepoint & 255
        page = pages.setdefault(tag, [0xFFFF] * 256)
        if page[low] < old_count:
            raise ValueError(f"U+{codepoint:04X} is already mapped")
        page[low] = old_count + index
        while next_identity in existing_ids:
            next_identity += 1
        existing_ids.add(next_identity)
        glyph["identity"] = next_identity
        next_identity += 1
    new_count = old_count + len(glyphs)
    if new_count >= 0xFFFF or len(pages) >= 0xFFFF:
        raise ValueError("FNT6 table capacity exceeded")
    new_data = HEADER_BYTES + len(pages) * PAGE_BYTES + new_count * DESC_BYTES
    shift = new_data - old_data
    for desc in descriptors:
        old_offset = u32(desc, 20)
        if old_offset < old_data or old_offset >= len(reference):
            raise ValueError("Reference glyph payload offset outside file")
        struct.pack_into("<I", desc, 20, old_offset + shift)
    output = bytearray(reference[:HEADER_BYTES])
    struct.pack_into("<H", output, 16, len(pages))
    struct.pack_into("<H", output, 18, new_count)
    for tag, page in sorted(pages.items()):
        output.extend(struct.pack("<H", tag))
        output.extend(struct.pack("<256H", *page))
    payload_offset = new_data + len(reference) - old_data
    for desc in descriptors:
        output.extend(desc)
    for _, glyph in glyphs:
        output.extend(struct.pack(
            "<hhHHHHIII",
            glyph["bearing_x"], glyph["bearing_y"], glyph["width"], glyph["height"],
            glyph["advance_16"], 0, glyph["identity"],
            (3 << 24), payload_offset,
        ))
        payload_offset += len(glyph["payload"])
    if len(output) != new_data:
        raise AssertionError("FNT6 table length error")
    output.extend(reference[old_data:])
    for _, glyph in glyphs:
        output.extend(glyph["payload"])
    struct.pack_into("<I", output, 8, len(output))
    return bytes(output)


def mapped_codepoints(data: bytes) -> set[int]:
    """Return codepoints already mapped in an original FNT6 font."""
    if data[:4] != b"FNT6" or u32(data, 4) != 1:
        raise ValueError("Expected an FNT6 version 1 font")
    pages = u16(data, 16)
    count = u16(data, 18)
    result: set[int] = set()
    for i in range(pages):
        at = HEADER_BYTES + i * PAGE_BYTES
        tag = u16(data, at)
        for low, glyph_id in enumerate(struct.unpack_from("<256H", data, at + 2)):
            if glyph_id < count:
                result.add((tag << 8) | low)
    return result


def advance_width(data: bytes, codepoint: int) -> float:
    pages = u16(data, 16)
    count = u16(data, 18)
    tag = codepoint >> 8
    for i in range(pages):
        at = HEADER_BYTES + i * PAGE_BYTES
        if u16(data, at) == tag:
            index = u16(data, at + 2 + (codepoint & 255) * 2)
            if index < count:
                desc = HEADER_BYTES + pages * PAGE_BYTES + index * DESC_BYTES
                return u16(data, desc + 8) / 16.0
            break
    raise ValueError(f"FNT6 has no glyph for U+{codepoint:04X}")


def build_font(
    reference: bytes,
    glyph_tokens: list[tuple[int, str]],
    arabic_font_path: Path = DEFAULT_ARABIC_FONT,
) -> bytes:
    """Build a patched font from explicit (codepoint, shaped-token) pairs."""
    if not features.check("raqm"):
        raise RuntimeError("Pillow must be built with libraqm for Arabic shaping")
    spread = u16(reference, 20)
    line_height = u16(reference, 24) + u16(reference, 26)
    if not 1 <= spread <= 128 or not 1 <= line_height <= 256:
        raise ValueError("Unexpected FNT6 font metrics")
    font_size = round(96 * line_height / 80)
    font = ImageFont.truetype(str(arabic_font_path), font_size, layout_engine=ImageFont.Layout.RAQM)
    glyphs = [(cp, render_word(token, font, spread, 4)) for cp, token in glyph_tokens]
    return append_glyphs(reference, glyphs)
