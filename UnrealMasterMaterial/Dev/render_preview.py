#!/usr/bin/env python3
"""
render_preview.py - an APPROXIMATE picture of what the demo instances look like.

It builds the master in the offline mock, then evaluates the material graph (graph_eval.py) for every pixel of a
flat card: textures are sampled bilinearly from the real demo PNG data, vertex colour comes from a painted test
pattern, and a very small shading model (diffuse + a Blinn highlight, one light) turns base colour / normal /
roughness / metallic / AO into a picture.

This is NOT an Unreal render: no real lighting, reflections, mip-mapping or post-processing. Its purpose is to
catch ugly numbers (black rust, three crates that look alike ...) before you open the editor, and to give the
documentation something to show.

    python3 Dev/render_preview.py                 # writes Docs/img/*.png (needs Pillow, takes ~1 minute)
    python3 Dev/render_preview.py --size 96 --out /tmp/previews
"""
import argparse
import importlib.util
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
os.environ["MM_NO_AUTORUN"] = "1"

import graph_eval as ge          # noqa: E402
import mock_unreal as mu         # noqa: E402

STATE = {}


def build():
    mu.install()
    spec = importlib.util.spec_from_file_location("build_master_material", os.path.join(ROOT, "Scripts", "build_master_material.py"))
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    gen.main()
    return gen


# --------------------------------------------------------------------------------------------- texture sampling
def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


class TexSampler:
    """Bilinear, wrapping lookup that returns what the engine's sampler type would: linear colour / unpacked normal / raw."""

    def __init__(self, tex, sampler):
        self.w, self.h, self.data, self.sampler = tex.width, tex.height, tex.rgba, sampler.name
        self.lut = [_lin(i / 255.0) for i in range(256)]

    def _px(self, ix, iy):
        i = ((iy % self.h) * self.w + (ix % self.w)) * 4
        return self.data[i:i + 4]

    def __call__(self, uv):
        x, y = (uv[0] % 1.0) * self.w - 0.5, (uv[1] % 1.0) * self.h - 0.5
        x0, y0 = math.floor(x), math.floor(y)
        fx, fy = x - x0, y - y0
        p00, p10, p01, p11 = self._px(x0, y0), self._px(x0 + 1, y0), self._px(x0, y0 + 1), self._px(x0 + 1, y0 + 1)
        rgba = [((p00[c] * (1 - fx) + p10[c] * fx) * (1 - fy) + (p01[c] * (1 - fx) + p11[c] * fx) * fy) / 255.0 for c in range(4)]
        if self.sampler == "SAMPLERTYPE_COLOR":
            return (_lin(rgba[0]), _lin(rgba[1]), _lin(rgba[2]), rgba[3])
        if self.sampler == "SAMPLERTYPE_NORMAL":
            nx, ny = rgba[0] * 2 - 1, rgba[1] * 2 - 1
            return (nx, ny, math.sqrt(max(0.0, 1.0 - nx * nx - ny * ny)), 1.0)
        return tuple(rgba)


# --------------------------------------------------------------------------------------------- vertex paint test pattern
def painted_vertices(n_verts, strokes):
    """Vertex colour grid (n_verts x n_verts, RGBA) with round soft strokes: [(cx, cy, radius, channel)] paint BLACK."""
    grid = [[[1.0, 1.0, 1.0, 1.0] for _ in range(n_verts)] for _ in range(n_verts)]
    for j in range(n_verts):
        for i in range(n_verts):
            x, y = i / (n_verts - 1.0), j / (n_verts - 1.0)
            for cx, cy, r, ch in strokes:
                d = math.hypot(x - cx, y - cy)
                strength = max(0.0, min(1.0, 1.0 - (d / r) ** 2))
                grid[j][i][ch] = min(grid[j][i][ch], 1.0 - strength)
    return grid


def vertex_at(grid, u, v):
    n = len(grid)
    x, y = min(max(u, 0.0), 1.0) * (n - 1), min(max(v, 0.0), 1.0) * (n - 1)
    i0, j0 = min(int(x), n - 2), min(int(y), n - 2)
    fx, fy = x - i0, y - j0
    out = []
    for c in range(4):
        a = grid[j0][i0][c] * (1 - fx) + grid[j0][i0 + 1][c] * fx
        b = grid[j0 + 1][i0][c] * (1 - fx) + grid[j0 + 1][i0 + 1][c] * fx
        out.append(a * (1 - fy) + b * fy)
    return tuple(out)


# --------------------------------------------------------------------------------------------- shading
LIGHT = (-0.45, -0.55, 0.70)
LIGHT = tuple(c / math.sqrt(sum(k * k for k in LIGHT)) for c in LIGHT)
HALF = (LIGHT[0], LIGHT[1], LIGHT[2] + 1.0)
HALF = tuple(c / math.sqrt(sum(k * k for k in HALF)) for c in HALF)


def shade(res):
    base, n = res["MP_BASE_COLOR"], res["MP_NORMAL"]
    rough, metal, ao = res["MP_ROUGHNESS"][0], res["MP_METALLIC"][0], res["MP_AMBIENT_OCCLUSION"][0]
    ndl = max(0.0, sum(a * b for a, b in zip(n, LIGHT)))
    ndh = max(0.0, sum(a * b for a, b in zip(n, HALF)))
    power = 2.0 / max(0.02, rough * rough * rough * rough + 0.004) - 2.0
    spec = ndh ** min(power, 400.0) * (1.0 - rough) ** 2 * 1.2
    out = []
    for c in range(3):
        diffuse = base[c] * (1.0 - metal) * (0.28 + 0.95 * ndl) * ao
        specular = (0.04 * (1 - metal) + base[c] * metal) * spec * ndl
        out.append(diffuse + specular + base[c] * metal * 0.10 * ao)
    return tuple(out)


def to_srgb8(c):
    c = max(0.0, min(1.0, c * 1.15))
    v = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return int(round(max(0.0, min(1.0, v)) * 255))


# --------------------------------------------------------------------------------------------- one instance
def instance_state(gen, inst_name):
    insts = {i.path.split("/")[-1]: i for i in mu.REGISTRY.values() if isinstance(i, mu.MaterialInstanceConstant)}
    chain, cur = [], insts[inst_name]
    while isinstance(cur, mu.MaterialInstanceConstant):
        chain.append(cur)
        cur = cur.parent
    master = cur
    static, scalar, vector, assets = {}, {}, {}, {}
    for i in reversed(chain):
        static.update(i.statics)
        scalar.update(i.scalars)
        vector.update({k: (v.r, v.g, v.b, v.a) for k, v in i.vectors.items()})
        assets.update(i.textures)
    samplers = {}
    for e in master.expressions:
        if e._short in ("TextureObjectParameter", "TextureSampleParameter2D"):
            name = str(e._props["parameter_name"])
            tex = assets.get(name) or e._props["texture"]
            samplers[name] = TexSampler(tex, e._props["sampler_type"])
            assets.setdefault(name, tex)
    return master, {"static": static, "scalar": scalar, "vector": vector, "texture_asset": assets, "texture": samplers}


def render_rows(args):
    inst_name, size, rows, tiles, vertex_strokes, extra_scalar = args
    gen, = STATE["gen"],
    master, base_ctx = instance_state(gen, inst_name)
    base_ctx["scalar"].update(extra_scalar)
    grid = painted_vertices(17, vertex_strokes) if vertex_strokes else None
    out = []
    for py in rows:
        line = []
        for px in range(size):
            u, v = (px + 0.5) / size, (py + 0.5) / size
            ctx = dict(base_ctx)
            ctx["uv"] = {0: (u * tiles, v * tiles), 1: (u, v)}
            ctx["vertex_color"] = vertex_at(grid, u, v) if grid else (1.0, 1.0, 1.0, 1.0)
            ctx["pixel_depth"] = 250.0
            ctx["world_pos"] = (u * 200.0, v * 200.0, 0.0)
            ctx["object_pos"] = (0.0, 0.0, 0.0)
            res, _ = ge.evaluate_material(master, ctx)
            if "MP_EMISSIVE_COLOR" in res and base_ctx["static"].get("Debug View"):
                col = res["MP_EMISSIVE_COLOR"]                       # debug views are shown flat, like the editor does
            else:
                col = shade(res)
            line.append(tuple(to_srgb8(c) for c in col))
        out.append((py, line))
    return out


def render(gen, inst_name, size, tiles=1.0, strokes=None, extra_scalar=None, workers=4):
    STATE["gen"] = gen
    jobs = [(inst_name, size, list(range(i, size, workers * 4)), tiles, strokes, extra_scalar or {}) for i in range(workers * 4)]
    try:
        import multiprocessing as mp
        with mp.get_context("fork").Pool(workers) as pool:
            parts = pool.map(render_rows, jobs)
    except (ValueError, ImportError, OSError):
        parts = [render_rows(j) for j in jobs]
    rows = {}
    for part in parts:
        for py, line in part:
            rows[py] = line
    return [rows[y] for y in range(size)]


def save_png(pixels, path):
    from PIL import Image
    h, w = len(pixels), len(pixels[0])
    im = Image.new("RGB", (w, h))
    im.putdata([p for row in pixels for p in row])
    im.save(path)
    return im


# (instance, file name, label under the picture, extra arguments for the renderer)
PLAN = [
    ("MI_Demo_Crate_Red", "crate_red", "Crate Red", dict()),
    ("MI_Demo_Crate_Blue", "crate_blue", "Crate Blue", dict()),
    ("MI_Demo_Crate_Cream_Weathered", "crate_cream_weathered", "Crate Cream", dict()),
    ("MI_Demo_Plaster_Brick_VertexPaint", "vertex_paint_plaster_brick", "Vertex paint",
     dict(strokes=[(0.30, 0.55, 0.30, 0), (0.62, 0.40, 0.22, 0), (0.72, 0.78, 0.18, 1)])),
    ("MI_Demo_Debug_Masks", "debug_mask_r_wear", "Debug: mask R", dict()),
]


def write_sheet(out_dir, size):
    """demo_sheet.png: the five pictures side by side with a caption each (rebuilt from the saved tiles)."""
    from PIL import Image, ImageDraw
    pad, label_h = 8, 20
    im = Image.new("RGB", (len(PLAN) * (size + pad) + pad, size + 2 * pad + label_h), (24, 28, 34))
    d = ImageDraw.Draw(im)
    for i, (_inst, fname, label, _kw) in enumerate(PLAN):
        x = pad + i * (size + pad)
        im.paste(Image.open(os.path.join(out_dir, fname + ".png")).convert("RGB").resize((size, size)), (x, pad))
        d.text((x, pad + size + 4), label, fill=(205, 212, 220))
    path = os.path.join(out_dir, "demo_sheet.png")
    im.save(path)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size", type=int, default=128)
    ap.add_argument("--out", default=os.path.join(ROOT, "Docs", "img"))
    ap.add_argument("--sheet-only", action="store_true", help="only rebuild demo_sheet.png from the pictures already in --out")
    args = ap.parse_args()
    try:
        import PIL                                                    # noqa: F401
    except ImportError:
        sys.exit("Pillow is needed to write the images:  pip install pillow")
    os.makedirs(args.out, exist_ok=True)
    if args.sheet_only:
        print("wrote", write_sheet(args.out, args.size))
        return
    t0 = time.time()
    gen = build()
    for inst, fname, _label, kw in PLAN:
        t1 = time.time()
        save_png(render(gen, inst, args.size, **kw), os.path.join(args.out, fname + ".png"))
        print("%-28s %.1fs" % (fname, time.time() - t1))
    print("wrote %s (%.0fs)" % (write_sheet(args.out, args.size), time.time() - t0))


if __name__ == "__main__":
    main()
