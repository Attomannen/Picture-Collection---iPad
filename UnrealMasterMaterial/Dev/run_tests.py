#!/usr/bin/env python3
"""
Offline test-suite for Scripts/build_master_material.py

    python3 Dev/run_tests.py            (from the UnrealMasterMaterial folder; plain Python 3.8+, no Unreal needed)

What is verified (against the strict mock in mock_unreal.py + the interpreter in graph_eval.py):

  * the generator runs end-to-end in BOTH modes (Material Functions / everything inline)
  * every API call has valid signatures, property names and enum members (taken from the UE 5.6 stub)
  * the graph "compiles": no dimension errors, missing inputs, sampler-type mismatches, in many
    static-switch permutations
  * numeric behaviour of the finished material for controlled inputs (masks, vertex colour, UVs ...)
  * function mode and inline mode produce identical numbers
  * parameter table <-> graph consistency, texture-sample budget, shared-sampler usage

It can NOT prove that Unreal accepts the graph (pin/output names are written from engine knowledge,
see mock_unreal.py). It does remove the large class of typo / wiring / maths mistakes.
"""
import importlib.util
import itertools
import math
import os
import random
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, "Scripts", "build_master_material.py")
sys.path.insert(0, HERE)
os.environ["MM_NO_AUTORUN"] = "1"

import mock_unreal as mu          # noqa: E402
import graph_eval as ge           # noqa: E402

MP = mu.ENUMS["MaterialProperty"]


# ------------------------------------------------------------------------------ helpers
def load_generator():
    """Fresh fake `unreal` + a fresh import of the generator."""
    mu.install()
    spec = importlib.util.spec_from_file_location("build_master_material", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Built:
    pass


_CACHE = {}


def build_all():
    """Build master (functions), master (inline, under another name) and the decal master once."""
    if "built" in _CACHE:
        return _CACHE["built"]
    gen = load_generator()
    b = Built()
    b.gen = gen
    gen.USE_MATERIAL_FUNCTIONS = True
    gen.CREATE_DEMO_TEXTURES = True
    gen.CREATE_DEMO_INSTANCES = True
    gen.main()
    reg = mu.REGISTRY
    b.fn_mat = reg[gen.ROOT_PATH + "/" + gen.SURFACE_MASTER_NAME]
    b.decal = reg[gen.ROOT_PATH + "/" + gen.DECAL_MASTER_NAME]
    # inline copy
    textures = gen.ensure_placeholder_textures()
    blocks = gen.make_blocks()
    gen.SURFACE_MASTER_NAME = "M_Master_Surface_Inline"
    b.inline_mat, b.inline_graph = gen.build_surface_master(blocks, None, textures)
    gen.SURFACE_MASTER_NAME = "M_Master_Surface"
    b.params = gen.define_surface_params()
    b.log = list(mu.LOG)
    _CACHE["built"] = b
    return b


def close(a, b, tol=1e-4):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    a, b = tuple(a), tuple(b)
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def expect(label, got, want, tol=1e-4):
    if not close(got, want, tol):
        raise AssertionError("%s: got %s, expected %s" % (label, _fmt(got), _fmt(want)))


def _fmt(x):
    if isinstance(x, (int, float)):
        return "%.5f" % x
    return "(" + ", ".join("%.5f" % v for v in x) + ")"


def lerp(a, b, t):
    if isinstance(a, (int, float)):
        return a + (b - a) * t
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def mul(a, b):
    return tuple(x * b for x in a) if isinstance(b, (int, float)) else tuple(x * y for x, y in zip(a, b))


def normalize(v):
    n = math.sqrt(sum(x * x for x in v))
    return tuple(x / n for x in v)


# layer constants used by most tests ---------------------------------------------------------------
LAYER = {
    "Base": dict(albedo=(0.20, 0.40, 0.60), orm=(0.9, 0.5, 0.0, 0.5), n=(0.0, 0.0, 1.0)),
    "Wear": dict(albedo=(0.80, 0.50, 0.10), orm=(0.7, 0.3, 1.0, 0.5), n=(0.3, 0.0, math.sqrt(1 - 0.09))),
    "Dirt": dict(albedo=(0.10, 0.08, 0.05), orm=(1.0, 0.9, 0.0, 0.5), n=(0.0, 0.2, math.sqrt(1 - 0.04))),
    "Vertex 1": dict(albedo=(0.60, 0.10, 0.10), orm=(0.8, 0.8, 0.0, 0.5), n=(-0.2, 0.0, math.sqrt(1 - 0.04))),
    "Vertex 2": dict(albedo=(0.10, 0.50, 0.10), orm=(0.6, 0.6, 0.0, 0.5), n=(0.0, -0.2, math.sqrt(1 - 0.04))),
    "Vertex 3": dict(albedo=(0.50, 0.50, 0.10), orm=(0.5, 0.7, 0.0, 0.5), n=(0.0, 0.0, 1.0)),
}
SCRATCH = dict(color=(0.78, 0.78, 0.80), rough=0.35, metal=1.0)
EDGE_COLOR, EDGE_STRENGTH = (0.06, 0.03, 0.02), 0.5       # defaults of the Wear layer


def make_ctx(mask=(0.0, 0.0, 0.0, 1.0), vertex=(1.0, 1.0, 1.0, 1.0), static=None, scalar=None, vector=None,
             texture=None, uv0=(0.3, 0.7), uv1=(0.3, 0.7), depth=100.0):
    tex = {"Mask Texture": tuple(mask), "Breakup Texture": (0.5, 0.5, 0.5, 1.0),
           "Detail Normal Texture": (0.0, 0.0, 1.0, 1.0), "Macro Texture": (0.5, 0.5, 0.5, 1.0),
           "Emissive Texture": (0.0, 0.0, 0.0, 1.0), "Opacity Texture": (1.0, 1.0, 1.0, 1.0)}
    vec = {}
    for name, d in LAYER.items():
        tex[name + " Albedo"] = d["albedo"] + (1.0,)
        tex[name + " Normal Map"] = d["n"] + (1.0,)
        tex[name + " ORMH Map"] = d["orm"]
        vec[name + " Tint"] = (1.0, 1.0, 1.0, 1.0)
    tex.update(texture or {})
    vec.update(vector or {})
    return {"static": dict(static or {}), "scalar": dict(scalar or {}), "vector": vec, "texture": tex,
            "uv": {0: uv0, 1: uv1}, "vertex_color": tuple(vertex), "pixel_depth": depth,
            "world_pos": (150.0, 250.0, 0.0), "object_pos": (1000.0, 2000.0, 0.0)}


def run(mat, ctx):
    res, ev = ge.evaluate_material(mat, ctx)
    return res, ev


def out(mat, ctx, prop):
    res, _ = run(mat, ctx)
    return res[prop]


# ------------------------------------------------------------------------------ tests
TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


@test
def test_generator_logged_no_errors_or_warnings():
    b = build_all()
    bad = [(l, m) for l, m in b.log if l in ("error", "warning")]
    assert not bad, "generator logged: %s" % bad[:3]


@test
def test_function_mode_was_used():
    b = build_all()
    assert any("built in 'functions' mode" in m for _, m in b.log), "master did not build in function mode"
    fns = [k for k in mu.REGISTRY if "/Functions/" in k]
    assert len(fns) == 5, fns


@test
def test_all_created_assets_saved():
    b = build_all()
    unsaved = [p for p, a in mu.REGISTRY.items() if hasattr(a, "saved") and not a.saved]
    assert not unsaved, "not saved: %s" % unsaved[:5]


@test
def test_master_has_one_node_per_parameter_and_no_duplicates():
    b = build_all()
    for mat in (b.fn_mat, b.inline_mat):
        names = {}
        for e in mat.expressions:
            if "parameter_name" in e._props and e._props["parameter_name"]:
                n = e._props["parameter_name"]
                names[n] = names.get(n, 0) + 1
        dup = [n for n, c in names.items() if c > 1]
        assert not dup, "duplicate parameter nodes: %s" % dup
        missing = [n for n in b.params.order if n not in names]
        extra = [n for n in names if n not in b.params.items]
        assert not missing, "parameters defined but never created: %s" % missing
        assert not extra, "parameter nodes not in the table: %s" % extra


@test
def test_parameter_properties_match_table():
    b = build_all()
    for e in b.fn_mat.expressions:
        n = e._props.get("parameter_name")
        if not n:
            continue
        d = b.params.items[n]
        assert e._props["group"] == d.group, (n, e._props["group"], d.group)
        assert e._props["sort_priority"] == d.prio, n
        if d.kind == "scalar":
            assert abs(e._props["default_value"] - d.default) < 1e-9, n
        if d.kind == "texture":
            assert e._props["texture"] is not None and e._props["sampler_type"].name == d.sampler, n


@test
def test_parameter_names_are_unique_ignoring_case_and_sane():
    """Unreal compares parameter names case-insensitively; a clash would silently merge two parameters."""
    b = build_all()
    for table in (b.params, b.gen.define_decal_params()):
        seen = {}
        for name in table.order:
            key = name.lower().replace(" ", "")
            assert key not in seen, "parameter names clash: %r vs %r" % (name, seen[key])
            seen[key] = name
            assert 0 < len(name) <= 48, name
            assert all(c.isalnum() or c == " " for c in name), "unexpected character in %r" % name
            assert name == name.strip() and "  " not in name, name


@test
def test_group_names_sort_in_intended_order():
    b = build_all()
    groups = sorted({d.group for d in b.params.items.values()})
    assert groups[0].startswith("00") and groups[-2].startswith("17") and groups[-1].startswith("99"), groups
    assert len(groups) == 19, groups
    assert [d.group for d in b.params.items.values() if d.name == "Mask Uses Tiling UV"] == [groups[-1]]


@test
def test_every_texture_sample_uses_shared_wrap_sampler():
    b = build_all()
    for mat in (b.fn_mat, b.inline_mat, b.decal):
        for e in list(mat.expressions) + [x for f in mu.REGISTRY.values() if isinstance(f, mu.MaterialFunction) for x in f.expressions]:
            if e._short in ("TextureSample", "TextureSampleParameter2D", "TextureObjectParameter"):
                assert e._props["sampler_source"].name == "SSM_WRAP_WORLD_GROUP_SETTINGS", e


def _all_static_names(b):
    return [n for n, d in b.params.items.items() if d.kind == "static"]


@test
def test_default_config_texture_budget():
    b = build_all()
    res, ev = run(b.fn_mat, make_ctx())
    samples = sorted(k for _, k, _, _ in ev.tex_samples)
    # defaults: Base, Wear, Dirt, Vertex1 layers (3 each) + mask + breakup + detail
    assert len(samples) == 15, (len(samples), samples)
    assert len(set(samples)) == 15


@test
def test_all_features_on_texture_budget():
    b = build_all()
    statics = {n: True for n in _all_static_names(b)}
    statics.update({"Debug View": False, "Vertex Paint White Adds": False, "Swap UV Channels": False,
                    "Mask Uses Tiling UV": False})
    res, ev = run(b.fn_mat, make_ctx(static=statics))
    assert len(ev.tex_samples) == 24, len(ev.tex_samples)


@test
def test_untouched_mesh_shows_only_the_base_layer():
    b = build_all()
    for mat in (b.fn_mat, b.inline_mat):
        res, _ = run(mat, make_ctx())
        base = LAYER["Base"]
        expect("BaseColor", res["MP_BASE_COLOR"], base["albedo"])
        expect("Roughness", res["MP_ROUGHNESS"], (base["orm"][1],))
        expect("Metallic", res["MP_METALLIC"], (base["orm"][2],))
        expect("AO", res["MP_AMBIENT_OCCLUSION"], (base["orm"][0],))
        expect("Normal", res["MP_NORMAL"], base["n"])
        expect("Emissive", res["MP_EMISSIVE_COLOR"], (0, 0, 0))
        expect("OpacityMask", res["MP_OPACITY_MASK"], (1.0,))


def _stack_expect(layer_name):
    d = LAYER[layer_name]
    return d["albedo"], d["orm"][1], d["orm"][2], d["orm"][0], d["n"]


@test
def test_mask_r_reveals_wear_layer_and_ao_blends():
    b = build_all()
    for mat in (b.fn_mat, b.inline_mat):
        res, _ = run(mat, make_ctx(mask=(1.0, 0.0, 0.0, 1.0)))
        color, rough, metal, ao, n = _stack_expect("Wear")
        expect("color", res["MP_BASE_COLOR"], color)
        expect("rough", res["MP_ROUGHNESS"], (rough,))
        expect("metal", res["MP_METALLIC"], (metal,))
        expect("ao", res["MP_AMBIENT_OCCLUSION"], (ao,))
        expect("normal", res["MP_NORMAL"], normalize(n))


@test
def test_half_mask_gives_half_weight_and_edge_rim():
    b = build_all()
    res, _ = run(b.fn_mat, make_ctx(mask=(0.5, 0.0, 0.0, 1.0)))
    base, wear = LAYER["Base"]["albedo"], LAYER["Wear"]["albedo"]
    mixed = lerp(base, wear, 0.5)                                   # weight exactly 0.5 for flat height/breakup
    rim = min(1.0, 4 * 0.5 * 0.5 * EDGE_STRENGTH)
    expect("color", res["MP_BASE_COLOR"], lerp(mixed, EDGE_COLOR, rim))
    expect("rough", res["MP_ROUGHNESS"], (lerp(0.5, 0.3, 0.5),))


@test
def test_mask_g_adds_dirt_and_b_adds_scratches():
    b = build_all()
    res, _ = run(b.fn_mat, make_ctx(mask=(0.0, 1.0, 0.0, 1.0)))
    expect("dirt colour", res["MP_BASE_COLOR"], LAYER["Dirt"]["albedo"])
    expect("dirt rough", res["MP_ROUGHNESS"], (0.9,))
    res, _ = run(b.fn_mat, make_ctx(mask=(0.0, 0.0, 1.0, 1.0)))
    expect("scratch colour", res["MP_BASE_COLOR"], SCRATCH["color"])
    expect("scratch rough", res["MP_ROUGHNESS"], (SCRATCH["rough"],))
    expect("scratch metal", res["MP_METALLIC"], (SCRATCH["metal"],))


@test
def test_layer_order_dirt_covers_wear_and_scratches_cover_dirt():
    b = build_all()
    res, _ = run(b.fn_mat, make_ctx(mask=(1.0, 1.0, 0.0, 1.0)))
    expect("dirt over wear", res["MP_BASE_COLOR"], LAYER["Dirt"]["albedo"])
    res, _ = run(b.fn_mat, make_ctx(mask=(1.0, 1.0, 1.0, 1.0)))
    expect("scratch on top", res["MP_BASE_COLOR"], SCRATCH["color"])


@test
def test_baked_ao_from_mask_alpha():
    b = build_all()
    res, _ = run(b.fn_mat, make_ctx(mask=(0, 0, 0, 0.5)))
    expect("ao", res["MP_AMBIENT_OCCLUSION"], (0.9 * 0.5,))
    res, _ = run(b.fn_mat, make_ctx(mask=(0, 0, 0, 0.5), static={"Use Baked AO": False}))
    expect("ao off", res["MP_AMBIENT_OCCLUSION"], (0.9,))
    res, _ = run(b.fn_mat, make_ctx(mask=(0, 0, 0, 0.5), scalar={"Mask AO Strength": 0.0}))
    expect("ao strength 0", res["MP_AMBIENT_OCCLUSION"], (0.9,))
    res, _ = run(b.fn_mat, make_ctx(mask=(0, 0, 0, 0.5), scalar={"Global AO Strength": 0.0}))
    expect("global ao 0", res["MP_AMBIENT_OCCLUSION"], (1.0,))


@test
def test_dirt_gathers_in_crevices_via_ao_boost():
    b = build_all()
    # no dirt painted, AO 0 -> AO boost 0.5 -> weight 0.5 -> halfway to dirt
    res, _ = run(b.fn_mat, make_ctx(mask=(0, 0, 0, 0.0)))
    expect("colour", res["MP_BASE_COLOR"], lerp(LAYER["Base"]["albedo"], LAYER["Dirt"]["albedo"], 0.5))


@test
def test_vertex_paint_black_adds_layer_white_does_nothing():
    b = build_all()
    for mat in (b.fn_mat, b.inline_mat):
        res, _ = run(mat, make_ctx(vertex=(0.0, 1.0, 1.0, 1.0)))
        expect("painted R=0", res["MP_BASE_COLOR"], LAYER["Vertex 1"]["albedo"])
        expect("normal", res["MP_NORMAL"], normalize(LAYER["Vertex 1"]["n"]))
        res, _ = run(mat, make_ctx(vertex=(1.0, 1.0, 1.0, 1.0)))
        expect("white", res["MP_BASE_COLOR"], LAYER["Base"]["albedo"])


@test
def test_vertex_layers_2_and_3_need_their_static_switch():
    b = build_all()
    res, _ = run(b.fn_mat, make_ctx(vertex=(1.0, 0.0, 1.0, 1.0)))
    expect("G painted but layer 2 off", res["MP_BASE_COLOR"], LAYER["Base"]["albedo"])
    res, _ = run(b.fn_mat, make_ctx(vertex=(1.0, 0.0, 1.0, 1.0), static={"Use Vertex Layer 2": True}))
    expect("layer 2 on", res["MP_BASE_COLOR"], LAYER["Vertex 2"]["albedo"])
    res, _ = run(b.fn_mat, make_ctx(vertex=(1.0, 1.0, 0.0, 1.0), static={"Use Vertex Layer 3": True}))
    expect("layer 3 on", res["MP_BASE_COLOR"], LAYER["Vertex 3"]["albedo"])
    # later vertex layers sit on top of earlier ones
    res, _ = run(b.fn_mat, make_ctx(vertex=(0.0, 0.0, 0.0, 1.0),
                                    static={"Use Vertex Layer 2": True, "Use Vertex Layer 3": True}))
    expect("all painted -> layer 3 wins", res["MP_BASE_COLOR"], LAYER["Vertex 3"]["albedo"])


@test
def test_vertex_paint_white_adds_mode():
    b = build_all()
    res, _ = run(b.fn_mat, make_ctx(vertex=(1.0, 1.0, 1.0, 1.0), static={"Vertex Paint White Adds": True}))
    expect("white now paints layer 1", res["MP_BASE_COLOR"], LAYER["Vertex 1"]["albedo"])
    res, _ = run(b.fn_mat, make_ctx(vertex=(0.0, 1.0, 1.0, 1.0), static={"Vertex Paint White Adds": True}))
    expect("black = nothing", res["MP_BASE_COLOR"], LAYER["Base"]["albedo"])


@test
def test_half_painted_vertex_is_half_blend():
    b = build_all()
    res, _ = run(b.fn_mat, make_ctx(vertex=(0.5, 1.0, 1.0, 1.0)))
    expect("colour", res["MP_BASE_COLOR"], lerp(LAYER["Base"]["albedo"], LAYER["Vertex 1"]["albedo"], 0.5))


@test
def test_vertex_paint_covers_wear_but_wear_applies_to_base_only():
    b = build_all()
    res, _ = run(b.fn_mat, make_ctx(mask=(1.0, 0, 0, 1), vertex=(0.0, 1, 1, 1)))
    expect("vertex layer replaces worn base", res["MP_BASE_COLOR"], LAYER["Vertex 1"]["albedo"])


@test
def test_vertex_alpha_paints_extra_dirt():
    b = build_all()
    res, _ = run(b.fn_mat, make_ctx(vertex=(1, 1, 1, 0.0), static={"Use Vertex Alpha Dirt": True}))
    expect("alpha painted", res["MP_BASE_COLOR"], LAYER["Dirt"]["albedo"])
    res, _ = run(b.fn_mat, make_ctx(vertex=(1, 1, 1, 0.0)))
    expect("switch off", res["MP_BASE_COLOR"], LAYER["Base"]["albedo"])
    res, _ = run(b.fn_mat, make_ctx(vertex=(1, 1, 1, 0.0),
                                    static={"Use Vertex Alpha Dirt": True}, scalar={"Vertex Alpha Dirt Strength": 0.5}))
    expect("half strength", res["MP_BASE_COLOR"], lerp(LAYER["Base"]["albedo"], LAYER["Dirt"]["albedo"], 0.5))


@test
def test_disabled_layers_are_not_compiled_at_all():
    b = build_all()
    res, ev = run(b.fn_mat, make_ctx(mask=(1, 1, 1, 1), vertex=(0, 0, 0, 0),
                                     static={"Use Wear Layer": False, "Use Dirt Layer": False, "Use Scratches": False,
                                             "Use Vertex Layer 1": False}))
    expect("only base", res["MP_BASE_COLOR"], LAYER["Base"]["albedo"])
    used = {k for _, k, _, _ in ev.tex_samples}
    for gone in ("Wear Albedo", "Wear Normal Map", "Wear ORMH Map", "Dirt Albedo", "Vertex 1 Albedo"):
        assert gone not in used, "%s still compiled although its switch is off" % gone
    # base(3) + mask + detail. The breakup texture is pruned too: only the disabled layers needed it.
    assert len(used) == 5 and "Breakup Texture" not in used, used


@test
def test_invert_controls():
    b = build_all()
    res, _ = run(b.fn_mat, make_ctx(mask=(0.0, 0, 0, 1), scalar={"Wear Invert": 1.0}))
    expect("inverted wear", res["MP_BASE_COLOR"], LAYER["Wear"]["albedo"])
    res, _ = run(b.fn_mat, make_ctx(mask=(0, 0.0, 0, 1), scalar={"Dirt Invert": 1.0}))
    expect("inverted dirt", res["MP_BASE_COLOR"], LAYER["Dirt"]["albedo"])


@test
def test_intensity_scales_the_mask():
    b = build_all()
    res, _ = run(b.fn_mat, make_ctx(mask=(0.5, 0, 0, 1), scalar={"Wear Intensity": 2.0}))
    expect("intensity 2 saturates", res["MP_BASE_COLOR"], LAYER["Wear"]["albedo"])
    res, _ = run(b.fn_mat, make_ctx(mask=(1.0, 0, 0, 1), scalar={"Wear Intensity": 0.0}))
    expect("intensity 0", res["MP_BASE_COLOR"], LAYER["Base"]["albedo"])


def _weight_via_debug(mat, mode, mask=None, vertex=None, texture=None, scalar=None, static=None):
    st = {"Debug View": True}
    st.update(static or {})
    sc = {"Debug Mode": float(mode)}
    sc.update(scalar or {})
    ctx = make_ctx(mask=mask or (0, 0, 0, 1), vertex=vertex or (1, 1, 1, 1), static=st, scalar=sc, texture=texture)
    res, _ = run(mat, ctx)
    em = res["MP_EMISSIVE_COLOR"]
    assert abs(em[0] - em[1]) < 1e-9 and abs(em[1] - em[2]) < 1e-9
    return em[0]


@test
def test_reveal_weight_endpoints_and_monotonic_for_any_height_and_breakup():
    b = build_all()
    rnd = random.Random(7)
    for _ in range(60):
        height = rnd.random()
        bk = rnd.random()
        scalar = {"Wear Softness": rnd.choice([0.0, 0.005, 0.03, 0.1, 0.5]), "Wear Height Influence": rnd.uniform(-1, 1),
                  "Wear Breakup": rnd.random()}
        tex = {"Wear ORMH Map": (1, 0.5, 0, height), "Breakup Texture": (bk, bk, bk, 1)}
        prev = -1.0
        for m in (0.0, 0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9, 1.0):
            w = _weight_via_debug(b.fn_mat, 7, mask=(m, 0, 0, 1), texture=tex, scalar=scalar)
            assert -1e-9 <= w <= 1 + 1e-9, (m, w, scalar)
            assert w >= prev - 1e-9, "weight not monotonic %s" % scalar
            prev = w
            if m == 0.0:
                assert w == 0.0, ("mask 0 must give weight 0", w, scalar, height, bk)
            if m == 1.0:
                assert abs(w - 1.0) < 1e-9, ("mask 1 must give weight 1", w, scalar, height, bk)


@test
def test_softness_controls_edge_width():
    b = build_all()
    narrow = [_weight_via_debug(b.fn_mat, 7, mask=(m, 0, 0, 1), scalar={"Wear Softness": 0.01}) for m in (0.4, 0.5, 0.6)]
    wide = [_weight_via_debug(b.fn_mat, 7, mask=(m, 0, 0, 1), scalar={"Wear Softness": 0.5}) for m in (0.4, 0.5, 0.6)]
    assert narrow[0] < 0.1 and narrow[2] > 0.9, narrow       # almost a step
    assert 0.2 < wide[0] < wide[2] < 0.8, wide               # gradual


@test
def test_height_decides_which_pixels_reveal_first():
    b = build_all()
    sc = {"Wear Softness": 0.02, "Wear Height Influence": 1.0, "Wear Breakup": 0.0}
    hi = _weight_via_debug(b.fn_mat, 7, mask=(0.5, 0, 0, 1), scalar=sc, texture={"Wear ORMH Map": (1, 0.5, 0, 0.9)})
    lo = _weight_via_debug(b.fn_mat, 7, mask=(0.5, 0, 0, 1), scalar=sc, texture={"Wear ORMH Map": (1, 0.5, 0, 0.1)})
    assert hi > 0.9 and lo < 0.1, (hi, lo)
    sc["Wear Height Influence"] = -1.0
    hi2 = _weight_via_debug(b.fn_mat, 7, mask=(0.5, 0, 0, 1), scalar=sc, texture={"Wear ORMH Map": (1, 0.5, 0, 0.9)})
    assert hi2 < 0.1, hi2                                    # negative influence flips it


@test
def test_breakup_noise_shifts_the_reveal_order():
    b = build_all()
    sc = {"Wear Softness": 0.02, "Wear Breakup": 1.0, "Wear Height Influence": 0.0}
    bright = _weight_via_debug(b.fn_mat, 7, mask=(0.5, 0, 0, 1), scalar=sc, texture={"Breakup Texture": (0.9, 0.9, 0.9, 1)})
    dark = _weight_via_debug(b.fn_mat, 7, mask=(0.5, 0, 0, 1), scalar=sc, texture={"Breakup Texture": (0.1, 0.1, 0.1, 1)})
    assert bright > 0.9 and dark < 0.1, (bright, dark)       # bright noise reveals first, dark noise last
    off = _weight_via_debug(b.fn_mat, 7, mask=(0.5, 0, 0, 1), scalar=sc, texture={"Breakup Texture": (0.9, 0.9, 0.9, 1)},
                            static={"Use Mask Breakup": False})
    assert 0.4 < off < 0.6, off


@test
def test_debug_views():
    b = build_all()
    mask = (0.1, 0.2, 0.3, 0.4)
    for mode, want in ((1, 0.1), (2, 0.2), (3, 0.3), (4, 0.4)):
        assert abs(_weight_via_debug(b.fn_mat, mode, mask=mask) - want) < 1e-6, mode
    ctx = make_ctx(mask=mask, vertex=(0.25, 0.5, 0.75, 0.9), static={"Debug View": True}, scalar={"Debug Mode": 5.0})
    res, _ = run(b.fn_mat, ctx)
    expect("vertex rgb", res["MP_EMISSIVE_COLOR"], (0.25, 0.5, 0.75))
    expect("debug base colour black", res["MP_BASE_COLOR"], (0, 0, 0))
    expect("debug metallic", res["MP_METALLIC"], (0.0,))
    expect("debug roughness", res["MP_ROUGHNESS"], (1.0,))
    ctx["scalar"]["Debug Mode"] = 6.0
    res, _ = run(b.fn_mat, ctx)
    expect("vertex alpha", res["MP_EMISSIVE_COLOR"], (0.9, 0.9, 0.9))
    ctx["scalar"]["Debug Mode"] = 13.0
    ctx["uv"][0] = (2.5, 3.2)                                   # floor 2 + 3 = odd -> 1
    res, _ = run(b.fn_mat, ctx)
    expect("checker odd", res["MP_EMISSIVE_COLOR"], (1, 1, 1))
    ctx["uv"][0] = (2.5, 4.2)                                   # even -> 0
    res, _ = run(b.fn_mat, ctx)
    expect("checker even", res["MP_EMISSIVE_COLOR"], (0, 0, 0))
    ctx["scalar"]["Debug Mode"] = 14.0
    ctx["uv"][1] = (0.25, 0.75)
    res, _ = run(b.fn_mat, ctx)
    expect("unique uv", res["MP_EMISSIVE_COLOR"], (0.25, 0.75, 0.0))
    ctx = make_ctx(mask=(0, 0, 0, 1), static={"Debug View": True}, scalar={"Debug Mode": 16.0})
    res, _ = run(b.fn_mat, ctx)
    expect("normal view", res["MP_EMISSIVE_COLOR"], (0.5, 0.5, 1.0))
    # debug off: normal material
    res, _ = run(b.fn_mat, make_ctx(static={"Debug View": False}, scalar={"Debug Mode": 3.0}))
    expect("normal output", res["MP_BASE_COLOR"], LAYER["Base"]["albedo"])


@test
def test_tiling_uv_pipeline_tiling_rotation_offset():
    b = build_all()
    tex = {"Base Albedo": lambda uv: (uv[0], uv[1], 0.0, 1.0)}
    ctx = make_ctx(texture=tex, uv0=(0.3, 0.7), uv1=(0.9, 0.1), scalar={"Global Tiling": 1.5, "Base Tiling": 2.0})
    res, _ = run(b.fn_mat, ctx)
    expect("uv0 * 1.5 * 2", res["MP_BASE_COLOR"], (0.9, 2.1, 0.0))
    ctx["scalar"]["Base Rotation"] = 90.0
    res, _ = run(b.fn_mat, ctx)
    expect("rotated 90deg about (.5,.5)", res["MP_BASE_COLOR"], (-1.1, 0.9, 0.0), 1e-4)
    ctx["scalar"]["Base Rotation"] = 0.0
    ctx["vector"]["Base Offset"] = (0.25, -0.5, 0, 0)
    res, _ = run(b.fn_mat, ctx)
    expect("offset", res["MP_BASE_COLOR"], (1.15, 1.6, 0.0))
    ctx["static"]["Swap UV Channels"] = True
    ctx["vector"]["Base Offset"] = (0, 0, 0, 0)
    res, _ = run(b.fn_mat, ctx)
    # swapped: tiling uv = uv1 * 1.5 = (1.35, 0.15), then * Base Tiling 2 = (2.7, 0.3)
    expect("swapped: tiling uses UV1", res["MP_BASE_COLOR"], (2.7, 0.3, 0.0))


@test
def test_mask_uses_unique_uv_and_swap_and_preview_switch():
    b = build_all()
    mask_tex = {"Mask Texture": lambda uv: (uv[0], 0.0, 0.0, 1.0)}      # wear = U
    # wear weight = clamp-ish of u (flat height / breakup) -> use the debug view of mask R
    def mask_r(static=None, uv0=(0.2, 0.5), uv1=(0.7, 0.5)):
        st = {"Debug View": True}
        st.update(static or {})
        res, _ = run(b.fn_mat, make_ctx(texture=mask_tex, uv0=uv0, uv1=uv1, static=st, scalar={"Debug Mode": 1.0}))
        return res["MP_EMISSIVE_COLOR"][0]
    assert abs(mask_r() - 0.7) < 1e-6                                     # unique = UV1
    assert abs(mask_r({"Swap UV Channels": True}) - 0.2) < 1e-6           # swapped: unique = UV0
    # preview switch: mask sampled with the tiling uv (= uv0 * Global Tiling)
    assert abs(mask_r({"Mask Uses Tiling UV": True}) - 0.2) < 1e-6


@test
def test_layer_adjustments_tint_brightness_saturation():
    b = build_all()
    base = LAYER["Base"]["albedo"]
    res, _ = run(b.fn_mat, make_ctx(vector={"Base Tint": (0.5, 1.0, 2.0, 1.0)}, scalar={"Base Brightness": 1.5}))
    expect("tint*brightness", res["MP_BASE_COLOR"], tuple(c * t * 1.5 for c, t in zip(base, (0.5, 1.0, 2.0))))
    res, _ = run(b.fn_mat, make_ctx(scalar={"Base Saturation": 0.0}))
    lum = base[0] * 0.3 + base[1] * 0.59 + base[2] * 0.11
    expect("desaturated", res["MP_BASE_COLOR"], (lum, lum, lum), 2e-3)


@test
def test_layer_roughness_metal_ao_height_controls():
    b = build_all()
    res, _ = run(b.fn_mat, make_ctx(scalar={"Base Roughness Min": 0.2, "Base Roughness Max": 0.4}))
    expect("remapped roughness", res["MP_ROUGHNESS"], (0.3,))
    res, _ = run(b.fn_mat, make_ctx(texture={"Base ORMH Map": (0.9, 0.5, 0.8, 0.5)}, scalar={"Base Metallic": 0.5}))
    expect("metal scale", res["MP_METALLIC"], (0.4,))
    res, _ = run(b.fn_mat, make_ctx(scalar={"Base AO Strength": 0.0}))
    expect("ao strength 0", res["MP_AMBIENT_OCCLUSION"], (1.0,))


@test
def test_normal_strength_flattens_and_exaggerates():
    b = build_all()
    n = LAYER["Wear"]["n"]
    res, _ = run(b.fn_mat, make_ctx(mask=(1, 0, 0, 1), scalar={"Wear Normal Strength": 0.0}))
    expect("flat", res["MP_NORMAL"], (0, 0, 1))
    res, _ = run(b.fn_mat, make_ctx(mask=(1, 0, 0, 1), scalar={"Wear Normal Strength": 2.0}))
    expect("x2", res["MP_NORMAL"], normalize((n[0] * 2, n[1] * 2, n[2])))


@test
def test_detail_normal_blend_and_distance_fade():
    b = build_all()
    d = (0.3, 0.0, math.sqrt(1 - 0.09))
    ctx = make_ctx(texture={"Detail Normal Texture": d + (1.0,)}, depth=100.0)
    res, _ = run(b.fn_mat, ctx)
    expect("near: detail fully applied", res["MP_NORMAL"], normalize(d))
    ctx["pixel_depth"] = 5000.0
    res, _ = run(b.fn_mat, ctx)
    expect("far: faded out", res["MP_NORMAL"], (0, 0, 1))
    ctx["pixel_depth"] = 950.0                                       # halfway between 400 and 1500
    res, _ = run(b.fn_mat, ctx)
    half = 0.5
    dd = normalize((d[0] * half, d[1] * half, d[2]))
    expect("mid fade", res["MP_NORMAL"], normalize((dd[0], dd[1], dd[2])))
    ctx["static"]["Use Detail Normal"] = False
    ctx["pixel_depth"] = 100.0
    res, _ = run(b.fn_mat, ctx)
    expect("detail off", res["MP_NORMAL"], (0, 0, 1))


@test
def test_detail_normal_keeps_base_normal_direction():
    b = build_all()
    d = (0.0, 0.3, math.sqrt(1 - 0.09))
    ctx = make_ctx(mask=(1, 0, 0, 1), texture={"Detail Normal Texture": d + (1.0,)})
    res, _ = run(b.fn_mat, ctx)
    nb = LAYER["Wear"]["n"]
    want = normalize((nb[0] + d[0], nb[1] + d[1], nb[2] * d[2]))
    expect("whiteout", res["MP_NORMAL"], want)


@test
def test_macro_variation():
    b = build_all()
    base = LAYER["Base"]["albedo"]
    res, _ = run(b.fn_mat, make_ctx(static={"Use Macro Variation": True}))
    expect("neutral grey = no change", res["MP_BASE_COLOR"], base, 2e-3)
    res, _ = run(b.fn_mat, make_ctx(static={"Use Macro Variation": True}, texture={"Macro Texture": (1, 1, 1, 1)}))
    expect("white noise +30%", res["MP_BASE_COLOR"], tuple(c * 1.3 for c in base))
    res, _ = run(b.fn_mat, make_ctx(static={"Use Macro Variation": True, "Macro Uses World Space": True},
                                    texture={"Macro Texture": lambda uv: (uv[0] % 1.0, 0, 0, 1)}))
    # world (150, 250) cm -> 1.5 m * 0.2 tiles/m = 0.3
    expect("world space uv", res["MP_ROUGHNESS"], (min(1.0, 0.5 + (0.3 - 0.5) * 0.2),))


@test
def test_instance_variation_is_deterministic_and_bounded():
    b = build_all()
    base = LAYER["Base"]["albedo"]
    ctx = make_ctx(static={"Use Instance Variation": True})
    r1, _ = run(b.fn_mat, ctx)
    r2, _ = run(b.fn_mat, ctx)
    assert r1["MP_BASE_COLOR"] == r2["MP_BASE_COLOR"]
    ctx2 = make_ctx(static={"Use Instance Variation": True})
    ctx2["object_pos"] = (5000.0, -300.0, 0.0)
    r3, _ = run(b.fn_mat, ctx2)
    assert r3["MP_BASE_COLOR"] != r1["MP_BASE_COLOR"], "different objects should vary differently"
    for r in (r1, r3):
        lum_ratio = sum(r["MP_BASE_COLOR"]) / sum(base)
        assert 0.7 < lum_ratio < 1.3, lum_ratio


@test
def test_global_grade_wetness_roughness_offset():
    b = build_all()
    base = LAYER["Base"]["albedo"]
    res, _ = run(b.fn_mat, make_ctx(vector={"Global Tint": (0.5, 0.5, 0.5, 1)}, scalar={"Global Brightness": 2.0}))
    expect("global tint x brightness", res["MP_BASE_COLOR"], base)
    res, _ = run(b.fn_mat, make_ctx(static={"Use Wetness": True}, scalar={"Wetness": 1.0}))
    expect("wet colour", res["MP_BASE_COLOR"], tuple(c * (1 - 0.35) for c in base))
    expect("wet roughness", res["MP_ROUGHNESS"], (0.08,))
    res, _ = run(b.fn_mat, make_ctx(static={"Use Wetness": True}, scalar={"Wetness": 0.0}))
    expect("dry", res["MP_BASE_COLOR"], base)
    res, _ = run(b.fn_mat, make_ctx(scalar={"Global Roughness Offset": -0.2}))
    expect("roughness offset", res["MP_ROUGHNESS"], (0.3,))


@test
def test_emissive_and_opacity():
    b = build_all()
    res, _ = run(b.fn_mat, make_ctx(static={"Use Emissive": True}, texture={"Emissive Texture": (1.0, 0.5, 0.0, 1.0)},
                                    vector={"Emissive Color": (1, 1, 1, 1)}, scalar={"Emissive Intensity": 2.0}))
    expect("emissive", res["MP_EMISSIVE_COLOR"], (2.0, 1.0, 0.0))
    res, _ = run(b.fn_mat, make_ctx(static={"Use Opacity Mask": True}, texture={"Opacity Texture": (0.25, 0, 0, 1)}))
    expect("opacity", res["MP_OPACITY_MASK"], (0.25,))
    res, _ = run(b.fn_mat, make_ctx(static={"Use Opacity Mask": True},
                                    texture={"Opacity Texture": lambda uv: (uv[0], 0, 0, 1)}, uv0=(0.2, 0.2), uv1=(0.6, 0.6)))
    expect("opacity on unique uv", res["MP_OPACITY_MASK"], (0.6,))
    res, _ = run(b.fn_mat, make_ctx(static={"Use Opacity Mask": True}, scalar={"Opacity Uses Tiling UV": 1.0},
                                    texture={"Opacity Texture": lambda uv: (uv[0], 0, 0, 1)}, uv0=(0.2, 0.2), uv1=(0.6, 0.6)))
    expect("opacity on tiling uv", res["MP_OPACITY_MASK"], (0.2,))


@test
def test_scratches_parameters():
    b = build_all()
    res, _ = run(b.fn_mat, make_ctx(mask=(0, 0, 1, 1), vector={"Scratch Color": (1, 0, 0, 1)},
                                    scalar={"Scratch Roughness": 0.1, "Scratch Metallic": 0.0}))
    expect("custom scratch", res["MP_BASE_COLOR"], (1, 0, 0))
    expect("rough", res["MP_ROUGHNESS"], (0.1,))
    expect("metal", res["MP_METALLIC"], (0.0,))


@test
def test_function_mode_equals_inline_mode_on_random_scenarios():
    b = build_all()
    rnd = random.Random(2024)
    static_names = _all_static_names(b)
    scalar_params = [n for n, d in b.params.items.items() if d.kind == "scalar" and d.lo is not None]
    for i in range(80):
        statics = {n: rnd.random() < 0.5 for n in static_names}
        scalars = {}
        for n in rnd.sample(scalar_params, 14):
            d = b.params.items[n]
            scalars[n] = rnd.uniform(d.lo, d.hi)
        tex = {}
        for name in LAYER:
            tex[name + " Albedo"] = (rnd.random(), rnd.random(), rnd.random(), 1.0)
            tex[name + " ORMH Map"] = (rnd.random(), rnd.random(), rnd.random(), rnd.random())
            nx, ny = rnd.uniform(-.5, .5), rnd.uniform(-.5, .5)
            tex[name + " Normal Map"] = (nx, ny, math.sqrt(1 - nx * nx - ny * ny), 1.0)
        tex["Mask Texture"] = tuple(rnd.random() for _ in range(4))
        tex["Breakup Texture"] = tuple([rnd.random()] * 3 + [1.0])
        nx, ny = rnd.uniform(-.4, .4), rnd.uniform(-.4, .4)
        tex["Detail Normal Texture"] = (nx, ny, math.sqrt(1 - nx * nx - ny * ny), 1.0)
        tex["Macro Texture"] = tuple([rnd.random()] * 3 + [1.0])
        tex["Emissive Texture"] = (rnd.random(), rnd.random(), rnd.random(), 1.0)
        tex["Opacity Texture"] = (rnd.random(), 0, 0, 1.0)
        ctx = make_ctx(static=statics, scalar=scalars, texture=tex, vertex=tuple(rnd.random() for _ in range(4)),
                       uv0=(rnd.random() * 3, rnd.random() * 3), uv1=(rnd.random(), rnd.random()),
                       depth=rnd.uniform(0, 3000))
        ctx["scalar"].setdefault("Debug Mode", float(rnd.randint(1, 16)))
        a, _ = run(b.fn_mat, ctx)
        c, _ = run(b.inline_mat, ctx)
        for prop in a:
            if not close(a[prop], c[prop], 1e-9):
                raise AssertionError("scenario %d: %s differs: functions=%s inline=%s" % (i, prop, a[prop], c[prop]))
        # sanity of the actual values
        for v in a["MP_BASE_COLOR"]:
            assert math.isfinite(v), a["MP_BASE_COLOR"]        # (saturation > 1 can push a channel below 0; the GBuffer clamps it)
        assert abs(math.sqrt(sum(x * x for x in a["MP_NORMAL"])) - 1.0) < 1e-6, a["MP_NORMAL"]
        for p in ("MP_ROUGHNESS", "MP_METALLIC", "MP_AMBIENT_OCCLUSION"):
            assert -1e-9 <= a[p][0] <= 1 + 1e-9, (p, a[p])


@test
def test_every_static_permutation_family_compiles_without_errors():
    """The engine only compiles the permutations an instance uses, so sweep many combinations."""
    b = build_all()
    names = _all_static_names(b)
    rnd = random.Random(5)
    combos = [{n: True for n in names}, {n: False for n in names}]
    combos += [{n: rnd.random() < 0.5 for n in names} for _ in range(60)]
    for single in names:                                         # every switch flipped alone from the default
        combos.append({single: not b.params.items[single].default})
    for st in combos:
        ctx = make_ctx(static=st, mask=(0.4, 0.4, 0.4, 0.8), vertex=(0.3, 0.3, 0.3, 0.3))
        ctx["scalar"]["Debug Mode"] = 7.0
        run(b.fn_mat, ctx)                                       # raises CompileError on any problem


@test
def test_no_division_by_zero_or_nan_at_slider_extremes():
    b = build_all()
    scalar_params = [n for n, d in b.params.items.items() if d.kind == "scalar" and d.lo is not None]
    rnd = random.Random(11)
    statics = {n: True for n in _all_static_names(b)}
    statics["Debug View"] = False
    for _ in range(40):
        scalars = {n: rnd.choice([b.params.items[n].lo, b.params.items[n].hi]) for n in scalar_params}
        res, _ = run(b.fn_mat, make_ctx(static=statics, scalar=scalars, mask=(0.5, 0.5, 0.5, 0.5), vertex=(0.5,) * 4))
        for k, v in res.items():
            assert all(math.isfinite(x) for x in v), (k, v)


@test
def test_decal_master_settings_and_outputs():
    b = build_all()
    d = b.decal
    assert d.get_editor_property("material_domain").name == "MD_DEFERRED_DECAL"
    assert d.get_editor_property("blend_mode").name == "BLEND_TRANSLUCENT"
    assert d.get_editor_property("decal_blend_mode").name == "DBM_D_BUFFER_COLOR_NORMAL_ROUGHNESS"
    ctx = {"texture": {"Decal Color Map": (0.8, 0.6, 0.2, 0.75), "Decal Normal Map": (0.0, 0.0, 1.0, 1.0),
                       "Decal ORM Map": (1.0, 0.4, 0.2, 1.0)},
           "uv": {0: (0.5, 0.5)}, "vector": {}, "scalar": {}, "static": {}}
    res, _ = run(d, ctx)
    expect("colour", res["MP_BASE_COLOR"], (0.8, 0.6, 0.2))
    expect("opacity (contrast 1 keeps alpha)", res["MP_OPACITY"], (0.75,))
    expect("roughness", res["MP_ROUGHNESS"], (0.4,))
    expect("metallic (default 1 = as authored)", res["MP_METALLIC"], (0.2,))
    expect("normal", res["MP_NORMAL"], (0, 0, 1))
    ctx["scalar"] = {"Decal Metallic": 0.0}
    res, _ = run(d, ctx)
    expect("metallic forced off", res["MP_METALLIC"], (0.0,))
    ctx["scalar"] = {"Decal Opacity Contrast": 4.0, "Decal Opacity": 0.5}
    res, _ = run(d, ctx)
    expect("contrast + opacity", res["MP_OPACITY"], (min(1.0, (0.75 - 0.5) * 4 + 0.5) * 0.5,))
    ctx["static"] = {"Decal Use Emissive": True}
    ctx["scalar"] = {"Decal Emissive Intensity": 2.0}
    res, _ = run(d, ctx)
    expect("emissive", res["MP_EMISSIVE_COLOR"], (1.6, 1.2, 0.4))


@test
def test_decal_uv_offset_and_tiling():
    b = build_all()
    ctx = {"texture": {"Decal Color Map": lambda uv: (uv[0], uv[1], 0.0, 1.0), "Decal Normal Map": (0, 0, 1, 1),
                       "Decal ORM Map": (1, .5, 0, 1)},
           "uv": {0: (0.25, 0.5)}, "vector": {"Decal UV Offset": (0.5, 0.25, 0, 0)}, "scalar": {"Decal UV Tiling": 2.0},
           "static": {}}
    res, _ = run(b.decal, ctx)
    expect("uv", res["MP_BASE_COLOR"], (0.25 * 2 + 0.5, 0.5 * 2 + 0.25, 0.0))


def resolve_instance(inst):
    """(root material, merged overrides) of an instance, parents first so a child's value wins."""
    chain = []
    cur = inst
    while isinstance(cur, mu.MaterialInstanceConstant):
        chain.append(cur)
        cur = cur.parent
    merged = {"static": {}, "scalar": {}, "vector": {}, "texture_asset": {}}
    for i in reversed(chain):
        merged["static"].update(i.statics)
        merged["scalar"].update(i.scalars)
        merged["vector"].update({k: (v.r, v.g, v.b, v.a) for k, v in i.vectors.items()})
        merged["texture_asset"].update(i.textures)
    return cur, merged


@test
def test_demo_instances_only_set_parameters_that_exist():
    b = build_all()
    mi = [a for a in mu.REGISTRY.values() if isinstance(a, mu.MaterialInstanceConstant)]
    assert len(mi) >= 9, len(mi)
    for inst in mi:
        parent = inst.parent
        assert parent is not None, inst.path
        if resolve_instance(inst)[0] is b.decal:
            table = b.gen.define_decal_params()
        else:
            table = b.params
        for kind, store in (("scalar", inst.scalars), ("vector", inst.vectors), ("texture", inst.textures),
                            ("static", inst.statics)):
            for name in store:
                assert name in table.items, "%s sets unknown parameter '%s'" % (inst.path, name)
                assert table.items[name].kind == kind, "%s: '%s' is %s, set as %s" % (inst.path, name, table.items[name].kind, kind)


@test
def test_demo_instances_compile_with_their_textures():
    """Evaluate every demo instance: parameter overrides applied on top of the parent's defaults."""
    b = build_all()
    for inst in [a for a in mu.REGISTRY.values() if isinstance(a, mu.MaterialInstanceConstant)]:
        root, merged = resolve_instance(inst)
        ctx = dict(merged)
        ctx.update({"uv": {0: (0.31, 0.62), 1: (0.31, 0.62)}, "vertex_color": (0.4, 0.4, 0.4, 0.4), "pixel_depth": 300.0})
        run(root, ctx)         # raises CompileError for e.g. a texture with the wrong compression for its sampler


@test
def test_texture_assets_have_correct_import_settings():
    b = build_all()
    for path, tex in mu.REGISTRY.items():
        if not isinstance(tex, mu.Texture2D):
            continue
        tc = tex.get_editor_property("compression_settings").name
        srgb = tex.get_editor_property("srgb")
        if tc in ("TC_NORMALMAP", "TC_MASKS"):
            assert srgb is False, "%s: %s must not be sRGB" % (path, tc)
        assert tex.saved, path


@test
def test_graph_has_no_dead_nodes():
    """Every non-comment expression must feed (directly or not) a material output / function output."""
    b = build_all()

    def dead(owner, roots):
        seen = set()
        stack = list(roots)
        while stack:
            e = stack.pop()
            if id(e) in seen:
                continue
            seen.add(id(e))
            for link in e.inputs:
                if link is not None:
                    stack.append(link[0])
        return [e for e in owner.expressions if id(e) not in seen and e._short != "Comment"]

    for mat in (b.fn_mat, b.inline_mat, b.decal):
        roots = [src for src, _ in mat.property_links.values()]
        d = dead(mat, roots)
        assert not d, "%s has unused nodes: %s" % (mat.path, d[:6])
    for fn in [a for a in mu.REGISTRY.values() if isinstance(a, mu.MaterialFunction)]:
        d = dead(fn, fn.function_outputs())
        assert not d, "%s has unused nodes: %s" % (fn.path, d[:6])


# ------------------------------------------------------------------------------ review round 2: behaviour fixes
def bare_ctx(mask=None, **kw):
    """make_ctx WITHOUT texture / tint overrides, so every parameter keeps its DEFAULT (placeholder textures, white tints)."""
    ctx = make_ctx(**kw)
    ctx["texture"] = {}
    ctx["vector"] = {}
    if mask is not None:
        ctx["texture"]["Mask Texture"] = tuple(mask)
    return ctx


def _lum(c):
    return 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]


@test
def test_layer_rotation_rotates_the_normal_with_the_uvs():
    """Review B1: rotating a layer's UVs must rotate its tangent-space normal back, or bumps are lit from the wrong side."""
    b = build_all()
    n = (0.4, 0.0, math.sqrt(1 - 0.16))
    for deg in (0.0, 30.0, 90.0, 180.0, 270.0):
        t = math.radians(deg)
        want = normalize((math.cos(t) * n[0] + math.sin(t) * n[1], -math.sin(t) * n[0] + math.cos(t) * n[1], n[2]))
        for mat in (b.fn_mat, b.inline_mat):
            res, _ = run(mat, make_ctx(texture={"Base Normal Map": n + (1.0,)}, scalar={"Base Rotation": deg}))
            expect("rotated normal at %g deg" % deg, res["MP_NORMAL"], want, 1e-6)


@test
def test_rotated_layer_normal_matches_the_height_field_that_is_displayed():
    """Independent check: finite differences of the texture lookup the shader really performs give the surface normal."""
    b = build_all()
    A, K = 0.02, 3.0

    def height(u):
        return A * math.sin(2 * math.pi * K * u)

    def normal_tex(uv):                                   # unpacked tangent-space normal of `height` at a texture position
        gx = A * 2 * math.pi * K * math.cos(2 * math.pi * K * uv[0])
        return normalize((-gx, 0.0, 1.0)) + (1.0,)

    for deg in (0.0, 45.0, 90.0, 135.0, 200.0):
        t = math.radians(deg)
        c, s = math.cos(t), math.sin(t)

        def shown(p):                                     # height of the surface point p once the layer is rotated about (.5,.5)
            q = (p[0] - 0.5, p[1] - 0.5)
            return height(q[0] * c - q[1] * s + 0.5)

        p0, e = (0.37, 0.61), 1e-6
        gx = (shown((p0[0] + e, p0[1])) - shown((p0[0] - e, p0[1]))) / (2 * e)
        gy = (shown((p0[0], p0[1] + e)) - shown((p0[0], p0[1] - e))) / (2 * e)
        want = normalize((-gx, -gy, 1.0))
        res, _ = run(b.fn_mat, make_ctx(texture={"Base Normal Map": normal_tex}, scalar={"Base Rotation": deg}, uv0=p0, uv1=p0))
        expect("normal of the displayed pattern at %g deg" % deg, res["MP_NORMAL"], want, 2e-4)


@test
def test_every_parameter_description_is_complete_in_the_tooltip():
    """Review B2: the old tooltip kept only the first sentence, which dropped most import instructions."""
    b = build_all()
    need = {"SAMPLERTYPE_NORMAL": "Normalmap", "SAMPLERTYPE_MASKS": "Masks", "SAMPLERTYPE_COLOR": "sRGB"}
    for table in (b.params, b.gen.define_decal_params()):
        for name in table.order:
            d = table.items[name]
            assert len(d.desc) <= b.gen.DESC_LIMIT, "%s: description is %d characters (limit %d)" % (name, len(d.desc), b.gen.DESC_LIMIT)
            assert b.gen.short_desc(d.desc) == d.desc, name
            if d.kind == "texture":
                assert need[d.sampler] in d.desc, "%s does not say how to import the texture" % name
    # and what is on the node is exactly that text
    for e in b.fn_mat.expressions:
        n = e._props.get("parameter_name")
        if n:
            assert e._props.get("desc") == b.params.items[n].desc, n


@test
def test_function_pins_explain_themselves():
    """Every Function Input / Output has a hover text (the five functions are meant to be read in the editor)."""
    b = build_all()
    n = 0
    for path, fn in mu.REGISTRY.items():
        if not isinstance(fn, mu.MaterialFunction):
            continue
        for e in fn.expressions:
            if e._short in ("FunctionInput", "FunctionOutput"):
                text = e.get_editor_property("description")
                name = e.get_editor_property("input_name" if e._short == "FunctionInput" else "output_name")
                assert text and len(text) <= 100, "%s pin %s has no usable description: %r" % (path, name, text)
                n += 1
    assert n >= 60, n


@test
def test_scalar_defaults_are_inside_their_slider_range():
    b = build_all()
    for table in (b.params, b.gen.define_decal_params()):
        for name, d in table.items.items():
            if d.kind == "scalar":
                assert d.lo is not None and d.lo <= d.default <= d.hi, (name, d.lo, d.default, d.hi)


@test
def test_tints_default_to_white_and_empty_layers_show_their_placeholder_colour():
    """Review D1: a texture you assign must show as authored; an EMPTY layer still shows its own colour."""
    b = build_all()
    for key, label, group, colour in b.gen.LAYERS:
        assert b.params.items[label + " Tint"].default == (1.0, 1.0, 1.0, 1.0), label

    def shows(label, **kw):
        res, _ = run(b.fn_mat, bare_ctx(**kw))
        return res["MP_BASE_COLOR"]

    cases = {"Base": {}, "Wear": {"mask": (1, 0, 0, 1)}, "Dirt": {"mask": (0, 1, 0, 1)},
             "Vertex 1": {"vertex": (0.0, 1, 1, 1)},
             "Vertex 2": {"vertex": (1, 0.0, 1, 1), "static": {"Use Vertex Layer 2": True}},
             "Vertex 3": {"vertex": (1, 1, 0.0, 1), "static": {"Use Vertex Layer 3": True}}}
    seen = {}
    for key, label, group, colour in b.gen.LAYERS:
        got = shows(label, **cases[label])
        expect("%s placeholder colour" % label, got, colour, 0.01)
        seen[label] = got
    labels = list(seen)
    for i, a in enumerate(labels):
        for c in labels[i + 1:]:
            assert math.dist(seen[a], seen[c]) > 0.1, "%s and %s look the same when empty" % (a, c)


@test
def test_breakup_noise_channels_drive_different_effects():
    """Review D7: R = wear edges, G = dirt edges, B = scratches and vertex paint."""
    b = build_all()
    sc = {"Wear Softness": 0.02, "Wear Breakup": 1.0, "Wear Height Influence": 0.0,
          "Dirt Softness": 0.02, "Dirt Breakup": 1.0, "Dirt Height Influence": 0.0, "Dirt AO Boost": 0.0}
    tex = {"Breakup Texture": (0.9, 0.1, 0.5, 1.0)}
    wear = _weight_via_debug(b.fn_mat, 7, mask=(0.5, 0.5, 0.5, 1), texture=tex, scalar=sc)
    dirt = _weight_via_debug(b.fn_mat, 8, mask=(0.5, 0.5, 0.5, 1), texture=tex, scalar=sc)
    assert wear > 0.9 and dirt < 0.1, (wear, dirt)               # R bright -> wear first, G dark -> dirt last
    tex_b = {"Breakup Texture": (0.1, 0.1, 0.9, 1.0)}
    scr = _weight_via_debug(b.fn_mat, 9, mask=(0, 0, 0.5, 1), texture=tex_b, scalar={"Scratch Softness": 0.02, "Scratch Breakup": 1.0})
    vtx = _weight_via_debug(b.fn_mat, 10, vertex=(0.5, 1, 1, 1), texture=tex_b,
                            scalar={"Vertex 1 Softness": 0.02, "Vertex 1 Breakup": 1.0, "Vertex 1 Height Influence": 0.0})
    assert scr > 0.9 and vtx > 0.9, (scr, vtx)                    # B bright -> scratches and vertex paint first
    ctx = make_ctx(static={"Debug View": True}, scalar={"Debug Mode": 15.0}, texture={"Breakup Texture": (0.2, 0.4, 0.6, 1.0)})
    res, _ = run(b.fn_mat, ctx)
    expect("debug 15 shows the three channels", res["MP_EMISSIVE_COLOR"], (0.2, 0.4, 0.6))


@test
def test_invert_blends_instead_of_folding_at_half():
    """Review D8: the old |Invert - mask| folded the mask when Invert was dragged to 0.5."""
    b = build_all()
    sc = {"Wear Invert": 0.5, "Wear Height Influence": 0.0, "Wear Breakup": 0.0}
    ws = [_weight_via_debug(b.fn_mat, 7, mask=(m, 0, 0, 1), scalar=sc) for m in (0.1, 0.5, 0.9)]
    assert max(ws) - min(ws) < 1e-9, ws                          # lerp(m, 1-m, 0.5) = 0.5 for every mask value
    assert abs(ws[0] - 0.5) < 1e-6, ws


@test
def test_debug_mode_and_opacity_uv_choice_snap_to_whole_numbers():
    b = build_all()
    mask = (0.1, 0.2, 0.3, 0.4)
    assert abs(_weight_via_debug(b.fn_mat, 2.4, mask=mask) - 0.2) < 1e-9        # 2.4 -> view 2
    assert abs(_weight_via_debug(b.fn_mat, 2.6, mask=mask) - 0.3) < 1e-9        # 2.6 -> view 3
    tex = {"Opacity Texture": lambda uv: (uv[0], 0, 0, 1)}
    for value, want in ((0.4, 0.6), (0.6, 0.2)):                                 # 0.4 -> unique UV, 0.6 -> tiling UV
        res, _ = run(b.fn_mat, make_ctx(static={"Use Opacity Mask": True}, scalar={"Opacity Uses Tiling UV": value},
                                        texture=tex, uv0=(0.2, 0.2), uv1=(0.6, 0.6)))
        expect("opacity uv %.1f" % value, res["MP_OPACITY_MASK"], (want,))


def _variation_factors(b, **kw):
    """(brightness, saturation) factors the instance variation applied, recovered from the output colour."""
    base = LAYER["Base"]["albedo"]
    ctx = make_ctx(static={"Use Instance Variation": True}, **kw)
    res, _ = run(b.fn_mat, ctx)
    return _factors_from(res["MP_BASE_COLOR"], base)


def _factors_from(out, base):
    lum_base = _lum(base)
    bri = _lum(out) / lum_base
    sat = ((out[0] / bri) - lum_base) / (base[0] - lum_base)
    return bri, sat


@test
def test_instance_variation_is_bounded_uniform_and_independent():
    """Review D6: no extreme look at the world origin, brightness and saturation independent, ISM/HISM instances differ."""
    b = build_all()
    base = LAYER["Base"]["albedo"]
    origin = make_ctx(static={"Use Instance Variation": True})
    origin["object_pos"] = (0.0, 0.0, 0.0)
    bri, sat = _factors_from(run(b.fn_mat, origin)[0]["MP_BASE_COLOR"], base)
    assert bri > 0.86 and sat > 0.86 or bri > 0.86 or sat > 0.86, (bri, sat)
    assert not (abs(bri - 0.85) < 0.005 and abs(sat - 0.85) < 0.005), (bri, sat)       # the old hash gave exactly (0.85, 0.85) here
    rnd = random.Random(1)
    pts = []
    for _ in range(300):
        ctx = make_ctx(static={"Use Instance Variation": True})
        ctx["object_pos"] = (rnd.uniform(-5000, 5000), rnd.uniform(-5000, 5000), 0.0)
        pts.append(_factors_from(run(b.fn_mat, ctx)[0]["MP_BASE_COLOR"], base))
    bs, ss = [p[0] for p in pts], [p[1] for p in pts]
    for v in bs + ss:
        assert 0.85 - 1e-6 <= v <= 1.15 + 1e-6, v                                      # +-15% as the sliders say
    mb, ms = sum(bs) / len(bs), sum(ss) / len(ss)
    cov = sum((x - mb) * (y - ms) for x, y in pts) / len(pts)
    corr = cov / math.sqrt(sum((x - mb) ** 2 for x in bs) / len(bs) * sum((y - ms) ** 2 for y in ss) / len(ss))
    assert abs(corr) < 0.2, "brightness and saturation are correlated: %.2f" % corr
    hist = [0] * 4
    for x in bs:
        hist[min(3, int((x - 0.85) / 0.30 * 4))] += 1
    assert min(hist) > 0.15 * len(bs), hist                                            # roughly uniform
    # the seed re-rolls everything, and instances of one HISM (same object position) differ through PerInstanceRandom
    assert _variation_factors(b) != _variation_factors(b, scalar={"Variation Seed": 5.0})
    a, c = make_ctx(static={"Use Instance Variation": True}), make_ctx(static={"Use Instance Variation": True})
    c["per_instance_random"] = 0.37
    assert run(b.fn_mat, a)[0]["MP_BASE_COLOR"] != run(b.fn_mat, c)[0]["MP_BASE_COLOR"]


def _consumed_outputs(mat, call):
    names = set()
    for e in mat.expressions:
        for link in e.inputs:
            if link is not None and link[0] is call:
                names.add(call.output_names()[link[1]])
    for _, (src, idx) in mat.property_links.items():
        if src is call:
            names.add(call.output_names()[idx])
    return names


@test
def test_scratches_do_not_build_no_op_normal_and_ao_blends():
    """Review D10: the scratch layer reuses the normal and AO of the stack below, so those outputs must stay unused."""
    b = build_all()
    calls = [e for e in b.fn_mat.expressions if e._short == "MaterialFunctionCall"
             and e.function.path.endswith("MF_LayerBlend")]
    scratch = []
    for c in calls:
        link = c.inputs[c.input_names().index("UseLayer")]
        if link is not None and link[0]._props.get("parameter_name") == "Use Scratches":
            scratch.append(c)
    assert len(scratch) == 1, scratch
    assert _consumed_outputs(b.fn_mat, scratch[0]) == {"Color", "Roughness", "Metallic"}, _consumed_outputs(b.fn_mat, scratch[0])
    assert len(calls) == 6, len(calls)               # wear, vertex 1-3, dirt, scratches


@test
def test_preview_switch_lives_only_on_the_demo_parent():
    """Review D2: duplicating a demo for a real two-UV mesh must not carry the single-UV preview hack along."""
    b = build_all()
    assert b.params.items["Mask Uses Tiling UV"].default is False
    insts = {i.path.split("/")[-1]: i for i in mu.REGISTRY.values() if isinstance(i, mu.MaterialInstanceConstant)}
    base = insts["MI_Demo_Base"]
    assert base.parent is b.fn_mat and base.statics.get("Mask Uses Tiling UV") is True
    for name, inst in insts.items():
        if name != "MI_Demo_Base":
            assert "Mask Uses Tiling UV" not in inst.statics, name
    surface = [n for n in insts if n.startswith("MI_Demo_") and "Decal" not in n and n != "MI_Demo_Base"]
    assert len(surface) >= 5, surface
    for name in surface:
        root, merged = resolve_instance(insts[name])
        assert root is b.fn_mat and insts[name].parent is base, name
        assert merged["static"]["Mask Uses Tiling UV"] is True, name


@test
def test_the_three_crate_instances_look_clearly_different():
    """The assignment wants at least three visibly different instances; compare their colours on plain and worn/dirty pixels."""
    b = build_all()
    insts = {i.path.split("/")[-1]: i for i in mu.REGISTRY.values() if isinstance(i, mu.MaterialInstanceConstant)}
    names = ["MI_Demo_Crate_Red", "MI_Demo_Crate_Blue", "MI_Demo_Crate_Cream_Weathered"]
    for mask in ((0.0, 0.0, 0.0, 1.0), (0.9, 0.0, 0.0, 1.0)):
        shown = {}
        for n in names:
            root, merged = resolve_instance(insts[n])
            ctx = dict(merged)
            ctx.update({"uv": {0: (0.31, 0.62), 1: (0.31, 0.62)}, "vertex_color": (1, 1, 1, 1), "pixel_depth": 300.0,
                        "texture": {"Mask Texture": mask, "Breakup Texture": (0.5, 0.5, 0.5, 1.0)}})
            shown[n] = run(root, ctx)[0]["MP_BASE_COLOR"]
        for i, a in enumerate(names):
            for c in names[i + 1:]:
                if mask[0] > 0.5 and "Cream" in c:
                    continue                                   # red and cream both show rust under the paint, by design
                assert math.dist(shown[a], shown[c]) > 0.12, (mask, a, c, shown[a], shown[c])


@test
def test_script_only_mentions_documentation_files_that_exist():
    b = build_all()
    import re
    text = open(SCRIPT, encoding="utf-8").read()
    for ref in set(re.findall(r"Docs/\d\d_\w+\.md", text)):
        assert os.path.exists(os.path.join(ROOT, ref)), "the script points to %s, which does not exist" % ref


def _load_tool(rel):
    spec = importlib.util.spec_from_file_location(os.path.basename(rel)[:-3], os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@test
def test_pack_channels_tool_packs_orm_height_and_masks():
    try:
        from PIL import Image
    except ImportError:
        return
    import tempfile
    pc = _load_tool("Tools/pack_channels.py")
    with tempfile.TemporaryDirectory() as d:
        ao, gloss, h16 = (os.path.join(d, n) for n in ("ao.png", "gloss.png", "h16.png"))
        Image.new("L", (8, 8), 200).save(ao)
        g = Image.new("L", (16, 16))
        g.putdata([x * 16 for x in range(16)] * 16)
        g.save(gloss)
        Image.new("I;16", (4, 4), 40000).save(h16)                      # 16-bit height: scaled, not clipped
        im = pc.pack({"r": ao, "g": gloss, "b": 0.0, "a": h16}, invert=("g",))
        assert im.mode == "RGBA" and im.size == (16, 16)               # everything scaled to the biggest input
        assert im.getpixel((0, 0)) == (200, 255, 0, 156), im.getpixel((0, 0))     # glossiness 0 -> roughness 255
        assert im.getpixel((15, 0)) == (200, 15, 0, 156), im.getpixel((15, 0))
        out = os.path.join(d, "mask.png")
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):                  # the tool prints a "wrote ..." line
            assert pc.main(["--r", "1", "--g", "0.5", "--b", "0", "--a", ao, "--size", "4", "-o", out]) == 0
        px = Image.open(out)
        assert px.size == (4, 4) and px.getpixel((1, 1)) == (255, 128, 0, 200), px.getpixel((1, 1))
        try:
            pc.pack({"r": ao})
        except ValueError as exc:
            assert "G, B, A" in str(exc), exc
        else:
            raise AssertionError("missing channels must be reported")


# ------------------------------------------------------------------------------ robustness tests
# These re-install the fake engine, so they run after everything that uses the cached build.
def _fresh_main(**flags):
    gen = load_generator()
    for k, v in flags.items():
        setattr(gen, k, v)
    gen.main()
    mat = mu.REGISTRY[gen.ROOT_PATH + "/" + gen.SURFACE_MASTER_NAME]
    return gen, mat


def _quick_numbers(mat):
    out = {}
    for name, ctx in (("plain", make_ctx()),
                      ("wear+dirt", make_ctx(mask=(0.7, 0.4, 0.2, 0.6))),
                      ("painted", make_ctx(vertex=(0.2, 0.9, 0.9, 0.3), mask=(0.1, 0.1, 0.0, 0.8),
                                           static={"Use Vertex Alpha Dirt": True}))):
        res, _ = run(mat, ctx)
        out[name] = res
    return out


def _same(a, b):
    for k in a:
        for prop in a[k]:
            if not close(a[k][prop], b[k][prop], 1e-9):
                return False, (k, prop, a[k][prop], b[k][prop])
    return True, None


@test
def zz_test_png_writer_roundtrip_with_optional_pillow():
    try:
        from PIL import Image
    except ImportError:
        return
    import io
    gen = load_generator()
    data = bytes([10, 20, 30, 255] * 4 + [200, 100, 50, 128] * 4)
    im = Image.open(io.BytesIO(gen.png_bytes(4, 2, data)))
    assert im.size == (4, 2) and im.mode == "RGBA" and im.getpixel((0, 0)) == (10, 20, 30, 255)


@test
def zz_test_runs_without_demo_content():
    gen, mat = _fresh_main(CREATE_DEMO_TEXTURES=False, CREATE_DEMO_INSTANCES=True)
    assert not [a for a in mu.REGISTRY.values() if isinstance(a, mu.MaterialInstanceConstant)]
    run(mat, make_ctx())


@test
def zz_test_inline_mode_via_main():
    ref = _quick_numbers(_fresh_main(USE_MATERIAL_FUNCTIONS=True)[1])
    gen, mat = _fresh_main(USE_MATERIAL_FUNCTIONS=False)
    assert not [k for k in mu.REGISTRY if "/Functions/" in k], "inline mode must not create function assets"
    ok, why = _same(ref, _quick_numbers(mat))
    assert ok, why


@test
def zz_test_works_without_get_material_expression_input_names():
    """Older engines lack this helper: the fallback pin table must cover every pin the generator uses."""
    ref = _quick_numbers(_fresh_main()[1])
    cls = mu.MaterialEditingLibrary
    saved = cls.__dict__["get_material_expression_input_names"]
    delattr(cls, "get_material_expression_input_names")
    try:
        for flag in (True, False):
            gen, mat = _fresh_main(USE_MATERIAL_FUNCTIONS=flag)
            assert not [m for l, m in mu.LOG if l in ("error", "warning")], mu.LOG
            ok, why = _same(ref, _quick_numbers(mat))
            assert ok, (flag, why)
    finally:
        setattr(cls, "get_material_expression_input_names", saved)


@test
def zz_test_texture_channel_outputs_missing_falls_back_to_rgba_mask():
    ref = _quick_numbers(_fresh_main()[1])
    keep = [o for o in mu.TEX_OUTS if o[0] in ("RGB", "RGBA")]
    saved = {k: mu.PINS[k] for k in ("TextureSample", "TextureSampleParameter2D")}
    for k in saved:
        mu.PINS[k] = (saved[k][0], keep)
    try:
        gen, mat = _fresh_main()
        warns = [m for l, m in mu.LOG if l == "warning"]
        assert warns and all("ComponentMask" in w for w in warns), warns[:2]
        ok, why = _same(ref, _quick_numbers(mat))
        assert ok, why
    finally:
        for k, v in saved.items():
            mu.PINS[k] = v


@test
def zz_test_function_call_failure_falls_back_to_inline():
    ref = _quick_numbers(_fresh_main(USE_MATERIAL_FUNCTIONS=False)[1])
    orig = mu.ExpressionBase.set_material_function
    mu.ExpressionBase.set_material_function = lambda self, fn: False
    mu.PROPERTY_REFRESHES_CALL_NODE[0] = False        # ... and assigning the property does not create the pins either
    try:
        gen, mat = _fresh_main(USE_MATERIAL_FUNCTIONS=True)
        assert any("Function-based build failed" in m for l, m in mu.LOG if l == "error")
        assert any("built in 'inline' mode" in m for _, m in mu.LOG)
        ok, why = _same(ref, _quick_numbers(mat))
        assert ok, why
    finally:
        mu.ExpressionBase.set_material_function = orig
        mu.PROPERTY_REFRESHES_CALL_NODE[0] = True


@test
def zz_test_prune_failure_is_not_fatal():
    ref = _quick_numbers(_fresh_main()[1])
    orig = mu.MaterialEditingLibrary.__dict__["delete_material_expression"]

    def boom(cls, *a, **k):
        raise mu.UnrealError("delete not allowed")
    mu.MaterialEditingLibrary.delete_material_expression = classmethod(boom)
    try:
        gen, mat = _fresh_main(USE_MATERIAL_FUNCTIONS=False)
        assert any("Could not delete an unused node" in m for l, m in mu.LOG if l == "warning")
        ok, why = _same(ref, _quick_numbers(mat))
        assert ok, why
    finally:
        mu.MaterialEditingLibrary.delete_material_expression = orig


@test
def zz_test_rerun_is_idempotent_and_keeps_user_work():
    gen = load_generator()
    gen.main()
    n_assets = len(mu.REGISTRY)
    inst = mu.REGISTRY[gen.INSTANCES_PATH + "/MI_Demo_Crate_Red"]
    inst.scalars["Wear Intensity"] = 0.123                      # a "user edit"
    tex = mu.REGISTRY[gen.TEXTURES_PATH + "/T_MM_Demo_Mask"]
    tex.set_editor_property("srgb", False)
    tex.rgba = b"user data"                                      # user replaced the image
    first = _quick_numbers(mu.REGISTRY[gen.ROOT_PATH + "/" + gen.SURFACE_MASTER_NAME])
    mu.LOG.clear()
    gen.main()
    assert len(mu.REGISTRY) == n_assets, "re-run created extra assets"
    assert inst.scalars["Wear Intensity"] == 0.123, "instance was overwritten"
    assert tex.rgba == b"user data", "user texture was overwritten"
    mat = mu.REGISTRY[gen.ROOT_PATH + "/" + gen.SURFACE_MASTER_NAME]
    ok, why = _same(first, _quick_numbers(mat))
    assert ok, why
    assert not [m for l, m in mu.LOG if l in ("error", "warning")], mu.LOG
    names = [e._props["parameter_name"] for e in mat.expressions if e._props.get("parameter_name")]
    assert len(names) == len(set(names)), "duplicate parameter nodes after re-run"


@test
def zz_test_function_mode_survives_a_missing_set_material_function():
    """Review A: when the helper does not exist, assigning the property creates the call node's pins instead."""
    ref = _quick_numbers(_fresh_main()[1])

    def missing(self, fn):
        raise AttributeError("'MaterialExpressionMaterialFunctionCall' object has no attribute 'set_material_function'")
    orig = mu.ExpressionBase.set_material_function
    mu.ExpressionBase.set_material_function = missing
    try:
        gen, mat = _fresh_main(USE_MATERIAL_FUNCTIONS=True)
        assert any("built in 'functions' mode" in m for _, m in mu.LOG), mu.LOG[-5:]
        warns = [m for l, m in mu.LOG if l == "warning"]
        assert len(warns) == 1 and "set_material_function is not available" in warns[0], warns
        ok, why = _same(ref, _quick_numbers(mat))
        assert ok, why
    finally:
        mu.ExpressionBase.set_material_function = orig


@test
def zz_test_instances_survive_setters_that_return_false():
    """Review A2 / Epic UE-291403: the setters apply the value but return False; that must not look like an error."""
    mu.SETTERS_RETURN_FALSE[0] = True
    try:
        gen = load_generator()
        gen.main()
        bad = [(l, m) for l, m in mu.LOG if l in ("warning", "error")]
        assert not bad, bad[:3]
        inst = mu.REGISTRY[gen.INSTANCES_PATH + "/MI_Demo_Crate_Red"]
        assert inst.scalars["Wear Intensity"] == 1.1 and "Base Tint" in inst.vectors
        assert mu.REGISTRY[gen.INSTANCES_PATH + "/MI_Demo_Base"].statics["Mask Uses Tiling UV"] is True
    finally:
        mu.SETTERS_RETURN_FALSE[0] = False


@test
def zz_test_instance_with_a_misspelled_parameter_is_reported():
    gen = load_generator()
    gen.main()
    master = mu.REGISTRY[gen.ROOT_PATH + "/" + gen.SURFACE_MASTER_NAME]
    mu.LOG.clear()
    inst = gen.make_instance("MI_Typo", master, scalars={"Wear Intensty": 1.0, "Wear Intensity": 0.5},
                             statics={"Use Wear Layr": True})
    warns = [m for l, m in mu.LOG if l == "warning"]
    assert len(warns) == 2 and any("Wear Intensty" in w for w in warns) and any("Use Wear Layr" in w for w in warns), warns
    assert inst.scalars == {"Wear Intensity": 0.5}, inst.scalars


@test
def zz_test_vertex_alpha_not_exposed_degrades_gracefully():
    """If the engine will not hand out the vertex-colour alpha, only the bonus 'alpha dirt' is lost - not the build."""
    saved = mu.PINS["VertexColor"]
    mu.PINS["VertexColor"] = (saved[0], [("", 3)])
    try:
        for flag in (True, False):
            gen, mat = _fresh_main(USE_MATERIAL_FUNCTIONS=flag)
            warns = [m for l, m in mu.LOG if l == "warning"]
            assert len(warns) == 1 and "Vertex Color alpha" in warns[0], warns
            assert not [m for l, m in mu.LOG if l == "error"]
            res, _ = run(mat, make_ctx(vertex=(0.0, 1, 1, 1)))
            expect("vertex layer 1 still paints", res["MP_BASE_COLOR"], LAYER["Vertex 1"]["albedo"])
            res, _ = run(mat, make_ctx(vertex=(1, 1, 1, 0.0), static={"Use Vertex Alpha Dirt": True}))
            expect("alpha dirt is inert", res["MP_BASE_COLOR"], LAYER["Base"]["albedo"])
    finally:
        mu.PINS["VertexColor"] = saved


@test
def zz_test_preview_value_type_differs_between_engine_versions():
    """Review A1 residual: where FunctionInput.preview_value is a double Vector4, assigning a Vector4f fails -> use Vector4."""
    info = mu.FACTS["classes"]["MaterialExpressionFunctionInput"]["props"]["preview_value"]
    saved = info["type"]
    info["type"] = "Vector4"
    try:
        gen, mat = _fresh_main()
        assert any("built in 'functions' mode" in m for _, m in mu.LOG)
        fn = mu.REGISTRY[gen.FUNCTIONS_PATH + "/MF_TilingLayer"]
        values = [e.get_editor_property("preview_value") for e in fn.function_inputs()
                  if e.get_editor_property("use_preview_value_as_default")]
        assert values and all(isinstance(v, mu.Vector4) for v in values), values
        assert not [m for l, m in mu.LOG if l in ("warning", "error")], mu.LOG
    finally:
        info["type"] = saved


@test
def zz_test_temporary_texture_files_are_removed_after_a_run():
    import glob
    import tempfile
    before = set(glob.glob(os.path.join(tempfile.gettempdir(), "mm_tex_*")))
    gen = load_generator()
    gen.main()
    after = set(glob.glob(os.path.join(tempfile.gettempdir(), "mm_tex_*")))
    assert after <= before, "left behind: %s" % sorted(after - before)[:3]
    assert gen._TEMP_PATHS == []


@test
def zz_test_fix_texture_settings_script_reads_the_names():
    mu.install()
    fts = _load_tool("Scripts/fix_texture_settings.py")
    T = mu.ENUMS["TextureCompressionSettings"]

    def make(name, comp=None, srgb=True):
        tex = mu.Texture2D("/Game/MyTex/" + name, 4, 4, bytes(64))
        tex.set_editor_property("compression_settings", comp or T.TC_DEFAULT)
        tex.set_editor_property("srgb", srgb)
        mu.REGISTRY[tex.path] = tex
        return tex

    assert [fts.classify(n) for n in ("T_Brick_A", "Brick_Normal_4k", "T_Rock_NormalGL", "T_Crate_ORMH_01", "T_Whatever")] == \
        [("color", False), ("normal", False), ("normal", True), ("masks", False), (None, False)]
    albedo = make("T_Brick_A", T.TC_MASKS, False)               # wrong on purpose
    normal = make("T_Brick_N_01")                               # default import of a normal map
    orm = make("T_Brick_ORMH_2k")
    gl = make("T_Rock_NormalGL")
    fine = make("T_Done_A")                                     # already right
    odd = make("T_Whatever", T.TC_MASKS, False)
    fts.FOLDER = "/Game/MyTex"
    fts.DRY_RUN = True
    assert fts.main() == 4 and albedo.get_editor_property("srgb") is False and not albedo.saved       # dry run touches nothing
    fts.DRY_RUN = False
    assert fts.main() == 4
    assert albedo.get_editor_property("compression_settings") is T.TC_DEFAULT and albedo.get_editor_property("srgb") is True
    assert normal.get_editor_property("compression_settings") is T.TC_NORMALMAP and normal.get_editor_property("srgb") is False
    assert orm.get_editor_property("compression_settings") is T.TC_MASKS and orm.get_editor_property("srgb") is False
    assert gl.get_editor_property("flip_green_channel") is True and normal.get_editor_property("flip_green_channel") is False
    assert fine.saved is False and odd.get_editor_property("compression_settings") is T.TC_MASKS     # untouched
    assert fts.main() == 0, "a second run has nothing left to change"
    mu.SELECTED_ASSETS[:] = [make("T_Other_N")]                 # the Content Browser selection wins over FOLDER
    try:
        assert fts.main() == 1
    finally:
        mu.SELECTED_ASSETS[:] = []
    assert not [m for l, m in mu.LOG if l in ("warning", "error")], mu.LOG


# ------------------------------------------------------------------------------ runner
def main():
    only = sys.argv[1:]
    fails = 0
    for fn in TESTS:
        if only and not any(o in fn.__name__ for o in only):
            continue
        try:
            fn()
            print("PASS  %s" % fn.__name__)
        except Exception as exc:                                   # noqa: BLE001
            fails += 1
            print("FAIL  %s\n      %s: %s" % (fn.__name__, type(exc).__name__, exc))
            if os.environ.get("MM_TRACE"):
                traceback.print_exc()
    print("\n%d tests, %d failed" % (len([t for t in TESTS if not only or any(o in t.__name__ for o in only)]), fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
