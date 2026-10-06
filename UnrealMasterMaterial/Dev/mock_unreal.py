"""
mock_unreal.py - a STRICT offline stand-in for the slice of Unreal's Python API that
Scripts/build_master_material.py uses.

Why it exists
-------------
Unreal Editor is not available where this project was written, so the generator could not be
run inside the real editor. To still catch as many mistakes as possible, the generator is
executed against this mock, which validates things the way the real API does:

* every `set_editor_property(name, ...)` must be a real, writable property of that class
  (property tables come from ue_api_facts.json, extracted from the UE 5.6 python stub)
* every enum member used (`unreal.BlendMode.BLEND_MASKED` ...) must exist
* every library call is checked against the real signature (names / arity / defaults)
* `connect_material_expressions` fails (returns False) for unknown pin names, like Unreal
* the graph can be "compiled": dimension checks, missing inputs, sampler-type vs. texture
  compression checks, static switch pruning (see graph_eval.py)

What it is NOT: a replacement for opening the material in Unreal. Pin names / output names
(`PINS` below) are written from knowledge of the engine, not extracted from it.
"""
import json
import os
import struct
import sys
import types
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
FACTS = json.load(open(os.path.join(HERE, "ue_api_facts.json")))

LOG = []          # (level, message) - everything the generator logs
PROPERTY_REFRESHES_CALL_NODE = [True]    # tests flip this to simulate an engine that does not refresh the pins
SETTERS_RETURN_FALSE = [False]           # Epic UE-291403: set_material_instance_*_parameter_value apply the value but return False
REGISTRY = {}     # asset path -> asset object


class UnrealError(Exception):
    """Raised where Unreal would raise a Python exception."""


# --------------------------------------------------------------------------- #
# Structs
# --------------------------------------------------------------------------- #
def _check_init(class_name, args, kwargs):
    """Struct constructors must match the stub's __init__ (e.g. Vector4f() takes NO arguments)."""
    init = FACTS["classes"].get(class_name, {}).get("init")
    if init is None:
        return
    names = [p["name"] for p in init]
    if len(args) > len(names):
        raise UnrealError("TypeError: %s.__init__() takes %d positional argument(s) but %d were given" % (class_name, len(names), len(args)))
    for k in kwargs:
        if k not in names:
            raise UnrealError("TypeError: %s.__init__() got an unexpected keyword argument '%s'" % (class_name, k))


class LinearColor:
    def __init__(self, *args, **kwargs):
        _check_init("LinearColor", args, kwargs)
        vals = dict(zip(("r", "g", "b", "a"), args))
        vals.update(kwargs)
        self.r, self.g, self.b, self.a = (float(vals.get(k, d)) for k, d in (("r", 0.0), ("g", 0.0), ("b", 0.0), ("a", 0.0)))

    def __repr__(self):
        return "LinearColor(%g,%g,%g,%g)" % (self.r, self.g, self.b, self.a)


class Vector4f:
    """UE 5.6 stub: `def __init__(self) -> None` - NO constructor arguments; fields are editor properties."""

    def __init__(self, *args, **kwargs):
        _check_init("Vector4f", args, kwargs)
        self.x = self.y = self.z = self.w = 0.0

    def set_editor_property(self, name, value, notify_mode=None):
        if name not in ("x", "y", "z", "w"):
            raise UnrealError("Exception: Failed to find property '%s' on 'Vector4f'" % name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise UnrealError("TypeError: Vector4f.%s expects float" % name)
        setattr(self, name, float(value))

    def get_editor_property(self, name):
        if name not in ("x", "y", "z", "w"):
            raise UnrealError("Exception: Failed to find property '%s' on 'Vector4f'" % name)
        return getattr(self, name)

    def __repr__(self):
        return "Vector4f(%g,%g,%g,%g)" % (self.x, self.y, self.z, self.w)


class Vector4:
    """Double-precision vector: positional constructor, but NOT accepted where a Vector4f property is expected."""

    def __init__(self, *args, **kwargs):
        _check_init("Vector4", args, kwargs)
        vals = dict(zip(("x", "y", "z", "w"), args))
        vals.update(kwargs)
        self.x, self.y, self.z, self.w = (float(vals.get(k, 0.0)) for k in "xyzw")


# --------------------------------------------------------------------------- #
# Enums (generated from the real stub)
# --------------------------------------------------------------------------- #
class EnumBase:
    def __init__(self, enum_name, name, value):
        self._enum, self.name, self.value = enum_name, name, value

    def __repr__(self):
        return "%s.%s" % (self._enum, self.name)


def _make_enum(enum_name, members):
    cls = type(enum_name, (EnumBase,), {})
    for mname, mval in members.items():
        setattr(cls, mname, cls(enum_name, mname, mval))
    return cls


ENUMS = {name: _make_enum(name, members) for name, members in FACTS["enums"].items()}


def enum_member_names(enum_name):
    return [k for k in vars(ENUMS[enum_name]) if k.isupper() or "_" in k and k == k.upper()]


# --------------------------------------------------------------------------- #
# Property validation helpers
# --------------------------------------------------------------------------- #
def _check_type(type_str, value, owner, name):
    t = type_str.strip()
    ok = True
    if t in ("float", "double"):
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif t.startswith("int") or t.startswith("uint"):
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif t == "bool":
        ok = isinstance(value, bool)
    elif t in ("str", "Name", "Text"):
        ok = isinstance(value, str)
    elif t == "LinearColor":
        ok = isinstance(value, LinearColor)
    elif t == "Vector4f":
        ok = isinstance(value, Vector4f)
    elif t == "Vector4":
        ok = isinstance(value, Vector4)
    elif t in ENUMS:
        ok = isinstance(value, ENUMS[t])
    elif t in ("Texture", "Texture2D"):
        ok = value is None or isinstance(value, Texture2D)
    elif t == "MaterialFunctionInterface":
        ok = value is None or isinstance(value, MaterialFunction)
    elif t == "MaterialInterface":
        ok = value is None or isinstance(value, (Material, MaterialInstanceConstant))
    if not ok:
        raise UnrealError("TypeError: property '%s' of %s expects %s, got %r" % (name, owner, t, value))


class PropObject:
    """Base for everything that has editor properties."""
    _cls_key = None
    _defaults = {}

    def __init__(self):
        self._props = {}

    @classmethod
    def _facts(cls):
        return FACTS["classes"].get(cls._cls_key, {}).get("props", {})

    def set_editor_property(self, name, value, notify_mode=None):
        info = self._facts().get(name)
        if info is None:
            raise UnrealError("Exception: Failed to find property '%s' for attribute '%s' on '%s'"
                              % (name, name, type(self).__name__))
        if info["access"] == "Read-Only":
            raise UnrealError("Exception: Property '%s' on '%s' is read-only" % (name, type(self).__name__))
        _check_type(info["type"], value, type(self).__name__, name)
        self._props[name] = value

    def get_editor_property(self, name):
        info = self._facts().get(name)
        if info is None:
            raise UnrealError("Exception: Failed to find property '%s' on '%s'" % (name, type(self).__name__))
        if name in self._props:
            return self._props[name]
        return self._defaults.get(name)


# --------------------------------------------------------------------------- #
# Textures / assets
# --------------------------------------------------------------------------- #
class Texture2D(PropObject):
    _cls_key = "Texture2D"
    _defaults = {
        "compression_settings": ENUMS["TextureCompressionSettings"].TC_DEFAULT,
        "srgb": True,
        "lod_group": ENUMS["TextureGroup"].TEXTUREGROUP_WORLD,
        "mip_gen_settings": ENUMS["TextureMipGenSettings"].TMGS_FROM_TEXTURE_GROUP,
        "filter": ENUMS["TextureFilter"].TF_DEFAULT,
        "address_x": ENUMS["TextureAddress"].TA_WRAP,
        "address_y": ENUMS["TextureAddress"].TA_WRAP,
        "never_stream": False,
        "compression_no_alpha": False,
        "flip_green_channel": False,
    }

    def __init__(self, path, width=0, height=0, rgba=b""):
        super().__init__()
        self.path, self.width, self.height, self.rgba = path, width, height, rgba
        self.saved = False

    def get_name(self):
        return self.path.rsplit("/", 1)[-1]

    def mean_rgba(self):
        n = self.width * self.height
        if not n:
            return (0.5, 0.5, 0.5, 1.0)
        acc = [0, 0, 0, 0]
        for i in range(n):
            for c in range(4):
                acc[c] += self.rgba[i * 4 + c]
        return tuple(a / n / 255.0 for a in acc)

    def sampler_type_expected(self):
        """Mirrors UMaterialExpressionTextureBase::GetSamplerTypeForTexture."""
        tc = self.get_editor_property("compression_settings")
        srgb = self.get_editor_property("srgb")
        S = ENUMS["MaterialSamplerType"]
        T = ENUMS["TextureCompressionSettings"]
        if tc is T.TC_NORMALMAP:
            return S.SAMPLERTYPE_NORMAL
        if tc is T.TC_GRAYSCALE:
            return S.SAMPLERTYPE_GRAYSCALE if srgb else S.SAMPLERTYPE_LINEAR_GRAYSCALE
        if tc is T.TC_MASKS:
            return S.SAMPLERTYPE_MASKS
        if tc is T.TC_ALPHA:
            return S.SAMPLERTYPE_ALPHA
        return S.SAMPLERTYPE_COLOR if srgb else S.SAMPLERTYPE_LINEAR_COLOR


class Material(PropObject):
    _cls_key = "Material"
    _defaults = {
        "blend_mode": ENUMS["BlendMode"].BLEND_OPAQUE,
        "material_domain": ENUMS["MaterialDomain"].MD_SURFACE,
        "shading_model": ENUMS["MaterialShadingModel"].MSM_DEFAULT_LIT,
        "two_sided": False,
        "tangent_space_normal": True,
        "use_material_attributes": False,
        "opacity_mask_clip_value": 0.3333,
    }

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.expressions = []
        self.property_links = {}        # MaterialProperty member -> (expr, out_idx)
        self.saved = False
        self.recompiles = 0


class MaterialFunction(PropObject):
    _cls_key = "MaterialFunction"
    _defaults = {"description": "", "expose_to_library": False}

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.expressions = []
        self.saved = False
        self.updates = 0

    def function_inputs(self):
        ins = [e for e in self.expressions if type(e).__name__ == "MaterialExpressionFunctionInput"]
        ins.sort(key=lambda e: (e.get_editor_property("sort_priority") or 0, e.creation_index))
        return ins

    def function_outputs(self):
        outs = [e for e in self.expressions if type(e).__name__ == "MaterialExpressionFunctionOutput"]
        outs.sort(key=lambda e: (e.get_editor_property("sort_priority") or 0, e.creation_index))
        return outs


class MaterialInstanceConstant(PropObject):
    _cls_key = "MaterialInstanceConstant"

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.parent = None
        self.scalars, self.vectors, self.textures, self.statics = {}, {}, {}, {}
        self.saved = False


# --------------------------------------------------------------------------- #
# Expression pin tables (written from engine knowledge - see module docstring)
#   ins  : input pin names in engine order
#   outs : (name, dim)  dim: int, or a rule name resolved by graph_eval
# --------------------------------------------------------------------------- #
TEX_OUTS = [("RGB", 3), ("R", 1), ("G", 1), ("B", 1), ("A", 1), ("RGBA", 4)]
PINS = {
    "Abs": (["Input"], [("", "same0")]),
    "Add": (["A", "B"], [("", "arith")]),
    "AppendVector": (["A", "B"], [("", "append")]),
    "Clamp": (["Input", "Min", "Max"], [("", "same0")]),
    "Comment": ([], []),
    "ComponentMask": (["Input"], [("", "mask")]),
    "Constant": ([], [("", 1)]),
    "Constant2Vector": ([], [("", 2)]),
    "Constant3Vector": ([], [("", 3)]),
    "Constant4Vector": ([], [("", 4)]),
    "Cosine": (["Input"], [("", "same0")]),
    "Desaturation": (["Input", "Fraction"], [("", 3)]),
    "Divide": (["A", "B"], [("", "arith")]),
    "DotProduct": (["A", "B"], [("", 1)]),
    "Floor": (["Input"], [("", "same0")]),
    "Frac": (["Input"], [("", "same0")]),
    "FunctionInput": (["Preview"], [("", "fninput")]),
    "FunctionOutput": (["Input"], []),
    "If": (["A", "B", "A > B", "A == B", "A < B"], [("", "arith_if")]),
    "LinearInterpolate": (["A", "B", "Alpha"], [("", "lerp")]),
    "MaterialFunctionCall": (None, None),   # dynamic
    "Max": (["A", "B"], [("", "arith")]),
    "Min": (["A", "B"], [("", "arith")]),
    "Multiply": (["A", "B"], [("", "arith")]),
    "Normalize": (["VectorInput"], [("", "same0")]),
    "ObjectPositionWS": ([], [("", 3)]),
    "OneMinus": (["Input"], [("", "same0")]),
    "PerInstanceRandom": ([], [("", 1)]),
    "PixelDepth": ([], [("", 1)]),
    "Power": (["Base", "Exponent"], [("", "same0")]),
    "Reroute": (["Input"], [("", "same0")]),
    "Saturate": (["Input"], [("", "same0")]),
    "ScalarParameter": ([], [("", 1)]),
    "Sine": (["Input"], [("", "same0")]),
    "SmoothStep": (["Min", "Max", "Value"], [("", "same2")]),
    "SquareRoot": (["Input"], [("", "same0")]),
    "StaticBoolParameter": ([], [("", "bool")]),
    "StaticSwitch": (["True", "False", "Value"], [("", "switch")]),
    "StaticSwitchParameter": (["True", "False"], [("", "switch")]),
    "Step": (["Y", "X"], [("", "arith")]),
    "Subtract": (["A", "B"], [("", "arith")]),
    "TextureCoordinate": ([], [("", 2)]),
    "TextureObjectParameter": ([], [("", "tex")]),
    "TextureSample": (["UVs", "Tex", "Level", "DDX(UVs)", "DDY(UVs)", "Apply View MipBias"], TEX_OUTS),
    "TextureSampleParameter2D": (["UVs", "Tex", "Level", "DDX(UVs)", "DDY(UVs)", "Apply View MipBias"], TEX_OUTS),
    "VectorParameter": ([], [("", 3), ("R", 1), ("G", 1), ("B", 1), ("A", 1)]),
    "VertexColor": ([], [("", 3), ("R", 1), ("G", 1), ("B", 1), ("A", 1)]),   # main pin = RGB, like the engine node
    "WorldPosition": ([], [("", 3)]),
}

# Defaults the engine gives to constants used when an input pin is not connected
EXPR_DEFAULTS = {
    "Add": {"const_a": 0.0, "const_b": 1.0},
    "Subtract": {"const_a": 1.0, "const_b": 1.0},
    "Multiply": {"const_a": 0.0, "const_b": 1.0},
    "Divide": {"const_a": 1.0, "const_b": 2.0},
    "Min": {"const_a": 0.0, "const_b": 1.0},
    "Max": {"const_a": 0.0, "const_b": 1.0},
    "LinearInterpolate": {"const_a": 0.0, "const_b": 1.0, "const_alpha": 0.5},
    "Power": {"const_exponent": 2.0},
    "Clamp": {"min_default": 0.0, "max_default": 1.0},
    "Constant": {"r": 0.0},
    "Constant2Vector": {"r": 0.0, "g": 0.0},
    "TextureCoordinate": {"coordinate_index": 0, "u_tiling": 1.0, "v_tiling": 1.0},
    "ComponentMask": {"r": True, "g": True, "b": False, "a": False},
    "Sine": {"period": 1.0},
    "Cosine": {"period": 1.0},
    "ScalarParameter": {"default_value": 0.0},
    "StaticBoolParameter": {"default_value": False},
    "StaticSwitch": {"default_value": False},
    "FunctionInput": {"use_preview_value_as_default": False},
    "SmoothStep": {"const_min": 0.0, "const_max": 1.0, "const_value": 0.5},
    "Step": {"const_x": 0.0, "const_y": 0.0},
    "TextureSample": {"sampler_type": ENUMS["MaterialSamplerType"].SAMPLERTYPE_COLOR,
                      "sampler_source": ENUMS["SamplerSourceMode"].SSM_FROM_TEXTURE_ASSET},
    "TextureSampleParameter2D": {"sampler_type": ENUMS["MaterialSamplerType"].SAMPLERTYPE_COLOR,
                                 "sampler_source": ENUMS["SamplerSourceMode"].SSM_FROM_TEXTURE_ASSET},
    "TextureObjectParameter": {"sampler_type": ENUMS["MaterialSamplerType"].SAMPLERTYPE_COLOR,
                               "sampler_source": ENUMS["SamplerSourceMode"].SSM_FROM_TEXTURE_ASSET},
}


class ExpressionBase(PropObject):
    _short = None
    _creation_counter = [0]

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        ExpressionBase._creation_counter[0] += 1
        self.creation_index = ExpressionBase._creation_counter[0]
        self._props.update(EXPR_DEFAULTS.get(self._short, {}))
        self._props["material_expression_editor_x"] = 0
        self._props["material_expression_editor_y"] = 0
        self.function = None            # for MaterialFunctionCall
        self.inputs = [None] * len(self.input_names())

    # ---- pins
    def input_names(self):
        if self._short == "MaterialFunctionCall":
            if self.function is None:
                return []
            return [str(f.get_editor_property("input_name")) for f in self.function.function_inputs()]
        return list(PINS[self._short][0])

    def output_specs(self):
        if self._short == "MaterialFunctionCall":
            if self.function is None:
                return []
            return [(str(f.get_editor_property("output_name")), "fnout") for f in self.function.function_outputs()]
        return list(PINS[self._short][1])

    def output_names(self):
        return [n for n, _ in self.output_specs()]

    # ---- python API used by the generator
    def set_editor_property(self, name, value, notify_mode=None):
        super().set_editor_property(name, value, notify_mode)
        # like the editor: assigning a texture re-derives the sampler type from the texture (AutoSetSampleType),
        # which is why the generator assigns `texture` BEFORE `sampler_type`
        if name == "texture" and value is not None and self._short in ("TextureSample", "TextureSampleParameter2D", "TextureObjectParameter"):
            self._props["sampler_type"] = value.sampler_type_expected()
        # like the editor: changing the property runs the post-edit refresh that creates the call node's pins
        if self._short == "MaterialFunctionCall" and name == "material_function" and PROPERTY_REFRESHES_CALL_NODE[0]:
            if isinstance(value, MaterialFunction):
                self.function = value
                self.inputs = [None] * len(self.input_names())

    def set_material_function(self, new_material_function):
        if self._short != "MaterialFunctionCall":
            raise UnrealError("AttributeError: set_material_function only exists on MaterialFunctionCall")
        if not isinstance(new_material_function, MaterialFunction):
            return False
        self.function = new_material_function
        self.inputs = [None] * len(self.input_names())
        return True

    def __repr__(self):
        nm = self._props.get("parameter_name") or self._props.get("input_name") or self._props.get("output_name") or ""
        return "<%s #%d %s>" % (type(self).__name__, self.creation_index, nm)


def _make_expression_classes():
    out = {}
    for full in FACTS["classes"]:
        if not full.startswith("MaterialExpression"):
            continue
        short = full[len("MaterialExpression"):]
        cls = type(full, (ExpressionBase,), {"_cls_key": full, "_short": short})
        out[full] = cls
    return out


EXPRESSION_CLASSES = _make_expression_classes()


# --------------------------------------------------------------------------- #
# Library mocks (signatures validated against the real ones)
# --------------------------------------------------------------------------- #
def _bind(class_name, method, args, kwargs):
    info = FACTS["classes"][class_name]["methods"].get(method)
    if info is None:
        raise UnrealError("AttributeError: %s has no method %s" % (class_name, method))
    params = info["params"]
    bound = {}
    if len(args) > len(params):
        raise UnrealError("TypeError: %s.%s takes %d args, got %d" % (class_name, method, len(params), len(args)))
    for p, a in zip(params, args):
        bound[p["name"]] = a
    for k, v in kwargs.items():
        if k not in [p["name"] for p in params]:
            raise UnrealError("TypeError: %s.%s got unexpected keyword '%s'" % (class_name, method, k))
        if k in bound:
            raise UnrealError("TypeError: %s.%s got multiple values for '%s'" % (class_name, method, k))
        bound[k] = v
    for p in params:
        if p["name"] not in bound:
            if not p["has_default"]:
                raise UnrealError("TypeError: %s.%s missing required '%s'" % (class_name, method, p["name"]))
            bound[p["name"]] = None
    return bound


def _is_function_expr(expr):
    return isinstance(expr.owner, MaterialFunction)


class MaterialEditingLibrary:
    """Only what the generator needs, each call signature-checked."""

    @classmethod
    def create_material_expression(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "create_material_expression", a, k)
        return cls._create(b["material"], b["expression_class"], b["node_pos_x"] or 0, b["node_pos_y"] or 0, False)

    @classmethod
    def create_material_expression_in_function(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "create_material_expression_in_function", a, k)
        return cls._create(b["material_function"], b["expression_class"], b["node_pos_x"] or 0, b["node_pos_y"] or 0, True)

    @staticmethod
    def _create(owner, expression_class, x, y, in_function):
        if in_function and not isinstance(owner, MaterialFunction):
            raise UnrealError("TypeError: expected MaterialFunction")
        if not in_function and not isinstance(owner, Material):
            raise UnrealError("TypeError: expected Material")
        if not (isinstance(expression_class, type) and issubclass(expression_class, ExpressionBase)):
            raise UnrealError("TypeError: expression_class must be a MaterialExpression subclass")
        if expression_class._short not in PINS:
            raise UnrealError("mock: no pin table for %s" % expression_class.__name__)
        e = expression_class(owner)
        e._props["material_expression_editor_x"] = int(x)
        e._props["material_expression_editor_y"] = int(y)
        owner.expressions.append(e)
        return e

    @classmethod
    def connect_material_expressions(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "connect_material_expressions", a, k)
        src, out_name, dst, in_name = b["from_expression"], b["from_output_name"], b["to_expression"], b["to_input_name"]
        if src is None or dst is None or src is dst:
            return False
        if src.owner is not dst.owner:
            return False
        if not isinstance(out_name, str) or not isinstance(in_name, str):
            raise UnrealError("TypeError: pin names must be str")
        in_names = dst.input_names()
        if in_name == "":
            if not in_names:
                return False
            in_idx = 0
        else:
            if in_name not in in_names:
                return False
            in_idx = in_names.index(in_name)
        out_names = src.output_names()
        if out_name == "":
            if not out_names:
                return False
            out_idx = 0
        else:
            if out_name not in out_names:
                return False
            out_idx = out_names.index(out_name)
        dst.inputs[in_idx] = (src, out_idx)
        return True

    @classmethod
    def connect_material_property(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "connect_material_property", a, k)
        src, out_name, prop = b["from_expression"], b["from_output_name"], b["property_"]
        if not isinstance(prop, ENUMS["MaterialProperty"]):
            raise UnrealError("TypeError: property_ must be unreal.MaterialProperty")
        out_names = src.output_names()
        if out_name == "":
            out_idx = 0 if out_names else None
        else:
            out_idx = out_names.index(out_name) if out_name in out_names else None
        if out_idx is None:
            return False
        src.owner.property_links[prop] = (src, out_idx)
        return True

    @classmethod
    def get_material_expression_input_names(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "get_material_expression_input_names", a, k)
        return list(b["material_expression"].input_names())

    @classmethod
    def recompile_material(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "recompile_material", a, k)
        b["material"].recompiles += 1

    @classmethod
    def update_material_function(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "update_material_function", a, k)
        b["material_function"].updates += 1

    @classmethod
    def delete_all_material_expressions(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "delete_all_material_expressions", a, k)
        b["material"].expressions = []
        b["material"].property_links = {}

    @classmethod
    def delete_all_material_expressions_in_function(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "delete_all_material_expressions_in_function", a, k)
        b["material_function"].expressions = []

    @staticmethod
    def _delete(owner, expr):
        if expr not in owner.expressions:
            raise UnrealError("expression does not belong to this asset")
        owner.expressions.remove(expr)
        for e in owner.expressions:                       # disconnect, like the engine does
            e.inputs = [None if (l is not None and l[0] is expr) else l for l in e.inputs]
        for prop, link in list(owner.property_links.items()):
            if link[0] is expr:
                del owner.property_links[prop]

    @classmethod
    def delete_material_expression(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "delete_material_expression", a, k)
        cls._delete(b["material"], b["expression"])

    @classmethod
    def delete_material_expression_in_function(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "delete_material_expression_in_function", a, k)
        cls._delete(b["material_function"], b["expression"])

    @classmethod
    def layout_material_expressions(cls, *a, **k):
        _bind("MaterialEditingLibrary", "layout_material_expressions", a, k)

    @classmethod
    def get_statistics(cls, *a, **k):
        _bind("MaterialEditingLibrary", "get_statistics", a, k)
        s = types.SimpleNamespace(num_pixel_shader_instructions=0, num_pixel_texture_samples=0,
                                  num_samplers=0, num_vertex_shader_instructions=0)
        return s

    @classmethod
    def set_material_usage(cls, *a, **k):
        _bind("MaterialEditingLibrary", "set_material_usage", a, k)
        return False

    @classmethod
    def set_material_instance_parent(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "set_material_instance_parent", a, k)
        b["instance"].parent = b["new_parent"]

    @classmethod
    def set_material_instance_scalar_parameter_value(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "set_material_instance_scalar_parameter_value", a, k)
        b["instance"].scalars[b["parameter_name"]] = float(b["value"])
        return not SETTERS_RETURN_FALSE[0]

    @classmethod
    def set_material_instance_vector_parameter_value(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "set_material_instance_vector_parameter_value", a, k)
        if not isinstance(b["value"], LinearColor):
            raise UnrealError("TypeError: value must be LinearColor")
        b["instance"].vectors[b["parameter_name"]] = b["value"]
        return not SETTERS_RETURN_FALSE[0]

    @classmethod
    def set_material_instance_texture_parameter_value(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "set_material_instance_texture_parameter_value", a, k)
        if not isinstance(b["value"], Texture2D):
            raise UnrealError("TypeError: value must be a Texture")
        b["instance"].textures[b["parameter_name"]] = b["value"]
        return not SETTERS_RETURN_FALSE[0]

    @classmethod
    def set_material_instance_static_switch_parameter_value(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "set_material_instance_static_switch_parameter_value", a, k)
        if not isinstance(b["value"], bool):
            raise UnrealError("TypeError: value must be bool")
        b["instance"].statics[b["parameter_name"]] = b["value"]
        return not SETTERS_RETURN_FALSE[0]

    @classmethod
    def update_material_instance(cls, *a, **k):
        _bind("MaterialEditingLibrary", "update_material_instance", a, k)

    # ---- parameter names of a material / instance chain
    @staticmethod
    def _root_material(mat):
        while isinstance(mat, MaterialInstanceConstant):
            mat = mat.parent
        return mat

    @classmethod
    def _names(cls, material, shorts):
        root = cls._root_material(material)
        if not isinstance(root, Material):
            return []
        out = []
        for e in root.expressions:
            if e._short in shorts and e._props.get("parameter_name"):
                out.append(str(e._props["parameter_name"]))
        return out

    @classmethod
    def get_scalar_parameter_names(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "get_scalar_parameter_names", a, k)
        return cls._names(b["material"], ("ScalarParameter",))

    @classmethod
    def get_vector_parameter_names(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "get_vector_parameter_names", a, k)
        return cls._names(b["material"], ("VectorParameter",))

    @classmethod
    def get_texture_parameter_names(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "get_texture_parameter_names", a, k)
        return cls._names(b["material"], ("TextureObjectParameter", "TextureSampleParameter2D"))

    @classmethod
    def get_static_switch_parameter_names(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "get_static_switch_parameter_names", a, k)
        return cls._names(b["material"], ("StaticBoolParameter", "StaticSwitchParameter"))

    # ---- read back what an instance overrides (0 / False / None when it does not)
    @classmethod
    def get_material_instance_scalar_parameter_value(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "get_material_instance_scalar_parameter_value", a, k)
        return b["instance"].scalars.get(b["parameter_name"], 0.0)

    @classmethod
    def get_material_instance_vector_parameter_value(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "get_material_instance_vector_parameter_value", a, k)
        return b["instance"].vectors.get(b["parameter_name"], LinearColor(0, 0, 0, 0))

    @classmethod
    def get_material_instance_texture_parameter_value(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "get_material_instance_texture_parameter_value", a, k)
        return b["instance"].textures.get(b["parameter_name"])

    @classmethod
    def get_material_instance_static_switch_parameter_value(cls, *a, **k):
        b = _bind("MaterialEditingLibrary", "get_material_instance_static_switch_parameter_value", a, k)
        return b["instance"].statics.get(b["parameter_name"], False)


class EditorAssetLibrary:
    @classmethod
    def does_asset_exist(cls, *a, **k):
        b = _bind("EditorAssetLibrary", "does_asset_exist", a, k)
        return _norm(b["asset_path"]) in REGISTRY

    @classmethod
    def load_asset(cls, *a, **k):
        b = _bind("EditorAssetLibrary", "load_asset", a, k)
        return REGISTRY.get(_norm(b["asset_path"]))

    @classmethod
    def save_loaded_asset(cls, *a, **k):
        b = _bind("EditorAssetLibrary", "save_loaded_asset", a, k)
        if b["asset_to_save"] is None:
            return False
        b["asset_to_save"].saved = True
        return True

    @classmethod
    def make_directory(cls, *a, **k):
        _bind("EditorAssetLibrary", "make_directory", a, k)
        return True

    @classmethod
    def list_assets(cls, *a, **k):
        b = _bind("EditorAssetLibrary", "list_assets", a, k)
        root = b["directory_path"].rstrip("/") + "/"
        recursive = True if b["recursive"] is None else b["recursive"]
        out = []
        for path in REGISTRY:
            if path.startswith(root) and (recursive or "/" not in path[len(root):]):
                out.append(path + "." + path.rsplit("/", 1)[-1])      # object paths, like the engine
        return out

    @classmethod
    def delete_asset(cls, *a, **k):
        b = _bind("EditorAssetLibrary", "delete_asset", a, k)
        return REGISTRY.pop(_norm(b["asset_path_to_delete"]), None) is not None


def _norm(path):
    path = path.split(".")[0] if path.count(".") == 1 and "/" in path else path
    return path.rstrip("/")


class Factory(PropObject):
    _cls_key = "MaterialFactoryNew"


class MaterialFactoryNew(Factory):
    _cls_key = "MaterialFactoryNew"
    makes = Material


class MaterialFunctionFactoryNew(Factory):
    _cls_key = "MaterialFunctionFactoryNew"
    makes = MaterialFunction


class MaterialInstanceConstantFactoryNew(Factory):
    _cls_key = "MaterialInstanceConstantFactoryNew"
    makes = MaterialInstanceConstant


class AssetImportTask(PropObject):
    _cls_key = "AssetImportTask"
    _defaults = {"replace_existing": False, "automated": False, "save": True}


def decode_png(data):
    """Minimal PNG decoder (8-bit, non-interlaced, filter 0 only) - validates our writer."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise UnrealError("import failed: not a PNG")
    pos, idat, w = 8, b"", None
    while pos < len(data):
        (ln,) = struct.unpack(">I", data[pos:pos + 4])
        typ = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        (crc,) = struct.unpack(">I", data[pos + 8 + ln:pos + 12 + ln])
        if zlib.crc32(typ + body) & 0xFFFFFFFF != crc:
            raise UnrealError("import failed: bad CRC in chunk %r" % typ)
        if typ == b"IHDR":
            w, h, depth, ctype, _, _, ilace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or ctype != 6 or ilace != 0:
                raise UnrealError("mock decoder supports 8-bit RGBA only")
        elif typ == b"IDAT":
            idat += body
        pos += 12 + ln
    raw = zlib.decompress(idat)
    stride = w * 4
    if len(raw) != h * (stride + 1):
        raise UnrealError("import failed: IDAT size mismatch")
    out = bytearray()
    for y in range(h):
        row = raw[y * (stride + 1):(y + 1) * (stride + 1)]
        if row[0] != 0:
            raise UnrealError("mock decoder supports filter 0 only")
        out += row[1:]
    return w, h, bytes(out)


SELECTED_ASSETS = []     # what the Content Browser "has selected" for EditorUtilityLibrary


class EditorUtilityLibrary:
    @classmethod
    def get_selected_assets(cls, *a, **k):
        _bind("EditorUtilityLibrary", "get_selected_assets", a, k)
        return list(SELECTED_ASSETS)


class AssetTools:
    def create_asset(self, *a, **k):
        b = _bind("AssetTools", "create_asset", a, k)
        cls, factory = b["asset_class"], b["factory"]
        if not isinstance(factory, Factory) or getattr(factory, "makes", None) is not cls:
            raise UnrealError("mock: factory %r cannot create %r" % (factory, cls))
        path = _norm(b["package_path"] + "/" + b["asset_name"])
        if path in REGISTRY:
            return None            # UE returns None when the asset exists
        asset = cls(path)
        REGISTRY[path] = asset
        return asset

    def import_asset_tasks(self, tasks):
        b = _bind("AssetTools", "import_asset_tasks", (tasks,), {})
        for t in b["import_tasks"]:
            fn = t.get_editor_property("filename")
            data = open(fn, "rb").read()
            w, h, rgba = decode_png(data)
            path = _norm(t.get_editor_property("destination_path") + "/" + t.get_editor_property("destination_name"))
            if path in REGISTRY and not t.get_editor_property("replace_existing"):
                continue
            tex = Texture2D(path, w, h, rgba)
            REGISTRY[path] = tex
            t.set_editor_property("result", [tex])
            t.set_editor_property("imported_object_paths", [path])


class AssetToolsHelpers:
    _tools = AssetTools()

    @classmethod
    def get_asset_tools(cls):
        return cls._tools


# --------------------------------------------------------------------------- #
# Module installation
# --------------------------------------------------------------------------- #
def install():
    """Create (or reset) the fake `unreal` module in sys.modules and return it."""
    LOG.clear()
    REGISTRY.clear()
    ExpressionBase._creation_counter[0] = 0
    mod = types.ModuleType("unreal")
    mod.__dict__.update({
        "LinearColor": LinearColor, "Vector4f": Vector4f, "Vector4": Vector4,
        "Material": Material, "MaterialFunction": MaterialFunction,
        "MaterialInstanceConstant": MaterialInstanceConstant, "Texture2D": Texture2D,
        "MaterialFactoryNew": MaterialFactoryNew, "MaterialFunctionFactoryNew": MaterialFunctionFactoryNew,
        "MaterialInstanceConstantFactoryNew": MaterialInstanceConstantFactoryNew,
        "AssetImportTask": AssetImportTask, "MaterialEditingLibrary": MaterialEditingLibrary,
        "EditorAssetLibrary": EditorAssetLibrary, "AssetToolsHelpers": AssetToolsHelpers,
        "EditorUtilityLibrary": EditorUtilityLibrary,
        "MaterialExpression": ExpressionBase,
        "log": lambda m: LOG.append(("info", str(m))),
        "log_warning": lambda m: LOG.append(("warning", str(m))),
        "log_error": lambda m: LOG.append(("error", str(m))),
    })
    mod.__dict__.update(ENUMS)
    mod.__dict__.update(EXPRESSION_CLASSES)
    sys.modules["unreal"] = mod
    return mod
