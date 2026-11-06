"""Render Arabic tokens with Pillow on systems with or without libraqm."""

from __future__ import annotations

from pathlib import Path

from PIL import ImageDraw, ImageFont, features


class ArabicFont:
    def __init__(self, path: Path, size: int) -> None:
        self.raqm = features.check("raqm")
        engine = ImageFont.Layout.RAQM if self.raqm else ImageFont.Layout.BASIC
        self.font = ImageFont.truetype(str(path), size, layout_engine=engine)
        if not self.raqm:
            from arabic_reshaper import ArabicReshaper
            from bidi.algorithm import get_display

            self.reshaper = ArabicReshaper(configuration={"delete_harakat": False})
            self.get_display = get_display

    def _layout(self, text: str) -> tuple[str, dict[str, str]]:
        if self.raqm:
            return text, {"direction": "rtl"}
        return self.get_display(self.reshaper.reshape(text), base_dir="R"), {}

    def getbbox(self, text: str) -> tuple[int, int, int, int]:
        display, options = self._layout(text)
        return self.font.getbbox(display, anchor="ls", **options)

    def getlength(self, text: str) -> float:
        display, options = self._layout(text)
        return self.font.getlength(display, **options)

    def draw(self, image: ImageDraw.ImageDraw, position: tuple[int, int], text: str) -> None:
        display, options = self._layout(text)
        image.text(position, display, font=self.font, fill=255, anchor="ls", **options)
