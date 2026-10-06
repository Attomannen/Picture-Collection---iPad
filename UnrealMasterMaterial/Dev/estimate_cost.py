#!/usr/bin/env python3
"""
Offline, rough estimate of the per-pixel cost of M_Master_Surface in a few configurations.

    python3 Dev/estimate_cost.py

The numbers are a PROXY (weighted count of vector ALU operations that depend on per-pixel data + texture samples).
Unreal's own counter (Material Editor > Window > Stats, or Platform Stats) is the authority.
"""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["MM_NO_AUTORUN"] = "1"

import run_tests as rt            # noqa: E402
import graph_eval as ge           # noqa: E402


def contexts(static):
    rnd = random.Random(99)
    out = []
    for _ in range(3):
        tex = {}
        for name in rt.LAYER:
            tex[name + " Albedo"] = (rnd.random(), rnd.random(), rnd.random(), 1.0)
            tex[name + " ORMH Map"] = (rnd.random(), rnd.random(), rnd.random(), rnd.random())
            nx, ny = rnd.uniform(-.4, .4), rnd.uniform(-.4, .4)
            tex[name + " Normal Map"] = (nx, ny, (1 - nx * nx - ny * ny) ** 0.5, 1.0)
        tex["Mask Texture"] = tuple(rnd.uniform(0.25, 0.75) for _ in range(4))
        tex["Breakup Texture"] = tuple([rnd.random()] * 3 + [1.0])
        tex["Macro Texture"] = tuple([rnd.random()] * 3 + [1.0])
        tex["Emissive Texture"] = (rnd.random(), rnd.random(), rnd.random(), 1.0)
        tex["Opacity Texture"] = (rnd.random(), 0, 0, 1.0)
        nx, ny = rnd.uniform(-.3, .3), rnd.uniform(-.3, .3)
        tex["Detail Normal Texture"] = (nx, ny, (1 - nx * nx - ny * ny) ** 0.5, 1.0)
        out.append(rt.make_ctx(static=static, texture=tex, vertex=tuple(rnd.uniform(0.2, 0.8) for _ in range(4)),
                               uv0=(rnd.random() * 4, rnd.random() * 4), uv1=(rnd.random(), rnd.random()),
                               depth=rnd.uniform(50, 800)))
    return out


def main():
    b = rt.build_all()
    names = [n for n, d in b.params.items.items() if d.kind == "static"]
    off = {n: False for n in names}
    configs = {
        "Minimal: Base layer only (all switches off)": dict(off),
        "Default switches": {},
        "Default + Vertex Layers 2 and 3": {"Use Vertex Layer 2": True, "Use Vertex Layer 3": True},
        "Everything on (no debug)": {n: True for n in names if n not in ("Debug View", "Vertex Paint White Adds", "Swap UV Channels", "Mask Uses Tiling UV")},
    }
    rows = []
    for label, st in configs.items():
        alu, samples, cls = ge.estimate_per_pixel_alu(b.fn_mat, contexts(st))
        rows.append((label, alu, samples))
        print("%-48s ~%4d ALU, %2d texture samples" % (label, alu, samples))
    return rows


if __name__ == "__main__":
    main()
