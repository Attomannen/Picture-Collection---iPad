#!/usr/bin/env python3
"""
pack_channels.py - pack four greyscale images into the R, G, B and A channels of ONE png.

It runs on your computer (not inside Unreal) and needs Python 3 and Pillow:   pip install pillow

Each channel is either an image file or a plain number 0..1 (a constant). Greyscale or colour, 8 or 16 bit,
png / jpg / tga / tif - everything Pillow can open. Images of different sizes are scaled to the biggest one
(or to --size).

Recipes for M_Master_Surface
----------------------------
ORMH map of a tiling material      R = ambient occlusion   G = roughness   B = metallic   A = height

    python pack_channels.py --r Brick_AO.png --g Brick_Roughness.png --b 0 --a Brick_Height.png -o T_Brick_ORMH.png

    (--b 0 means "not metal everywhere". A texture set that ships GLOSSINESS instead of roughness: add --invert-g.
     No AO map: --r 1.  No height map: --a 0.5.)

RGBA mask for the UNIQUE UV set     R = wear   G = dirt   B = scratches   A = baked AO

    python pack_channels.py --r Wear.png --g Dirt.png --b Scratches.png --a AO.png -o T_Crate_Mask.png

    (Substance Painter can export this packed straight away with an output template - see Docs/02.)

Import the result in Unreal with compression "Masks (no sRGB)"  (Scripts/fix_texture_settings.py does that for you
when the file name ends in _ORMH or _Mask).
"""
import argparse
import os
import sys

try:
    from PIL import Image
except ImportError:                                           # pragma: no cover
    Image = None

CHANNELS = ("r", "g", "b", "a")


def _resample():
    return getattr(getattr(Image, "Resampling", Image), "LANCZOS")


def load_grey(path):
    """Any image -> 8-bit greyscale ('L'). 16-bit data is scaled down, not clipped."""
    im = Image.open(path)
    im.load()
    if im.mode in ("I;16", "I;16L", "I;16B", "I"):
        im = im.point(lambda v: v * (1.0 / 256.0))
        if im.mode != "L":
            im = im.convert("L")
        return im
    if im.mode in ("LA", "PA"):
        im = im.convert("RGBA")
    return im.convert("L")


def parse_source(text):
    """'0.5' -> a constant, anything else -> a file path."""
    try:
        value = float(text)
    except ValueError:
        if not os.path.isfile(text):
            raise argparse.ArgumentTypeError("file not found: %s" % text)
        return text
    if not 0.0 <= value <= 1.0:
        raise argparse.ArgumentTypeError("a constant must be between 0 and 1 (got %s)" % text)
    return value


def pack(sources, invert=(), size=None):
    """sources: dict channel -> path | float. Returns an RGBA Pillow image."""
    if Image is None:
        raise RuntimeError("Pillow is needed:  pip install pillow")
    missing = [c.upper() for c in CHANNELS if c not in sources]
    if missing:
        raise ValueError("channel(s) %s not given - use a file, or a number such as 1 or 0.5" % ", ".join(missing))
    loaded = {c: load_grey(s) for c, s in sources.items() if not isinstance(s, (int, float))}
    if size is None:
        size = (max(im.width for im in loaded.values()), max(im.height for im in loaded.values())) if loaded else (4, 4)
    elif isinstance(size, int):
        size = (size, size)
    bands = []
    for c in CHANNELS:
        src = sources[c]
        if isinstance(src, (int, float)):
            band = Image.new("L", size, int(round(float(src) * 255)))
        else:
            band = loaded[c]
            if band.size != size:
                band = band.resize(size, _resample())
        if c in invert:
            band = band.point(lambda v: 255 - v)
        bands.append(band)
    return Image.merge("RGBA", bands)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for c in CHANNELS:
        ap.add_argument("--" + c, type=parse_source, metavar="FILE|0..1", help="image or constant for the %s channel" % c.upper())
        ap.add_argument("--invert-" + c, action="store_true", help="invert the %s channel (e.g. glossiness -> roughness)" % c.upper())
    ap.add_argument("--size", type=int, help="scale everything to SIZE x SIZE (default: the biggest input)")
    ap.add_argument("-o", "--out", required=True, help="output png")
    args = ap.parse_args(argv)
    sources = {c: getattr(args, c) for c in CHANNELS if getattr(args, c) is not None}
    invert = tuple(c for c in CHANNELS if getattr(args, "invert_" + c))
    try:
        im = pack(sources, invert, args.size)
    except (ValueError, RuntimeError, OSError) as exc:
        ap.error(str(exc))
    im.save(args.out)
    print("wrote %s  (%dx%d)  R=%s G=%s B=%s A=%s" % ((args.out,) + im.size + tuple(
        (os.path.basename(sources[c]) if isinstance(sources[c], str) else "%g" % sources[c]) + (" (inverted)" if c in invert else "")
        for c in CHANNELS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
