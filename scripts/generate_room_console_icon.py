#!/usr/bin/env python3
"""Generate a Mac app icon for the room console."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageFilter


SIZES = [16, 32, 64, 128, 256, 512, 1024]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a room-console icon set and icns bundle.")
    parser.add_argument("--png", required=True, help="Path for the main 1024px PNG output.")
    parser.add_argument("--icns", required=True, help="Path for the generated icns file.")
    parser.add_argument("--iconset-dir", help="Optional explicit iconset directory.")
    return parser.parse_args()


def rounded_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, fill: tuple[int, int, int, int]) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def build_icon(size: int) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    pad = int(size * 0.07)
    radius = int(size * 0.22)
    rounded_panel(sdraw, (pad, pad + int(size * 0.02), size - pad, size - pad), radius, (0, 0, 0, 180))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(4, size // 48)))
    canvas.alpha_composite(shadow)

    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pixels = bg.load()
    for y in range(size):
        for x in range(size):
            tx = x / max(1, size - 1)
            ty = y / max(1, size - 1)
            top = (107, 196, 255)
            mid = (79, 112, 232)
            low = (22, 27, 47)
            mix = 0.58 * tx + 0.42 * ty
            if mix < 0.56:
                ratio = mix / 0.56
                color = tuple(int(top[i] * (1.0 - ratio) + mid[i] * ratio) for i in range(3))
            else:
                ratio = (mix - 0.56) / 0.44
                color = tuple(int(mid[i] * (1.0 - ratio) + low[i] * ratio) for i in range(3))
            pixels[x, y] = (*color, 255)
    mask = Image.new("L", (size, size), 0)
    mdraw = ImageDraw.Draw(mask)
    rounded_panel(mdraw, (pad, pad, size - pad, size - pad), radius, 255)
    bg.putalpha(mask)
    canvas.alpha_composite(bg)

    draw = ImageDraw.Draw(canvas)
    bubble = (
        int(size * 0.16),
        int(size * 0.2),
        int(size * 0.84),
        int(size * 0.72),
    )
    rounded_panel(draw, bubble, int(size * 0.13), (239, 247, 255, 235))
    tail = [
        (int(size * 0.34), int(size * 0.68)),
        (int(size * 0.26), int(size * 0.84)),
        (int(size * 0.44), int(size * 0.73)),
    ]
    draw.polygon(tail, fill=(239, 247, 255, 235))

    head_box = (
        int(size * 0.33),
        int(size * 0.31),
        int(size * 0.67),
        int(size * 0.65),
    )
    draw.ellipse(head_box, fill=(255, 226, 238, 255))

    hair = [
        (int(size * 0.3), int(size * 0.43)),
        (int(size * 0.38), int(size * 0.24)),
        (int(size * 0.53), int(size * 0.22)),
        (int(size * 0.69), int(size * 0.35)),
        (int(size * 0.66), int(size * 0.52)),
        (int(size * 0.58), int(size * 0.36)),
        (int(size * 0.42), int(size * 0.36)),
    ]
    draw.polygon(hair, fill=(57, 74, 158, 255))
    draw.rounded_rectangle(
        (int(size * 0.3), int(size * 0.35), int(size * 0.7), int(size * 0.49)),
        radius=int(size * 0.09),
        fill=(74, 97, 204, 255),
    )

    eye_y = int(size * 0.47)
    eye_w = max(3, size // 26)
    draw.ellipse((int(size * 0.43) - eye_w, eye_y - eye_w, int(size * 0.43) + eye_w, eye_y + eye_w), fill=(49, 43, 78, 255))
    draw.ellipse((int(size * 0.57) - eye_w, eye_y - eye_w, int(size * 0.57) + eye_w, eye_y + eye_w), fill=(49, 43, 78, 255))
    draw.arc(
        (int(size * 0.44), int(size * 0.5), int(size * 0.56), int(size * 0.6)),
        start=20,
        end=160,
        fill=(255, 120, 156, 255),
        width=max(2, size // 64),
    )

    draw.rounded_rectangle(
        (int(size * 0.22), int(size * 0.18), int(size * 0.31), int(size * 0.54)),
        radius=int(size * 0.04),
        fill=(93, 181, 255, 255),
    )
    draw.rounded_rectangle(
        (int(size * 0.69), int(size * 0.18), int(size * 0.78), int(size * 0.54)),
        radius=int(size * 0.04),
        fill=(93, 181, 255, 255),
    )
    draw.arc(
        (int(size * 0.22), int(size * 0.15), int(size * 0.78), int(size * 0.54)),
        start=185,
        end=355,
        fill=(93, 181, 255, 255),
        width=max(5, size // 42),
    )

    badge = (
        int(size * 0.66),
        int(size * 0.66),
        int(size * 0.84),
        int(size * 0.84),
    )
    draw.ellipse(badge, fill=(255, 143, 174, 255))
    draw.rounded_rectangle(
        (int(size * 0.705), int(size * 0.732), int(size * 0.795), int(size * 0.756)),
        radius=max(2, size // 64),
        fill=(255, 255, 255, 255),
    )
    draw.rounded_rectangle(
        (int(size * 0.705), int(size * 0.772), int(size * 0.765), int(size * 0.796)),
        radius=max(2, size // 64),
        fill=(255, 255, 255, 255),
    )
    return canvas


def write_iconset(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for size in SIZES[:-1]:
        image = build_icon(size)
        if size in {16, 32, 128, 256, 512}:
            image.save(root / f"icon_{size}x{size}.png")
            build_icon(size * 2).save(root / f"icon_{size}x{size}@2x.png")
    build_icon(1024).save(root / "icon_512x512@2x.png")


def main() -> int:
    args = parse_args()
    png_path = Path(args.png).expanduser().resolve()
    icns_path = Path(args.icns).expanduser().resolve()
    iconset_dir = Path(args.iconset_dir).expanduser().resolve() if args.iconset_dir else icns_path.with_suffix(".iconset")
    iconset_dir.parent.mkdir(parents=True, exist_ok=True)
    png_path.parent.mkdir(parents=True, exist_ok=True)

    build_icon(1024).save(png_path)
    write_iconset(iconset_dir)
    subprocess.run(["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
