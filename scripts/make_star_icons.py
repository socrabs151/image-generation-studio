"""Build the favourite star icons from a generated source image.

The app ships small pre-coloured PNGs instead of a text glyph: the star
characters U+2605/U+2606 are not in Segoe UI, so they came out of a fallback
font whose size, weight and availability the app does not control.

The source is a white star on a transparent background, generated with the app
itself. Only its alpha channel is used, so the source may be any shade: the
icon colours come from the palettes below, one pair per theme.

The filled variant is not generated separately. It is the outline's own
silhouette with the hollow middle filled in, which keeps both states of the
toggle the same size and shape. A separately generated filled star came out
slightly larger and, in one take, clipped by the canvas edge, which makes the
button jump between states.

Usage:

    python scripts/make_star_icons.py resources/icons/src/star-outline.png

Requires Pillow, which is already a dependency of the test tooling.
"""

from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "resources" / "icons" / "star"
# Large enough to stay crisp on a 200% display when Qt scales it down.
ICON_SIZE = 48
# The work is done small: at 48 px the wobble of a generated edge is invisible,
# and speckles disappear in the downscale.
WORK_SIZE = 256
# A speckle is much smaller than the star; anything under this share of the
# largest blob is noise from the generator, not part of the icon.
SPECKLE_SHARE = 0.02
# Width of the outline in the working resolution, before the downscale. The
# erosion filter takes an odd size, so the stroke is 12 px there and about
# 1.5 px once Qt shows the icon at 16 px.
STROKE = 25

# Icon colour per theme: (unchecked, checked). Matches the button rules in
# resources/themes/*.qss, which no longer colour the glyph but still draw the
# checked border.
PALETTES = {
    "dark": ((0x9A, 0x9A, 0xB0), (0xF5, 0xC4, 0x51)),
    "light": ((0x8A, 0x93, 0xA3), (0xC9, 0x8A, 0x06)),
}


def _mask_from_alpha(image: Image.Image) -> Image.Image:
    """A hard black-and-white mask of the opaque part of the picture."""
    alpha = image.getchannel("A").resize((WORK_SIZE, WORK_SIZE), Image.LANCZOS)
    return alpha.point(lambda value: 255 if value > 100 else 0, mode="L")


def _drop_speckles(mask: Image.Image) -> Image.Image:
    """Remove blobs far smaller than the main shape."""
    pixels = mask.load()
    seen = bytearray(WORK_SIZE * WORK_SIZE)
    blobs: list[list[int]] = []
    for start in range(WORK_SIZE * WORK_SIZE):
        if seen[start] or pixels[start % WORK_SIZE, start // WORK_SIZE] == 0:
            continue
        queue = deque([start])
        seen[start] = 1
        blob: list[int] = []
        while queue:
            index = queue.popleft()
            blob.append(index)
            x, y = index % WORK_SIZE, index // WORK_SIZE
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if not 0 <= nx < WORK_SIZE or not 0 <= ny < WORK_SIZE:
                    continue
                neighbour = ny * WORK_SIZE + nx
                if seen[neighbour] or pixels[nx, ny] == 0:
                    continue
                seen[neighbour] = 1
                queue.append(neighbour)
        blobs.append(blob)
    if not blobs:
        return mask
    biggest = max(len(blob) for blob in blobs)
    keep = [0] * (WORK_SIZE * WORK_SIZE)
    for blob in blobs:
        if len(blob) < biggest * SPECKLE_SHARE:
            continue
        for index in blob:
            keep[index] = 255
    cleaned = Image.new("L", (WORK_SIZE, WORK_SIZE), 0)
    cleaned.putdata(keep)
    return cleaned


def _fill_inside(mask: Image.Image) -> Image.Image:
    """Fill everything the shape encloses, so a ring becomes a solid star."""
    pixels = mask.load()
    filled = bytearray(pixels[x, y] for y in range(WORK_SIZE) for x in range(WORK_SIZE))
    outside = bytearray(WORK_SIZE * WORK_SIZE)
    queue: deque[tuple[int, int]] = deque()

    def is_empty(x: int, y: int) -> bool:
        return 0 <= x < WORK_SIZE and 0 <= y < WORK_SIZE and filled[y * WORK_SIZE + x] == 0

    for x in range(WORK_SIZE):
        for y in (0, WORK_SIZE - 1):
            index = y * WORK_SIZE + x
            if is_empty(x, y) and not outside[index]:
                outside[index] = 1
                queue.append((x, y))
    for y in range(WORK_SIZE):
        for x in (0, WORK_SIZE - 1):
            index = y * WORK_SIZE + x
            if is_empty(x, y) and not outside[index]:
                outside[index] = 1
                queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if not is_empty(nx, ny):
                continue
            index = ny * WORK_SIZE + nx
            if outside[index]:
                continue
            outside[index] = 1
            queue.append((nx, ny))
    result = bytearray(
        0 if outside[index] else 255 for index in range(WORK_SIZE * WORK_SIZE)
    )
    return Image.frombytes("L", (WORK_SIZE, WORK_SIZE), bytes(result))


def _erode(mask: Image.Image, size: int) -> Image.Image:
    """Pull the shape inwards by about half of ``size``."""
    return mask.filter(ImageFilter.MinFilter(size))


def _ring(solid: Image.Image, stroke: int) -> Image.Image:
    """An even outline of a solid shape: the shape minus a shrunken copy.

    The generated outline has a stroke that wanders between thin and thick, and
    at 16 px it fades away. Deriving the ring from the solid silhouette instead
    gives an even stroke and puts both states in exactly the same place.
    """
    inner = _erode(solid, stroke)
    ring = Image.new("L", solid.size, 0)
    solid_px = solid.load()
    inner_px = inner.load()
    ring_px = ring.load()
    for y in range(solid.height):
        for x in range(solid.width):
            ring_px[x, y] = 0 if inner_px[x, y] else solid_px[x, y]
    return ring


def _center_on_square(mask: Image.Image) -> Image.Image:
    """Trim to the shape and put it on a square with an even margin."""
    box = mask.getbbox()
    if box is None:
        raise SystemExit("The source image has no visible pixels.")
    shape = mask.crop(box)
    side = max(shape.size) + max(shape.size) // 8
    canvas = Image.new("L", (side, side), 0)
    canvas.paste(shape, ((side - shape.width) // 2, (side - shape.height) // 2))
    return canvas


def _write_icon(mask: Image.Image, path: Path, colour: tuple[int, int, int]) -> None:
    """Save the mask as a coloured icon with a soft edge."""
    alpha = mask.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
    image = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), colour + (0,))
    image.putalpha(alpha)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def build(source: Path) -> list[Path]:
    """Write the whole icon set and return the files it created."""
    image = Image.open(source).convert("RGBA")
    cleaned = _drop_speckles(_mask_from_alpha(image))
    solid = _center_on_square(_fill_inside(cleaned))
    outline = _ring(solid, STROKE)
    written: list[Path] = []
    for theme, (unchecked, checked) in PALETTES.items():
        for state, mask, colour in (
            ("outline", outline, unchecked),
            ("filled", solid, checked),
        ):
            path = OUTPUT_DIR / f"star-{state}-{theme}.png"
            _write_icon(mask, path, colour)
            written.append(path)
    return written


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    for path in build(Path(argv[0])):
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
