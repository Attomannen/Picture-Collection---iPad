"""
================================================================================
 M_Master  -  layered AAA-style master material for Unreal Engine 5   (Python Editor Script)
================================================================================
 Run this file once inside the Unreal Editor. It builds ONE master material, M_Master, with 266 artist-facing parameters
 (21 groups; 24 static switches that remove unused features, and their texture samples, from the shader) and 13 tiny
 placeholder textures that are the defaults of the texture slots. Nothing else is created.
 Built for Unreal Engine 5.x and the classic material pins (Substrate off, the default); with Substrate on the engine converts
 them, which has not been tested.

 WHAT THE MATERIAL DOES
   Layer stack, bottom to top:   Base > Wear > Vertex 1 > Vertex 2 > Vertex 3 > Dirt > Scratches > Top Coat
   Every layer has its own Albedo / Normal / ORMH textures and: tint, hue shift, saturation, brightness, tiling, rotation,
   offset, normal flip / intensity / FLATTEN, roughness range, metallic, AO, height contrast / offset.

   RGB MASK    one RGBA texture on the UNIQUE uv set:   R = wear   G = dirt   B = scratches   A = baked AO
   VERTEX PAINT Mesh Paint colour:  R -> Vertex Layer 1,  G -> Vertex Layer 2,  B -> Vertex Layer 3,  A -> extra dirt
   BLENDING    each layer is revealed through the height of its own texture and a tiling breakup noise, so a soft 1k mask
               or a painted vertex gradient turns into a crisp, organic edge (Softness / Height Influence / Breakup);
               every layer also has an Opacity.
   NORMALS     FlattenNormal (Epic's Material Function when the engine has it, otherwise identical nodes) is used for: the
               per-layer Normal Flatten, the "cover flatten" that lets Wear / Dirt / Vertex / Coat layers bury the relief
               below them, scratches, puddles, thick dirt / snow over the detail normal, and the distance fade of the detail
               normal and of the whole normal. Layers are combined with a reoriented (angle-correct) normal blend, so no
               layer loses its detail.
   LOOK        global hue / saturation / contrast / tint / brightness, albedo clamp, roughness offset and floor, specular,
               baked AO, macro variation, per-object and per-instance variation (HISM / foliage), wetness with height-filled
               puddles, world-up Top Coat (dust / snow / moss), parallax, emissive (pulse), opacity mask, 24 debug views
   ENGINE      Nanite + instanced-mesh usage flags, shared wrap samplers (no sampler-slot limit), normal-curvature-to-roughness
               (specular anti-aliasing)

 HOW TO RUN
   1. Edit > Plugins > enable "Python Editor Script Plugin", restart the editor.
   2. Close M_Master (and its instances) if they are open. Tools > Execute Python Script...  and pick this file
      (or: Output Log > Cmd >  py "C:/full/path/build_master_material.py").
   3. Content Browser > MasterMaterial > M_Master > right-click > Create Material Instance.
   Allow a minute or two: the editor is busy while it builds and compiles the material. The script can be run again at any
   time: it rebuilds M_Master from scratch, instances keep their values (parameters are matched by name) and the placeholder
   textures are never replaced. Progress is in the Output Log (filter: MasterMaterial).
   Compile errors of the material itself are NOT printed there: open M_Master and look for red nodes, the Stats panel and
   Window > Developer Tools > Message Log.
   If the normals look wrong or flat, set USE_ENGINE_FUNCTIONS = False below and run again (uses plain nodes instead of Epic's
   FlattenNormal function).

 WHAT YOU FEED IT
   UVs      UV0 = tiling (texel density, faces may overlap)      UV1 = unique 0-1 layout without overlap (the RGBA mask,
            emissive).  Unreal builds the tangents of normal maps from UV0, so keep the tiling set there. Untick "Generate
            Lightmap UVs" on import (it would overwrite UV1).
   Albedo   sRGB colour (compression: Default)
   Normal   compression "Normalmap", DirectX convention (green down). OpenGL maps (Substance Painter's default): set the
            layer's "Normal Flip Green" to 1.
   ORMH     R = AO, G = roughness, B = metallic, A = height  ->  compression "Masks (no sRGB)"
            (Substance Painter: its packed Unreal export preset gives ORM in RGB; put the height into the alpha channel with a
            custom preset.)
   Mask     R wear, G dirt, B scratches, A baked AO, on the unique UVs  ->  "Masks (no sRGB)"
   Breakup  tileable noise, R = wear edges, G = dirt edges, B = scratch / vertex paint / coat edges  ->  "Masks (no sRGB)"
   Vertex   Modes > Mesh Paint > Vertex Color: Paint Color BLACK, Erase Color white, Channels: Red only -> Vertex Layer 1
            (Green -> Layer 2, Blue -> Layer 3; switch them on in the instance). An unpainted mesh is white = no paint; a mesh
            that arrives with its own vertex colours needs Mesh Paint > Fill with white first.
            Nanite meshes ignore per-instance painted vertex colours: paint on a non-Nanite mesh.
   If a texture node shows "Sampler type is X, should be Y", the texture's import settings do not match its role (above).

 THREE LOOKS FROM ONE MASTER (instances; everything not mentioned stays at its default)
   Worn red paint     "Base Tint" red, "Wear Intensity" 1.2, "Wear Softness" 0.05, "Scratch Intensity" 1.3
   Clean plastic      "Wear Intensity" 0, "Dirt Intensity" 0.2, "Scratch Intensity" 0, "Base Metallic" 0, "Base Roughness Max" 0.4
   Mossy wet wall     switch on "Use Vertex Layer 2" (moss textures) and "Use Wetness", "Global Tint" slightly green
   For cut-outs set the instance's Blend Mode to Masked (or Translucent) and switch on "Use Opacity Mask".
   The master is a Surface material: a mesh decal needs the Deferred Decal domain, which an instance cannot change.

 READING THE CODE   1 configuration | 2 helpers | 3 graph-building mini-language | 4 parameter table (every name, default,
   range and tooltip) | 5 shader building blocks | 6 the master, one numbered block per stage | 7 placeholder textures | 8 main.
   The finished graph is laid out in the same numbered blocks; a small marker node above each block carries its title as a
   comment (Python cannot draw comment boxes).
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
except ImportError:                       # lets the file be imported in plain Python (offline tests)
    unreal = None


# ==============================================================================
# 1. CONFIGURATION  (safe to edit)
# ==============================================================================
ROOT_PATH = "/Game/MasterMaterial"
MASTER_NAME = "M_Master"
TEXTURES_PATH = ROOT_PATH + "/Textures"

CREATE_PLACEHOLDER_TEXTURES = True   # tiny flat textures: the defaults of the texture parameters
PRINT_SHADER_STATISTICS = False      # log instruction / sampler counts (makes the editor wait for a shader compile: a minute or more)
USE_ENGINE_FUNCTIONS = True          # call Epic's FlattenNormal Material Function when the engine has it (else identical nodes)
SET_USAGE_FLAGS = True               # Nanite + instanced static meshes (avoids a shader recompile later)

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
    """unreal.<enum_name>.<member> with a readable error if this Unreal version lacks it."""
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


def notify_never():
    """unreal.PropertyAccessChangeNotifyMode.NEVER, or None on an engine that does not have it."""
    mode = getattr(unreal, "PropertyAccessChangeNotifyMode", None)
    return getattr(mode, "NEVER", None) if mode is not None else None


def set_prop(obj, name, value, required=True, quiet=False):
    """
    set_editor_property with a message that names the property (names differ between engine versions).
    quiet=True skips the editor's change notification. Each NOTIFIED write to a node of a material makes the engine
    translate the whole material again - seconds per write once the material is wired up, which would add up to a frozen
    editor for the ~5000 writes of this build. So nodes are written quietly and the material is compiled once, at the end.
    """
    try:
        mode = notify_never() if quiet else None
        if mode is not None:
            obj.set_editor_property(name, value, mode)
        else:
            obj.set_editor_property(name, value)
        return True
    except Exception as exc:                       # noqa: BLE001 - Unreal raises plain Exception
        if required:
            raise BuildError("Could not set property '%s' on %s: %s" % (name, type(obj).__name__, exc))
        warn("Optional property '%s' on %s not set (%s)" % (name, type(obj).__name__, exc))
        return False


DESC_LIMIT = 170


def short_desc(text, limit=DESC_LIMIT):
    """A node's Desc is drawn ON the node and is the tooltip in the Material Instance editor, so it stays compact.
    Every parameter description is written to fit `limit`; cutting at a word boundary is only a safety net."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[:limit - 3].rsplit(" ", 1)[0].rstrip(" ,;:.") + "..."


def linear_color(r, g=None, b=None, a=1.0):
    if g is None:
        r, g, b, a = r
    return unreal.LinearColor(float(r), float(g), float(b), float(a))


# Input pin names, used only if MaterialEditingLibrary.get_material_expression_input_names is missing.
# Index 0 is always addressed with "" (= first input, documented behaviour).
FALLBACK_INPUT_PINS = {
    "Add": ["A", "B"], "Subtract": ["A", "B"], "Multiply": ["A", "B"], "Divide": ["A", "B"],
    "Min": ["A", "B"], "Max": ["A", "B"], "AppendVector": ["A", "B"], "DotProduct": ["A", "B"], "CrossProduct": ["A", "B"],
    "LinearInterpolate": ["A", "B", "Alpha"], "Clamp": ["Input", "Min", "Max"],
    "Power": ["Base", "Exp"], "Desaturation": ["Input", "Fraction"],
    "StaticSwitch": ["True", "False", "Value"], "TextureSample": ["UVs", "Tex"],
    "TextureSampleParameter2D": ["UVs", "Tex"], "BumpOffset": ["Coordinate", "Height", "HeightRatioInput"],
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
# Writing a Material graph through the raw Python API means dozens of create /
# set_editor_property / connect calls per node. Graph + V wrap that, so a block of
# shader logic reads like maths:
#
#       m = ((flag - mask).abs() * intensity).sat()
#       w = ((m * (1 + 2 * soft) - thresh) / (2 * soft)).sat()
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
        self.sources = []          # nodes feeding this one (layout depth + pruning)
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


# Layout of the finished graph: sections become blocks of columns, blocks are tiled left to right and wrap into rows.
ROW_PAD = 26            # vertical gap between two nodes of a column
COL_W = 340             # horizontal pitch of the columns inside a block
HEADER_H = 150          # room for the block's title comment
BLOCK_GAP_X = 400
BLOCK_GAP_Y = 360
SHEET_W = 16000         # a row of blocks wraps once it is wider than this
MAX_COL_H = 3400        # a column taller than this continues in a new column


class Graph:
    """Wraps the Material and everything created inside it."""

    def __init__(self, asset, label, params=None, textures=None):
        self.asset, self.label = asset, label
        self.params = params                      # ParamTable
        self.textures = textures or {}            # placeholder key -> Texture asset
        self.nodes = []
        self.section_name = "Main"
        self.section_order = []
        self.labels = []                          # the marker node of every block (see _label_node)
        self.roots = []                           # nodes that feed a material output
        self._pcache = {}
        self._warned = set()

    # --- sections (purely cosmetic: layout + a marker node per block) ---------
    def section(self, name):
        self.section_name = name
        if name not in self.section_order:
            self.section_order.append(name)
        return name

    # --- node creation ------------------------------------------------------
    def add_node(self, short, props=None, desc=None, required_props=True):
        cls = expr_class(short)
        expr = unreal.MaterialEditingLibrary.create_material_expression(self.asset, cls, 0, 0)
        if expr is None:
            raise BuildError("Engine refused to create MaterialExpression%s" % short)
        for k, v in (props or {}).items():
            set_prop(expr, k, v, required=required_props, quiet=True)
        if desc:
            set_prop(expr, "desc", desc, required=False, quiet=True)
        node = Node(expr, short, self.section_name)
        node.desc_lines = (len(desc) // 32 + 1) if desc else 0
        if self.section_name not in self.section_order:
            self.section_order.append(self.section_name)
        self.nodes.append(node)
        return node

    def link(self, src, dst_node, pin):
        """Connect V `src` into input `pin` (index or exact name) of `dst_node`."""
        if src.g is not self:
            raise BuildError("Tried to connect nodes of two different graphs")
        name = pin if isinstance(pin, str) else input_pin_name(dst_node.expr, dst_node.short, pin)
        if unreal.MaterialEditingLibrary.connect_material_expressions(src.node.expr, src.out, dst_node.expr, name):
            dst_node.sources.append(src.node)
            return
        if self._link_channel_fallback(src, dst_node, name):
            return
        raise BuildError("connect_material_expressions failed: %s[%r] -> %s.%r" %
                         (src.node.short, src.out, dst_node.short, name))

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
        return V(self, self.add_node("Constant", {"r": self._num(x, "const")}), "", 1)

    def vec2(self, x, y):
        return V(self, self.add_node("Constant2Vector", {"r": float(x), "g": float(y)}), "", 2)

    def vec3(self, r, g=None, b=None):
        if g is None:
            r, g, b = r
        return V(self, self.add_node("Constant3Vector", {"constant": linear_color(r, g, b, 1.0)}), "", 3)

    def vec4(self, r, g, b, a):
        return V(self, self.add_node("Constant4Vector", {"constant": linear_color(r, g, b, a)}), "", 4)

    # --- engine inputs ---------------------------------------------------------
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

    def vertex_normal_ws(self):
        """World-space vertex normal (the smooth mesh normal, without the normal map)."""
        return V(self, self.add_node("VertexNormalWS"), "", 3)

    def time(self):
        return V(self, self.add_node("Time"), "", 1)

    def tangent_to_world(self, v):
        """Tangent-space direction -> world space (a normal map result -> which way the pixel really faces)."""
        node = self.add_node("Transform", {
            "transform_source_type": enum("MaterialVectorCoordTransformSource", "TRANSFORMSOURCE_TANGENT"),
            "transform_type": enum("MaterialVectorCoordTransform", "TRANSFORM_WORLD")})
        self.link(v, node, 0)
        return V(self, node, "", 3)

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
        node_props, dims, links = {}, [], []
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
    def vmin(self, a, b): return self.binary("Min", a, b)

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

    def cross(self, a, b):
        if a.dim != 3 or b.dim != 3:
            raise BuildError("cross expects two float3 values")
        node = self.add_node("CrossProduct")
        self.link(a, node, 0)
        self.link(b, node, 1)
        return V(self, node, "", 3)

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
        props, links = {}, []
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

    def power(self, base, exponent):
        """Power node; `exponent` is a V or a number."""
        props = {}
        if not isinstance(exponent, V):
            props["const_exponent"] = self._num(exponent, "power")
        node = self.add_node("Power", props)
        self.link(base, node, 0)
        if isinstance(exponent, V):
            self.link(exponent, node, 1)
        return V(self, node, "", base.dim)

    def smoothstep(self, x, lo, hi):
        """Hermite smoothstep(lo, hi, x) from plain nodes (no dependence on the engine node's pin order)."""
        t = ((x - lo) / self.vmax(hi - lo, 0.0001)).sat()
        return t * t * (3.0 - t * 2.0)

    def desaturate(self, color, fraction):
        """Desaturation node: fraction 1 -> grey (luminance), 0 -> unchanged."""
        if color.dim != 3:
            raise BuildError("desaturate expects a float3")
        node = self.add_node("Desaturation", {"luminance_factors": linear_color(0.2126, 0.7152, 0.0722, 0.0)})   # Rec.709, for linear colour
        self.link(color, node, 0)
        self.link(fraction if isinstance(fraction, V) else self.const(fraction), node, 1)
        return V(self, node, "", 3)

    def broadcast(self, x, dim):
        """Scalar -> vector of `dim` components (multiply by (1,1,1))."""
        if x.dim == dim:
            return x
        if x.dim != 1:
            raise BuildError("cannot broadcast %d components to %d" % (x.dim, dim))
        ones = {2: self.vec2(1, 1), 3: self.vec3(1, 1, 1), 4: self.vec4(1, 1, 1, 1)}[dim]
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

    # --- engine nodes with more than arithmetic in them ----------------------------
    def bump_offset(self, coordinate, height, ratio):
        """Parallax: shifts `coordinate` along the view direction by height * ratio (pass the height already centred on 0).
        The reference plane stays 0: older engines subtract ReferencePlane * the node's own HeightRatio property (not the ratio pin)."""
        node = self.add_node("BumpOffset", {"reference_plane": 0.0})
        self.link(coordinate, node, 0)
        self.link(height, node, 1)
        self.link(ratio, node, 2)
        return V(self, node, "", 2)

    def call_function(self, fn, args, out_dim):
        """MaterialFunctionCall to an engine / project Material Function; `args` fill the function's inputs in order."""
        node = self.add_node("MaterialFunctionCall")
        assigned = False
        try:
            assigned = bool(node.expr.set_material_function(fn))
        except Exception as exc:                    # noqa: BLE001 - not every engine version exposes the helper
            if "set_material_function" not in self._warned:
                self._warned.add("set_material_function")
                warn("set_material_function is not available (%s); assigning the 'material_function' property instead." % exc)
        if not assigned:
            # the editor refreshes the call node's pins when this property changes (same path as picking it in Details)
            set_prop(node.expr, "material_function", fn)
        node.n_pins = max(len(args), 2)
        for i, a in enumerate(args):
            if a is not None:                       # None = leave this input at the function's own default
                self.link(a, node, i)
        return V(self, node, "", out_dim)

    def function_input_names(self, fn):
        """Input names of a Material Function as the engine lists them (probe: creates and removes one call node)."""
        mel = unreal.MaterialEditingLibrary
        node = self.add_node("MaterialFunctionCall")
        try:
            try:
                ok = bool(node.expr.set_material_function(fn))
            except Exception:                       # noqa: BLE001
                ok = False
            if not ok:
                node.expr.set_editor_property("material_function", fn)
            return [str(n) for n in mel.get_material_expression_input_names(node.expr)]
        finally:
            self.nodes.remove(node)
            try:
                mel.delete_material_expression(self.asset, node.expr)
            except Exception:                       # noqa: BLE001 - cosmetic
                pass

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
            node = self.add_node("ScalarParameter", props, desc=short_desc(d.desc, max(DESC_LIMIT, len(d.desc)) if d.name == "Debug Mode" else DESC_LIMIT))
            if d.lo is not None:
                set_prop(node.expr, "slider_max", float(d.hi), required=False, quiet=True)
                set_prop(node.expr, "slider_min", float(d.lo), required=False, quiet=True)
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
                             "Set CREATE_PLACEHOLDER_TEXTURES = True." % (d.tex, d.name))
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
        """Delete nodes that do not feed any output (probe nodes, outputs of a block nobody uses)."""
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
            if id(n) in live or n.short.endswith("Parameter"):
                continue                                    # parameter nodes stay: the instance editor lists them
            try:
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

    def _layout_block(self, nodes):
        """Column per dependency depth; a column taller than MAX_COL_H continues in a new column.
        Returns ({id(node): (dx, dy)}, width, height)."""
        in_sec = set(id(n) for n in nodes)
        depth = {}

        def dep(n):
            if id(n) in depth:
                return depth[id(n)]
            depth[id(n)] = 0                              # cycle guard
            d = 0
            for s in n.sources:
                if id(s) in in_sec:
                    d = max(d, dep(s) + 1)
            depth[id(n)] = d
            return d

        by_depth = {}
        for n in nodes:
            by_depth.setdefault(dep(n), []).append(n)
        pos, col, height = {}, 0, 0
        for d in sorted(by_depth):
            y = 0
            for n in by_depth[d]:
                w, h = self._size(n)
                if y > 0 and y + h > MAX_COL_H:
                    col += 1
                    y = 0
                pos[id(n)] = (col * COL_W, y)
                y += h + ROW_PAD
                height = max(height, y)
            col += 1
        return pos, col * COL_W, height

    def finish(self):
        """Tile the sections as blocks (left to right, wrapping into rows) and put a marker node above each.
        Blocks follow the numbers in their titles ("01 | UV SETS", "02 | RGB MASK" ...), not the order they were built in."""
        by_section = {}
        for n in self.nodes:
            by_section.setdefault(n.section, []).append(n)
        cur_x = cur_y = row_h = 0
        for sec in sorted(self.section_order):
            nodes = by_section.get(sec)
            if not nodes:
                continue
            pos, w, h = self._layout_block(nodes)
            if cur_x > 0 and cur_x + w > SHEET_W:
                cur_x, cur_y, row_h = 0, cur_y + row_h + BLOCK_GAP_Y, 0
            for n in nodes:
                dx, dy = pos[id(n)]
                n.x, n.y = cur_x + dx, cur_y + HEADER_H + dy
                set_prop(n.expr, "material_expression_editor_x", int(n.x), required=False, quiet=True)
                set_prop(n.expr, "material_expression_editor_y", int(n.y), required=False, quiet=True)
            self._label_node(sec, cur_x, cur_y)
            cur_x += w + BLOCK_GAP_X
            row_h = max(row_h, HEADER_H + h)

    def _label_node(self, text, x, y):
        """
        Marks a block: a small unconnected Constant whose description is the block's title (a node's description is drawn as
        the comment bubble above it). Python cannot create real comment boxes - a Comment expression made through
        create_material_expression is drawn as a plain node, and editing its colour in Details would crash the editor.
        """
        try:
            expr = unreal.MaterialEditingLibrary.create_material_expression(self.asset, expr_class("Constant"), int(x), int(y))
            set_prop(expr, "desc", " - ".join(line.strip() for line in text.split("\n")), required=False, quiet=True)
            self.labels.append(expr)
        except Exception as exc:                            # noqa: BLE001 - labels are cosmetic
            warn("Could not add the marker for block '%s': %s" % (text, exc))


# ==============================================================================
# 4. THE PARAMETER TABLE
# ------------------------------------------------------------------------------
# One entry per parameter: name (shown in the Material Instance editor), group,
# sort priority, default, slider range and tooltip. The graph builder creates the
# nodes from this table, so what you see in the instance is exactly what is here.
#
# Group names start with a number because Unreal sorts groups alphabetically.
# ==============================================================================
GROUPS = {
    "feat": "00 Features (static switches)",
    "glob": "01 Global Look",
    "mask": "02 RGB Mask and Breakup",
    "base": "03 Base Layer",
    "wear": "04 Wear Layer (mask R)",
    "dirt": "05 Dirt Layer (mask G)",
    "scr": "06 Scratches (mask B)",
    "vp": "07 Vertex Paint",
    "vp1": "08 Vertex Layer 1 (paint R)",
    "vp2": "09 Vertex Layer 2 (paint G) - off by default",
    "vp3": "10 Vertex Layer 3 (paint B) - off by default",
    "coat": "11 Top Coating (dust, snow, moss) - off by default",
    "det": "12 Detail Normal",
    "norm": "13 Normal Finish",
    "mac": "14 Macro Variation - off by default",
    "inst": "15 Instance Variation - off by default",
    "wet": "16 Wetness and Puddles - off by default",
    "par": "17 Parallax - off by default",
    "emi": "18 Emissive - off by default",
    "opa": "19 Opacity Mask - off by default",
    "dbg": "20 Debug",
}

# (key, label used in parameter names, group key). Bottom of the stack first.
LAYERS = [
    ("Base", "Base", "base"),
    ("Wear", "Wear", "wear"),
    ("Dirt", "Dirt", "dirt"),
    ("Vertex1", "Vertex 1", "vp1"),
    ("Vertex2", "Vertex 2", "vp2"),
    ("Vertex3", "Vertex 3", "vp3"),
    ("Coat", "Coat", "coat"),
]

DEBUG_MODES = [
    "Mask R (wear)", "Mask G (dirt)", "Mask B (scratches)", "Mask A (baked AO)",
    "Vertex colour RGB", "Vertex colour alpha", "Breakup noise (RGB)",
    "Tiling UV checker (1 square = 1 tile)", "Unique UV (U red, V green)",
    "Wear weight", "Dirt weight", "Scratch weight",
    "Vertex 1 weight", "Vertex 2 weight", "Vertex 3 weight", "Coat weight",
    "Wetness (R) and puddles (G)", "Blended height", "Final normal (n * 0.5 + 0.5)",
    "Coat slope (white = faces the coat direction)", "Albedo", "Roughness", "Metallic", "Ambient occlusion",
]


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
    g.texture(label + " Albedo", "alb_" + key.lower(), "SAMPLERTYPE_COLOR",
              "Tileable colour map, imported as sRGB colour. Empty = a flat placeholder colour, so the layer is visible before you have textures.")
    g.texture(label + " Normal Map", "flatnormal", "SAMPLERTYPE_NORMAL",
              "Tileable normal map, compression 'Normalmap'. DirectX / Unreal style (green down); an OpenGL map needs Normal Flip Green = 1.")
    g.texture(label + " ORMH Map", "ormh", "SAMPLERTYPE_MASKS",
              "Packed: R = AO, G = roughness, B = metallic, A = height (shapes the blend edges). Compression 'Masks (no sRGB)'.")
    g.vector(label + " Tint", (1.0, 1.0, 1.0), "Multiplies the albedo. White = texture unchanged. The main art-direction knob: recolour paint, rust or dirt.")
    return g


def _layer_tail(g, label, with_height=True):
    """The adjustments every layer has (after the effect-specific knobs of that layer)."""
    L = label
    g.scalar(L + " Hue Shift", 0.0, -180.0, 180.0, "Rotates the hue of this layer's albedo, in degrees (0 = unchanged).")
    g.scalar(L + " Saturation", 1.0, 0.0, 2.0, "0 = greyscale, 1 = as authored, 2 = double saturation.")
    g.scalar(L + " Brightness", 1.0, 0.0, 3.0, "Albedo multiplier (applied after the tint).")
    g.scalar(L + " Tiling", 1.0, 0.05, 16.0, "UV scale of this layer on top of Global Tiling. Different values per layer hide repetition.")
    g.scalar(L + " Rotation", 0.0, 0.0, 360.0, "UV rotation in degrees about the tile centre (the normal map is rotated with it).")
    g.vector(L + " Offset", (0.0, 0.0, 0.0), "UV shift: R = U, G = V. Type the numbers instead of using the colour picker.")
    g.scalar(L + " Normal Flip Green", 0.0, 0.0, 1.0, "0 = DirectX normal map (Unreal, green down). 1 = OpenGL map (green up): flips the green channel.")
    g.scalar(L + " Normal Intensity", 1.0, 0.0, 3.0, "Strength of this layer's normal map: 1 = as authored, above 1 = exaggerated bumps, 0 = flat.")
    g.scalar(L + " Normal Flatten", 0.0, 0.0, 1.0, "FlattenNormal on this layer's normal map: 0 = as authored, 1 = completely flat (smooths the layer, keeps the colour).")
    g.scalar(L + " Roughness Min", 0.0, 0.0, 1.0, "Roughness where the ORMH green channel is 0 (together with Max it remaps the roughness range).")
    g.scalar(L + " Roughness Max", 1.0, 0.0, 1.0, "Roughness where the ORMH green channel is 1.")
    g.scalar(L + " Metallic", 1.0, 0.0, 1.0, "Multiplier on the ORMH blue channel (metallic). 0 forces a non-metal.")
    g.scalar(L + " AO Strength", 1.0, 0.0, 1.0, "How much the ORMH red channel (AO) darkens.")
    if with_height:        # the Base layer is never "revealed", so its height only matters for parallax
        g.scalar(L + " Height Contrast", 1.0, 0.0, 4.0, "Contrast of the ORMH alpha (height) used for blend edges and puddles.")
        g.scalar(L + " Height Offset", 0.0, -1.0, 1.0, "Shifts the height up or down (which areas count as 'high').")
    return g


def define_params():
    pt = ParamTable()

    # ---- 00 Features ---------------------------------------------------------
    f = pt.group("feat")
    f.static("Use Wear Layer", True, "Reveal the Wear layer (rust, bare metal, brick ...) where mask R says so. OFF removes the layer and its 3 texture samples.")
    f.static("Use Dirt Layer", True, "Blend the Dirt layer where mask G says so (and in crevices via the baked AO). OFF removes its 3 texture samples.")
    f.static("Use Scratches", True, "Apply scratches where mask B says so (colour, roughness, metallic, flatter normal). OFF removes them.")
    f.static("Use Top Coating", False, "Dust / snow / moss that settles on surfaces facing the Coat direction (up by default). ON adds the Coat layer's 3 samples.")
    f.static("Use Vertex Layer 1", True, "Vertex colour RED paints Vertex Layer 1 over everything below it (Mesh Paint, paint colour black). Not for Nanite meshes.")
    f.static("Use Vertex Layer 2", False, "Vertex colour GREEN paints Vertex Layer 2.")
    f.static("Use Vertex Layer 3", False, "Vertex colour BLUE paints Vertex Layer 3.")
    f.static("Use Vertex Alpha Dirt", False, "Vertex colour ALPHA paints extra dirt on top of the mask-driven dirt (needs Use Dirt Layer).")
    f.static("Vertex Paint White Adds", False, "OFF (default): paint BLACK to add a layer (an unpainted mesh is white). ON: paint WHITE - fill the mesh with black first.")
    f.static("Use Baked AO", True, "Multiply the baked ambient occlusion stored in the ALPHA channel of the RGB mask. Turn OFF if your mask alpha is not AO.")
    f.static("Use Mask Breakup", True, "Erode the soft, low-resolution mask edges with the tiling Breakup texture so wear and dirt stay crisp up close.")
    f.static("Use Layer Hue Shift", True, "Allow the per-layer Hue Shift controls. OFF skips that colour maths in every layer (about 8 instructions per layer).")
    f.static("Use Layer Rotation", True, "Allow the per-layer UV Rotation (its normal map turns with it). OFF skips that maths (about 16 instructions per layer).")
    f.static("Use Detail Normal", True, "Add the tiling detail normal on top of the layer normals (angle-correct blend, flattens with distance).")
    f.static("Use Distance Flatten", True, "Flatten the final normal with distance (FlattenNormal): calmer, less noisy specular on far surfaces.")
    f.static("Use Macro Variation", False, "Multiply a very large, low-contrast noise over colour and roughness to hide tiling repetition.")
    f.static("Macro Uses World Space", False, "Project the macro noise top-down in world X/Y so neighbouring props differ. OFF uses the tiling UVs (better on walls).")
    f.static("Use Instance Variation", False,
             "Random brightness, saturation and hue per object (per instance on HISM / foliage), from its position: for static props, a moving object would flicker.")
    f.static("Use Wetness", False, "Enable the Wetness and Puddles parameters: darker, glossier surfaces and flat puddles that fill the low parts of the height.")
    f.static("Use Parallax", False, "Parallax offset (BumpOffset) driven by the BASE layer's height: depth for bricks and cobblestones. One extra texture sample.")
    f.static("Use Emissive", False, "Add an emissive texture (signs, lights, screens) on the unique UV set.")
    f.static("Use Opacity Mask", False,
             "Cut-out / fade from the Opacity Texture. Also needs Blend Mode = Masked or Translucent (Details > Base Property Overrides on the instance).")
    f.static("Swap UV Channels", False,
             "ON: tiling = UV1, unique = UV0. Tangents still come from UV0, so normal maps can be lit wrongly on rotated islands. Better: fix the UV order in your DCC.")
    f.static("Debug View", False, "Show a mask, weight, UV or surface value as an unlit colour instead of the material. Pick it with Debug Mode.")

    # ---- 01 Global ---------------------------------------------------------------
    g = pt.group("glob")
    g.scalar("Global Tiling", 1.0, 0.05, 16.0, "Multiplies the tiling of every tiling texture (layers, breakup, detail, macro). Your texel-density knob.")
    g.vector("Global Tint", (1.0, 1.0, 1.0), "Colour multiplied over the final albedo (after all layers).")
    g.scalar("Global Hue Shift", 0.0, -180.0, 180.0, "Rotates the hue of the final albedo, in degrees (0 = unchanged).")
    g.scalar("Global Saturation", 1.0, 0.0, 2.0, "Final saturation: 0 = greyscale, 1 = unchanged.")
    g.scalar("Global Contrast", 1.0, 0.0, 2.0, "Contrast of the final albedo as a power curve around mid-grey (0.18 linear): 1 = unchanged, above 1 = punchier.")
    g.scalar("Global Brightness", 1.0, 0.0, 3.0, "Final albedo multiplier.")
    g.scalar("Albedo Min", 0.0, 0.0, 0.5, "Darkest allowed albedo (linear). Real materials rarely go below 0.02; 0 = no limit.")
    g.scalar("Albedo Max", 1.0, 0.5, 1.0, "Brightest allowed albedo (linear). Even fresh snow stays under about 0.9; 1 = no limit.")
    g.scalar("Global Roughness Offset", 0.0, -1.0, 1.0, "Added to the final roughness (negative = glossier).")
    g.scalar("Roughness Floor", 0.0, 0.0, 1.0, "Lowest roughness that can reach the shader (applied last). 0.04 avoids mirror-like pixels that shimmer.")
    g.scalar("Specular", 0.5, 0.0, 1.0, "Specular pin: 0.5 = the usual 4% reflectance of non-metals. Lower for cloth and dust, higher for gems and wet stone.")
    g.scalar("Global AO Strength", 1.0, 0.0, 1.0, "Strength of the combined ambient occlusion (ORMH AO of the layers and the baked mask AO).")
    g.scalar("AO Color Influence", 0.0, 0.0, 1.0, "How much the baked AO (mask alpha) also darkens the albedo directly. 0 = only the AO pin.")

    # ---- 02 Mask ---------------------------------------------------------------------
    m = pt.group("mask")
    m.texture("Mask Texture", "mask", "SAMPLERTYPE_MASKS",
              "RGBA mask on the UNIQUE UV set: R wear, G dirt, B scratches, A baked AO. Compression 'Masks (no sRGB)'.", use="sample")
    m.scalar("Mask AO Strength", 1.0, 0.0, 1.0, "How strongly the baked AO (mask alpha) darkens the surface.")
    m.texture("Breakup Texture", "neutral", "SAMPLERTYPE_MASKS",
              "Tileable noise: R = wear edges, G = dirt edges, B = scratch / vertex paint / coat edges. 50% grey = neutral. 'Masks (no sRGB)'.", use="sample")
    m.scalar("Breakup Tiling", 2.0, 0.1, 32.0, "Tiling of the breakup noise on the tiling UVs.")

    # ---- 03-05, 08-11 layers + their effect controls ------------------------------------
    for key, label, group in LAYERS:
        lg = _layer_head(pt, key, label, group)
        if key == "Wear":
            lg.scalar("Wear Intensity", 1.0, 0.0, 2.0, "Scales mask R before the reveal. Above 1 the worn area grows, below 1 it shrinks, 0 = no wear.")
            lg.scalar("Wear Opacity", 1.0, 0.0, 1.0, "Strength of the whole layer: 1 = full, 0 = off. Fades it smoothly (Intensity instead moves the edge).")
            lg.scalar("Wear Softness", 0.08, 0.005, 0.5, "Edge width. 0.005 = razor-sharp chipping, 0.08 = default, 0.5 = very soft fade.")
            lg.scalar("Wear Height Influence", 0.5, -1.0, 1.0, "How much the Wear layer's height map decides where wear shows first. 0 = ignore height, negative flips it.")
            lg.scalar("Wear Breakup", 0.4, 0.0, 1.0, "How much the Breakup texture (R) erodes the wear edge. 0 = clean mask edge.")
            lg.scalar("Wear Invert", 0.0, 0.0, 1.0, "0 = use mask R as painted, 1 = invert it (snaps to 0 or 1).")
            lg.vector("Wear Edge Color", (0.06, 0.03, 0.02), "Colour of the thin rim where the top coat meets the exposed layer.")
            lg.scalar("Wear Edge Strength", 0.5, 0.0, 1.0, "Visibility of that rim (0 = off). Its width follows Wear Softness.")
            lg.scalar("Wear Cover Flatten", 1.0, 0.0, 1.0, "How much exposed Wear flattens the relief of the layer it replaces (1 = the old surface bumps vanish).")
        elif key == "Dirt":
            lg.scalar("Dirt Intensity", 1.0, 0.0, 2.0, "Scales mask G (plus the AO and vertex-alpha dirt) before the reveal. Above 1 more dirt, 0 = none.")
            lg.scalar("Dirt Opacity", 1.0, 0.0, 1.0, "Strength of the whole layer: 1 = full, 0 = off. Fades it smoothly (Intensity instead moves the edge).")
            lg.scalar("Dirt Softness", 0.2, 0.005, 0.5, "Edge width of the dirt. 0.005 = hard stains, 0.5 = very soft.")
            lg.scalar("Dirt Height Influence", 0.3, -1.0, 1.0, "How much the Dirt layer's height map decides where dirt shows first. 0 = ignore height.")
            lg.scalar("Dirt Breakup", 0.4, 0.0, 1.0, "How much the Breakup texture (G) erodes the dirt edge.")
            lg.scalar("Dirt AO Boost", 0.5, 0.0, 1.0, "Adds extra dirt in crevices using the baked AO (mask alpha). 0 = off.")
            lg.scalar("Dirt Invert", 0.0, 0.0, 1.0, "0 = use mask G as painted, 1 = invert it (snaps to 0 or 1). The AO and vertex-alpha dirt are not inverted.")
            lg.scalar("Dirt Cover Flatten", 0.6, 0.0, 1.0, "How much dirt fills the relief below it (FlattenNormal). 0 = a thin film, 1 = a thick layer that hides the bumps.")
        elif key.startswith("Vertex"):
            lg.scalar(label + " Opacity", 1.0, 0.0, 1.0, "Strength of the whole painted layer: 1 = full, 0 = off. Handy to dial it per instance.")
            lg.scalar(label + " Softness", 0.1, 0.005, 0.5, "Softness of the painted edge. Small = crisp and height-driven, large = a plain fade.")
            lg.scalar(label + " Height Influence", 0.5, -1.0, 1.0, "How much this layer's height map shapes the painted edge. 0 = plain gradient.")
            lg.scalar(label + " Breakup", 0.3, 0.0, 1.0, "How much the Breakup texture (B) erodes the painted edge.")
            lg.scalar(label + " Cover Flatten", 1.0, 0.0, 1.0, "How much the painted layer flattens the relief below it (1 = the layer underneath loses its bumps).")
        elif key == "Coat":
            lg.scalar("Coat Amount", 0.5, 0.0, 1.0, "How much coating settles. 0 = none, 1 = every surface that faces the coat direction is covered.")
            lg.scalar("Coat Elevation", 90.0, 0.0, 90.0, "Angle of the direction the coating falls from: 90 = straight down on upward faces, lower = from the side (drifts).")
            lg.scalar("Coat Azimuth", 0.0, 0.0, 360.0, "Compass heading of that direction (matters when Elevation is below 90).")
            lg.scalar("Coat Slope Cutoff", 0.3, -1.0, 1.0, "Facing needed to hold coating: 0.99 = only flat tops, 0 = up to vertical walls, -1 = even undersides.")
            lg.scalar("Coat Slope Softness", 0.35, 0.01, 1.0, "How gradually the coating builds up above the cutoff.")
            lg.scalar("Coat Normal Influence", 0.5, 0.0, 1.0, "0 = follow only the mesh shape, 1 = also follow the bumps of the normal maps (coating gathers on tiny ledges).")
            lg.scalar("Coat Softness", 0.15, 0.005, 0.5, "Edge width of the coating (organic, height-driven edge when small).")
            lg.scalar("Coat Height Influence", 0.3, -1.0, 1.0, "How much the Coat layer's height map decides where coating shows first.")
            lg.scalar("Coat Breakup", 0.4, 0.0, 1.0, "How much the Breakup texture (B) erodes the coating edge.")
            lg.scalar("Coat Cover Flatten", 0.8, 0.0, 1.0, "How much the coating fills the relief below it (1 = snow-deep, 0 = a thin dust film).")
        _layer_tail(lg, label, with_height=(key != "Base"))

    # ---- 06 Scratches -------------------------------------------------------------------
    s = pt.group("scr")
    s.scalar("Scratch Intensity", 1.0, 0.0, 2.0, "Scales mask B before the reveal.")
    s.scalar("Scratch Opacity", 1.0, 0.0, 1.0, "Strength of the scratches: 1 = full, 0 = off. Fades them smoothly (Intensity instead moves the edge).")
    s.scalar("Scratch Softness", 0.05, 0.005, 0.5, "Edge width of the scratch lines.")
    s.scalar("Scratch Breakup", 0.2, 0.0, 1.0, "How much the Breakup texture (B) erodes the scratch lines.")
    s.vector("Scratch Color", (0.78, 0.78, 0.80), "Colour of the exposed material inside a scratch.")
    s.scalar("Scratch Roughness", 0.35, 0.0, 1.0, "Roughness inside scratches.")
    s.scalar("Scratch Metallic", 1.0, 0.0, 1.0, "Metallic inside scratches (1 = bare metal showing through the paint).")
    s.scalar("Scratch Normal Flatten", 0.5, 0.0, 1.0, "FlattenNormal inside scratches: the worn spot loses the relief of the surface it cuts through.")
    s.scalar("Scratch Invert", 0.0, 0.0, 1.0, "0 = use mask B as painted, 1 = invert it (snaps to 0 or 1).")

    # ---- 07 Vertex paint -----------------------------------------------------------------
    v = pt.group("vp")
    v.scalar("Vertex Alpha Dirt Strength", 1.0, 0.0, 1.0, "How much dirt painted into vertex ALPHA adds (needs Use Vertex Alpha Dirt).")

    # ---- 12 Detail normal ------------------------------------------------------------------
    d = pt.group("det")
    d.texture("Detail Normal Texture", "flatnormal", "SAMPLERTYPE_NORMAL",
              "Fine tileable normal map layered over everything (RNM blend). Compression 'Normalmap'.", use="sample")
    d.scalar("Detail Normal Tiling", 8.0, 0.1, 64.0, "Tiling of the detail normal on the tiling UVs.")
    d.scalar("Detail Normal Intensity", 1.0, 0.0, 3.0, "Strength of the detail normal.")
    d.scalar("Detail Normal Flip Green", 0.0, 0.0, 1.0, "1 = the detail map is OpenGL style (green up).")
    d.scalar("Detail Fade Start", 400.0, 0.0, 5000.0, "Distance (cm) where the detail starts to flatten out.")
    d.scalar("Detail Fade End", 1500.0, 1.0, 10000.0, "Distance (cm) where the detail is completely flat.")

    # ---- 13 Normal finish -------------------------------------------------------------------
    n = pt.group("norm")
    n.scalar("Global Normal Intensity", 1.0, 0.0, 3.0, "Strength of the final normal (all layers plus detail): 1 = as authored, 0 = flat.")
    n.scalar("Distance Flatten Start", 1500.0, 0.0, 20000.0, "Distance (cm) where the normal starts to flatten (needs Use Distance Flatten).")
    n.scalar("Distance Flatten End", 6000.0, 1.0, 50000.0, "Distance (cm) where the flattening reaches its full Amount.")
    n.scalar("Distance Flatten Amount", 0.8, 0.0, 1.0, "How flat the normal gets far away: 1 = completely flat.")

    # ---- 14 Macro ------------------------------------------------------------------------------
    mc = pt.group("mac")
    mc.texture("Macro Texture", "neutral", "SAMPLERTYPE_MASKS",
               "Large-scale greyscale noise (R channel); 50% grey = no change. Compression 'Masks (no sRGB)'.", use="sample")
    mc.scalar("Macro Tiling", 0.2, 0.01, 4.0, "UV mode: tiles per tiling-UV unit. World mode: tiles per metre.")
    mc.scalar("Macro Intensity", 0.3, 0.0, 1.0, "Brightness variation strength.")
    mc.scalar("Macro Roughness Variation", 0.2, 0.0, 1.0, "Roughness variation strength.")

    # ---- 15 Instance variation ------------------------------------------------------------------
    iv = pt.group("inst")
    iv.scalar("Variation Brightness", 0.15, 0.0, 0.5, "Max random brightness change per object (0.15 = plus or minus 15%).")
    iv.scalar("Variation Saturation", 0.15, 0.0, 0.5, "Max random saturation change per object.")
    iv.scalar("Variation Hue", 8.0, 0.0, 90.0, "Max random hue rotation per object, in degrees (plus or minus).")
    iv.scalar("Variation Seed", 0.0, 0.0, 100.0, "Re-rolls every object's random look at once, without moving the props.")

    # ---- 16 Wetness --------------------------------------------------------------------------------
    w = pt.group("wet")
    w.scalar("Wetness", 0.6, 0.0, 1.0, "Dampness of the whole surface: 0 = dry, 1 = soaked (darker and glossier).")
    w.scalar("Wet Darken", 0.35, 0.0, 1.0, "How much a soaked surface darkens (bare metal does not darken).")
    w.scalar("Wet Saturation", 1.15, 0.0, 2.0, "Saturation of wet areas (wet colours look richer): 1 = unchanged.")
    w.scalar("Wet Roughness", 0.1, 0.0, 1.0, "Roughness of a soaked surface (a surface that is already smoother keeps its lower value).")
    w.scalar("Puddles", 0.6, 0.0, 1.0, "Amount of standing water. It collects in the LOW parts of the blended height map.")
    w.scalar("Puddle Height Influence", 0.8, 0.0, 1.0, "How strongly the height map decides where puddles form. 0 = even coverage, 1 = only the lowest spots.")
    w.scalar("Puddle Softness", 0.1, 0.005, 0.5, "Edge width of the puddles.")
    w.scalar("Puddle Slope Limit", 0.6, 0.0, 1.0, "Puddles only form where the mesh faces up more than this (0.99 = flat tops only, 0 = anything not facing down).")
    w.scalar("Puddle Roughness", 0.03, 0.0, 1.0, "Roughness of standing water.")
    w.scalar("Puddle Darken", 0.25, 0.0, 1.0, "How much the ground darkens under standing water (bare metal does not).")
    w.scalar("Puddle Flatten", 1.0, 0.0, 1.0, "FlattenNormal inside puddles: water has a flat surface (1 = perfectly flat).")

    # ---- 17 Parallax -----------------------------------------------------------------------------------
    pr = pt.group("par")
    pr.scalar("Parallax Depth", 0.05, 0.0, 0.3, "Apparent depth as a fraction of the Base layer's tile width. 0.03 - 0.08 suits bricks and cobblestones.")
    pr.scalar("Parallax Fade Start", 500.0, 0.0, 5000.0, "Distance (cm) where the parallax starts to fade out (cheaper and calmer far away).")
    pr.scalar("Parallax Fade End", 2000.0, 1.0, 10000.0, "Distance (cm) where the parallax is gone.")

    # ---- 18 Emissive -----------------------------------------------------------------------------------
    e = pt.group("emi")
    e.texture("Emissive Texture", "black", "SAMPLERTYPE_COLOR", "Emissive colour (sRGB) on the UNIQUE UV set.", use="sample")
    e.vector("Emissive Color", (1.0, 1.0, 1.0), "Tint multiplied onto the emissive texture.")
    e.scalar("Emissive Intensity", 1.0, 0.0, 50.0, "Emissive brightness multiplier.")
    e.scalar("Emissive Pulse Speed", 0.0, 0.0, 10.0, "Pulses per second (0 = steady glow).")
    e.scalar("Emissive Pulse Amount", 0.3, 0.0, 1.0, "How deep the pulse dips: 0.3 = brightness swings plus or minus 30%.")

    # ---- 19 Opacity ------------------------------------------------------------------------------------
    o = pt.group("opa")
    o.texture("Opacity Texture", "white_mask", "SAMPLERTYPE_MASKS", "Opacity (R channel) for cut-outs such as fences or leaves. Compression 'Masks (no sRGB)'.", use="sample")
    o.scalar("Opacity Uses Tiling UV", 0.0, 0.0, 1.0, "0 = sample on the unique UV set, 1 = on the tiling UV set (values snap to 0 or 1).")
    o.scalar("Opacity Threshold", 0.5, 0.0, 1.0, "Texture values below this are cut away.")
    o.scalar("Opacity Softness", 0.05, 0.001, 0.5, "Edge softness of the cut (small = crisp).")

    # ---- 20 Debug --------------------------------------------------------------------------------------
    db = pt.group("dbg")
    db.scalar("Debug Mode", 1.0, 1.0, float(len(DEBUG_MODES)),
              "View shown while Debug View is ON:  " + ",  ".join("%d %s" % (i, name) for i, name in enumerate(DEBUG_MODES, start=1)))
    return pt


# ==============================================================================
# 5. SHADER BUILDING BLOCKS
# ------------------------------------------------------------------------------
# Small functions that add nodes to the graph. Section 6 uses them to assemble the
# material. Everything that does a certain job lives in one place:
#
#   NormalOps       FlattenNormal (Epic's function, or the same maths inline) + the angle-correct normal blend
#   uv_*            tiling / rotation / offset of a layer's UVs
#   hue_shift       RGB rotation around the grey axis
#   reveal_weight   mask + height + breakup noise  ->  crisp 0..1 blend weight
#   sample_layer    samples and adjusts one tiling PBR layer
#   blend_layer     lays one layer over the stack (colour, normal, roughness, metallic, AO, height)
# ==============================================================================
ENGINE_FLATTEN_NORMAL = "/Engine/Functions/Engine_MaterialFunctions01/Texturing/FlattenNormal"


def load_engine_function(name, path):
    """Find one of Epic's Material Functions by its known path, else by name in the Asset Registry. None if absent."""
    eal = unreal.EditorAssetLibrary
    try:
        if eal.does_asset_exist(path):
            fn = eal.load_asset(path)
            if fn is not None:
                return fn
    except Exception:                                       # noqa: BLE001
        pass
    try:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        for data in registry.get_assets_by_path("/Engine/Functions", recursive=True):
            if str(data.asset_name) == name:
                fn = data.get_asset()
                if fn is not None:
                    return fn
    except Exception as exc:                                # noqa: BLE001
        warn("Asset Registry search for %s failed (%s)." % (name, exc))
    return None


class NormalOps:
    """
    The two normal operations the layer stack is built on.

        flatten(n, a)   FlattenNormal: normalize(lerp(n, (0,0,1), a))        a = 0 unchanged, 1 completely flat
        blend(b, d)     reoriented normal mapping (the algorithm behind Epic's BlendAngleCorrectedNormals): the detail
                        normal d follows the slope of b instead of just being added:
                        t = b + (0,0,1);  u = d * (-1,-1,1);  normalize(t * dot(t,u) / t.z - u)

    With USE_ENGINE_FUNCTIONS the flatten calls go to Epic's own FlattenNormal Material Function (you can open it from the
    graph), after its pins were checked. If the engine has no such function, or its pins look different, the identical maths
    is built from plain nodes instead. The blend is always built from plain nodes: it is a handful of nodes and there is
    no doubt about the value range it works in (unpacked tangent-space normals, -1..1).
    """

    def __init__(self, g, use_engine):
        self.g = g
        self.flatten_fn = None
        self.flatten_order = None                           # positions of (normal, amount) among the function's inputs
        self.mode = "inline"
        if use_engine:
            self._discover()

    @staticmethod
    def _pick(names):
        """Indices of the (normal, flatness) inputs, found by name; None if the pins are not what we expect."""
        low = [n.lower() for n in names]
        if len(low) != 2:
            return None
        a = [i for i, n in enumerate(low) if "normal" in n and "flat" not in n]
        b = [i for i, n in enumerate(low) if "flat" in n]
        if len(a) == 1 and len(b) == 1 and a[0] != b[0]:
            return a[0], b[0]
        return None

    def _discover(self):
        name = "FlattenNormal"
        try:
            fn = load_engine_function(name, ENGINE_FLATTEN_NORMAL)
            if fn is None:
                warn("Engine function %s not found - using the identical built-in version." % name)
                return
            names = self.g.function_input_names(fn)
            order = self._pick(names)
            if order is None:
                warn("Engine function %s has inputs %s, not what was expected - using the built-in version." % (name, names))
                return
        except Exception as exc:                            # noqa: BLE001 - any trouble: use the inline version
            warn("Could not use engine function %s (%s) - using the built-in version." % (name, exc))
            return
        self.flatten_fn, self.flatten_order = fn, order
        self.mode = "engine FlattenNormal"
        log("using the engine's %s function" % name)

    def flatten(self, n, amount):
        """Flatten a tangent-space normal: amount 0 = unchanged, 1 = (0,0,1). `amount` is a V or a number."""
        g = self.g
        if not isinstance(amount, V):
            amount = g.const(amount)
        if self.flatten_fn is not None:
            args = [None, None]
            args[self.flatten_order[0]], args[self.flatten_order[1]] = n, amount
            return g.normalize(g.call_function(self.flatten_fn, args, 3))      # our own normalize: no assumption about the function
        return g.normalize(g.lerp(n, g.vec3(0.0, 0.0, 1.0), amount))

    def blend(self, base, detail):
        """Reoriented normal blend: `detail` is added on top of `base` and follows its slope."""
        g = self.g
        t = base + g.vec3(0.0, 0.0, 1.0)
        u = detail * g.vec3(-1.0, -1.0, 1.0)
        return g.normalize(t * (g.dot(t, u) / t.mask("b")) - u)


# ---- UV helpers --------------------------------------------------------------------
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


# ---- normal helpers ------------------------------------------------------------------
def flip_green(g, n, flip):
    """OpenGL (green up) -> DirectX (green down) when `flip` is 1: the green channel is multiplied by 1 - 2*round(flip)."""
    sign = 1.0 - g.floor(flip + 0.5) * 2.0
    return g.append(g.append(n.mask("r"), n.mask("g") * sign), n.mask("b"))


def rotate_normal_back(g, n, c, s):
    """A layer whose UVs are rotated by +angle is sampled with a rotated texture, so the tangent-space normal read
    from it has to be rotated by -angle to agree with the surface (otherwise bumps are lit from the wrong side)."""
    nx, ny = n.mask("r"), n.mask("g")
    return g.append(g.append(nx * c + ny * s, ny * c - nx * s), n.mask("b"))


def normal_intensity(g, n, strength):
    """Scale the slope of a tangent-space normal: xy * strength, then renormalise (0 = flat, 1 = unchanged).
    z is kept a hair above 0 so a strength of 0 on a steep texel cannot normalise a zero vector."""
    return g.normalize(g.append(n.mask("rg") * strength, g.vmax(n.mask("b"), 0.0001)))


# ---- colour helpers --------------------------------------------------------------------
LUMINANCE = (0.2126, 0.7152, 0.0722)            # Rec.709 weights for linear colour


def hue_shift(g, color, degrees):
    """
    Rotate the hue of an RGB colour: a rotation around the grey axis (Rodrigues: c*v + s*(axis x v) + (1-c)*(axis . v)*axis),
    then the luminance of the input is restored by adding the missing grey, so a hue shift does not also change the
    brightness. Negative results are cut off.
    """
    turns = degrees / 360.0
    c, s = g.cosine(turns), g.sine(turns)
    axis = g.vec3(0.57735027, 0.57735027, 0.57735027)
    rotated = color * c + g.cross(axis, color) * s + axis * (g.dot(axis, color) * (1.0 - c))
    weights = g.vec3(*LUMINANCE)
    rotated = rotated + (g.dot(weights, color) - g.dot(weights, rotated))
    return g.vmax(rotated, 0.0)


def contrast(g, color, amount, pivot=0.18):
    """Contrast as a power curve around `pivot` (linear mid-grey): 0 stays 0, `pivot` stays `pivot`, nothing goes negative."""
    return g.power(g.vmax(color / pivot, 0.0001), amount) * pivot


def saturate_color(g, color, amount):
    """amount 0 = greyscale, 1 = unchanged, 2 = double saturation."""
    return g.lerp(g.desaturate(color, 1.0), color, amount)


# ---- the blend weight ------------------------------------------------------------------
def reveal_weight(g, mask, softness, height=None, height_influence=None, breakup=None, breakup_strength=None,
                  intensity=None, invert=None):
    """
    weight = saturate( (m * (1 + 2W) - T) / (2W) )
      m  mask after invert / intensity                                (0..1)
      T  reveal threshold = 0.5 - HeightInfluence*(Height-0.5) + BreakupStrength*(0.5-Breakup)
      W  softness (edge width)
    Guarantees weight = 0 where m = 0 and weight = 1 where m = 1 for every T in 0..1, while the height / breakup noise
    decides in which ORDER pixels switch on - that is what turns a soft 1k mask into crisp, organic chipped edges.
    """
    m = mask
    if invert is not None:
        m = g.lerp(m, m.one_minus(), g.floor(invert + 0.5))          # 0 or 1: a half-inverted mask would be a flat grey
    if intensity is not None:
        m = m * intensity
    m = m.sat()
    t = g.const(0.5)
    if height is not None:
        t = 0.5 - height_influence * (height - 0.5)
    if breakup is not None:
        t = t + breakup_strength * (0.5 - breakup)
    t = t.sat()
    w2 = g.vmax(softness, 0.001) * 2.0
    return ((m * (w2 + 1.0) - t) / w2).sat()


# ---- one tiling PBR layer ---------------------------------------------------------------
class Surface:
    """Everything the stack knows about the surface at one point. normal is tangent space, the rest are scalars / colour."""
    __slots__ = ("color", "normal", "rough", "metal", "ao", "height", "flatten")

    def __init__(self, color, normal, rough, metal, ao, height, flatten=None):
        self.color, self.normal, self.rough, self.metal, self.ao, self.height = color, normal, rough, metal, ao, height
        self.flatten = flatten            # the layer's own Normal Flatten (applied while blending), None for the base


def sample_layer(g, P, label, tiling_uv, is_base=False):
    """Samples Albedo / Normal / ORMH of one layer with its own tiling, rotation and offset and applies all the
    adjustments of its parameter group (hue, saturation, tint, brightness, normal flip / intensity, roughness range ...)."""
    sw = g.static_switch
    use_rotation = P("Use Layer Rotation")
    c, s = uv_rotation(g, P(label + " Rotation"))
    tiling, offset = P(label + " Tiling"), P(label + " Offset").mask("rg")
    uv = sw(use_rotation, uv_transform(g, tiling_uv, tiling, c, s, offset), tiling_uv * tiling + offset)
    albedo = g.sample(P(label + " Albedo"), uv, "SAMPLERTYPE_COLOR")
    nmap = g.sample(P(label + " Normal Map"), uv, "SAMPLERTYPE_NORMAL")
    orm = g.sample(P(label + " ORMH Map"), uv, "SAMPLERTYPE_MASKS")

    albedo = sw(P("Use Layer Hue Shift"), hue_shift(g, albedo, P(label + " Hue Shift")), albedo)
    color = saturate_color(g, albedo, P(label + " Saturation")) * P(label + " Tint") * P(label + " Brightness")

    n = flip_green(g, nmap, P(label + " Normal Flip Green"))
    n = sw(use_rotation, rotate_normal_back(g, n, c, s), n)
    n = normal_intensity(g, n, P(label + " Normal Intensity"))

    rough = g.lerp(P(label + " Roughness Min"), P(label + " Roughness Max"), orm.mask("g")).sat()
    metal = (orm.mask("b") * P(label + " Metallic")).sat()
    ao = g.lerp(1.0, orm.mask("r"), P(label + " AO Strength"))
    if is_base:
        height = g.alpha_of(orm)
    else:
        height = ((g.alpha_of(orm) - 0.5) * P(label + " Height Contrast") + 0.5 + P(label + " Height Offset")).sat()
    return Surface(color, n, rough, metal, ao, height, P(label + " Normal Flatten"))


def blend_layer(g, nops, below, layer, w, cover_flatten, use, edge=None):
    """
    Lay `layer` over `below` with weight w (0..1). Colour, roughness, metallic, AO and height are lerped. The normal is
    the interesting part: the relief underneath is flattened by w * CoverFlatten (the new layer fills the cracks), the new
    layer's own relief fades in with w, and both are combined with the angle-correct blend, so neither loses its detail.
    `use` is the layer's static switch: OFF passes `below` through, and the new layer is not compiled at all.
    edge = (colour, strength) draws a thin rim where the weight is half-way.
    """
    color = g.lerp(below.color, layer.color, w)
    if edge is not None:
        rim = ((w * w.one_minus()) * 4.0 * edge[1]).sat()
        color = g.lerp(color, edge[0], rim)
    n_below = nops.flatten(below.normal, w * cover_flatten)
    n_layer = nops.flatten(layer.normal, 1.0 - layer.flatten.one_minus() * w)
    normal = nops.blend(n_below, n_layer)
    rough = g.lerp(below.rough, layer.rough, w)
    metal = g.lerp(below.metal, layer.metal, w)
    ao = g.lerp(below.ao, layer.ao, w)
    height = g.lerp(below.height, layer.height, w)
    sw = g.static_switch
    return Surface(sw(use, color, below.color), sw(use, normal, below.normal), sw(use, rough, below.rough),
                   sw(use, metal, below.metal), sw(use, ao, below.ao), sw(use, height, below.height))


# ==============================================================================
# 6. THE MASTER   (read top to bottom - one numbered block per stage)
# ------------------------------------------------------------------------------
# Stage order:  UVs -> RGB mask -> breakup noise -> vertex paint -> layer stack
#               (Base, Wear, Vertex 1-3, Dirt, Scratches, Top Coat) -> macro / instance
#               variation -> global grade -> wetness -> AO -> normal finish -> emissive,
#               opacity -> debug view -> material outputs
# ==============================================================================


def connect_property(g, prop_name, v, components):
    if v.kind != "num" or v.dim != components:
        raise BuildError("%s needs %d components, got %s/%d" % (prop_name, components, v.kind, v.dim))
    ok = unreal.MaterialEditingLibrary.connect_material_property(v.node.expr, v.out, enum("MaterialProperty", prop_name))
    if not ok:
        raise BuildError("connect_material_property failed for %s" % prop_name)
    g.mark_root(v)


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


def clear_graph(mat):
    """
    Delete every node of `mat`. Epic's delete_all_material_expressions deletes while it walks the live node array, so one call
    leaves about half of the nodes behind: repeat until the material is really empty.
    """
    mel = unreal.MaterialEditingLibrary
    for _ in range(64):
        try:
            if mel.get_num_material_expressions(mat) == 0:
                return
        except Exception:                                   # noqa: BLE001 - no counter: just call it often enough
            pass
        mel.delete_all_material_expressions(mat)
    try:
        left = mel.get_num_material_expressions(mat)
    except Exception:                                       # noqa: BLE001
        return
    if left:
        raise BuildError("Could not clear the old graph of the material (%d nodes left)" % left)


def build_master(mat, textures, use_engine_functions):
    """Builds the whole graph into `mat` (any old graph is deleted first). Returns the Graph."""
    clear_graph(mat)
    params = define_params()
    g = Graph(mat, MASTER_NAME, params, textures)
    P = g.P
    sw = g.static_switch
    nops = NormalOps(g, use_engine_functions)
    log("normal operations: %s" % nops.mode)

    # ---- 1. UV SETS (+ parallax) -----------------------------------------------------------------
    # UV0 = tiling (texel-density) UVs, UV1 = unique (non-overlapping 0-1) UVs for the RGB mask.
    g.section("05 | BASE LAYER")
    for name in ("Base Rotation", "Base Tiling", "Base Offset", "Base ORMH Map"):
        P(name)                                         # created here, used by the parallax height below
    g.section("01 | UV SETS + PARALLAX\nUV0 tiling, UV1 unique")
    uv0, uv1 = g.texcoord(0), g.texcoord(1)
    swap = P("Swap UV Channels")
    tile_raw = sw(swap, uv1, uv0)
    unique_uv = sw(swap, uv0, uv1)
    tiling_uv_flat = tile_raw * P("Global Tiling")
    depth = g.pixel_depth()

    # Parallax height = the BASE layer's height, read at the plain tiling UVs; every layer then samples at the shifted UVs.
    bc, bs = uv_rotation(g, P("Base Rotation"))
    base_uv = uv_transform(g, tiling_uv_flat, P("Base Tiling"), bc, bs, P("Base Offset").mask("rg"))
    par_height = g.alpha_of(g.sample(P("Base ORMH Map"), base_uv, "SAMPLERTYPE_MASKS")) - 0.5          # centred on 0
    # depth in fractions of the Base layer's tile (not of the Global-tiled UV unit), fading out with distance
    par_ratio = (P("Parallax Depth") / g.vmax(P("Base Tiling"), 0.05)
                 * g.smoothstep(depth, P("Parallax Fade Start"), P("Parallax Fade End")).one_minus())
    tiling_uv = sw(P("Use Parallax"), g.bump_offset(tiling_uv_flat, par_height, par_ratio), tiling_uv_flat)

    # ---- 2. RGB MASK -------------------------------------------------------------------------------
    g.section("02 | RGB MASK (unique UV)\nR wear  G dirt  B scratch  A AO")
    mask_rgb = g.sample_param("Mask Texture", unique_uv)
    m_wear, m_dirt, m_scr = mask_rgb.mask("r"), mask_rgb.mask("g"), mask_rgb.mask("b")
    m_ao_raw = g.alpha_of(mask_rgb)
    ao_mask = sw(P("Use Baked AO"), m_ao_raw, 1.0)

    g.section("03 | BREAKUP NOISE\nR wear  G dirt  B scratch / vertex / coat")
    bk_tex = g.sample_param("Breakup Texture", tiling_uv * P("Breakup Tiling"))
    use_breakup = P("Use Mask Breakup")
    bk_wear = sw(use_breakup, bk_tex.mask("r"), 0.5)         # 0.5 = neutral (no erosion)
    bk_dirt = sw(use_breakup, bk_tex.mask("g"), 0.5)
    bk_b = sw(use_breakup, bk_tex.mask("b"), 0.5)

    # ---- 3. VERTEX COLOUR ----------------------------------------------------------------------------
    # Unpainted meshes read as white. Default: painting BLACK adds a layer (Mesh Paint: Paint Color black, Erase Color white).
    g.section("04 | VERTEX PAINT\nR G B = layers 1-3, A = dirt")
    vc = g.vertex_color()
    white_adds = P("Vertex Paint White Adds")

    def painted(v):
        return sw(white_adds, v, v.one_minus())

    alpha_ok = g.vertex_alpha_available(vc)
    vc_alpha = g.vertex_alpha(vc) if alpha_ok else g.const(1.0)          # 1 = white = nothing painted
    paint_r, paint_g, paint_b = painted(vc.mask("r")), painted(vc.mask("g")), painted(vc.mask("b"))
    paint_a = painted(vc_alpha) if alpha_ok else g.const(0.0)

    # ---- 4. THE LAYER STACK (bottom -> top) ---------------------------------------------------------------
    g.section("05 | BASE LAYER")
    S = sample_layer(g, P, "Base", tiling_uv, is_base=True)
    S.normal = nops.flatten(S.normal, S.flatten)

    g.section("06 | WEAR LAYER: sample")
    wear = sample_layer(g, P, "Wear", tiling_uv)
    g.section("06 | WEAR LAYER: weight + blend")
    w_wear = reveal_weight(g, m_wear, P("Wear Softness"), wear.height, P("Wear Height Influence"), bk_wear,
                           P("Wear Breakup"), P("Wear Intensity"), P("Wear Invert")) * P("Wear Opacity")
    S = blend_layer(g, nops, S, wear, w_wear, P("Wear Cover Flatten"), P("Use Wear Layer"),
                    edge=(P("Wear Edge Color"), P("Wear Edge Strength")))

    w_vp = []
    for i, (paint, ch) in enumerate(((paint_r, "R"), (paint_g, "G"), (paint_b, "B")), start=1):
        label = "Vertex %d" % i
        g.section("%02d | VERTEX LAYER %d (paint %s): sample" % (6 + i, i, ch))
        lay = sample_layer(g, P, label, tiling_uv)
        g.section("%02d | VERTEX LAYER %d: weight + blend" % (6 + i, i))
        w = reveal_weight(g, paint, P(label + " Softness"), lay.height, P(label + " Height Influence"), bk_b,
                          P(label + " Breakup")) * P(label + " Opacity")
        S = blend_layer(g, nops, S, lay, w, P(label + " Cover Flatten"), P("Use Vertex Layer %d" % i))
        w_vp.append(w)

    g.section("10 | DIRT LAYER (mask G): sample")
    dirt = sample_layer(g, P, "Dirt", tiling_uv)
    g.section("10 | DIRT LAYER: weight + blend")
    dirt_vertex = sw(P("Use Vertex Alpha Dirt"), paint_a * P("Vertex Alpha Dirt Strength"), 0.0)
    dirt_painted = g.lerp(m_dirt, m_dirt.one_minus(), g.floor(P("Dirt Invert") + 0.5))      # only the painted mask is inverted
    dirt_mask = (dirt_painted + (1.0 - ao_mask) * P("Dirt AO Boost") + dirt_vertex).sat()
    w_dirt = reveal_weight(g, dirt_mask, P("Dirt Softness"), dirt.height, P("Dirt Height Influence"), bk_dirt,
                           P("Dirt Breakup"), P("Dirt Intensity")) * P("Dirt Opacity")
    S = blend_layer(g, nops, S, dirt, w_dirt, P("Dirt Cover Flatten"), P("Use Dirt Layer"))

    g.section("11 | SCRATCHES (mask B)")
    w_scr = reveal_weight(g, m_scr, P("Scratch Softness"), None, None, bk_b, P("Scratch Breakup"),
                          P("Scratch Intensity"), P("Scratch Invert")) * P("Scratch Opacity")
    use_scr = P("Use Scratches")
    S = Surface(sw(use_scr, g.lerp(S.color, P("Scratch Color"), w_scr), S.color),
                sw(use_scr, nops.flatten(S.normal, w_scr * P("Scratch Normal Flatten")), S.normal),
                sw(use_scr, g.lerp(S.rough, P("Scratch Roughness"), w_scr), S.rough),
                sw(use_scr, g.lerp(S.metal, P("Scratch Metallic"), w_scr), S.metal),
                S.ao, S.height)

    g.section("12 | TOP COAT (dust, snow, moss): sample")
    coat = sample_layer(g, P, "Coat", tiling_uv)
    g.section("12 | TOP COAT: slope + weight + blend")
    # Direction the coating falls from. Maths on parameters only: the engine folds it before the shader runs (free per pixel).
    el, az = P("Coat Elevation") / 360.0, P("Coat Azimuth") / 360.0
    ce, se, ca, sa = g.cosine(el), g.sine(el), g.cosine(az), g.sine(az)
    coat_dir = g.append(g.append(ce * ca, ce * sa), se)
    slope_mesh = g.dot(g.vertex_normal_ws(), coat_dir)                          # shape of the mesh
    slope_pixel = g.dot(g.tangent_to_world(S.normal), coat_dir)                 # ... including the normal-map bumps
    coat_slope = g.lerp(slope_mesh, slope_pixel, P("Coat Normal Influence"))
    cutoff = g.vmin(P("Coat Slope Cutoff"), 0.99)
    ramp = g.vmax(g.vmin(P("Coat Slope Softness"), 1.0 - cutoff), 0.01)                 # the ramp always ends at "faces straight up"
    coat_mask = ((coat_slope - cutoff) / ramp).sat() * P("Coat Amount")
    w_coat = reveal_weight(g, coat_mask, P("Coat Softness"), coat.height, P("Coat Height Influence"), bk_b,
                           P("Coat Breakup"))
    S = blend_layer(g, nops, S, coat, w_coat, P("Coat Cover Flatten"), P("Use Top Coating"))
    color, rough, metal, normal, height = S.color, S.rough, S.metal, S.normal, S.height

    # ---- 5. POST: macro variation, per-object variation -----------------------------------------------------
    g.section("13 | MACRO + INSTANCE VARIATION")
    macro_scale = P("Macro Tiling")
    macro_uv = sw(P("Macro Uses World Space"),
                  g.world_position().mask("rg") * 0.01 * macro_scale,        # cm -> m
                  tiling_uv * macro_scale)
    macro_n = g.sample_param("Macro Texture", macro_uv).mask("r")
    k = P("Macro Intensity")
    use_macro = P("Use Macro Variation")
    color = sw(use_macro, color * g.lerp(1.0 - k, k + 1.0, macro_n), color)      # 1.0 when the noise is 0.5
    rough = sw(use_macro, (rough + (macro_n - 0.5) * P("Macro Roughness Variation")).sat(), rough)

    # Pseudo-random numbers per object: a hash of the object position (ordinary meshes) plus PerInstanceRandom
    # (every instance of a HISM / foliage mesh shares one object position but not this value).
    seed_in = (g.dot(g.object_position(), g.vec3(12.9898, 78.233, 37.719)) + g.per_instance_random() * 1000.0
               + P("Variation Seed") * 17.0 + 1.0)
    r1 = (g.sine(seed_in, 2.0 * math.pi) * 43758.5453).frac()
    r2 = (g.sine(seed_in * 1.37 + 4.1, 2.0 * math.pi) * 24634.6345).frac()
    r3 = (g.sine(seed_in * 0.73 + 9.7, 2.0 * math.pi) * 35731.1297).frac()
    vb, vs = P("Variation Brightness"), P("Variation Saturation")
    color_inst = hue_shift(g, color, (r3 * 2.0 - 1.0) * P("Variation Hue"))
    color_inst = saturate_color(g, color_inst, g.lerp(1.0 - vs, vs + 1.0, r2)) * g.lerp(1.0 - vb, vb + 1.0, r1)
    color = sw(P("Use Instance Variation"), color_inst, color)

    # ---- 6. GLOBAL GRADE -----------------------------------------------------------------------------------------
    g.section("14 | GLOBAL GRADE\nhue, saturation, contrast, tint")
    color = hue_shift(g, color, P("Global Hue Shift"))
    color = saturate_color(g, color, P("Global Saturation"))
    color = contrast(g, color, P("Global Contrast"))
    color = color * P("Global Tint") * P("Global Brightness")
    color = color * g.lerp(1.0, ao_mask, P("AO Color Influence"))

    # ---- 7. WETNESS + PUDDLES ----------------------------------------------------------------------------------------
    g.section("15 | WETNESS + PUDDLES\ndamp surface, standing water in the low height")
    wet = P("Wetness")
    nonmetal = metal.one_minus()                                                  # water darkens dielectrics, not bare metal
    color_wet = saturate_color(g, color * (1.0 - P("Wet Darken") * wet * nonmetal), g.lerp(1.0, P("Wet Saturation"), wet))
    rough_wet = g.lerp(rough, g.vmin(rough, P("Wet Roughness")), wet)             # water only ever makes a surface smoother
    limit = g.vmin(P("Puddle Slope Limit"), 0.99)
    slope_ok = ((g.vertex_normal_ws().mask("b") - limit) / (1.0 - limit)).sat()
    puddle = reveal_weight(g, (P("Puddles") * slope_ok).sat(), P("Puddle Softness"), height,
                           0.0 - P("Puddle Height Influence"))                    # water fills the LOW parts first
    color_wet = color_wet * (1.0 - P("Puddle Darken") * puddle * nonmetal)
    rough_wet = g.lerp(rough_wet, g.vmin(rough_wet, P("Puddle Roughness")), puddle)
    use_wet = P("Use Wetness")
    color = sw(use_wet, color_wet, color)
    rough = sw(use_wet, rough_wet, rough)

    # ---- 8. FINAL LIMITS ---------------------------------------------------------------------------------------------
    # Applied last, so nothing upstream (saturation boosts, wetness ...) can leave the plausible range.
    g.section("16 | FINAL LIMITS\nalbedo clamp, roughness, AO")
    color = g.vmax(g.vmin(color, P("Albedo Max")), P("Albedo Min"))
    rough = g.vmax((rough + P("Global Roughness Offset")).sat(), P("Roughness Floor"))
    ao = S.ao * g.lerp(1.0, ao_mask, P("Mask AO Strength"))
    ao = g.lerp(1.0, ao, P("Global AO Strength"))
    specular = P("Specular")

    # ---- 9. NORMAL FINISH ----------------------------------------------------------------------------------------------
    g.section("17 | NORMAL FINISH\ndetail, intensity, puddles, distance")
    detail = g.sample_param("Detail Normal Texture", tiling_uv * P("Detail Normal Tiling"))
    detail = normal_intensity(g, flip_green(g, detail, P("Detail Normal Flip Green")), P("Detail Normal Intensity"))
    detail_far = g.smoothstep(depth, P("Detail Fade Start"), P("Detail Fade End"))
    cover = g.vmax(sw(P("Use Top Coating"), w_coat * P("Coat Cover Flatten"), 0.0),          # thick dirt / snow hide the fine detail too
                   sw(P("Use Dirt Layer"), w_dirt * P("Dirt Cover Flatten"), 0.0))
    detail = nops.flatten(detail, g.vmax(detail_far, cover))                      # ... and it melts away with distance
    normal = sw(P("Use Detail Normal"), nops.blend(normal, detail), normal)
    normal = normal_intensity(g, normal, P("Global Normal Intensity"))
    normal = sw(use_wet, nops.flatten(normal, puddle * P("Puddle Flatten")), normal)       # water is flat
    far = g.smoothstep(depth, P("Distance Flatten Start"), P("Distance Flatten End")) * P("Distance Flatten Amount")
    normal = sw(P("Use Distance Flatten"), nops.flatten(normal, far), normal)
    normal = g.normalize(normal)

    # ---- 10. EMISSIVE + OPACITY -------------------------------------------------------------------------------------------
    g.section("18 | EMISSIVE + OPACITY")
    emissive_tex = g.sample_param("Emissive Texture", unique_uv)
    pulse = 1.0 + P("Emissive Pulse Amount") * g.sine(g.time() * P("Emissive Pulse Speed"), 1.0)
    emissive = sw(P("Use Emissive"), emissive_tex * P("Emissive Color") * P("Emissive Intensity") * pulse,
                  g.vec3(0.0, 0.0, 0.0))
    opacity_uv = g.lerp(unique_uv, tiling_uv, g.floor(P("Opacity Uses Tiling UV") + 0.5))      # 0 / 1 only
    opacity_tex = g.sample_param("Opacity Texture", opacity_uv).mask("r")
    opacity_cut = ((opacity_tex - P("Opacity Threshold")) / g.vmax(P("Opacity Softness"), 0.001) + 0.5).sat()
    opacity = sw(P("Use Opacity Mask"), opacity_cut, 1.0)

    # ---- 11. DEBUG VIEW ---------------------------------------------------------------------------------------------------------
    g.section("19 | DEBUG VIEW\nfree while switched off")

    def v3(x):
        return g.broadcast(x, 3)

    u_floor, v_floor = g.floor(tiling_uv.mask("r")), g.floor(tiling_uv.mask("g"))
    checker = ((u_floor + v_floor) * 0.5).frac() * 2.0
    views = [
        v3(m_wear), v3(m_dirt), v3(m_scr), v3(m_ao_raw),                                       # 1-4
        vc, v3(vc_alpha),                                                                      # 5-6
        g.append(g.append(bk_wear, bk_dirt), bk_b),                                            # 7
        v3(checker), g.append(unique_uv, g.const(0.0)),                                        # 8-9
        v3(w_wear), v3(w_dirt), v3(w_scr), v3(w_vp[0]), v3(w_vp[1]), v3(w_vp[2]), v3(w_coat),  # 10-16
        g.append(g.append(sw(use_wet, wet, 0.0), sw(use_wet, puddle, 0.0)), g.const(0.0)),    # 17 (zero while Use Wetness is off)
        v3(height), normal * 0.5 + 0.5,                                                        # 18-19
        v3((coat_slope * 0.5 + 0.5).sat()),                                                    # 20
        color, v3(rough), v3(metal), v3(ao),                                                   # 21-24
    ]
    if len(views) != len(DEBUG_MODES):
        raise BuildError("debug views (%d) and DEBUG_MODES (%d) differ" % (len(views), len(DEBUG_MODES)))
    mode = g.floor(P("Debug Mode") + 0.5)                                                      # whole numbers only
    dbg = None
    for i, view in enumerate(views, start=1):
        term = view * (mode - float(i)).abs().one_minus().sat()                                # 1 when Mode == i, else 0
        dbg = term if dbg is None else dbg + term
    dbg_on = P("Debug View")

    # ---- 12. OUTPUTS ------------------------------------------------------------------------------------------------------------------
    g.section("20 | MATERIAL OUTPUTS")
    connect_property(g, "MP_BASE_COLOR", sw(dbg_on, g.vec3(0.0, 0.0, 0.0), color), 3)
    connect_property(g, "MP_METALLIC", sw(dbg_on, 0.0, metal), 1)
    connect_property(g, "MP_SPECULAR", sw(dbg_on, 0.0, specular), 1)
    connect_property(g, "MP_ROUGHNESS", sw(dbg_on, 1.0, rough), 1)
    connect_property(g, "MP_NORMAL", normal, 3)
    connect_property(g, "MP_AMBIENT_OCCLUSION", sw(dbg_on, 1.0, ao), 1)
    connect_property(g, "MP_EMISSIVE_COLOR", sw(dbg_on, dbg, emissive), 3)
    connect_property(g, "MP_OPACITY_MASK", opacity, 1)                       # Blend Mode Masked
    connect_property(g, "MP_OPACITY", opacity, 1)                            # Blend Mode Translucent (ignored while Opaque)

    removed = g.prune()
    if removed:
        log("%s: removed %d unused nodes" % (MASTER_NAME, removed))
    g.finish()
    return g


# ==============================================================================
# 7. PLACEHOLDER TEXTURES (the defaults of the texture parameters)
# ------------------------------------------------------------------------------
# Thirteen tiny flat textures so the master compiles and every texture slot has a sensible
# neutral value until you assign your own (each layer's albedo placeholder has its own colour,
# so the layer stack is readable before you have textures). No external files are needed: the PNGs are
# written with plain Python (zlib), imported through the normal pipeline and given the
# correct compression / sRGB settings. These settings matter: the sampler type of a
# texture parameter must match the texture (Color <-> sRGB colour, Normal <-> Normalmap,
# Masks <-> "Masks (no sRGB)"), otherwise Unreal reports "Sampler type is X, should be Y".
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


def _srgb8(linear):
    """Linear 0..1 -> 8-bit sRGB, so a placeholder texture decodes back to the intended linear colour."""
    c = min(1.0, max(0.0, linear))
    v = 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055
    return int(round(v * 255.0))


def ensure_texture_settings(tex, compression, srgb, name):
    """An existing placeholder is never re-imported, but its settings must still match the sampler type of its slots."""
    changed = False
    want = enum("TextureCompressionSettings", compression)
    if tex.get_editor_property("compression_settings") != want:
        set_prop(tex, "compression_settings", want)
        changed = True
    if bool(tex.get_editor_property("srgb")) != bool(srgb):
        set_prop(tex, "srgb", bool(srgb))
        changed = True
    if changed:
        warn("Placeholder texture %s had the wrong import settings (they must match its role); corrected." % name)
        unreal.EditorAssetLibrary.save_loaded_asset(tex)


def import_texture(name, width, height, rgba, compression, srgb, normal_map=False):
    """Imports a flat-colour PNG as /Game/.../name unless that asset already exists (an existing one is never replaced)."""
    eal = unreal.EditorAssetLibrary
    full = TEXTURES_PATH + "/" + name
    if eal.does_asset_exist(full):
        tex = eal.load_asset(full)
        ensure_texture_settings(tex, compression, srgb, name)
        return tex
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


# key -> (asset name, RGBA, compression, sRGB, is normal map)
PLACEHOLDERS = {
    "black": ("T_MM_Black", (0, 0, 0, 255), "TC_DEFAULT", True, False),                 # emissive default
    "flatnormal": ("T_MM_FlatNormal", (128, 128, 255, 255), "TC_NORMALMAP", False, True),
    "ormh": ("T_MM_ORMH", (255, 128, 0, 128), "TC_MASKS", False, False),                # AO 1, rough .5, metal 0, height .5
    "mask": ("T_MM_Mask", (0, 0, 0, 255), "TC_MASKS", False, False),                    # no wear / dirt / scratches, AO 1
    "neutral": ("T_MM_Neutral", (128, 128, 128, 255), "TC_MASKS", False, False),        # breakup / macro: no change
    "white_mask": ("T_MM_WhiteMask", (255, 255, 255, 255), "TC_MASKS", False, False),   # opacity: fully opaque
}


# the colour of an empty layer lives in its placeholder albedo (the tints all default to white, so a texture you assign
# shows exactly as authored); linear values
LAYER_PLACEHOLDER_COLOR = {
    "Base": (0.62, 0.66, 0.72), "Wear": (0.50, 0.28, 0.17), "Dirt": (0.13, 0.10, 0.08), "Vertex1": (0.45, 0.12, 0.09),
    "Vertex2": (0.20, 0.36, 0.12), "Vertex3": (0.58, 0.50, 0.36), "Coat": (0.80, 0.82, 0.86),
}
for _key, _label, _group in LAYERS:
    PLACEHOLDERS["alb_" + _key.lower()] = ("T_MM_%s_Albedo" % _label.replace(" ", ""),
                                           tuple(_srgb8(c) for c in LAYER_PLACEHOLDER_COLOR[_key]) + (255,),
                                           "TC_DEFAULT", True, False)


def ensure_placeholder_textures():
    eal = unreal.EditorAssetLibrary
    out = {}
    for key, (name, rgba, tc, srgb, is_normal) in PLACEHOLDERS.items():
        if CREATE_PLACEHOLDER_TEXTURES:
            out[key] = import_texture(name, 8, 8, bytes(rgba) * 64, tc, srgb, is_normal)
        else:
            tex = eal.load_asset(TEXTURES_PATH + "/" + name)
            if tex is None:
                raise BuildError("Placeholder texture %s/%s is missing - set CREATE_PLACEHOLDER_TEXTURES = True" % (TEXTURES_PATH, name))
            ensure_texture_settings(tex, tc, srgb, name)
            out[key] = tex
    return out


# ==============================================================================
# 8. MATERIAL SETTINGS + MAIN
# ==============================================================================
def configure_material(mat):
    """Properties of the Material asset itself (not of the graph)."""
    set_prop(mat, "normal_curvature_to_roughness", True, required=False)   # specular anti-aliasing: bumpy normals raise roughness
    set_prop(mat, "tangent_space_normal", True, required=False)
    if not SET_USAGE_FLAGS:
        return
    mel = unreal.MaterialEditingLibrary
    for usage, flag in (("MATUSAGE_NANITE", "used_with_nanite"),
                        ("MATUSAGE_INSTANCED_STATIC_MESHES", "used_with_instanced_static_meshes")):
        try:
            mel.set_material_usage(mat, enum("MaterialUsage", usage))
        except Exception:                                   # noqa: BLE001 - fall back to the plain property
            set_prop(mat, flag, True, required=False)


def report_statistics(mat):
    """get_statistics makes the editor compile the representative shaders and WAIT for them: only used on request."""
    try:
        st = unreal.MaterialEditingLibrary.get_statistics(mat)
        log("%s: %d pixel-shader instructions, %d texture samples, %d samplers" % (
            MASTER_NAME, st.num_pixel_shader_instructions, st.num_pixel_texture_samples, st.num_samplers))
    except Exception as exc:                                # noqa: BLE001
        warn("statistics not available: %s" % exc)


def check_substrate():
    """M_Master drives the classic material pins (Base Color, Roughness ...). With Substrate on, the engine converts them."""
    for cvar in ("r.Substrate", "r.Strata"):
        try:
            on = int(unreal.SystemLibrary.get_console_variable_int_value(cvar)) != 0
        except Exception:                                   # noqa: BLE001 - no such variable / call: nothing to check
            continue
        if on:
            warn("Substrate is enabled in this project (%s). M_Master drives the classic material pins; the engine converts them, "
                 "but this has not been tested. If the material looks wrong, try it with Substrate off." % cvar)
            return


def main():
    try:
        return _build_everything()
    except BuildError as exc:
        err(str(exc))
        raise
    finally:
        cleanup_temp_files()


def _build_everything():
    mel = unreal.MaterialEditingLibrary
    log("=" * 70)
    log("Building %s/%s" % (ROOT_PATH, MASTER_NAME))
    check_substrate()
    textures = ensure_placeholder_textures()
    mat = get_or_create_asset(ROOT_PATH, MASTER_NAME, unreal.Material, unreal.MaterialFactoryNew)
    clear_graph(mat)                                        # empty first: the recompiles the property changes below cause are trivial
    configure_material(mat)
    try:
        graph = build_master(mat, textures, USE_ENGINE_FUNCTIONS)
    except Exception as exc:                                # noqa: BLE001
        if not USE_ENGINE_FUNCTIONS:
            raise
        err("Build with the engine's FlattenNormal failed: %s" % exc)
        err(traceback.format_exc())
        warn("Retrying with the built-in FlattenNormal.")
        graph = build_master(mat, textures, False)
    mel.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    log("%s built: %d nodes, %d parameters in %d groups" % (MASTER_NAME, len(graph.nodes), len(graph.params.order),
                                                          len({d.group for d in graph.params.items.values()})))
    if PRINT_SHADER_STATISTICS:
        report_statistics(mat)
    log("DONE. Open %s/%s, then right-click it > Create Material Instance." % (ROOT_PATH, MASTER_NAME))
    log("Compile errors do NOT show up in this log: open the master and look for red nodes / the Stats panel, "
        "and read Window > Developer Tools > Message Log.")
    return mat


# Runs when executed inside Unreal (also via "Execute Python Script", where __name__ may not be "__main__").
# The offline test-suite sets MM_NO_AUTORUN=1 so it can import this file and drive the pieces.
if unreal is not None and not os.environ.get("MM_NO_AUTORUN"):
    main()
