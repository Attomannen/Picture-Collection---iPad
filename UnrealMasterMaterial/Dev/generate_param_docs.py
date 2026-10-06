#!/usr/bin/env python3
"""
Writes Docs/03_Parameter_Reference.md from the parameter tables inside Scripts/build_master_material.py
(single source of truth) and measures, with the offline interpreter, what every static switch costs in
texture samples. Run from anywhere:

    python3 Dev/generate_param_docs.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
os.environ["MM_NO_AUTORUN"] = "1"

import run_tests as rt            # noqa: E402  (builds the master in the offline engine)
import graph_eval as ge           # noqa: E402

OUT = os.path.join(ROOT, "Docs", "03_Parameter_Reference.md")

TEX_DEFAULT_TEXT = {
    "white": "flat white", "black": "flat black", "flatnormal": "flat normal", "ormh": "flat ORMH (AO 1, rough 0.5, metal 0, height 0.5)",
    "mask_black": "black mask (no wear/dirt/scratches), AO 1", "gray": "50% grey (neutral)", "white_mask": "white (fully opaque)",
    "alb_base": "flat blue-grey placeholder", "alb_wear": "flat rust-orange placeholder", "alb_dirt": "flat dark-brown placeholder",
    "alb_vertex1": "flat brick-red placeholder", "alb_vertex2": "flat moss-green placeholder", "alb_vertex3": "flat sand placeholder",
}
SAMPLER_TEXT = {
    "SAMPLERTYPE_COLOR": "Color (sRGB)", "SAMPLERTYPE_NORMAL": "Normalmap", "SAMPLERTYPE_MASKS": "Masks (no sRGB)",
}


def fmt(x):
    s = ("%.3f" % x).rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def default_text(d):
    if d.kind == "scalar":
        return fmt(d.default)
    if d.kind == "vector":
        return "(" + ", ".join(fmt(c) for c in d.default[:3]) + ")"
    if d.kind == "static":
        return "On" if d.default else "Off"
    return TEX_DEFAULT_TEXT.get(d.tex, d.tex)


def range_text(d):
    if d.kind == "scalar" and d.lo is not None:
        return "%s .. %s" % (fmt(d.lo), fmt(d.hi))
    if d.kind == "texture":
        return SAMPLER_TEXT.get(d.sampler, d.sampler)
    return ""


def esc(t):
    return t.replace("|", "\\|")


def measure_switch_costs(b):
    """Texture samples with each static switch ON vs OFF (everything else at default)."""
    costs = {}
    for name, d in b.params.items.items():
        if d.kind != "static":
            continue
        counts = []
        for val in (True, False):
            ctx = rt.make_ctx(static={name: val})
            _, ev = ge.evaluate_material(b.fn_mat, ctx, props=[rt.MP.MP_BASE_COLOR, rt.MP.MP_NORMAL,
                                                                rt.MP.MP_EMISSIVE_COLOR, rt.MP.MP_OPACITY_MASK,
                                                                rt.MP.MP_AMBIENT_OCCLUSION, rt.MP.MP_ROUGHNESS,
                                                                rt.MP.MP_METALLIC])
            counts.append(len(ev.tex_samples))
        costs[name] = counts[0] - counts[1]
    return costs


def section_table(pt, costs=None):
    lines = []
    groups = {}
    for name in pt.order:
        d = pt.items[name]
        groups.setdefault(d.group, []).append(d)
    for group in sorted(groups):
        items = sorted(groups[group], key=lambda d: d.prio)
        lines.append("#### %s\n" % group)
        is_static = all(d.kind == "static" for d in items)
        if is_static and costs is not None:
            lines.append("| Switch | Default | Texture samples when ON | What it does |")
            lines.append("|---|---|---|---|")
            for d in items:
                c = costs.get(d.name, 0)
                cost = ("+%d" % c) if c > 0 else ("%d" % c if c < 0 else "-")
                lines.append("| `%s` | %s | %s | %s |" % (d.name, default_text(d), cost, esc(d.desc)))
        else:
            lines.append("| Parameter | Type | Default | Range / import setting | What it does |")
            lines.append("|---|---|---|---|---|")
            kind_text = {"scalar": "Scalar", "vector": "Colour", "static": "Switch", "texture": "Texture"}
            for d in items:
                lines.append("| `%s` | %s | %s | %s | %s |" % (d.name, kind_text[d.kind], default_text(d), range_text(d), esc(d.desc)))
        lines.append("")
    return lines


def main():
    b = rt.build_all()
    costs = measure_switch_costs(b)
    pt = b.params
    dt = b.gen.define_decal_params()
    n_params = len(pt.order)
    kinds = {}
    for n in pt.order:
        kinds[pt.items[n].kind] = kinds.get(pt.items[n].kind, 0) + 1

    L = []
    L.append("# Parameter reference\n")
    L.append("> **Generated file** - produced by `Dev/generate_param_docs.py` from the parameter table in "
             "`Scripts/build_master_material.py`, so it always matches the material. Do not edit by hand.\n")
    L.append("The Material Instance editor lists parameters in **groups** (numbered so they sort in the order below) "
             "and, inside a group, by sort priority (the order of the tables). Hover a parameter in the editor to see the "
             "same description that is printed here. Groups marked **extra** are not needed for the assignment - ignore them "
             "until you want them.\n")
    L.append("`M_Master_Surface` has **%d parameters** (%d scalars, %d colours, %d textures, %d static switches).\n"
             % (n_params, kinds.get("scalar", 0), kinds.get("vector", 0), kinds.get("texture", 0), kinds.get("static", 0)))
    L.append("**Layer parameter sets.** The six layers (Base, Wear, Dirt, Vertex 1-3) share the same set of parameters "
             "(textures, tint, then the layer's own effect knobs, then brightness, saturation, tiling, rotation, offset, normal strength, "
             "roughness range, metallic, AO strength, height contrast/offset - the Base layer has no height parameters because its "
             "height is never used). They are written out in full for each layer so you can search for a parameter by name. "
             "All tints default to **white**: a texture you assign shows exactly as authored; an empty layer shows a flat "
             "placeholder colour so the stack is visible before you have textures.\n")
    L.append("## M_Master_Surface\n")
    L.extend(section_table(pt, costs))
    L.append("### Debug modes\n")
    L.append("Turn on **Debug View** (group 00) and set **Debug Mode** (group 17) to a number:\n")
    L.append("| Mode | Shows |")
    L.append("|---|---|")
    for i, name in enumerate(b.gen.DEBUG_MODES, start=1):
        L.append("| %d | %s |" % (i, name))
    L.append("")
    L.append("## M_Master_MeshDecal\n")
    L.append("Material Domain **Deferred Decal**, Blend Mode **Translucent**, Decal Blend Mode **DBuffer Translucent Color, Normal, Roughness**. "
             "Put the decal mesh's UVs on the cells of your decal sheet; use *Decal UV Tiling/Offset* to move to another cell without re-UVing.\n")
    L.extend(section_table(dt))
    with open(OUT, "w") as f:
        f.write("\n".join(L) + "\n")
    print("wrote", OUT)
    print("samples default config: 15; switch costs:", {k: v for k, v in costs.items() if v})


if __name__ == "__main__":
    main()
