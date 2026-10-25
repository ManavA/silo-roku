#!/usr/bin/env python3
"""Generate the small UI bitmaps (gradients, 9-patch pills) under images/ui."""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "images" / "ui"
BG = (8, 10, 16)


def gradient(name, size, alpha_at):
    w, h = size
    img = Image.new("RGBA", size)
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = BG + (int(255 * alpha_at(x / (w - 1), y / (h - 1))),)
    img.save(OUT / name)


def nine_patch(name, radius, fill, outline=None, width=0):
    # Roku 9-patch: 1px border with black marks for the stretchable centre.
    size = radius * 2 + 4
    body = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(body)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius, fill=fill, outline=outline, width=width)
    img = Image.new("RGBA", (size + 2, size + 2), (0, 0, 0, 0))
    img.paste(body, (1, 1))
    m = ImageDraw.Draw(img)
    c = size // 2 + 1
    m.point([(c, 0), (0, c), (c, size + 1), (size + 1, c)], fill=(0, 0, 0, 255))
    img.save(OUT / (name + ".9.png"))


def transport_backdrop():
    # Small neutral scrim; feather outside the existing control layout.
    # Alpha blending needs no video capture, blur or additional decode surface.
    w, h = 304, 50
    image = Image.new("RGBA", (w, h))
    pixels = image.load()

    def feather(distance, extent):
        t = max(0.0, min(1.0, distance / extent))
        return t * t * (3 - 2 * t)

    for y in range(h):
        for x in range(w):
            edge = feather(min(x, w - 1 - x), 18) * feather(min(y, h - 1 - y), 8)
            pixels[x, y] = (3, 6, 10, round(196 * edge))
    image.save(OUT / "transport_backdrop.png")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    gradient("fade_left.png", (64, 4), lambda x, y: max(0.0, 1 - x) ** 1.4 * 0.95)
    gradient("fade_bottom.png", (4, 64), lambda x, y: min(1.0, y ** 1.6))
    gradient("fade_top.png", (4, 32), lambda x, y: (1 - y) * 0.7)
    nine_patch("pill", 18, (255, 255, 255, 38), (255, 255, 255, 70), 1)
    nine_patch("pill_focus", 18, (255, 255, 255, 240))
    nine_patch("chip", 6, (0, 0, 0, 170))
    nine_patch("card_focus", 10, (0, 0, 0, 0), (255, 255, 255, 255), 3)
    nine_patch("card_bg", 8, (28, 33, 44, 255))
    nine_patch("button", 22, (255, 255, 255, 235))
    nine_patch("button_dim", 22, (255, 255, 255, 40), (255, 255, 255, 90), 1)
    transport_backdrop()
    nine_patch("transport_button", 12, (24, 31, 41, 230), (255, 255, 255, 104), 1)
    nine_patch("transport_button_focus", 12, (245, 248, 252, 255), (255, 255, 255, 255), 1)


if __name__ == "__main__":
    main()
