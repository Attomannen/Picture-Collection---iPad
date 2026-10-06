"""
================================================================================
 MASTER MATERIAL GENERATOR  -  Unreal Engine 5.x  (Python Editor Script)
================================================================================
 Builds, inside your Unreal project, a complete layered "Master Material" with
 support for:

   * two UV sets      UV0 = tiling / texel density     UV1 = unique (RGB masks)
   * an RGB(A) mask   R = Wear   G = Dirt   B = Scratches   A = baked AO
   * tiling PBR layers (Base, Wear, Dirt) + 3 vertex-paintable layers (R/G/B)
   * height-aware blending (crisp, organic edges instead of blurry fades)
   * detail normal, macro variation, instance variation, wetness, emissive,
     opacity mask, debug views, mesh-decal master material

 HOW TO RUN
   1. Edit > Plugins > enable "Python Editor Script Plugin", restart the editor.
   2. Tools > Execute Python Script...  (UE 4.x: File > Execute Python Script)
      and pick this file.   (or: Output Log, switch to "Cmd" and type
      py "C:/full/path/to/build_master_material.py" )
   3. Open  /Game/MasterMaterial/  in the Content Browser.

 The script is idempotent: running it again rebuilds the master materials and
 the function library (your existing instances keep their settings because
 parameters are matched by name) and never overwrites textures you replaced.

 Everything the script creates lives under ROOT_PATH. Read the sections in
 order - the file is meant to be read as well as run:

   1. configuration
   2. small helpers (logging, enum/class lookup, pin-name resolution)
   3. the graph-building mini-DSL  (Graph / V)   <- how nodes get created
   4. parameter table               <- every parameter, group, default, tooltip
   5. reusable blocks               <- the Material Functions (also usable inline)
   6. the surface master            <- the big graph, section by section
   7. the mesh-decal master
   8. default / demo textures       <- generated procedurally, no external files
   9. demo material instances
  10. main()

 Documentation:  see ../README.md and ../Docs/
================================================================================
"""
import math
import os
import struct
import tempfile
import traceback
import zlib

try:
    import unreal
except ImportError:                       # allows importing this file in plain Python (docs / tests)
    unreal = None


# ==============================================================================
# 1. CONFIGURATION  (safe to edit)
# ==============================================================================
ROOT_PATH = "/Game/MasterMaterial"
SURFACE_MASTER_NAME = "M_Master_Surface"
DECAL_MASTER_NAME = "M_Master_MeshDecal"

# True : the master is a tidy graph of Material Function calls (recommended, easier to read).
# False: every function is expanded inline (bigger graph, zero asset dependencies).
# If creating/using functions fails for any reason the script automatically retries inline.
USE_MATERIAL_FUNCTIONS = True

CREATE_DEFAULT_TEXTURES = True    # tiny flat placeholder textures the parameters default to
CREATE_DEMO_TEXTURES = True       # procedural paint / rust / dirt / brick / plaster + a demo mask
CREATE_DEMO_INSTANCES = True      # MI_Demo_* material instances using the demo textures
OVERWRITE_EXISTING_TEXTURES = False   # never replace textures you may have swapped yourself

FUNCTIONS_PATH = ROOT_PATH + "/Functions"
TEXTURES_PATH = ROOT_PATH + "/Textures"
INSTANCES_PATH = ROOT_PATH + "/Instances"

TAG = "[MasterMaterial] "


# ==============================================================================
# 2. SMALL HELPERS
# ==============================================================================
class BuildError(Exception):
    """Anything that stops the build; the message says what to look at."""


def log(msg):
    unreal.log(TAG + str(msg))


def warn(msg):
    unreal.log_warning(TAG + str(msg))


def err(msg):
    unreal.log_error(TAG + str(msg))


def enum(enum_name, member):
    """unreal.<enum_name>.<member> with a readable error if this UE version lacks it."""
    e = getattr(unreal, enum_name, None)
    m = getattr(e, member, None) if e is not None else None
    if m is None:
        raise BuildError("This Unreal version has no unreal.%s.%s" % (enum_name, member))
    return m


def expr_class(short):
    cls = getattr(unreal, "MaterialExpression" + short, None)
    if cls is None:
        raise BuildError("This Unreal version has no unreal.MaterialExpression%s" % short)
    return cls


def set_prop(obj, name, value, required=True):
    """set_editor_property with a message that names the property (they differ between versions)."""
    try:
        obj.set_editor_property(name, value)
        return True
    except Exception as exc:                       # noqa: BLE001 - UE raises plain Exception
        if required:
            raise BuildError("Could not set property '%s' on %s: %s" % (name, type(obj).__name__, exc))
        warn("Optional property '%s' on %s not set (%s)" % (name, type(obj).__name__, exc))
        return False


DESC_LIMIT = 170


def short_desc(text, limit=DESC_LIMIT):
    """A node's Desc is drawn ON the node in the Material Editor and is the tooltip in the Material Instance
    editor, so it has to stay compact. Every parameter description is written to fit `limit` (a test enforces
    it), which means nothing is lost here; cutting at a word boundary is only a safety net."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[:limit - 3].rsplit(" ", 1)[0].rstrip(" ,;:.") + "..."


def linear_color(r, g=None, b=None, a=1.0):
    if g is None:
        r, g, b, a = r
    return unreal.LinearColor(float(r), float(g), float(b), float(a))


def _vector4_of(cls_name, vals):
    """One attempt at an unreal.<cls_name> holding `vals`; None if this engine has no such class or will not take them."""
    cls = getattr(unreal, cls_name, None)
    if cls is None:
        return None
    for how in ("properties", "attributes", "constructor"):
        try:
            if how == "constructor":
                return cls(*vals)
            v = cls()
            for key, val in zip("xyzw", vals):
                if how == "properties":
                    v.set_editor_property(key, val)
                else:
                    setattr(v, key, val)
            return v
        except Exception:                                   # noqa: BLE001
            continue
    return None


def set_preview_value(expr, values):
    """
    FunctionInput.preview_value is an unreal.Vector4f in UE 5.x. The UE 5.6 stub says Vector4f.__init__(self) takes NO
    arguments, so the fields are set one by one. Older engines use the double-precision unreal.Vector4: try both, and
    only accept a type once the engine has actually taken it.
    """
    vals = tuple(float(v) for v in values) + (0.0,) * (4 - len(values))
    last = None
    for cls_name in ("Vector4f", "Vector4"):
        v = _vector4_of(cls_name, vals)
        if v is None:
            continue
        try:
            expr.set_editor_property("preview_value", v)
            return
        except Exception as exc:                            # noqa: BLE001
            last = exc
    raise BuildError("Cannot set the preview value of a Function Input (%s)" % last)


# Pin names used only if MaterialEditingLibrary.get_material_expression_input_names is missing
# (older engines). Index 0 is always addressed with "" (= first input, documented behaviour).
FALLBACK_INPUT_PINS = {
    "Add": ["A", "B"], "Subtract": ["A", "B"], "Multiply": ["A", "B"], "Divide": ["A", "B"],
    "Min": ["A", "B"], "Max": ["A", "B"], "AppendVector": ["A", "B"], "DotProduct": ["A", "B"],
    "LinearInterpolate": ["A", "B", "Alpha"], "Clamp": ["Input", "Min", "Max"],
    "Power": ["Base", "Exponent"], "Desaturation": ["Input", "Fraction"],
    "StaticSwitch": ["True", "False", "Value"], "TextureSample": ["UVs", "Tex"],
    "TextureSampleParameter2D": ["UVs", "Tex"],
}


def input_pin_name(expr, short, index):
    if index == 0:
        return ""
    names = []
    try:
        names = [str(n) for n in unreal.MaterialEditingLibrary.get_material_expression_input_names(expr)]
    except Exception:                               # noqa: BLE001
        names = []
    if index < len(names) and names[index]:
        return names[index]
    fb = FALLBACK_INPUT_PINS.get(short)
    if fb and index < len(fb):
        return fb[index]
    raise BuildError("Cannot resolve input pin #%d of %s (engine reported: %s)" % (index, short, names))


# ==============================================================================
# 3. THE GRAPH-BUILDING MINI-DSL
# ------------------------------------------------------------------------------
# Writing a Material graph through the raw Python API means dozens of
# create / set_editor_property / connect calls per node. Graph + V wrap that so a
# block of material logic reads like maths:
#
#       m  = ((flag - mask).abs() * intensity).sat()
#       w  = ((m * (1 + 2 * soft) - thresh) / (2 * soft)).sat()
#
# Every V is "one output of one node" and knows how many components it has, so
# dimension mistakes (float3 + float2) are reported while building instead of
# showing up as red nodes later.
# ==============================================================================
DIM_OF_KIND = {"s": 1, "v2": 2, "v3": 3, "v4": 4}


class Node:
    __slots__ = ("expr", "short", "section", "sources", "n_pins", "desc_lines", "x", "y")

    def __init__(self, expr, short, section):
        self.expr, self.short, self.section = expr, short, section
        self.sources = []          # nodes feeding this one (used for layout depth and for pruning)
        self.n_pins = 1
        self.desc_lines = 0
        self.x = self.y = 0


class V:
    """One output of one node.  kind: 'num' (dim 1-4) | 'bool' (static bool) | 'tex' (texture object)."""
    __slots__ = ("g", "node", "out", "dim", "kind", "_masks")

    def __init__(self, g, node, out="", dim=1, kind="num"):
        self.g, self.node, self.out, self.dim, self.kind = g, node, out, dim, kind
        self._masks = {}

    # --- arithmetic sugar --------------------------------------------------
    def __add__(self, o): return self.g.binary("Add", self, o)
    def __radd__(self, o): return self.g.binary("Add", o, self)
    def __sub__(self, o): return self.g.binary("Subtract", self, o)
    def __rsub__(self, o): return self.g.binary("Subtract", o, self)
    def __mul__(self, o): return self.g.binary("Multiply", self, o)
    def __rmul__(self, o): return self.g.binary("Multiply", o, self)
    def __truediv__(self, o): return self.g.binary("Divide", self, o)
    def __rtruediv__(self, o): return self.g.binary("Divide", o, self)

    # --- unary helpers -----------------------------------------------------
    def sat(self): return self.g.unary("Saturate", self)
    def abs(self): return self.g.unary("Abs", self)
    def one_minus(self): return self.g.unary("OneMinus", self)
    def frac(self): return self.g.unary("Frac", self)

    def mask(self, channels):
        """ComponentMask, e.g. v.mask('rg'). Cached so repeated use shares one node."""
        if channels not in self._masks:
            self._masks[channels] = self.g.component_mask(self, channels)
        return self._masks[channels]


class Graph:
    """Wraps a Material or MaterialFunction and everything created inside it."""

    ROW_PAD = 26
    COL_W = 340
    BAND_GAP = 260

    def __init__(self, asset, is_function, label, params=None, textures=None):
        self.asset, self.is_function, self.label = asset, is_function, label
        self.params = params                      # ParamTable (master only)
        self.textures = textures or {}            # placeholder key -> Texture asset
        self.nodes = []
        self.section_name = "Main"
        self.prefix = ""
        self.section_color = {}
        self.section_order = []
        self.roots = []                           # nodes that feed a material output / function output
        self._pcache = {}
        self._warned = set()

    # --- sections (purely cosmetic: layout + header comments) ---------------
    def section(self, name, color=None):
        full = (self.prefix + " | " + name) if self.prefix else name
        self.section_name = full
        if full not in self.section_order:
            self.section_order.append(full)
            self.section_color[full] = color
        return full

    # --- node creation ------------------------------------------------------
    def add_node(self, short, props=None, desc=None, required_props=True):
        cls = expr_class(short)
        mel = unreal.MaterialEditingLibrary
        if self.is_function:
            expr = mel.create_material_expression_in_function(self.asset, cls, 0, 0)
        else:
            expr = mel.create_material_expression(self.asset, cls, 0, 0)
        if expr is None:
            raise BuildError("Engine refused to create MaterialExpression%s" % short)
        for k, v in (props or {}).items():
            set_prop(expr, k, v, required=required_props)
        if desc:
            set_prop(expr, "desc", desc, required=False)
        node = Node(expr, short, self.section_name)
        node.desc_lines = (len(desc) // 32 + 1) if desc else 0
        if self.section_name not in self.section_order:
            self.section_order.append(self.section_name)
            self.section_color.setdefault(self.section_name, None)
        self.nodes.append(node)
        return node

    def link(self, src, dst_node, pin):
        """Connect V `src` into input `pin` (index or exact name) of `dst_node`."""
        if src.g is not self:
            raise BuildError("Tried to connect nodes of two different graphs (%s -> %s)" % (src.g.label, self.label))
        name = pin if isinstance(pin, str) else input_pin_name(dst_node.expr, dst_node.short, pin)
        mel = unreal.MaterialEditingLibrary
        if mel.connect_material_expressions(src.node.expr, src.out, dst_node.expr, name):
            dst_node.sources.append(src.node)
            return
        if self._link_channel_fallback(src, dst_node, name):
            return
        raise BuildError("connect_material_expressions failed: %s[%r] -> %s.%r in %s" %
                         (src.node.short, src.out, dst_node.short, name, self.label))

    def _link_channel_fallback(self, src, dst_node, name):
        """A single channel of a texture sample / vertex colour is addressed by its output name (R G B A).
        If the engine rejects the name, go through a ComponentMask instead: R, G and B are inside the main (RGB)
        output, the alpha of a texture is inside its RGBA output."""
        is_tex = src.node.short.startswith("TextureSample")
        is_vc = src.node.short == "VertexColor"
        if not ((is_tex or is_vc) and src.out in ("R", "G", "B", "A")):
            return False
        ch = src.out.lower()
        if is_vc and ch == "a":
            return False                              # a Vertex Color node has no 4-component output to mask (see vertex_alpha_available)
        if ("mask", src.node.short, src.out) not in self._warned:
            self._warned.add(("mask", src.node.short, src.out))
            warn("Output '%s' of %s was not accepted by name; taking it through a ComponentMask instead." % (src.out, src.node.short))
        m = self.add_node("ComponentMask", {"r": ch == "r", "g": ch == "g", "b": ch == "b", "a": ch == "a"})
        mel = unreal.MaterialEditingLibrary
        if not mel.connect_material_expressions(src.node.expr, "RGBA" if ch == "a" else "", m.expr, ""):
            return False                              # the unused mask node is removed by prune()
        m.sources.append(src.node)
        if not mel.connect_material_expressions(m.expr, "", dst_node.expr, name):
            return False
        dst_node.sources.append(m)
        return True

    def _num(self, x, what):
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise BuildError("%s: expected a number or a value, got %r" % (what, x))
        return float(x)

    # --- constants -----------------------------------------------------------
    def const(self, x):
        n = self.add_node("Constant", {"r": self._num(x, "const")})
        return V(self, n, "", 1)

    def vec2(self, x, y):
        n = self.add_node("Constant2Vector", {"r": float(x), "g": float(y)})
        return V(self, n, "", 2)

    def vec3(self, r, g=None, b=None):
        if g is None:
            r, g, b = r
        n = self.add_node("Constant3Vector", {"constant": linear_color(r, g, b, 1.0)})
        return V(self, n, "", 3)

    def vec4(self, r, g, b, a):
        n = self.add_node("Constant4Vector", {"constant": linear_color(r, g, b, a)})
        return V(self, n, "", 4)

    def texcoord(self, index):
        n = self.add_node("TextureCoordinate", {"coordinate_index": int(index), "u_tiling": 1.0, "v_tiling": 1.0})
        return V(self, n, "", 2)

    def vertex_color(self):
        """Main output = RGB (float3), exactly like Epic's Vertex Color node. Alpha: vertex_alpha()."""
        return V(self, self.add_node("VertexColor"), "", 3)

    def vertex_alpha(self, vc):
        return V(self, vc.node, "A", 1)

    def vertex_alpha_available(self, vc):
        """Does this engine hand out the Vertex Color alpha as an output pin? The alpha only feeds an optional bonus
        (extra dirt), so if it does not, that bonus is switched off instead of failing the build. The probe node it
        creates is unused and removed by prune()."""
        probe = self.add_node("Saturate")
        if unreal.MaterialEditingLibrary.connect_material_expressions(vc.node.expr, "A", probe.expr, ""):
            return True
        warn("Could not read the Vertex Color alpha output: 'Use Vertex Alpha Dirt' will do nothing. "
             "Everything else (vertex layers 1-3) is unaffected.")
        return False

    def world_position(self):
        return V(self, self.add_node("WorldPosition"), "", 3)

    def object_position(self):
        return V(self, self.add_node("ObjectPositionWS"), "", 3)

    def pixel_depth(self):
        return V(self, self.add_node("PixelDepth"), "", 1)

    def per_instance_random(self):
        """0..1, different for every instance of an instanced mesh (HISM, foliage, PCG); constant on ordinary meshes."""
        return V(self, self.add_node("PerInstanceRandom"), "", 1)

    # --- arithmetic ----------------------------------------------------------
    @staticmethod
    def _merge_dim(a, b, what):
        if a == b or b == 1:
            return a
        if a == 1:
            return b
        raise BuildError("%s: incompatible component counts %d and %d" % (what, a, b))

    def binary(self, short, a, b):
        """Add / Subtract / Multiply / Divide / Min / Max. Python numbers use the node's own constants."""
        node_props = {}
        dims = []
        links = []
        for idx, (val, cname) in enumerate(((a, "const_a"), (b, "const_b"))):
            if isinstance(val, V):
                if val.kind != "num":
                    raise BuildError("%s: operand %d is not a number (%s)" % (short, idx, val.kind))
                dims.append(val.dim)
                links.append((idx, val))
            else:
                node_props[cname] = self._num(val, short)
        if not links:
            raise BuildError("%s needs at least one connected operand" % short)
        dim = dims[0]
        if len(dims) == 2:
            dim = self._merge_dim(dims[0], dims[1], short)
        node = self.add_node(short, node_props)
        for idx, val in links:
            self.link(val, node, idx)
        return V(self, node, "", dim)

    def vmax(self, a, b): return self.binary("Max", a, b)

    def unary(self, short, x):
        if not isinstance(x, V) or x.kind != "num":
            raise BuildError("%s expects a value" % short)
        node = self.add_node(short)
        self.link(x, node, 0)
        return V(self, node, "", x.dim)

    def floor(self, x): return self.unary("Floor", x)

    def sine(self, x, period=1.0):
        node = self.add_node("Sine", {"period": float(period)})
        self.link(x, node, 0)
        return V(self, node, "", x.dim)

    def cosine(self, x, period=1.0):
        node = self.add_node("Cosine", {"period": float(period)})
        self.link(x, node, 0)
        return V(self, node, "", x.dim)

    def normalize(self, x):
        node = self.add_node("Normalize")
        self.link(x, node, 0)
        return V(self, node, "", x.dim)

    def dot(self, a, b):
        if a.dim != b.dim:
            raise BuildError("dot: component counts differ (%d vs %d)" % (a.dim, b.dim))
        node = self.add_node("DotProduct")
        self.link(a, node, 0)
        self.link(b, node, 1)
        return V(self, node, "", 1)

    def append(self, a, b):
        if a.dim + b.dim > 4:
            raise BuildError("append: %d + %d components > 4" % (a.dim, b.dim))
        node = self.add_node("AppendVector")
        self.link(a, node, 0)
        self.link(b, node, 1)
        return V(self, node, "", a.dim + b.dim)

    def component_mask(self, x, channels):
        idx = {"r": 0, "g": 1, "b": 2, "a": 3}
        for c in channels:
            if c not in idx or idx[c] >= x.dim:
                raise BuildError("mask '%s' invalid for a %d-component value" % (channels, x.dim))
        node = self.add_node("ComponentMask", {c: (c in channels) for c in "rgba"})
        self.link(x, node, 0)
        return V(self, node, "", len(channels))

    def lerp(self, a, b, t):
        props, links, dims = {}, [], []
        for idx, (val, cname) in enumerate(((a, "const_a"), (b, "const_b"), (t, "const_alpha"))):
            if isinstance(val, V):
                if val.kind != "num":
                    raise BuildError("lerp: operand %d is not a number" % idx)
                links.append((idx, val))
            else:
                props[cname] = self._num(val, "lerp")
        da = a.dim if isinstance(a, V) else 1
        db = b.dim if isinstance(b, V) else 1
        dim = self._merge_dim(da, db, "lerp A/B")
        if isinstance(t, V) and t.dim not in (1, dim):
            raise BuildError("lerp: Alpha has %d components, A/B have %d" % (t.dim, dim))
        node = self.add_node("LinearInterpolate", props)
        for idx, val in links:
            self.link(val, node, idx)
        return V(self, node, "", dim)

    def desaturate(self, color, fraction):
        """Desaturation node: fraction 1 -> grey (luminance), 0 -> unchanged."""
        if color.dim != 3:
            raise BuildError("desaturate expects a float3")
        node = self.add_node("Desaturation")
        self.link(color, node, 0)
        self.link(fraction if isinstance(fraction, V) else self.const(fraction), node, 1)
        return V(self, node, "", 3)

    def broadcast(self, x, dim):
        """Scalar -> vector of `dim` components (multiply by (1,1,1))."""
        if x.dim == dim:
            return x
        if x.dim != 1:
            raise BuildError("cannot broadcast %d components to %d" % (x.dim, dim))
        if dim == 2:
            ones = self.vec2(1, 1)
        elif dim == 3:
            ones = self.vec3(1, 1, 1)
        else:
            ones = self.vec4(1, 1, 1, 1)
        return ones * x

    def static_switch(self, cond, true_v, false_v):
        """Compile-time branch. Only the chosen input is compiled (the other costs nothing)."""
        if cond.kind != "bool":
            raise BuildError("static_switch condition must be a static bool")
        if not isinstance(false_v, V):
            false_v = self.const(false_v)
        if not isinstance(true_v, V):
            true_v = self.const(true_v)
        if true_v.dim != false_v.dim:
            raise BuildError("static_switch: branches have %d and %d components" % (true_v.dim, false_v.dim))
        node = self.add_node("StaticSwitch")
        self.link(true_v, node, 0)
        self.link(false_v, node, 1)
        self.link(cond, node, 2)
        return V(self, node, "", true_v.dim)

    # --- textures ------------------------------------------------------------
    def sample(self, tex, uv, sampler, desc=None):
        """TextureSample fed by a texture object. Shared:Wrap sampler => costs no sampler slot."""
        if tex.kind != "tex":
            raise BuildError("sample: first argument must be a texture object")
        if uv.dim != 2:
            raise BuildError("sample: UVs must have 2 components (got %d)" % uv.dim)
        node = self.add_node("TextureSample", {
            "sampler_type": enum("MaterialSamplerType", sampler),
            "sampler_source": enum("SamplerSourceMode", "SSM_WRAP_WORLD_GROUP_SETTINGS"),
        }, desc=desc)
        self.link(uv, node, 0)
        self.link(tex, node, 1)
        return V(self, node, "", 3)             # "" = first output (RGB) - no dependence on its display name

    def alpha_of(self, sample_v):
        """Alpha output of a texture sample as a scalar."""
        return V(self, sample_v.node, "A", 1)

    # --- parameters (driven by the ParamTable) ---------------------------------
    def _param_common(self, d):
        return {"parameter_name": d.name, "group": d.group, "sort_priority": int(d.prio)}

    def P(self, name):
        """Parameter by name -> V (scalar / RGB vector / static bool / texture object)."""
        if name in self._pcache:
            return self._pcache[name]
        if self.params is None or name not in self.params.items:
            raise BuildError("Unknown parameter '%s'" % name)
        d = self.params.items[name]
        if d.kind == "scalar":
            props = self._param_common(d)
            props["default_value"] = float(d.default)
            node = self.add_node("ScalarParameter", props, desc=short_desc(d.desc))
            if d.lo is not None:
                set_prop(node.expr, "slider_max", float(d.hi), required=False)
                set_prop(node.expr, "slider_min", float(d.lo), required=False)
            v = V(self, node, "", 1)
        elif d.kind == "vector":
            props = self._param_common(d)
            props["default_value"] = linear_color(d.default)
            node = self.add_node("VectorParameter", props, desc=short_desc(d.desc))
            v = V(self, node, "", 3)
        elif d.kind == "static":
            props = self._param_common(d)
            props["default_value"] = bool(d.default)
            node = self.add_node("StaticBoolParameter", props, desc=short_desc(d.desc))
            v = V(self, node, "", 1, kind="bool")
        elif d.kind == "texture":
            if d.use != "object":
                raise BuildError("Texture parameter '%s' is a direct sample; use sample_param()" % name)
            props = self._param_common(d)
            props["texture"] = self._default_texture(d)                    # ORDER MATTERS: assigning a texture makes the editor
            props["sampler_type"] = enum("MaterialSamplerType", d.sampler)  # re-derive the sampler type, so sampler_type must come after
            props["sampler_source"] = enum("SamplerSourceMode", "SSM_WRAP_WORLD_GROUP_SETTINGS")
            node = self.add_node("TextureObjectParameter", props, desc=short_desc(d.desc))
            v = V(self, node, "", 0, kind="tex")
        else:
            raise BuildError("bad parameter kind %r" % d.kind)
        self._pcache[name] = v
        return v

    def _default_texture(self, d):
        tex = self.textures.get(d.tex)
        if tex is None:
            raise BuildError("Default texture '%s' for parameter '%s' does not exist. "
                             "Enable CREATE_DEFAULT_TEXTURES." % (d.tex, d.name))
        return tex

    def sample_param(self, name, uv):
        """TextureSampleParameter2D for a parameter flagged use='sample' -> RGB V (alpha via alpha_of)."""
        d = self.params.items[name]
        if d.kind != "texture" or d.use != "sample":
            raise BuildError("'%s' is not a direct-sample texture parameter" % name)
        if name in self._pcache:
            raise BuildError("Texture parameter '%s' sampled twice (would create duplicate parameter nodes)" % name)
        props = self._param_common(d)
        props["texture"] = self._default_texture(d)                        # texture first, sampler_type second (see P())
        props["sampler_type"] = enum("MaterialSamplerType", d.sampler)
        props["sampler_source"] = enum("SamplerSourceMode", "SSM_WRAP_WORLD_GROUP_SETTINGS")
        node = self.add_node("TextureSampleParameter2D", props, desc=short_desc(d.desc))
        self.link(uv, node, 0)
        v = V(self, node, "", 3)
        self._pcache[name] = v
        return v

    # --- finishing -----------------------------------------------------------------------
    def mark_root(self, v):
        self.roots.append(v.node)

    def prune(self):
        """Delete nodes that do not feed any output (an inline-expanded block also builds outputs nobody uses)."""
        live, stack = set(), list(self.roots)
        while stack:
            n = stack.pop()
            if id(n) in live:
                continue
            live.add(id(n))
            stack.extend(n.sources)
        mel = unreal.MaterialEditingLibrary
        deleted = set()
        for n in self.nodes:
            if id(n) in live:
                continue
            try:
                if self.is_function:
                    mel.delete_material_expression_in_function(self.asset, n.expr)
                else:
                    mel.delete_material_expression(self.asset, n.expr)
            except Exception as exc:                        # noqa: BLE001 - cosmetic clean-up, never fatal
                warn("Could not delete an unused node (%s); leaving the remaining unused nodes in place." % exc)
                break
            deleted.add(id(n))
        self.nodes = [n for n in self.nodes if id(n) not in deleted]
        return len(deleted)

    def _size(self, n):
        """Rough node footprint (width, height) in graph units - only used for spacing."""
        s = n.short
        extra = 16 * n.desc_lines
        if s in ("TextureSampleParameter2D", "TextureObjectParameter", "TextureSample"):
            return 280, 260 + extra
        if s == "MaterialFunctionCall":
            return 330, 80 + 22 * max(n.n_pins, 4)
        if s in ("VectorParameter", "Constant3Vector", "Constant4Vector"):
            return 220, 150 + extra
        if s in ("ScalarParameter", "StaticBoolParameter"):
            return 240, 112 + extra
        return 210, 100 + extra

    def finish(self):
        """Lay the nodes out in one horizontal band per section and add a header comment per band."""
        by_section = {}
        for n in self.nodes:
            by_section.setdefault(n.section, []).append(n)
        y_cursor = 0
        for sec in self.section_order:
            nodes = by_section.get(sec)
            if not nodes:
                continue
            in_sec = set(id(n) for n in nodes)
            depth = {}

            def dep(n):
                if id(n) in depth:
                    return depth[id(n)]
                depth[id(n)] = 0                      # cycle guard
                d = 0
                for s in n.sources:
                    if id(s) in in_sec:
                        d = max(d, dep(s) + 1)
                depth[id(n)] = d
                return d

            cols = {}
            for n in nodes:
                cols.setdefault(dep(n), []).append(n)
            header_y = y_cursor
            body_y = y_cursor + 150
            band_h = 0
            for d in sorted(cols):
                y = body_y
                for n in cols[d]:
                    w, h = self._size(n)
                    n.x, n.y = d * self.COL_W, y
                    y += h + self.ROW_PAD
                band_h = max(band_h, y - body_y)
            for n in nodes:
                set_prop(n.expr, "material_expression_editor_x", int(n.x), required=False)
                set_prop(n.expr, "material_expression_editor_y", int(n.y), required=False)
            self._header_comment(sec, 0, header_y)
            y_cursor = body_y + band_h + self.BAND_GAP

    def _header_comment(self, text, x, y):
        try:
            mel = unreal.MaterialEditingLibrary
            cls = expr_class("Comment")
            if self.is_function:
                c = mel.create_material_expression_in_function(self.asset, cls, int(x), int(y))
            else:
                c = mel.create_material_expression(self.asset, cls, int(x), int(y))
            set_prop(c, "text", text, required=False)
            set_prop(c, "font_size", 20, required=False)
            col = self.section_color.get(text)
            if col is not None:
                set_prop(c, "comment_color", linear_color(col), required=False)
        except Exception as exc:                            # noqa: BLE001 - comments are cosmetic
            warn("Could not add header comment '%s': %s" % (text, exc))


# ==============================================================================
# 4. THE PARAMETER TABLE
# ------------------------------------------------------------------------------
# One entry per parameter: name (shown in the Material Instance editor), group,
# sort priority, default, slider range and tooltip. The graph builder creates the
# nodes from this table, the demo instances use the names, and Docs/03_Parameter_
# Reference.md is generated from it - so code and documentation cannot drift.
#
# Group names start with a number because Unreal sorts groups alphabetically.
# ==============================================================================
GROUPS = {
    "feat": "00 Features (static switches)",
    "glob": "01 Global",
    "mask": "02 RGB Mask and Breakup",
    "base": "03 Base Layer",
    "wear": "04 Wear Layer (mask R)",
    "dirt": "05 Dirt Layer (mask G)",
    "scr": "06 Scratches (mask B)",
    "vp": "07 Vertex Paint",
    "vp1": "08 Vertex Layer 1 (paint R)",
    "vp2": "09 Vertex Layer 2 (paint G) - extra",
    "vp3": "10 Vertex Layer 3 (paint B) - extra",
    "det": "11 Detail Normal",
    "mac": "12 Macro Variation - extra",
    "inst": "13 Instance Variation - extra",
    "wet": "14 Wetness - extra",
    "emi": "15 Emissive - extra",
    "opa": "16 Opacity Mask - extra",
    "dbg": "17 Debug",
    "prev": "99 Preview (demo only)",
}

# (key, label used in parameter names, group key, colour of the layer's PLACEHOLDER albedo, linear).
# The tints all default to white: a texture you assign shows exactly as authored, and an empty layer still shows
# its own colour (carried by the placeholder texture, not by the tint), so the stack is readable before you have textures.
LAYERS = [
    ("Base", "Base", "base", (0.62, 0.66, 0.72)),
    ("Wear", "Wear", "wear", (0.50, 0.28, 0.17)),
    ("Dirt", "Dirt", "dirt", (0.13, 0.10, 0.08)),
    ("Vertex1", "Vertex 1", "vp1", (0.45, 0.12, 0.09)),
    ("Vertex2", "Vertex 2", "vp2", (0.20, 0.36, 0.12)),
    ("Vertex3", "Vertex 3", "vp3", (0.58, 0.50, 0.36)),
]

DEBUG_MODES = [
    "Mask R (wear)", "Mask G (dirt)", "Mask B (scratches)", "Mask A (baked AO)",
    "Vertex colour RGB", "Vertex colour alpha",
    "Wear weight (after height + breakup)", "Dirt weight", "Scratch weight",
    "Vertex layer 1 weight", "Vertex layer 2 weight", "Vertex layer 3 weight",
    "Tiling UV checker (1 square = 1 tile)", "Unique UV gradient (U=red, V=green)",
    "Breakup noise", "Final normal (n*0.5+0.5)",
]


DEBUG_LEGEND = ("1-4 mask R G B A   5 vertex RGB   6 vertex alpha\n"
                "7 wear  8 dirt  9 scratch  10-12 vertex layer weights\n"
                "13 tiling UV checker   14 unique UV   15 breakup RGB   16 normal")


class Param:
    __slots__ = ("name", "kind", "default", "group", "prio", "desc", "lo", "hi", "sampler", "tex", "use")

    def __init__(self, name, kind, default, group, prio, desc, lo=None, hi=None, sampler=None, tex=None, use=None):
        self.name, self.kind, self.default, self.group, self.prio = name, kind, default, group, prio
        self.desc, self.lo, self.hi, self.sampler, self.tex, self.use = desc, lo, hi, sampler, tex, use


class ParamTable:
    def __init__(self):
        self.items = {}
        self.order = []

    def add(self, p):
        if p.name in self.items:
            raise BuildError("duplicate parameter name '%s'" % p.name)
        self.items[p.name] = p
        self.order.append(p.name)
        return p

    def group(self, key_or_name):
        return _GroupAdder(self, GROUPS.get(key_or_name, key_or_name))


class _GroupAdder:
    """Adds parameters to one group with automatically increasing sort priorities."""

    def __init__(self, table, group):
        self.t, self.group, self.n = table, group, 0

    def _p(self):
        self.n += 10
        return self.n

    def scalar(self, name, default, lo, hi, desc):
        return self.t.add(Param(name, "scalar", default, self.group, self._p(), desc, lo, hi))

    def vector(self, name, default, desc):
        return self.t.add(Param(name, "vector", tuple(default) + ((1.0,) if len(default) == 3 else ()), self.group, self._p(), desc))

    def static(self, name, default, desc):
        return self.t.add(Param(name, "static", bool(default), self.group, self._p(), desc))

    def texture(self, name, tex, sampler, desc, use="object"):
        return self.t.add(Param(name, "texture", None, self.group, self._p(), desc, sampler=sampler, tex=tex, use=use))


def _layer_head(pt, key, label, group):
    """The first parameters of every layer group: its three textures and its tint (the knobs you touch first)."""
    g = pt.group(group)
    L = label
    g.texture(L + " Albedo", "alb_" + key.lower(), "SAMPLERTYPE_COLOR",
              "Tileable colour map, imported as sRGB colour. Empty = a flat placeholder colour, so the layer is visible before you have textures.")
    g.texture(L + " Normal Map", "flatnormal", "SAMPLERTYPE_NORMAL",
              "Tileable normal map, DirectX/Unreal style (green = down). Import with compression 'Normalmap'. Lighting inverted? Tick Flip Green Channel on the texture.")
    g.texture(L + " ORMH Map", "ormh", "SAMPLERTYPE_MASKS",
              "Packed: R = AO, G = roughness, B = metallic, A = height (drives the blend edges). Import with compression 'Masks (no sRGB)'.")
    g.vector(L + " Tint", (1.0, 1.0, 1.0), "Multiplies the albedo. White = texture unchanged. The main art-direction knob: recolour paint, rust or dirt.")
    return g


def _layer_tail(g, label, with_height=True):
    """The remaining per-layer adjustments (after the effect-specific knobs of that layer)."""
    L = label
    g.scalar(L + " Brightness", 1.0, 0.0, 3.0, "Albedo multiplier (applied after the tint).")
    g.scalar(L + " Saturation", 1.0, 0.0, 2.0, "0 = greyscale, 1 = as authored, 2 = double saturation.")
    g.scalar(L + " Tiling", 1.0, 0.05, 16.0, "UV scale of this layer, on top of Global Tiling. Different values per layer hide repetition.")
    g.scalar(L + " Rotation", 0.0, 0.0, 360.0, "UV rotation in degrees about the tile centre (the normal map is rotated with it).")
    g.vector(L + " Offset", (0.0, 0.0, 0.0), "UV shift: R = U, G = V. Type the numbers instead of using the colour picker.")
    g.scalar(L + " Normal Strength", 1.0, 0.0, 3.0, "0 = flat, 1 = as authored, above 1 = exaggerated bumps.")
    g.scalar(L + " Roughness Min", 0.0, 0.0, 1.0, "Roughness where the ORMH green channel is 0 (together with Max it remaps the roughness range).")
    g.scalar(L + " Roughness Max", 1.0, 0.0, 1.0, "Roughness where the ORMH green channel is 1.")
    g.scalar(L + " Metallic", 1.0, 0.0, 1.0, "Multiplier on the ORMH blue channel (metallic). 0 forces a non-metal.")
    g.scalar(L + " AO Strength", 1.0, 0.0, 1.0, "How much the ORMH red channel (AO) darkens.")
    if with_height:        # the Base layer is never "revealed", so its height is never used
        g.scalar(L + " Height Contrast", 1.0, 0.0, 4.0, "Contrast of the ORMH alpha (height) used for the blend edges.")
        g.scalar(L + " Height Offset", 0.0, -1.0, 1.0, "Shifts the height up or down (which areas count as 'high').")
    return g


def define_surface_params():
    pt = ParamTable()

    # ---- 00 Features ---------------------------------------------------------
    f = pt.group("feat")
    f.static("Use Wear Layer", True, "Reveal the Wear layer (rust, bare metal, brick ...) where mask R says so. OFF removes the layer and its 3 texture samples from the shader.")
    f.static("Use Dirt Layer", True, "Blend the Dirt layer where mask G says so. OFF removes its 3 texture samples.")
    f.static("Use Scratches", True, "Apply scratches where mask B says so (changes colour, roughness and metallic).")
    f.static("Use Baked AO", True, "Multiply the baked ambient occlusion stored in the ALPHA channel of the RGB mask. Turn OFF if your mask alpha is not AO.")
    f.static("Use Mask Breakup", True, "Erode the soft, low-resolution mask edges with the tiling Breakup texture so wear and dirt stay crisp up close.")
    f.static("Use Vertex Layer 1", True, "Vertex colour RED paints Vertex Layer 1 over everything below it (the assignment's vertex painting).")
    f.static("Use Vertex Layer 2", False, "Vertex colour GREEN paints Vertex Layer 2.")
    f.static("Use Vertex Layer 3", False, "Vertex colour BLUE paints Vertex Layer 3.")
    f.static("Use Vertex Alpha Dirt", False, "Vertex colour ALPHA paints extra dirt on top of the mask-driven dirt (needs Use Dirt Layer).")
    f.static("Vertex Paint White Adds", False, "OFF (default): paint BLACK to add a layer (an unpainted mesh is white). ON: paint WHITE - fill the mesh with black first (Mesh Paint > Fill).")
    f.static("Use Detail Normal", True, "Add the tiling detail normal on top of the layer normals (it fades out with distance).")
    f.static("Use Macro Variation", False, "Multiply a very large, low-contrast noise over colour and roughness to hide tiling repetition.")
    f.static("Macro Uses World Space", False, "Project the macro noise top-down in world X/Y so neighbouring props differ. OFF uses the tiling UVs (better on walls).")
    f.static("Use Instance Variation", False, "Random brightness and saturation per object (from its position, and per instance on HISM or foliage) so copies do not look identical.")
    f.static("Use Wetness", False, "Enable the Wetness parameters (darker albedo, lower roughness).")
    f.static("Use Emissive", False, "Add an emissive texture (signs, lights, screens) on the unique UV set.")
    f.static("Use Opacity Mask", False, "Cut-out transparency from the Opacity Texture. Also needs Blend Mode = Masked: Details > Base Property Overrides in your instance.")
    f.static("Swap UV Channels", False, "OFF: tiling = UV0, unique mask = UV1. ON: tiling = UV1, unique mask = UV0. Use it if your mesh has the sets the other way round (debug 13/14 shows which).")
    f.static("Debug View", False, "Show a mask, weight or UV as an unlit colour instead of the material. Pick it with Debug Mode.")

    # ---- 01 Global ---------------------------------------------------------------
    g = pt.group("glob")
    g.scalar("Global Tiling", 1.0, 0.05, 16.0, "Multiplies the tiling of every tiling texture (layers, breakup, detail, macro). Your texel-density knob.")
    g.vector("Global Tint", (1.0, 1.0, 1.0), "Colour multiplied over the final albedo (after all layers).")
    g.scalar("Global Brightness", 1.0, 0.0, 3.0, "Final albedo multiplier.")
    g.scalar("Global Saturation", 1.0, 0.0, 2.0, "Final saturation: 0 = greyscale, 1 = unchanged.")
    g.scalar("Global Roughness Offset", 0.0, -1.0, 1.0, "Added to the final roughness (negative = glossier).")
    g.scalar("Global AO Strength", 1.0, 0.0, 1.0, "Strength of the combined ambient occlusion.")

    # ---- 02 Mask ---------------------------------------------------------------------
    m = pt.group("mask")
    m.texture("Mask Texture", "mask_black", "SAMPLERTYPE_MASKS",
              "RGBA mask on the UNIQUE UV set: R wear, G dirt, B scratches, A baked AO. Import with compression 'Masks (no sRGB)'.", use="sample")
    m.scalar("Mask AO Strength", 1.0, 0.0, 1.0, "How strongly the baked AO (mask alpha) darkens the surface.")
    m.texture("Breakup Texture", "gray", "SAMPLERTYPE_MASKS",
              "Tileable noise: R = wear edges, G = dirt edges, B = scratch and vertex-paint edges (greyscale is fine). 50% grey = neutral. Import as 'Masks (no sRGB)'.", use="sample")
    m.scalar("Breakup Tiling", 2.0, 0.1, 32.0, "Tiling of the breakup noise on the tiling UVs.")

    # ---- 03 / 04 / 05 layers + their effect controls --------------------------------------
    for key, label, group, _colour in LAYERS:
        lg = _layer_head(pt, key, label, group)
        if key == "Wear":
            lg.scalar("Wear Intensity", 1.0, 0.0, 2.0, "Scales mask R before the reveal. Above 1 the worn area grows, below 1 it shrinks, 0 = no wear.")
            lg.scalar("Wear Softness", 0.08, 0.005, 0.5, "Edge width. 0.005 = razor-sharp chipping, 0.08 = default, 0.5 = very soft fade.")
            lg.scalar("Wear Height Influence", 0.5, -1.0, 1.0, "How much the Wear layer's height map decides where wear shows first. 0 = ignore height, negative flips it.")
            lg.scalar("Wear Breakup", 0.4, 0.0, 1.0, "How much the Breakup texture (R) erodes the wear edge. 0 = clean mask edge.")
            lg.vector("Wear Edge Color", (0.06, 0.03, 0.02), "Colour of the thin rim where the top coat meets the exposed layer.")
            lg.scalar("Wear Edge Strength", 0.5, 0.0, 1.0, "Visibility of that rim (0 = off).")
            lg.scalar("Wear Invert", 0.0, 0.0, 1.0, "0 = use mask R as painted, 1 = invert it.")
        elif key == "Dirt":
            lg.scalar("Dirt Intensity", 1.0, 0.0, 2.0, "Scales mask G before the reveal. Above 1 more dirt, below 1 less, 0 = none.")
            lg.scalar("Dirt Softness", 0.2, 0.005, 0.5, "Edge width of the dirt. 0.005 = hard stains, 0.5 = very soft.")
            lg.scalar("Dirt Height Influence", 0.3, -1.0, 1.0, "How much the Dirt layer's height map decides where dirt shows first. 0 = ignore height.")
            lg.scalar("Dirt Breakup", 0.4, 0.0, 1.0, "How much the Breakup texture (G) erodes the dirt edge.")
            lg.scalar("Dirt AO Boost", 0.5, 0.0, 1.0, "Adds extra dirt in crevices using the baked AO (mask alpha). 0 = off.")
            lg.scalar("Dirt Invert", 0.0, 0.0, 1.0, "0 = use mask G as painted, 1 = invert it.")
        elif key.startswith("Vertex"):
            lg.scalar(label + " Softness", 0.1, 0.005, 0.5, "Softness of the painted edge. Small = crisp and height-driven, large = a plain fade.")
            lg.scalar(label + " Height Influence", 0.5, -1.0, 1.0, "How much this layer's height map shapes the painted edge. 0 = plain gradient.")
            lg.scalar(label + " Breakup", 0.3, 0.0, 1.0, "How much the Breakup texture (B) erodes the painted edge.")
        _layer_tail(lg, label, with_height=(key != "Base"))

    # ---- 06 Scratches -----------------------------------------------------------------------
    s = pt.group("scr")
    s.scalar("Scratch Intensity", 1.0, 0.0, 2.0, "Scales mask B before the reveal.")
    s.scalar("Scratch Softness", 0.05, 0.005, 0.5, "Edge width of the scratch lines.")
    s.scalar("Scratch Breakup", 0.2, 0.0, 1.0, "How much the Breakup texture (B) erodes the scratch lines.")
    s.vector("Scratch Color", (0.78, 0.78, 0.80), "Colour of the exposed material inside a scratch.")
    s.scalar("Scratch Roughness", 0.35, 0.0, 1.0, "Roughness inside scratches.")
    s.scalar("Scratch Metallic", 1.0, 0.0, 1.0, "Metallic inside scratches (1 = bare metal showing through the paint).")
    s.scalar("Scratch Invert", 0.0, 0.0, 1.0, "0 = use mask B as painted, 1 = invert it.")

    # ---- 07 Vertex paint -----------------------------------------------------------------------
    v = pt.group("vp")
    v.scalar("Vertex Alpha Dirt Strength", 1.0, 0.0, 1.0, "How much dirt painted into vertex ALPHA adds (needs Use Vertex Alpha Dirt).")

    # ---- 11 Detail normal -------------------------------------------------------------------------
    d = pt.group("det")
    d.texture("Detail Normal Texture", "flatnormal", "SAMPLERTYPE_NORMAL",
              "Fine tileable normal map layered over everything. Import with compression 'Normalmap'.", use="sample")
    d.scalar("Detail Normal Tiling", 8.0, 0.1, 64.0, "Tiling of the detail normal on the tiling UVs.")
    d.scalar("Detail Normal Intensity", 1.0, 0.0, 3.0, "Strength of the detail normal.")
    d.scalar("Detail Fade Start", 400.0, 0.0, 5000.0, "Distance (cm) where the detail starts to fade out.")
    d.scalar("Detail Fade End", 1500.0, 1.0, 10000.0, "Distance (cm) where the detail is gone.")

    # ---- 12 Macro -------------------------------------------------------------------------------------
    mc = pt.group("mac")
    mc.texture("Macro Texture", "gray", "SAMPLERTYPE_MASKS",
               "Large-scale greyscale noise (R channel); 50% grey = no change. Import as 'Masks (no sRGB)'.", use="sample")
    mc.scalar("Macro Tiling", 0.2, 0.01, 4.0, "UV mode: tiles per tiling-UV unit. World mode: tiles per metre.")
    mc.scalar("Macro Intensity", 0.3, 0.0, 1.0, "Brightness variation strength.")
    mc.scalar("Macro Roughness Variation", 0.2, 0.0, 1.0, "Roughness variation strength.")

    # ---- 13 Instance variation ----------------------------------------------------------------------------
    iv = pt.group("inst")
    iv.scalar("Variation Brightness", 0.15, 0.0, 0.5, "Max random brightness change per object (0.15 = plus or minus 15%).")
    iv.scalar("Variation Saturation", 0.15, 0.0, 0.5, "Max random saturation change per object.")
    iv.scalar("Variation Seed", 0.0, 0.0, 100.0, "Re-rolls every object's random look at once, without moving the props.")

    # ---- 14 Wetness -------------------------------------------------------------------------------------------
    w = pt.group("wet")
    w.scalar("Wetness", 0.0, 0.0, 1.0, "0 = dry, 1 = soaked.")
    w.scalar("Wetness Darken", 0.35, 0.0, 1.0, "How much a soaked surface darkens.")
    w.scalar("Wetness Roughness", 0.08, 0.0, 1.0, "Roughness of a soaked surface.")

    # ---- 15 Emissive ---------------------------------------------------------------------------------------------
    e = pt.group("emi")
    e.texture("Emissive Texture", "black", "SAMPLERTYPE_COLOR", "Emissive colour (sRGB) on the UNIQUE UV set.", use="sample")
    e.vector("Emissive Color", (1.0, 1.0, 1.0), "Tint multiplied onto the emissive texture.")
    e.scalar("Emissive Intensity", 1.0, 0.0, 50.0, "Emissive brightness multiplier.")

    # ---- 16 Opacity ---------------------------------------------------------------------------------------------------
    o = pt.group("opa")
    o.texture("Opacity Texture", "white_mask", "SAMPLERTYPE_MASKS", "Opacity (R channel) for cut-outs such as fences or leaves. Import as 'Masks (no sRGB)'.", use="sample")
    o.scalar("Opacity Uses Tiling UV", 0.0, 0.0, 1.0, "0 = sample on the unique UV set, 1 = on the tiling UV set (values snap to 0 or 1).")

    # ---- 17 Debug -------------------------------------------------------------------------------------------------------
    db = pt.group("dbg")
    db.scalar("Debug Mode", 1.0, 1.0, 16.0,
              "View shown by Debug View (1-16): 1-4 mask R G B A, 5-6 vertex RGB / alpha, 7-12 layer weights, 13-14 UV checks, 15 breakup, 16 normal.")

    # ---- 99 Preview (demo only) ----------------------------------------------------------------------------------------------
    pv = pt.group("prev")
    pv.static("Mask Uses Tiling UV", False, "PREVIEW ONLY: samples the RGB mask with the tiling UVs so the demo instances work on meshes with ONE UV set. Leave OFF on your own meshes.")
    return pt


# ==============================================================================
# 5. REUSABLE BLOCKS  (become Material Functions, or are expanded inline)
# ------------------------------------------------------------------------------
# A Block is "logic with named inputs and outputs". The same Python code can be
#   * baked into a Material Function asset  (USE_MATERIAL_FUNCTIONS = True), or
#   * expanded directly into the master graph  (False / automatic fallback).
#
#   MF_TilingLayer  - samples + adjusts one tiling PBR layer (the workhorse)
#   MF_RevealWeight - mask + height + breakup noise  ->  crisp 0..1 blend weight
#   MF_LayerBlend   - blends two layers (colour/normal/rough/metal/AO), static on/off
#   MF_NormalBlend  - whiteout blend of a detail normal onto a base normal
#   MF_DebugSelect  - picks one of 16 debug colours by index
# ==============================================================================
class Pin:
    __slots__ = ("name", "kind", "default", "desc")

    def __init__(self, name, kind, default=None, desc=""):
        self.name, self.kind, self.default, self.desc = name, kind, default, desc

    @property
    def dim(self):
        return DIM_OF_KIND.get(self.kind, 0)


class Block:
    def __init__(self, name, desc, inputs, outputs, build):
        self.name, self.desc, self.inputs, self.outputs, self.build = name, desc, inputs, outputs, build


# ---- shared node-building helpers (used inside several blocks) -----------------
def uv_rotation(g, rotation):
    """cos and sin of a rotation given in degrees (Sine/Cosine nodes take a period: 1 = one full turn)."""
    turns = rotation / 360.0
    return g.cosine(turns), g.sine(turns)


def uv_transform(g, uv, tiling, c, s, offset):
    """uv * tiling, rotated about (0.5, 0.5) by the angle whose cos/sin are c, s, then offset."""
    q = uv * tiling - 0.5
    qx, qy = q.mask("r"), q.mask("g")
    rx = qx * c - qy * s
    ry = qx * s + qy * c
    return g.append(rx, ry) + 0.5 + offset


def rotate_normal_back(g, n, c, s):
    """A layer whose UVs are rotated by +angle is sampled with a rotated texture, so the tangent-space normal read
    from it has to be rotated by -angle to agree with the surface (otherwise bumps are lit from the wrong side)."""
    nx, ny = n.mask("r"), n.mask("g")
    return g.append(g.append(nx * c + ny * s, ny * c - nx * s), n.mask("b"))


def normal_with_strength(g, n, strength):
    """Scale the XY of a tangent-space normal and renormalise (0 = flat, 1 = unchanged)."""
    xy = n.mask("rg") * strength
    z = n.mask("b")
    return g.normalize(g.append(xy, z))


# ---- block bodies ------------------------------------------------------------------
def build_tiling_layer(g, I):
    g.section("UV transform")
    c, s = uv_rotation(g, I["Rotation"])
    uv = uv_transform(g, I["UV"], I["Tiling"], c, s, I["Offset"])

    g.section("Sample the 3 textures")
    albedo = g.sample(I["AlbedoTex"], uv, "SAMPLERTYPE_COLOR")
    nmap = g.sample(I["NormalTex"], uv, "SAMPLERTYPE_NORMAL")
    orm = g.sample(I["ORMHTex"], uv, "SAMPLERTYPE_MASKS")
    height_raw = g.alpha_of(orm)

    g.section("Colour: saturation, tint, brightness")
    grey = g.desaturate(albedo, 1.0)
    color = g.lerp(grey, albedo, I["Saturation"]) * I["Tint"] * I["Brightness"]

    g.section("Normal, roughness, metallic, AO, height")
    normal = normal_with_strength(g, rotate_normal_back(g, nmap, c, s), I["NormalStrength"])
    rough = g.lerp(I["RoughnessMin"], I["RoughnessMax"], orm.mask("g")).sat()
    metal = (orm.mask("b") * I["Metallic"]).sat()
    ao = g.lerp(1.0, orm.mask("r"), I["AOStrength"])
    height = ((height_raw - 0.5) * I["HeightContrast"] + 0.5 + I["HeightOffset"]).sat()
    return {"BaseColor": color, "Normal": normal, "Roughness": rough, "Metallic": metal, "AO": ao, "Height": height}


def build_reveal_weight(g, I):
    """
    weight = saturate( (m * (1 + 2W) - T) / (2W) )
      m  mask after invert / intensity                       (0..1)
      T  reveal threshold = 0.5 - HeightInfluence*(Height-0.5) + BreakupStrength*(0.5-Breakup)
      W  softness (edge width)
    Guarantees weight = 0 where m = 0 and weight = 1 where m = 1 for every T in 0..1,
    while the height/breakup noise decides in which ORDER pixels switch on (organic chipped edges).
    """
    g.section("Mask: invert and intensity")
    m = (g.lerp(I["Mask"], I["Mask"].one_minus(), I["Invert"]) * I["Intensity"]).sat()

    g.section("Reveal threshold: height + breakup")
    h_term = 0.5 - I["HeightInfluence"] * (I["Height"] - 0.5)
    threshold = (h_term + I["BreakupStrength"] * (0.5 - I["Breakup"])).sat()

    g.section("Weight")
    w2 = g.vmax(I["Softness"], 0.001) * 2.0
    weight = ((m * (w2 + 1.0) - threshold) / w2).sat()
    return {"Weight": weight}


def build_layer_blend(g, I):
    use, w = I["UseLayer"], I["Weight"]
    g.section("Blend A -> B by weight")
    color = g.lerp(I["A_Color"], I["B_Color"], w)
    rim = ((w * (1.0 - w)) * 4.0 * I["EdgeStrength"]).sat()          # peaks where the edge is half-way
    color = g.lerp(color, I["EdgeColor"], rim)
    normal = g.normalize(g.lerp(I["A_Normal"], I["B_Normal"], w))
    rough = g.lerp(I["A_Rough"], I["B_Rough"], w)
    metal = g.lerp(I["A_Metal"], I["B_Metal"], w)
    ao = g.lerp(I["A_AO"], I["B_AO"], w)

    g.section("Static on/off (OFF = pass A through, B is not compiled)")
    return {
        "Color": g.static_switch(use, color, I["A_Color"]),
        "Normal": g.static_switch(use, normal, I["A_Normal"]),
        "Roughness": g.static_switch(use, rough, I["A_Rough"]),
        "Metallic": g.static_switch(use, metal, I["A_Metal"]),
        "AO": g.static_switch(use, ao, I["A_AO"]),
    }


def build_normal_blend(g, I):
    g.section("Whiteout blend")
    d = normal_with_strength(g, I["Detail"], I["Intensity"])          # intensity 0 -> (0,0,1) = no change
    xy = I["Base"].mask("rg") + d.mask("rg")
    z = I["Base"].mask("b") * d.mask("b")
    return {"Normal": g.normalize(g.append(xy, z))}


def build_debug_select(g, I):
    g.section("Pick colour by Mode")
    mode = g.floor(I["Mode"] + 0.5)                                  # whole numbers only (7.4 -> view 7)
    acc = None
    for i in range(1, 17):
        eq = (mode - float(i)).abs().one_minus().sat()               # 1 when Mode == i, else 0
        term = I["C%02d" % i] * eq
        acc = term if acc is None else acc + term
    return {"Color": acc}


def make_blocks():
    B = {}
    B["MF_TilingLayer"] = Block(
        "MF_TilingLayer",
        "Samples Albedo / Normal / ORMH of one tiling layer with its own tiling, rotation and offset, "
        "applies tint, brightness, saturation, normal strength, roughness range, metallic, AO and height.",
        [Pin("AlbedoTex", "tex"), Pin("NormalTex", "tex"), Pin("ORMHTex", "tex"),
         Pin("UV", "v2"),
         Pin("Tiling", "s", 1.0), Pin("Rotation", "s", 0.0), Pin("Offset", "v2", (0.0, 0.0)),
         Pin("Tint", "v3", (1.0, 1.0, 1.0)), Pin("Brightness", "s", 1.0), Pin("Saturation", "s", 1.0),
         Pin("NormalStrength", "s", 1.0), Pin("RoughnessMin", "s", 0.0), Pin("RoughnessMax", "s", 1.0),
         Pin("Metallic", "s", 1.0), Pin("AOStrength", "s", 1.0),
         Pin("HeightContrast", "s", 1.0), Pin("HeightOffset", "s", 0.0)],
        [Pin("BaseColor", "v3"), Pin("Normal", "v3"), Pin("Roughness", "s"), Pin("Metallic", "s"),
         Pin("AO", "s"), Pin("Height", "s")],
        build_tiling_layer)
    B["MF_RevealWeight"] = Block(
        "MF_RevealWeight",
        "Turns a (soft, low-res) mask into a crisp blend weight. Height map + breakup noise decide where the "
        "layer appears first; Softness sets the edge width. weight is exactly 0 at mask 0 and 1 at mask 1.",
        [Pin("Mask", "s"), Pin("Height", "s", 0.5), Pin("Intensity", "s", 1.0), Pin("Invert", "s", 0.0),
         Pin("HeightInfluence", "s", 0.0), Pin("Breakup", "s", 0.5), Pin("BreakupStrength", "s", 0.0),
         Pin("Softness", "s", 0.1)],
        [Pin("Weight", "s")],
        build_reveal_weight)
    B["MF_LayerBlend"] = Block(
        "MF_LayerBlend",
        "Blends layer B over layer A (colour, normal, roughness, metallic, AO) with a weight, optional edge rim "
        "colour, and a static on/off switch that removes B from the shader entirely when OFF.",
        [Pin("UseLayer", "bool"),
         Pin("A_Color", "v3"), Pin("A_Normal", "v3"), Pin("A_Rough", "s"), Pin("A_Metal", "s"), Pin("A_AO", "s"),
         Pin("B_Color", "v3"), Pin("B_Normal", "v3"), Pin("B_Rough", "s"), Pin("B_Metal", "s"), Pin("B_AO", "s"),
         Pin("Weight", "s"),
         Pin("EdgeColor", "v3", (0.0, 0.0, 0.0)), Pin("EdgeStrength", "s", 0.0)],
        [Pin("Color", "v3"), Pin("Normal", "v3"), Pin("Roughness", "s"), Pin("Metallic", "s"), Pin("AO", "s")],
        build_layer_blend)
    B["MF_NormalBlend"] = Block(
        "MF_NormalBlend",
        "Whiteout-blends a detail normal (scaled by Intensity) onto a base normal. Intensity 0 returns the base unchanged.",
        [Pin("Base", "v3"), Pin("Detail", "v3"), Pin("Intensity", "s", 1.0)],
        [Pin("Normal", "v3")],
        build_normal_blend)
    pins = [Pin("Mode", "s", 1.0)] + [Pin("C%02d" % i, "v3", (0.0, 0.0, 0.0)) for i in range(1, 17)]
    B["MF_DebugSelect"] = Block(
        "MF_DebugSelect",
        "Returns input C<Mode> (1..16). Used by the Debug View.",
        pins, [Pin("Color", "v3")], build_debug_select)
    return B


# Hover text of the function pins (Function Input / Output descriptions): the five functions explain themselves in the editor.
PIN_DOCS = {
    "MF_TilingLayer": {
        "AlbedoTex": "Texture object: tileable colour map (sRGB).",
        "NormalTex": "Texture object: tileable normal map (Normalmap).",
        "ORMHTex": "Texture object: R = AO, G = roughness, B = metallic, A = height (Masks).",
        "UV": "UV for all three textures (already multiplied by Global Tiling).",
        "Tiling": "This layer's UV scale.", "Rotation": "UV rotation in degrees (the normal is rotated with it).",
        "Offset": "UV shift (U, V).", "Tint": "Multiplies the albedo. White = unchanged.",
        "Brightness": "Albedo multiplier.", "Saturation": "0 = greyscale, 1 = as authored.",
        "NormalStrength": "0 = flat, 1 = as authored.", "RoughnessMin": "Roughness where ORMH green = 0.",
        "RoughnessMax": "Roughness where ORMH green = 1.", "Metallic": "Multiplier on ORMH blue.",
        "AOStrength": "How much ORMH red (AO) darkens.", "HeightContrast": "Contrast of the ORMH alpha height.",
        "HeightOffset": "Shifts the ORMH alpha height up or down.",
        "BaseColor": "Linear colour after saturation, tint and brightness.", "Normal": "Tangent-space normal, unit length.",
        "Roughness": "Remapped roughness 0..1.", "Metallic_out": "Metallic 0..1 (ORMH blue times Metallic).", "AO": "Ambient occlusion 0..1.",
        "Height": "Height 0..1, used by MF_RevealWeight.",
    },
    "MF_RevealWeight": {
        "Mask": "Mask value 0..1 (wear R, dirt G, scratches B, or vertex paint).",
        "Height": "Height of the layer being revealed (0.5 = neutral).", "Intensity": "Scales the mask first.",
        "Invert": "0 = as painted, 1 = inverted (values in between blend).",
        "HeightInfluence": "-1..1: how much the height decides where the layer shows first.",
        "Breakup": "Breakup noise 0..1 (0.5 = neutral).", "BreakupStrength": "0..1: how much the noise erodes the edge.",
        "Softness": "Edge width: 0.005 = razor sharp, 0.5 = very soft.",
        "Weight": "Blend weight 0..1; exactly 0 at mask 0 and 1 at mask 1.",
    },
    "MF_LayerBlend": {
        "UseLayer": "Static switch. OFF returns A and B is never compiled.",
        "A_Color": "Stack below: colour.", "A_Normal": "Stack below: normal.", "A_Rough": "Stack below: roughness.",
        "A_Metal": "Stack below: metallic.", "A_AO": "Stack below: AO.",
        "B_Color": "Layer on top: colour.", "B_Normal": "Layer on top: normal.", "B_Rough": "Layer on top: roughness.",
        "B_Metal": "Layer on top: metallic.", "B_AO": "Layer on top: AO.",
        "Weight": "0 = only A, 1 = only B.", "EdgeColor": "Rim colour where the weight is between 0 and 1.",
        "EdgeStrength": "Rim visibility (0 = off).",
        "Color": "Blended colour.", "Normal": "Blended normal (normalised).", "Roughness": "Blended roughness.",
        "Metallic": "Blended metallic.", "AO": "Blended AO.",
    },
    "MF_NormalBlend": {
        "Base": "Base tangent-space normal.", "Detail": "Detail tangent-space normal.",
        "Intensity": "0 = base unchanged, 1 = full detail.", "Normal": "Whiteout-blended normal, unit length.",
    },
    "MF_DebugSelect": {"Mode": "View number 1..16 (whole numbers).", "Color": "The chosen colour."},
}


def pin_doc(block_name, pin, is_output=False):
    """Description of a function pin (an input and an output may share a name, e.g. Metallic: inputs win, outputs get a suffix)."""
    docs = PIN_DOCS.get(block_name, {})
    if pin.desc:
        return pin.desc
    if block_name == "MF_DebugSelect" and pin.name.startswith("C") and pin.name[1:].isdigit():
        return "Colour shown for view %d." % int(pin.name[1:])
    if is_output and pin.name + "_out" in docs:
        return docs[pin.name + "_out"]
    return docs.get(pin.name, "")


FUNCTION_INPUT_TYPES = {
    "s": "FUNCTION_INPUT_SCALAR", "v2": "FUNCTION_INPUT_VECTOR2", "v3": "FUNCTION_INPUT_VECTOR3",
    "v4": "FUNCTION_INPUT_VECTOR4", "tex": "FUNCTION_INPUT_TEXTURE2D", "bool": "FUNCTION_INPUT_STATIC_BOOL",
}


# ---- turning blocks into assets / nodes -----------------------------------------------
def get_or_create_asset(folder, name, asset_class, factory_class):
    eal = unreal.EditorAssetLibrary
    full = folder + "/" + name
    if eal.does_asset_exist(full):
        return eal.load_asset(full)
    eal.make_directory(folder)
    asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, asset_class, factory_class())
    if asset is None:
        raise BuildError("Could not create asset %s" % full)
    return asset


def build_function_asset(block, textures):
    mel = unreal.MaterialEditingLibrary
    fn = get_or_create_asset(FUNCTIONS_PATH, block.name, unreal.MaterialFunction, unreal.MaterialFunctionFactoryNew)
    mel.delete_all_material_expressions_in_function(fn)
    g = Graph(fn, True, block.name)
    g.section("Inputs", (0.1, 0.25, 0.45, 1.0))
    I = {}
    for i, pin in enumerate(block.inputs):
        props = {"input_name": pin.name, "input_type": enum("FunctionInputType", FUNCTION_INPUT_TYPES[pin.kind]),
                 "sort_priority": i}
        if pin.default is not None:
            props["use_preview_value_as_default"] = True
        if pin_doc(block.name, pin):
            props["description"] = pin_doc(block.name, pin)
        node = g.add_node("FunctionInput", props)
        if pin.default is not None:
            set_preview_value(node.expr, pin.default if isinstance(pin.default, tuple) else (pin.default,))
        kind = {"tex": "tex", "bool": "bool"}.get(pin.kind, "num")
        I[pin.name] = V(g, node, "", pin.dim, kind)
    g.section("Logic")
    outs = block.build(g, I)
    g.section("Outputs", (0.45, 0.15, 0.15, 1.0))
    for i, pin in enumerate(block.outputs):
        out_props = {"output_name": pin.name, "sort_priority": i}
        if pin_doc(block.name, pin, True):
            out_props["description"] = pin_doc(block.name, pin, True)
        node = g.add_node("FunctionOutput", out_props)
        g.link(outs[pin.name], node, 0)
        g.roots.append(node)
    g.prune()
    g.finish()
    set_prop(fn, "description", block.desc, required=False)
    set_prop(fn, "expose_to_library", False, required=False)
    mel.update_material_function(fn)
    unreal.EditorAssetLibrary.save_loaded_asset(fn)
    return fn


def build_all_functions(blocks, textures):
    assets = {}
    for name, blk in blocks.items():
        assets[name] = build_function_asset(blk, textures)
        log("function ready: %s/%s" % (FUNCTIONS_PATH, name))
    return assets


class BlockUser:
    """Use a block from a graph: as a function-call node (assets given) or expanded inline (assets None)."""

    def __init__(self, g, blocks, assets):
        self.g, self.blocks, self.assets = g, blocks, assets

    def __call__(self, name, supplied, label=None):
        blk = self.blocks[name]
        for pin_name in supplied:
            if pin_name not in [p.name for p in blk.inputs]:
                raise BuildError("%s has no input named '%s'" % (name, pin_name))
        if self.assets is not None:
            return self._call(blk, supplied)
        return self._inline(blk, supplied, label or name)

    def _check(self, blk, pin, v):
        want_kind = {"tex": "tex", "bool": "bool"}.get(pin.kind, "num")
        if v.kind != want_kind:
            raise BuildError("%s.%s expects a %s value, got %s" % (blk.name, pin.name, want_kind, v.kind))
        if want_kind == "num" and v.dim not in (1, pin.dim):
            raise BuildError("%s.%s expects %d components, got %d" % (blk.name, pin.name, pin.dim, v.dim))

    def _call(self, blk, supplied):
        g = self.g
        node = g.add_node("MaterialFunctionCall")
        fn = self.assets[blk.name]
        assigned = False
        try:
            assigned = bool(node.expr.set_material_function(fn))
        except Exception as exc:                    # noqa: BLE001 - not every engine version exposes the helper
            if "set_material_function" not in g._warned:
                g._warned.add("set_material_function")
                warn("set_material_function is not available (%s); assigning the 'material_function' property instead." % exc)
        if not assigned:
            # the editor refreshes the call node's pins when this property changes (same path as picking it in Details)
            set_prop(node.expr, "material_function", fn)
        try:
            names = [str(n) for n in unreal.MaterialEditingLibrary.get_material_expression_input_names(node.expr)]
        except Exception:                           # noqa: BLE001
            names = [p.name for p in blk.inputs]
        missing = [p.name for p in blk.inputs if p.name not in names]
        if missing:
            raise BuildError("function call node for %s has no pins %s (engine reported %s)" % (blk.name, missing, names))
        node.n_pins = max(len(blk.inputs), len(blk.outputs))
        for pin in blk.inputs:
            if pin.name in supplied:
                self._check(blk, pin, supplied[pin.name])
                g.link(supplied[pin.name], node, pin.name)
            elif pin.default is None:
                raise BuildError("%s: required input '%s' was not supplied" % (blk.name, pin.name))
        return {o.name: V(g, node, o.name, o.dim) for o in blk.outputs}

    def _inline(self, blk, supplied, label):
        g = self.g
        I = {}
        for pin in blk.inputs:
            if pin.name in supplied:
                v = supplied[pin.name]
                self._check(blk, pin, v)
                if pin.kind in ("s", "v2", "v3", "v4") and v.dim != pin.dim:
                    v = g.broadcast(v, pin.dim)
                I[pin.name] = v
            elif pin.default is not None:
                if pin.kind == "s":
                    I[pin.name] = g.const(pin.default)
                elif pin.kind == "v2":
                    I[pin.name] = g.vec2(*pin.default)
                elif pin.kind == "v3":
                    I[pin.name] = g.vec3(*pin.default)
                else:
                    raise BuildError("no inline default for %s.%s" % (blk.name, pin.name))
            else:
                raise BuildError("%s: required input '%s' was not supplied" % (blk.name, pin.name))
        saved_prefix, saved_section = g.prefix, g.section_name
        g.prefix = label
        try:
            outs = blk.build(g, I)
        finally:
            g.prefix = saved_prefix
            g.section_name = saved_section
        return outs


# ==============================================================================
# 6. THE SURFACE MASTER   (read top to bottom - one numbered section per band)
# ==============================================================================
C_UV = (0.10, 0.28, 0.55, 1.0)
C_MASK = (0.38, 0.18, 0.55, 1.0)
C_VERTEX = (0.60, 0.30, 0.08, 1.0)
C_LAYER = (0.50, 0.40, 0.08, 1.0)
C_STACK = (0.15, 0.48, 0.20, 1.0)
C_POST = (0.30, 0.30, 0.34, 1.0)
C_OUT = (0.58, 0.14, 0.14, 1.0)


def stack_of(layer_out):
    """MF_TilingLayer outputs -> the 5-channel dict MF_LayerBlend works with."""
    return {"Color": layer_out["BaseColor"], "Normal": layer_out["Normal"], "Rough": layer_out["Roughness"],
            "Metal": layer_out["Metallic"], "AO": layer_out["AO"]}


def connect_property(g, prop_name, v, components):
    if v.kind != "num" or v.dim != components:
        raise BuildError("%s needs %d components, got %s/%d" % (prop_name, components, v.kind, v.dim))
    ok = unreal.MaterialEditingLibrary.connect_material_property(v.node.expr, v.out, enum("MaterialProperty", prop_name))
    if not ok:
        raise BuildError("connect_material_property failed for %s" % prop_name)
    g.mark_root(v)


def build_surface_master(blocks, fn_assets, textures):
    """Returns (material, graph). fn_assets None => blocks are expanded inline."""
    mel = unreal.MaterialEditingLibrary
    mat = get_or_create_asset(ROOT_PATH, SURFACE_MASTER_NAME, unreal.Material, unreal.MaterialFactoryNew)
    mel.delete_all_material_expressions(mat)
    params = define_surface_params()
    g = Graph(mat, False, SURFACE_MASTER_NAME, params, textures)
    use = BlockUser(g, blocks, fn_assets)
    P = g.P

    # ---- 1. UV SETS -----------------------------------------------------------------------
    # UV0 = tiling (texel-density) UVs, UV1 = unique (non-overlapping 0-1) UVs for the RGB mask.
    g.section("1 | UV SETS (tiling + unique)", C_UV)
    uv0, uv1 = g.texcoord(0), g.texcoord(1)
    swap = P("Swap UV Channels")
    tile_raw = g.static_switch(swap, uv1, uv0)
    unique_std = g.static_switch(swap, uv0, uv1)
    unique_uv = g.static_switch(P("Mask Uses Tiling UV"), tile_raw, unique_std)
    tiling_uv = tile_raw * P("Global Tiling")

    # ---- 2. RGB MASK -------------------------------------------------------------------------
    g.section("2 | RGB MASK (unique UV)\nR wear  G dirt  B scratch  A AO", C_MASK)
    mask_rgb = g.sample_param("Mask Texture", unique_uv)
    m_wear, m_dirt, m_scr = mask_rgb.mask("r"), mask_rgb.mask("g"), mask_rgb.mask("b")
    m_ao_raw = g.alpha_of(mask_rgb)
    ao_mask = g.static_switch(P("Use Baked AO"), m_ao_raw, 1.0)

    g.section("3 | BREAKUP NOISE\nR wear  G dirt  B scratch + vertex", C_MASK)
    bk_tex = g.sample_param("Breakup Texture", tiling_uv * P("Breakup Tiling"))
    use_breakup = P("Use Mask Breakup")
    bk_wear = g.static_switch(use_breakup, bk_tex.mask("r"), 0.5)         # 0.5 = neutral (no erosion)
    bk_dirt = g.static_switch(use_breakup, bk_tex.mask("g"), 0.5)
    bk_other = g.static_switch(use_breakup, bk_tex.mask("b"), 0.5)

    # ---- 4. VERTEX COLOUR ------------------------------------------------------------------------
    # Unpainted meshes read as white. Default: painting BLACK adds a layer (like the course reference).
    g.section("4 | VERTEX COLOUR\nR G B = layers 1-3, A = dirt", C_VERTEX)
    vc = g.vertex_color()
    white_adds = P("Vertex Paint White Adds")

    def painted(v):
        return g.static_switch(white_adds, v, v.one_minus())

    alpha_ok = g.vertex_alpha_available(vc)
    vc_alpha = g.vertex_alpha(vc) if alpha_ok else g.const(1.0)          # 1 = white = nothing painted
    paint_r, paint_g, paint_b = painted(vc.mask("r")), painted(vc.mask("g")), painted(vc.mask("b"))
    paint_a = painted(vc_alpha) if alpha_ok else g.const(0.0)

    # ---- layers + their blend weights ------------------------------------------------------------------
    def layer(label):
        ins = {
            "AlbedoTex": P(label + " Albedo"), "NormalTex": P(label + " Normal Map"), "ORMHTex": P(label + " ORMH Map"),
            "UV": tiling_uv,
            "Tiling": P(label + " Tiling"), "Rotation": P(label + " Rotation"), "Offset": P(label + " Offset").mask("rg"),
            "Tint": P(label + " Tint"), "Brightness": P(label + " Brightness"), "Saturation": P(label + " Saturation"),
            "NormalStrength": P(label + " Normal Strength"),
            "RoughnessMin": P(label + " Roughness Min"), "RoughnessMax": P(label + " Roughness Max"),
            "Metallic": P(label + " Metallic"), "AOStrength": P(label + " AO Strength"),
        }
        if label != "Base":                       # Base is never revealed -> its height is unused
            ins["HeightContrast"] = P(label + " Height Contrast")
            ins["HeightOffset"] = P(label + " Height Offset")
        return use("MF_TilingLayer", ins, label + " layer")

    def reveal(label, mask_v, layer_out, breakup_v, softness, height_infl, breakup_str, intensity=None, invert=None):
        ins = {"Mask": mask_v, "Breakup": breakup_v, "BreakupStrength": P(breakup_str), "Softness": P(softness)}
        if layer_out is not None:
            ins["Height"] = layer_out["Height"]
            ins["HeightInfluence"] = P(height_infl)
        if intensity:
            ins["Intensity"], ins["Invert"] = P(intensity), P(invert)
        return use("MF_RevealWeight", ins, label)["Weight"]

    g.section("5 | BASE LAYER", C_LAYER)
    base = layer("Base")

    g.section("6 | WEAR LAYER (mask R)", C_LAYER)
    wear = layer("Wear")
    w_wear = reveal("Wear weight", m_wear, wear, bk_wear, "Wear Softness", "Wear Height Influence", "Wear Breakup",
                    "Wear Intensity", "Wear Invert")

    g.section("7 | DIRT LAYER (mask G)", C_LAYER)
    dirt = layer("Dirt")
    dirt_vertex = g.static_switch(P("Use Vertex Alpha Dirt"), paint_a * P("Vertex Alpha Dirt Strength"), 0.0)
    dirt_mask = (m_dirt + (1.0 - ao_mask) * P("Dirt AO Boost") + dirt_vertex).sat()
    w_dirt = reveal("Dirt weight", dirt_mask, dirt, bk_dirt, "Dirt Softness", "Dirt Height Influence", "Dirt Breakup",
                    "Dirt Intensity", "Dirt Invert")

    g.section("8 | SCRATCHES (mask B)", C_LAYER)
    w_scr = reveal("Scratch weight", m_scr, None, bk_other, "Scratch Softness", None, "Scratch Breakup",
                   "Scratch Intensity", "Scratch Invert")

    vp, w_vp = [], []
    for i, (paint, ch) in enumerate(((paint_r, "R"), (paint_g, "G"), (paint_b, "B")), start=1):
        g.section("%d | VERTEX LAYER %d (paint %s)" % (8 + i, i, ch), C_VERTEX)
        lay = layer("Vertex %d" % i)
        vp.append(lay)
        w_vp.append(reveal("Vertex %d weight" % i, paint, lay, bk_other, "Vertex %d Softness" % i,
                           "Vertex %d Height Influence" % i, "Vertex %d Breakup" % i))

    # ---- 12. LAYER STACK ---------------------------------------------------------------------------------
    # Order (bottom -> top): Base, Wear, Vertex 1-3, Dirt, Scratches.
    g.section("12 | LAYER STACK\nBase > Wear > Vtx 1-3 > Dirt > Scr", C_STACK)

    def blend(static_name, S, B, weight, label, edge=None):
        ins = {"UseLayer": P(static_name), "Weight": weight}
        for k in ("Color", "Normal", "Rough", "Metal", "AO"):
            ins["A_" + k], ins["B_" + k] = S[k], B[k]
        if edge:
            ins["EdgeColor"], ins["EdgeStrength"] = edge
        o = use("MF_LayerBlend", ins, label)
        return {"Color": o["Color"], "Normal": o["Normal"], "Rough": o["Roughness"], "Metal": o["Metallic"], "AO": o["AO"]}

    S = stack_of(base)
    S = blend("Use Wear Layer", S, stack_of(wear), w_wear, "Blend wear", (P("Wear Edge Color"), P("Wear Edge Strength")))
    for i in range(3):
        S = blend("Use Vertex Layer %d" % (i + 1), S, stack_of(vp[i]), w_vp[i], "Blend vertex layer %d" % (i + 1))
    S = blend("Use Dirt Layer", S, stack_of(dirt), w_dirt, "Blend dirt")
    scratch_layer = {"Color": P("Scratch Color"), "Normal": S["Normal"], "Rough": P("Scratch Roughness"),
                     "Metal": P("Scratch Metallic"), "AO": S["AO"]}
    S_below = S
    S = blend("Use Scratches", S, scratch_layer, w_scr, "Blend scratches")
    color, rough, metal = S["Color"], S["Rough"], S["Metal"]
    S = {"Color": color, "Rough": rough, "Metal": metal,               # scratches leave normal and AO alone, so take them
         "Normal": S_below["Normal"], "AO": S_below["AO"]}             # from below (the unused blend outputs are never built)

    # ---- 13. POST: macro, instance variation, global grade, wetness ---------------------------------------------
    g.section("13 | POST: macro, variation,\nglobal grade, wetness", C_POST)
    macro_scale = P("Macro Tiling")
    macro_uv = g.static_switch(P("Macro Uses World Space"),
                               g.world_position().mask("rg") * 0.01 * macro_scale,   # cm -> m
                               tiling_uv * macro_scale)
    macro_n = g.sample_param("Macro Texture", macro_uv).mask("r")
    k = P("Macro Intensity")
    color_macro = color * g.lerp(1.0 - k, k + 1.0, macro_n)                         # 1.0 when noise = 0.5
    rough_macro = (rough + (macro_n - 0.5) * P("Macro Roughness Variation")).sat()
    use_macro = P("Use Macro Variation")
    color = g.static_switch(use_macro, color_macro, color)
    rough = g.static_switch(use_macro, rough_macro, rough)

    # Two independent pseudo-random numbers per object: a hash of the object position (ordinary meshes), plus
    # PerInstanceRandom (every instance of a HISM / foliage mesh shares one object position but not this value).
    pos = g.object_position().mask("rg")
    seed_in = g.dot(pos, g.vec2(12.9898, 78.233)) + g.per_instance_random() * 1000.0 + P("Variation Seed") * 17.0 + 1.0
    r1 = (g.sine(seed_in, 2.0 * math.pi) * 43758.5453).frac()
    r2 = (g.sine(seed_in * 1.37 + 4.1, 2.0 * math.pi) * 24634.6345).frac()
    vb, vs = P("Variation Brightness"), P("Variation Saturation")
    grey_i = g.desaturate(color, 1.0)
    color_inst = g.lerp(grey_i, color, g.lerp(1.0 - vs, vs + 1.0, r2)) * g.lerp(1.0 - vb, vb + 1.0, r1)
    color = g.static_switch(P("Use Instance Variation"), color_inst, color)

    grey_g = g.desaturate(color, 1.0)
    color = g.lerp(grey_g, color, P("Global Saturation")) * P("Global Tint") * P("Global Brightness")

    wet = P("Wetness")
    color_wet = color * (1.0 - P("Wetness Darken") * wet)
    rough_wet = g.lerp(rough, P("Wetness Roughness"), wet)
    use_wet = P("Use Wetness")
    color = g.static_switch(use_wet, color_wet, color)
    rough = g.static_switch(use_wet, rough_wet, rough)
    rough = (rough + P("Global Roughness Offset")).sat()

    # ---- 14. AO --------------------------------------------------------------------------------------------------
    g.section("14 | AMBIENT OCCLUSION", C_POST)
    ao = S["AO"] * g.lerp(1.0, ao_mask, P("Mask AO Strength"))
    ao = g.lerp(1.0, ao, P("Global AO Strength"))

    # ---- 15. NORMAL + DETAIL NORMAL --------------------------------------------------------------------------------
    g.section("15 | NORMAL + DETAIL NORMAL", C_POST)
    detail = g.sample_param("Detail Normal Texture", tiling_uv * P("Detail Normal Tiling"))
    d_start, d_end = P("Detail Fade Start"), P("Detail Fade End")
    fade = 1.0 - ((g.pixel_depth() - d_start) / g.vmax(d_end - d_start, 1.0)).sat()
    n_detail = use("MF_NormalBlend", {"Base": S["Normal"], "Detail": detail,
                                       "Intensity": P("Detail Normal Intensity") * fade}, "Detail normal")["Normal"]
    normal = g.static_switch(P("Use Detail Normal"), n_detail, S["Normal"])

    # ---- 16. EMISSIVE + OPACITY ----------------------------------------------------------------------------------------
    g.section("16 | EMISSIVE + OPACITY", C_POST)
    emissive_tex = g.sample_param("Emissive Texture", unique_uv)
    emissive = g.static_switch(P("Use Emissive"), emissive_tex * P("Emissive Color") * P("Emissive Intensity"),
                               g.vec3(0.0, 0.0, 0.0))
    opacity_uv = g.lerp(unique_uv, tiling_uv, g.floor(P("Opacity Uses Tiling UV") + 0.5))     # 0 / 1 only
    opacity_tex = g.sample_param("Opacity Texture", opacity_uv).mask("r")
    opacity = g.static_switch(P("Use Opacity Mask"), opacity_tex, 1.0)

    # ---- 17. DEBUG VIEW ---------------------------------------------------------------------------------------------------------
    g.section("17 | DEBUG VIEW (free when switched off)\n" + DEBUG_LEGEND, C_POST)

    def v3(x):
        return g.broadcast(x, 3)

    u_floor, v_floor = g.floor(tiling_uv.mask("r")), g.floor(tiling_uv.mask("g"))
    checker = ((u_floor + v_floor) * 0.5).frac() * 2.0
    dbg = use("MF_DebugSelect", {
        "Mode": P("Debug Mode"),
        "C01": v3(m_wear), "C02": v3(m_dirt), "C03": v3(m_scr), "C04": v3(m_ao_raw),
        "C05": vc, "C06": v3(vc_alpha),
        "C07": v3(w_wear), "C08": v3(w_dirt), "C09": v3(w_scr),
        "C10": v3(w_vp[0]), "C11": v3(w_vp[1]), "C12": v3(w_vp[2]),
        "C13": v3(checker), "C14": g.append(unique_uv, g.const(0.0)),
        "C15": g.append(g.append(bk_wear, bk_dirt), bk_other), "C16": normal * 0.5 + 0.5,
    }, "Debug select")["Color"]
    dbg_on = P("Debug View")

    # ---- 18. OUTPUTS ----------------------------------------------------------------------------------------------------------------
    g.section("18 | MATERIAL OUTPUTS", C_OUT)
    connect_property(g, "MP_BASE_COLOR", g.static_switch(dbg_on, g.vec3(0.0, 0.0, 0.0), color), 3)
    connect_property(g, "MP_METALLIC", g.static_switch(dbg_on, 0.0, metal), 1)
    connect_property(g, "MP_ROUGHNESS", g.static_switch(dbg_on, 1.0, rough), 1)
    connect_property(g, "MP_NORMAL", normal, 3)
    connect_property(g, "MP_AMBIENT_OCCLUSION", g.static_switch(dbg_on, 1.0, ao), 1)
    connect_property(g, "MP_EMISSIVE_COLOR", g.static_switch(dbg_on, dbg, emissive), 3)
    connect_property(g, "MP_OPACITY_MASK", opacity, 1)

    removed = g.prune()
    if removed:
        log("%s: removed %d unused nodes" % (SURFACE_MASTER_NAME, removed))
    g.finish()
    mel.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    return mat, g


# ==============================================================================
# 7. THE MESH-DECAL MASTER
# ------------------------------------------------------------------------------
# A "mesh decal" is an ordinary mesh (plane / strip / bent card) whose UVs point into
# a decal sheet. With Material Domain = Deferred Decal the engine renders it like a
# decal (DBuffer) onto the surface below instead of as a floating translucent card,
# so it picks up the surface's lighting, shadows and roughness correctly.
# ==============================================================================
def define_decal_params():
    pt = ParamTable()
    s = pt.group("01 Decal Sheet")
    s.texture("Decal Color Map", "white", "SAMPLERTYPE_COLOR",
              "Decal sheet colour (sRGB). The ALPHA channel is the decal's opacity, so import the PNG with its alpha and pad the cells.", use="sample")
    s.texture("Decal Normal Map", "flatnormal", "SAMPLERTYPE_NORMAL", "Decal sheet normal map. Import with compression 'Normalmap'.", use="sample")
    s.texture("Decal ORM Map", "ormh", "SAMPLERTYPE_MASKS",
              "Decal sheet packed map: G = roughness, B = metallic (R and A unused). Import with compression 'Masks (no sRGB)'.", use="sample")
    u = pt.group("02 Decal UV")
    u.scalar("Decal UV Tiling", 1.0, 0.1, 8.0, "Scales the mesh UVs (1 = use the UVs as modelled).")
    u.vector("Decal UV Offset", (0.0, 0.0, 0.0), "Shifts the UVs (R = U, G = V) - slide to another cell of the sheet.")
    l = pt.group("03 Look")
    l.vector("Decal Tint", (1.0, 1.0, 1.0), "Colour multiplied onto the decal.")
    l.scalar("Decal Brightness", 1.0, 0.0, 3.0, "Colour multiplier.")
    l.scalar("Decal Saturation", 1.0, 0.0, 2.0, "Colour saturation.")
    l.scalar("Decal Opacity", 1.0, 0.0, 1.0, "Overall opacity (fade the decal in/out).")
    l.scalar("Decal Opacity Contrast", 1.0, 0.1, 8.0, "Sharpens the alpha edge (>1 = crisper stickers / stencils).")
    l.scalar("Decal Normal Strength", 1.0, 0.0, 3.0, "Normal map strength.")
    l.scalar("Decal Roughness Min", 0.0, 0.0, 1.0, "Roughness at ORM.G = 0.")
    l.scalar("Decal Roughness Max", 1.0, 0.0, 1.0, "Roughness at ORM.G = 1.")
    l.scalar("Decal Metallic", 1.0, 0.0, 1.0, "Multiplier for the sheet's ORM blue channel (metallic). 1 = as authored, 0 = force non-metal.")
    e = pt.group("04 Emissive")
    e.static("Decal Use Emissive", False, "Make the decal glow with its own colour. Nothing glows? Set Decal Blend Mode = Translucent in the master's Details (see Docs/05).")
    e.scalar("Decal Emissive Intensity", 1.0, 0.0, 50.0, "Glow strength.")
    return pt


def build_decal_master(textures):
    mel = unreal.MaterialEditingLibrary
    mat = get_or_create_asset(ROOT_PATH, DECAL_MASTER_NAME, unreal.Material, unreal.MaterialFactoryNew)
    mel.delete_all_material_expressions(mat)
    set_prop(mat, "material_domain", enum("MaterialDomain", "MD_DEFERRED_DECAL"))
    set_prop(mat, "blend_mode", enum("BlendMode", "BLEND_TRANSLUCENT"))
    set_prop(mat, "decal_blend_mode", enum("DecalBlendMode", "DBM_D_BUFFER_COLOR_NORMAL_ROUGHNESS"))
    params = define_decal_params()
    g = Graph(mat, False, DECAL_MASTER_NAME, params, textures)
    P = g.P

    g.section("1 | UV (mesh UV0 = sheet)", C_UV)
    uv = g.texcoord(0) * P("Decal UV Tiling") + P("Decal UV Offset").mask("rg")

    g.section("2 | DECAL SHEET", C_LAYER)
    col = g.sample_param("Decal Color Map", uv)
    alpha = g.alpha_of(col)
    nrm = g.sample_param("Decal Normal Map", uv)
    orm = g.sample_param("Decal ORM Map", uv)

    g.section("3 | LOOK", C_POST)
    grey = g.desaturate(col, 1.0)
    color = g.lerp(grey, col, P("Decal Saturation")) * P("Decal Tint") * P("Decal Brightness")
    opacity = ((alpha - 0.5) * P("Decal Opacity Contrast") + 0.5).sat() * P("Decal Opacity")
    normal = normal_with_strength(g, nrm, P("Decal Normal Strength"))
    rough = g.lerp(P("Decal Roughness Min"), P("Decal Roughness Max"), orm.mask("g")).sat()
    metal = (orm.mask("b") * P("Decal Metallic")).sat()
    emissive = g.static_switch(P("Decal Use Emissive"), color * P("Decal Emissive Intensity"), g.vec3(0.0, 0.0, 0.0))

    g.section("4 | OUTPUTS", C_OUT)
    connect_property(g, "MP_BASE_COLOR", color, 3)
    connect_property(g, "MP_METALLIC", metal, 1)
    connect_property(g, "MP_ROUGHNESS", rough, 1)
    connect_property(g, "MP_NORMAL", normal, 3)
    connect_property(g, "MP_OPACITY", opacity, 1)
    connect_property(g, "MP_EMISSIVE_COLOR", emissive, 3)
    g.prune()
    g.finish()
    mel.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    return mat, g


# ==============================================================================
# 8. TEXTURES: flat placeholders (parameter defaults) + procedural demo textures
# ------------------------------------------------------------------------------
# No external files are needed: PNGs are written with plain Python (zlib), imported
# with the normal import pipeline and given the correct compression / sRGB settings.
# The import settings matter: the sampler type of a texture parameter must match the
# texture (Color <-> sRGB colour, Normal <-> Normalmap, Masks <-> Masks no-sRGB),
# otherwise Unreal reports "Sampler type is X, should be Y".
# ==============================================================================
def png_bytes(width, height, rgba):
    """8-bit RGBA PNG from width*height*4 bytes."""
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)                                        # filter type 0 (None)
        raw += rgba[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


_TEMP_PATHS = []      # temporary PNGs written for import; removed at the end of main() (an import may be asynchronous)


def cleanup_temp_files():
    for path in reversed(_TEMP_PATHS):
        try:
            if os.path.isdir(path):
                os.rmdir(path)
            else:
                os.remove(path)
        except OSError:
            pass
    del _TEMP_PATHS[:]


def import_texture(name, width, height, rgba, compression, srgb, normal_map=False, overwrite=None):
    eal = unreal.EditorAssetLibrary
    full = TEXTURES_PATH + "/" + name
    if overwrite is None:
        overwrite = OVERWRITE_EXISTING_TEXTURES
    if eal.does_asset_exist(full) and not overwrite:
        return eal.load_asset(full)
    eal.make_directory(TEXTURES_PATH)
    tmpdir = tempfile.mkdtemp(prefix="mm_tex_")
    png_path = os.path.join(tmpdir, name + ".png")
    _TEMP_PATHS.extend([tmpdir, png_path])
    with open(png_path, "wb") as f:
        f.write(png_bytes(width, height, rgba))
    task = unreal.AssetImportTask()
    set_prop(task, "filename", png_path)
    set_prop(task, "destination_path", TEXTURES_PATH)
    set_prop(task, "destination_name", name)
    set_prop(task, "replace_existing", True)
    set_prop(task, "automated", True)
    set_prop(task, "save", False)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    tex = eal.load_asset(full)
    if tex is None:
        raise BuildError("Texture import failed for %s" % full)
    set_prop(tex, "compression_settings", enum("TextureCompressionSettings", compression))
    set_prop(tex, "srgb", bool(srgb))
    if normal_map:
        set_prop(tex, "lod_group", enum("TextureGroup", "TEXTUREGROUP_WORLD_NORMAL_MAP"), required=False)
    eal.save_loaded_asset(tex)
    return tex


def _srgb8(linear):
    """Linear 0..1 -> 8-bit sRGB, so a placeholder texture decodes back to the intended linear colour."""
    c = min(1.0, max(0.0, linear))
    v = 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055
    return int(round(v * 255.0))


# key -> (asset name, RGBA, compression, sRGB, is normal map)
PLACEHOLDERS = {
    "white": ("T_MM_White", (255, 255, 255, 255), "TC_DEFAULT", True, False),
    "black": ("T_MM_Black", (0, 0, 0, 255), "TC_DEFAULT", True, False),
    "flatnormal": ("T_MM_FlatNormal", (128, 128, 255, 255), "TC_NORMALMAP", False, True),
    "ormh": ("T_MM_ORMH_Default", (255, 128, 0, 128), "TC_MASKS", False, False),       # AO 1, rough .5, metal 0, height .5
    "mask_black": ("T_MM_Mask_Default", (0, 0, 0, 255), "TC_MASKS", False, False),       # no wear/dirt/scratches, AO 1
    "gray": ("T_MM_Gray", (128, 128, 128, 255), "TC_MASKS", False, False),               # neutral breakup / macro
    "white_mask": ("T_MM_WhiteMask", (255, 255, 255, 255), "TC_MASKS", False, False),
}
for _key, _label, _group, _colour in LAYERS:           # the colour of an empty layer lives in its placeholder albedo
    PLACEHOLDERS["alb_" + _key.lower()] = ("T_MM_%s_Albedo_Default" % _label.replace(" ", ""),
                                           tuple(_srgb8(c) for c in _colour) + (255,), "TC_DEFAULT", True, False)


def ensure_placeholder_textures():
    eal = unreal.EditorAssetLibrary
    out = {}
    for key, (name, rgba, tc, srgb, is_normal) in PLACEHOLDERS.items():
        if CREATE_DEFAULT_TEXTURES:
            out[key] = import_texture(name, 8, 8, bytes(rgba) * 64, tc, srgb, is_normal)
        else:
            tex = eal.load_asset(TEXTURES_PATH + "/" + name)
            if tex is None:
                raise BuildError("Placeholder texture %s/%s is missing - set CREATE_DEFAULT_TEXTURES = True" % (TEXTURES_PATH, name))
            out[key] = tex
    return out


# ---- procedural demo textures (pure Python, deterministic, tileable) ---------------------
class Rng:
    """Tiny LCG so the demo textures are identical on every machine."""

    def __init__(self, seed):
        self.s = (seed * 2654435761 + 1) & 0x7FFFFFFF

    def next(self):
        self.s = (self.s * 1103515245 + 12345) & 0x7FFFFFFF
        return self.s / 0x7FFFFFFF


def _smooth(t):
    return t * t * (3.0 - 2.0 * t)


def value_noise(size, cells, seed):
    """Tileable value noise, size*size floats in 0..1."""
    rng = Rng(seed)
    lat = [[rng.next() for _ in range(cells)] for _ in range(cells)]
    out = [0.0] * (size * size)
    for y in range(size):
        fy = y * cells / float(size)
        y0 = int(fy)
        ty = _smooth(fy - y0)
        r0, r1 = lat[y0 % cells], lat[(y0 + 1) % cells]
        for x in range(size):
            fx = x * cells / float(size)
            x0 = int(fx)
            tx = _smooth(fx - x0)
            x1 = (x0 + 1) % cells
            x0 %= cells
            a = r0[x0] + (r0[x1] - r0[x0]) * tx
            b = r1[x0] + (r1[x1] - r1[x0]) * tx
            out[y * size + x] = a + (b - a) * ty
    return out


def fbm(size, base_cells, octaves, seed, contrast=1.6):
    total = [0.0] * (size * size)
    amp, norm, cells = 1.0, 0.0, base_cells
    for o in range(octaves):
        n = value_noise(size, cells, seed + o * 101)
        for i in range(size * size):
            total[i] += n[i] * amp
        norm += amp
        amp *= 0.5
        cells *= 2
    return [min(1.0, max(0.0, (t / norm - 0.5) * contrast + 0.5)) for t in total]


def _b(x):
    return 0 if x <= 0.0 else 255 if x >= 1.0 else int(x * 255.0 + 0.5)


def pack_rgba(n, fn):
    out = bytearray()
    for i in range(n):
        r, g, b, a = fn(i)
        out += bytes((_b(r), _b(g), _b(b), _b(a)))
    return bytes(out)


def normal_from_height(h, size, strength):
    """Tangent-space normal map in Unreal's DirectX convention (green points DOWN the image)."""
    px = bytearray()
    for y in range(size):
        ym, yp = ((y - 1) % size) * size, ((y + 1) % size) * size
        row = y * size
        for x in range(size):
            dx = h[row + (x + 1) % size] - h[row + (x - 1) % size]
            dy = h[yp + x] - h[ym + x]
            nx, ny, nz = -dx * strength, -dy * strength, 1.0
            ln = math.sqrt(nx * nx + ny * ny + nz * nz)
            px += bytes((_b(nx / ln * 0.5 + 0.5), _b(ny / ln * 0.5 + 0.5), _b(nz / ln * 0.5 + 0.5), 255))
    return bytes(px)


def brick_height_and_id(size, rows=8, cols=4, mortar=2.0, seed=3):
    rh, bw = size / float(rows), size / float(cols)
    noise = fbm(size, 16, 3, seed, 1.2)
    rng_tab = {}
    h, ids = [0.0] * (size * size), [0.0] * (size * size)
    for y in range(size):
        row = int(y / rh)
        fy = y - row * rh
        off = bw * 0.5 if row % 2 else 0.0
        for x in range(size):
            xx = (x + off) % size
            col = int(xx / bw)
            fx = xx - col * bw
            d = min(fy, rh - fy, fx, bw - fx)
            t = _smooth(min(1.0, max(0.0, (d - mortar * 0.5) / (mortar + 1.5))))
            if (row, col) not in rng_tab:
                rng_tab[(row, col)] = Rng(seed + row * 17 + col * 31).next()
            ids[y * size + x] = rng_tab[(row, col)]
            h[y * size + x] = 0.08 + t * (0.70 + 0.22 * noise[y * size + x])
    return h, ids


def line_mask(size, lines, seed):
    """Thin random scratch lines, 0..1."""
    rng = Rng(seed)
    m = [0.0] * (size * size)
    for _ in range(lines):
        x, y = rng.next() * size, rng.next() * size
        ang = rng.next() * math.pi
        ln = 8 + rng.next() * 34
        dx, dy = math.cos(ang), math.sin(ang)
        for t in range(int(ln)):
            ix, iy = int(x + dx * t) % size, int(y + dy * t) % size
            m[iy * size + ix] = 1.0
    return m


def ensure_demo_textures():
    """Creates the demo texture set; returns {key: Texture}. Existing textures are kept."""
    log("Creating procedural demo textures (a few seconds) ...")
    N = 128
    T = {}

    def tex(key, name, size, rgba, tc="TC_DEFAULT", srgb=True, is_normal=False):
        T[key] = import_texture(name, size, size, rgba, tc, srgb, is_normal)

    # each texture is only generated when its asset does not exist yet (cheap re-runs)
    def missing(*names):
        return any(not unreal.EditorAssetLibrary.does_asset_exist(TEXTURES_PATH + "/" + n) for n in names) \
            or OVERWRITE_EXISTING_TEXTURES

    def load(key, name):
        T[key] = unreal.EditorAssetLibrary.load_asset(TEXTURES_PATH + "/" + name)

    sets = {
        "paint": ("T_MM_Demo_Paint_A", "T_MM_Demo_Paint_N", "T_MM_Demo_Paint_ORMH"),
        "rust": ("T_MM_Demo_Rust_A", "T_MM_Demo_Rust_N", "T_MM_Demo_Rust_ORMH"),
        "dirt": ("T_MM_Demo_Dirt_A", "T_MM_Demo_Dirt_N", "T_MM_Demo_Dirt_ORMH"),
        "plaster": ("T_MM_Demo_Plaster_A", "T_MM_Demo_Plaster_N", "T_MM_Demo_Plaster_ORMH"),
        "brick": ("T_MM_Demo_Brick_A", "T_MM_Demo_Brick_N", "T_MM_Demo_Brick_ORMH"),
        "moss": ("T_MM_Demo_Moss_A", "T_MM_Demo_Moss_N", "T_MM_Demo_Moss_ORMH"),
    }

    def material_set(key, height, albedo_fn, orm_fn, normal_strength):
        a, n, o = sets[key]
        if not missing(a, n, o):
            load(key + "_a", a), load(key + "_n", n), load(key + "_orm", o)
            return
        tex(key + "_a", a, N, pack_rgba(N * N, lambda i: albedo_fn(i) + (1.0,)))
        tex(key + "_n", n, N, normal_from_height(height, N, normal_strength), "TC_NORMALMAP", False, True)
        tex(key + "_orm", o, N, pack_rgba(N * N, orm_fn), "TC_MASKS", False)

    # paint: near-white so the Tint colours it; mild orange-peel normal
    n1 = fbm(N, 16, 3, 11)
    material_set("paint", n1, lambda i: (0.90 + 0.08 * n1[i],) * 3,
                 lambda i: (1.0, 0.42 + 0.10 * n1[i], 0.0, 0.35 + 0.5 * n1[i]), 1.5)
    # rust: orange/brown, rough, strong height variation
    n2, n2b = fbm(N, 6, 5, 21), fbm(N, 12, 4, 22)
    material_set("rust", n2, lambda i: (0.30 + 0.45 * n2[i], 0.10 + 0.25 * n2[i], 0.04 + 0.08 * n2b[i]),
                 lambda i: (0.6 + 0.4 * n2b[i], 0.70 + 0.25 * n2[i], 0.15, n2[i]), 4.0)
    # dirt: muddy brown grime (these are sRGB values; the layer's tint stays white)
    n3 = fbm(N, 5, 5, 31)
    material_set("dirt", n3, lambda i: (0.27 + 0.14 * n3[i], 0.20 + 0.10 * n3[i], 0.13 + 0.07 * n3[i]),
                 lambda i: (1.0, 0.92, 0.0, n3[i]), 3.0)
    # moss: soft green growth
    n5 = fbm(N, 9, 5, 91)
    material_set("moss", n5, lambda i: (0.20 + 0.12 * n5[i], 0.34 + 0.22 * n5[i], 0.07 + 0.06 * n5[i]),
                 lambda i: (0.8 + 0.2 * n5[i], 0.88, 0.0, n5[i]), 4.0)
    # plaster
    n4 = fbm(N, 10, 5, 41)
    material_set("plaster", n4, lambda i: (0.78 + 0.10 * n4[i], 0.75 + 0.10 * n4[i], 0.68 + 0.09 * n4[i]),
                 lambda i: (1.0, 0.88, 0.0, 0.3 + 0.7 * n4[i]), 3.5)
    # brick (+ mortar)
    bh, bid = brick_height_and_id(N)
    material_set("brick", bh, lambda i: ((0.46 + 0.22 * bid[i]) * (0.35 + 0.65 * bh[i]) + 0.10 * (1 - bh[i]),
                                         (0.16 + 0.08 * bid[i]) * (0.35 + 0.65 * bh[i]) + 0.10 * (1 - bh[i]),
                                         (0.10 + 0.05 * bid[i]) * (0.35 + 0.65 * bh[i]) + 0.09 * (1 - bh[i])),
                 lambda i: (0.35 + 0.65 * bh[i], 0.86, 0.0, bh[i]), 5.0)

    if missing("T_MM_Demo_Mask"):
        S = 256
        wn, dn = fbm(S, 5, 5, 51), fbm(S, 4, 5, 52)
        sc = line_mask(S, 34, 53)

        def border(i):
            x, y = i % S, i // S
            d = min(x, y, S - 1 - x, S - 1 - y) / float(S)
            return max(0.0, 1.0 - d * 7.0)

        def mask_px(i):
            y = (i // S) / float(S)
            edge = border(i)
            wear = min(1.0, max(0.0, (wn[i] - 0.55) * 3.0 + 0.5 * edge + 0.15))
            dirt = min(1.0, max(0.0, (0.15 + 0.85 * y * y) * (0.35 + 0.9 * dn[i]) - 0.1))
            ao = 1.0 - 0.45 * edge
            return (wear, dirt, sc[i], ao)
        tex("mask", "T_MM_Demo_Mask", S, pack_rgba(S * S, mask_px), "TC_MASKS", False)
    else:
        load("mask", "T_MM_Demo_Mask")
    if missing("T_MM_Demo_Breakup"):
        nr, ng, nb = fbm(N, 8, 5, 61, 1.4), fbm(N, 8, 5, 62, 1.4), fbm(N, 8, 5, 63, 1.4)
        tex("breakup", "T_MM_Demo_Breakup", N, pack_rgba(N * N, lambda i: (nr[i], ng[i], nb[i], 1.0)), "TC_MASKS", False)
    else:
        load("breakup", "T_MM_Demo_Breakup")
    if missing("T_MM_Demo_DetailNormal"):
        nd = fbm(N, 32, 3, 71, 1.0)
        tex("detail_n", "T_MM_Demo_DetailNormal", N, normal_from_height(nd, N, 2.0), "TC_NORMALMAP", False, True)
    else:
        load("detail_n", "T_MM_Demo_DetailNormal")

    # decal sheet: 2x2 cells - hazard stripes | round warning sticker / arrow sign | grime stain
    if missing("T_MM_Demo_DecalSheet_C", "T_MM_Demo_DecalSheet_ORM"):
        S = 256
        stain = fbm(S, 5, 5, 81, 1.3)

        def decal_px(i):
            x, y = i % S, i // S
            cx, cy = (x % 128) / 127.0, (y % 128) / 127.0
            cell = (1 if x >= 128 else 0) + (2 if y >= 128 else 0)
            if cell == 0:                                    # hazard stripes band
                inside = 0.08 < cx < 0.92 and 0.30 < cy < 0.70
                stripe = int((cx + cy) * 9) % 2
                col = (0.96, 0.78, 0.05) if stripe else (0.05, 0.05, 0.05)
                return col + (1.0 if inside else 0.0,)
            if cell == 1:                                    # round sticker with an exclamation mark
                d = math.hypot(cx - 0.5, cy - 0.5)
                bar = abs(cx - 0.5) < 0.05 and 0.22 < cy < 0.60
                dot = math.hypot(cx - 0.5, cy - 0.75) < 0.06
                if d > 0.44:
                    return (0.0, 0.0, 0.0, 0.0)
                if d > 0.38 or bar or dot:
                    return (0.04, 0.04, 0.04, 1.0)
                return (0.96, 0.78, 0.05, 1.0)
            if cell == 2:                                    # arrow sign
                inside = 0.1 < cx < 0.9 and 0.1 < cy < 0.9
                shaft = 0.42 < cy < 0.58 and 0.2 < cx < 0.62
                head = cx >= 0.55 and abs(cy - 0.5) < (0.9 - cx) * 0.85 + 0.0 and cx < 0.82
                col = (0.95, 0.95, 0.95) if (shaft or head) else (0.05, 0.20, 0.60)
                return col + (1.0 if inside else 0.0,)
            v = stain[i]                                     # grime stain
            a = min(1.0, max(0.0, (v - 0.35) * 2.5)) * max(0.0, 1.0 - 2.0 * math.hypot(cx - 0.5, cy - 0.5))
            return (0.10, 0.07, 0.05, a)
        px = pack_rgba(S * S, decal_px)
        tex("decal_c", "T_MM_Demo_DecalSheet_C", S, px, "TC_DEFAULT", True)
        tex("decal_orm", "T_MM_Demo_DecalSheet_ORM", S, pack_rgba(S * S, lambda i: (1.0, 0.45, 0.0, 1.0)), "TC_MASKS", False)
    else:
        load("decal_c", "T_MM_Demo_DecalSheet_C")
        load("decal_orm", "T_MM_Demo_DecalSheet_ORM")
    return T


# ==============================================================================
# 9. DEMO MATERIAL INSTANCES
# ------------------------------------------------------------------------------
# Different looks from ONE master - exactly what the assignment asks for. They also
# double as templates: duplicate one, swap the textures, change the colours.
# ==============================================================================
def _parameter_names(getter, parent):
    """Lower-cased parameter names of `parent` (None if this engine lacks the helper -> no name check)."""
    try:
        names = {str(n).lower() for n in getter(parent)}
    except Exception:                                       # noqa: BLE001
        return None
    return names or None                                    # an empty list would only mean the helper is not usable


def make_instance(name, parent, scalars=None, vectors=None, textures=None, statics=None):
    """
    Create a Material Instance Constant under `parent` (the master, or another instance) with parameter overrides.

    The set_material_instance_*_parameter_value functions are documented to return success, but Epic's issue UE-291403
    reports that they return False even when the value was applied. So the return values are ignored; instead every name
    is checked against the parent's parameter list first (a typo cannot hide), and the scalars are read back at the end.
    """
    mel = unreal.MaterialEditingLibrary
    eal = unreal.EditorAssetLibrary
    full = INSTANCES_PATH + "/" + name
    if eal.does_asset_exist(full):
        log("instance %s already exists - left untouched" % name)
        return eal.load_asset(full)
    inst = get_or_create_asset(INSTANCES_PATH, name, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew)
    mel.set_material_instance_parent(inst, parent)
    known = {"scalar": _parameter_names(mel.get_scalar_parameter_names, parent),
             "vector": _parameter_names(mel.get_vector_parameter_names, parent),
             "texture": _parameter_names(mel.get_texture_parameter_names, parent),
             "static": _parameter_names(mel.get_static_switch_parameter_names, parent)}

    def exists(kind, key):
        names = known[kind]
        if names is not None and key.lower() not in names:
            warn("%s: the parent has no %s parameter called '%s' - skipped" % (name, kind, key))
            return False
        return True

    for key, val in (statics or {}).items():
        if exists("static", key):
            try:                                            # one recompile at the end instead of one per switch
                mel.set_material_instance_static_switch_parameter_value(inst, key, bool(val), update_material_instance=False)
            except TypeError:                               # older engines have no such argument
                mel.set_material_instance_static_switch_parameter_value(inst, key, bool(val))
    applied = {}
    for key, val in (scalars or {}).items():
        if exists("scalar", key):
            mel.set_material_instance_scalar_parameter_value(inst, key, float(val))
            applied[key] = float(val)
    for key, val in (vectors or {}).items():
        if exists("vector", key):
            mel.set_material_instance_vector_parameter_value(inst, key, linear_color(val if len(val) == 4 else tuple(val) + (1.0,)))
    for key, val in (textures or {}).items():
        if val is None:
            warn("%s: no texture to assign to '%s'" % (name, key))
        elif exists("texture", key):
            mel.set_material_instance_texture_parameter_value(inst, key, val)
    mel.update_material_instance(inst)

    unreadable = 0
    for key, val in applied.items():
        try:
            if abs(float(mel.get_material_instance_scalar_parameter_value(inst, key)) - val) > 1e-4:
                unreadable += 1
        except Exception:                                   # noqa: BLE001
            unreadable += 1
    if unreadable:
        warn("%s: %d scalar override(s) did not read back as set. Open the instance and check its parameters; "
             "if they look right this is just the engine's getter." % (name, unreadable))
    eal.save_loaded_asset(inst)
    log("instance created: %s" % full)
    return inst


def make_demo_instances(master, decal, textures, demo):
    if not demo:
        warn("Demo textures are disabled: the demo instances are skipped.")
        return
    D = demo

    def layer_tex(label, key):
        return {label + " Albedo": D[key + "_a"], label + " Normal Map": D[key + "_n"], label + " ORMH Map": D[key + "_orm"]}

    # MI_Demo_Base is the PARENT of every surface demo: it holds the textures they share and the single PREVIEW switch
    # (the engine's cube / sphere have ONE UV set, so the demo mask is read with the tiling UVs). Your own instances
    # for a mesh with a real second UV set must NOT have that switch - make them from M_Master_Surface.
    base_tex = {"Mask Texture": D["mask"], "Breakup Texture": D["breakup"], "Detail Normal Texture": D["detail_n"],
                "Macro Texture": D["breakup"]}
    base_tex.update(layer_tex("Base", "paint"))
    base_tex.update(layer_tex("Wear", "rust"))
    base_tex.update(layer_tex("Dirt", "dirt"))
    parent = make_instance("MI_Demo_Base", master, scalars={"Global Tiling": 2.0}, textures=base_tex,
                           statics={"Mask Uses Tiling UV": True})

    # three crates = ONE parent, three sets of numbers (red: rust under the paint, blue: bare steel under it, cream: old and dirty)
    make_instance("MI_Demo_Crate_Red", parent,
                  scalars={"Wear Intensity": 1.1, "Wear Softness": 0.06, "Dirt Intensity": 0.9, "Wear Brightness": 1.3,
                           "Base Roughness Min": 0.25, "Base Roughness Max": 0.55},
                  vectors={"Base Tint": (0.72, 0.06, 0.04)})
    make_instance("MI_Demo_Crate_Blue", parent,
                  scalars={"Wear Intensity": 0.8, "Dirt Intensity": 1.2, "Scratch Intensity": 1.3, "Wear Edge Strength": 0.9,
                           "Wear Saturation": 0.0, "Wear Brightness": 1.8, "Wear Roughness Max": 0.45},
                  vectors={"Base Tint": (0.05, 0.12, 0.50), "Wear Tint": (0.85, 0.90, 1.0)})
    make_instance("MI_Demo_Crate_Cream_Weathered", parent,
                  scalars={"Wear Intensity": 1.4, "Wear Softness": 0.04, "Dirt Intensity": 1.1, "Dirt AO Boost": 0.8,
                           "Macro Intensity": 0.4, "Base Rotation": 90.0, "Wear Brightness": 1.2},
                  vectors={"Base Tint": (0.85, 0.80, 0.66)},
                  statics={"Use Macro Variation": True, "Use Instance Variation": True, "Macro Uses World Space": True})

    # vertex painting: plaster on top, brick underneath it (paint Red), moss as a second paintable layer (paint Green).
    # The mask only adds grime at the bottom here (Use Wear Layer is OFF), so the painted layers are what you look at.
    vp_tex = {}
    vp_tex.update(layer_tex("Base", "plaster"))
    vp_tex.update(layer_tex("Dirt", "dirt"))
    vp_tex.update(layer_tex("Vertex 1", "brick"))
    vp_tex.update(layer_tex("Vertex 2", "moss"))
    make_instance("MI_Demo_Plaster_Brick_VertexPaint", parent,
                  scalars={"Vertex 1 Softness": 0.05, "Vertex 1 Height Influence": 0.9, "Vertex 1 Breakup": 0.4,
                           "Vertex 2 Softness": 0.12, "Dirt Intensity": 0.8},
                  textures=vp_tex, statics={"Use Wear Layer": False, "Use Vertex Layer 2": True})

    make_instance("MI_Demo_Debug_Masks", parent, scalars={"Debug Mode": 1.0}, statics={"Debug View": True})

    decal_common = {"Decal Color Map": D["decal_c"], "Decal ORM Map": D["decal_orm"]}
    for name, off in (("MI_Demo_Decal_Hazard", (0.0, 0.0)), ("MI_Demo_Decal_Sticker", (0.5, 0.0)),
                      ("MI_Demo_Decal_Stain", (0.5, 0.5))):
        make_instance(name, decal, scalars={"Decal UV Tiling": 0.5},
                      vectors={"Decal UV Offset": (off[0], off[1], 0.0)}, textures=decal_common)


# ==============================================================================
# 10. MAIN
# ==============================================================================
def report_statistics(mat, label):
    try:
        st = unreal.MaterialEditingLibrary.get_statistics(mat)
        log("%s: %d pixel-shader instructions, %d texture samples, %d samplers (shaders may still be compiling - "
            "open the material for final numbers)" % (label, st.num_pixel_shader_instructions,
                                                      st.num_pixel_texture_samples, st.num_samplers))
    except Exception as exc:                                # noqa: BLE001
        warn("statistics not available: %s" % exc)


def main():
    try:
        return _build_everything()
    finally:
        cleanup_temp_files()


def _build_everything():
    log("=" * 70)
    log("Building the master materials under %s" % ROOT_PATH)
    textures = ensure_placeholder_textures()
    demo = ensure_demo_textures() if CREATE_DEMO_TEXTURES else {}

    blocks = make_blocks()
    mat = graph = None
    mode = "inline"
    if USE_MATERIAL_FUNCTIONS:
        try:
            fn_assets = build_all_functions(blocks, textures)
            mat, graph = build_surface_master(blocks, fn_assets, textures)
            mode = "functions"
        except Exception as exc:                            # noqa: BLE001
            err("Function-based build failed: %s" % exc)
            err(traceback.format_exc())
            warn("Retrying with everything expanded inline (no Material Function assets).")
            mat = graph = None
    if mat is None:
        mat, graph = build_surface_master(blocks, None, textures)
        mode = "inline"
    log("%s built in '%s' mode (%d nodes)" % (SURFACE_MASTER_NAME, mode, len(graph.nodes)))
    report_statistics(mat, SURFACE_MASTER_NAME)

    decal, dgraph = build_decal_master(textures)
    log("%s built (%d nodes)" % (DECAL_MASTER_NAME, len(dgraph.nodes)))

    if CREATE_DEMO_INSTANCES:
        make_demo_instances(mat, decal, textures, demo)

    log("DONE. Open %s/%s, then right-click it > Create Material Instance." % (ROOT_PATH, SURFACE_MASTER_NAME))
    log("Material compile errors do NOT show up here: open the master and look for red nodes / the Stats panel, "
        "and read Window > Developer Tools > Message Log. See Docs/07_Troubleshooting_and_Performance.md")
    return mat


# Runs when executed inside Unreal (also via "Execute Python Script", where __name__ may not be "__main__").
# The offline test-suite sets MM_NO_AUTORUN=1 so it can import this file and drive the pieces.
if unreal is not None and not os.environ.get("MM_NO_AUTORUN"):
    main()
