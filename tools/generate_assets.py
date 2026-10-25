#!/usr/bin/env python3
"""Regenerate Silo launch artwork and native focus bitmap; requires librsvg and Pillow."""

from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "images"
OUT.mkdir(exist_ok=True)
SVG = "http://www.w3.org/2000/svg"


def render(name: str, size: tuple[int, int], splash: bool) -> None:
    """Export supplied vector artwork without redrawing or cropping the mark."""
    renderer = shutil.which("rsvg-convert")
    if not renderer:
        raise RuntimeError("Install librsvg (rsvg-convert) to export official Silo artwork")
    width, height = size
    asset = "silo-wordmark-white.svg" if splash else "silo-app-icon.svg"
    logo = ET.fromstring((OUT / "brand" / asset).read_bytes())
    viewbox = [float(part) for part in logo.get("viewBox").split()]
    scale = min(width * 0.60 / viewbox[2], height * 0.36 / viewbox[3]) if splash else height / viewbox[3]
    logo_width, logo_height = viewbox[2] * scale, viewbox[3] * scale
    canvas = ET.Element(f"{{{SVG}}}svg", {"width":str(width), "height":str(height), "viewBox":f"0 0 {width} {height}"})
    # Extend the official square icon's background across Roku's wider tile.
    background = "#000000" if splash else logo.find(f"{{{SVG}}}rect").get("fill")
    ET.SubElement(canvas, f"{{{SVG}}}rect", {"width":str(width), "height":str(height), "fill":background})
    for key, value in {"x":(width-logo_width)/2, "y":(height-logo_height)/2, "width":logo_width, "height":logo_height}.items():
        logo.set(key, str(value))
    canvas.append(logo)
    subprocess.run([renderer, "--format", "png", "--output", str(OUT / name)],
                   input=ET.tostring(canvas), check=True)


for filename, dimensions, is_splash in (
    ("icon_hd.png", (290, 218), False),
    ("icon_fhd.png", (540, 405), False),
    ("splash_sd.png", (720, 480), True),
    ("splash_hd.png", (1280, 720), True),
    ("splash_fhd.png", (1920, 1080), True),
):
    render(filename, dimensions, is_splash)

# Native Button and ButtonGroup use a bitmap, rather than a blend-color field.
# Black outer-edge markers define stretch/content regions; they are not drawn.
focus = Image.new("RGBA", (34, 34), (0, 0, 0, 0))
draw = ImageDraw.Draw(focus)
draw.rounded_rectangle((1, 1, 32, 32), radius=7, fill="#7cd4ff")
draw.line((12, 0, 21, 0), fill="black")
draw.line((0, 12, 0, 21), fill="black")
draw.line((7, 33, 26, 33), fill="black")
draw.line((33, 7, 33, 26), fill="black")
focus.save(OUT / "button_focus.9.png", optimize=True)
