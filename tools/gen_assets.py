#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate app/tray icons from the shared theme tokens (Pillow only).

Outputs:
  windows/src/ElementBlocks.Desktop/Assets/ElementBlocks.ico
  windows/src/ElementBlocks.Desktop/Assets/{Square44x44Logo,Square150x150Logo,StoreLogo,SplashScreen}.png
  linux/data/icons/hicolor/{16x16,32x32,48x48,64x64,128x128,256x256}/apps/*.png
  preview/data/icon.png
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
THEME = json.loads((ROOT / "shared" / "theme.json").read_text(encoding="utf-8"))
BG = THEME["tile"]["background"]
FG = THEME["tile"]["foreground"]
ACCENT = THEME["tile"]["accent"]
BORDER = THEME["tile"]["border"]

WIN = ROOT / "windows" / "src" / "ElementBlocks.Desktop" / "Assets"
LINUX = ROOT / "linux" / "data" / "icons" / "hicolor"
PREVIEW = ROOT / "preview" / "data"
for p in (WIN, PREVIEW):
    p.mkdir(parents=True, exist_ok=True)


def font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in (
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def draw_icon(size: int, supersample: int = 4) -> Image.Image:
    s = size * supersample
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pad = max(1, int(s * 0.045))
    d.rounded_rectangle([pad, pad, s - pad, s - pad], radius=int(s * 0.10),
                        fill=BG, outline=BORDER, width=max(1, int(s * 0.025)))
    # corner accent: small dark-red square, echoes the radioactive number in the tile
    q = int(s * 0.15)
    d.rectangle([pad + q // 2, pad + q // 2, pad + q // 2 + q // 2, pad + q // 2 + q // 2],
                fill=ACCENT)
    # big "E" (Element) in the middle
    f = font(int(s * 0.56))
    text = "E"
    box = d.textbbox((0, 0), text, font=f)
    tw, th = box[2] - box[0], box[3] - box[1]
    d.text(((s - tw) / 2 - box[0], (s - th) / 2 - box[1] - s * 0.01),
           text, font=f, fill=FG)
    if supersample > 1:
        im = im.resize((size, size), Image.LANCZOS)
    return im


# Windows: multi-resolution .ico for the tray + MSIX logos
sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
icons = [draw_icon(n) for n in sizes]
icons[-1].save(WIN / "ElementBlocks.ico", format="ICO",
               sizes=[(n, n) for n in sizes], append_images=icons[:-1])
print("wrote ElementBlocks.ico")

for name, size in (("Square44x44Logo.png", 44), ("Square150x150Logo.png", 150),
                   ("StoreLogo.png", 50), ("SplashScreen.png", 620)):
    if size == 620:
        im = Image.new("RGBA", (size, size), "#1E1E24")
        tile = draw_icon(180)
        im.alpha_composite(tile, ((size - 180) // 2, (size - 180) // 2))
    else:
        im = draw_icon(size)
    im.save(WIN / name)
    print("wrote", name)

# Linux: hicolor theme
for size in (16, 32, 48, 64, 128, 256):
    folder = LINUX / f"{size}x{size}" / "apps"
    folder.mkdir(parents=True, exist_ok=True)
    draw_icon(size).save(folder / "element-blocks-desktop.png")
print("wrote hicolor icons")

draw_icon(64).save(PREVIEW / "icon.png")
print("wrote preview/data/icon.png")
