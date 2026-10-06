"""
graph_eval.py - interpreter for graphs built through mock_unreal.

* "compile" semantics: dimension checks (float3 + float2 is an error, scalars broadcast),
  missing inputs, static-switch pruning, sampler-type vs texture-compression checks,
  function inputs/outputs.
* numeric semantics: evaluates the reachable part of the graph for ONE pixel given a
  context (UVs, vertex colour, parameter overrides, constant textures ...).

Textures in tests are supplied *after* sampler decoding, i.e. a Normal-type texture override
must already be an unpacked tangent-space vector in [-1, 1] (that is what the real
`SAMPLERTYPE_NORMAL` sample returns). Textures that are NOT overridden come from the
imported placeholder PNG (decoded; normals are unpacked like BC5 would be).
"""
import math

import mock_unreal as mu

U = mu.ENUMS


class CompileError(Exception):
    """What would be a red error in the Unreal material editor."""


def _broadcast(a, b, what):
    la, lb = len(a), len(b)
    if la == lb:
        return a, b
    if la == 1:
        return a * lb, b
    if lb == 1:
        return a, b * la
    raise CompileError("%s: incompatible dimensions %d and %d" % (what, la, lb))


def _arith(a, b, fn, what):
    a, b = _broadcast(a, b, what)
    return tuple(fn(x, y) for x, y in zip(a, b))


def _unary(a, fn):
    return tuple(fn(x) for x in a)


def _sat(x):
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _div(x, y):
    # GPUs return +-inf / NaN; the tests treat that as a failure, so surface it as one
    if y == 0.0:
        raise CompileError("division by zero at runtime (would be INF/NaN on the GPU)")
    return x / y


class Frame:
    """One function-call activation (the master is frame None)."""
    def __init__(self, call_expr, caller_frame, evaluator):
        self.call = call_expr
        self.caller = caller_frame
        self.ev = evaluator
        self.memo = {}


class Evaluator:
    def __init__(self, material, ctx=None):
        self.material = material
        self.ctx = ctx or {}
        self.visited = set()           # expressions touched (reachable under the static config)
        self.tex_samples = []          # (node, texture param name, sampler type, sampler source) - unique per call frame
        self._sample_ids = set()
        self._frames = {}
        self.errors = []

    # ------------------------------------------------------------------ context
    def static_value(self, expr):
        name = str(expr.get_editor_property("parameter_name"))
        if name in self.ctx.get("static", {}):
            return bool(self.ctx["static"][name])
        return bool(expr.get_editor_property("default_value"))

    def scalar_param(self, expr):
        name = str(expr.get_editor_property("parameter_name"))
        if name in self.ctx.get("scalar", {}):
            return float(self.ctx["scalar"][name])
        return float(expr.get_editor_property("default_value") or 0.0)

    def vector_param(self, expr):
        name = str(expr.get_editor_property("parameter_name"))
        if name in self.ctx.get("vector", {}):
            v = self.ctx["vector"][name]
            return tuple(v) if not isinstance(v, mu.LinearColor) else (v.r, v.g, v.b, v.a)
        c = expr.get_editor_property("default_value")
        return (c.r, c.g, c.b, c.a) if c is not None else (0.0, 0.0, 0.0, 1.0)

    # ------------------------------------------------------------------ top level
    def property_value(self, prop):
        link = self.material.property_links.get(prop)
        if link is None:
            return None
        src, out_idx = link
        return self.out(src, out_idx, None)

    # ------------------------------------------------------------------ graph walk
    def inp(self, expr, idx, frame, required=True, what=None):
        """Value feeding input pin idx (None if unconnected and not required)."""
        link = expr.inputs[idx]
        if link is None:
            if required:
                raise CompileError("%s: input '%s' is not connected" % (expr, expr.input_names()[idx]))
            return None
        src, out_idx = link
        return self.out(src, out_idx, frame)

    def out(self, expr, out_idx, frame):
        key = (id(expr), out_idx)
        memo = frame.memo if frame is not None else self.__dict__.setdefault("_root_memo", {})
        if key in memo:
            return memo[key]
        self.visited.add(expr)
        val = self._eval(expr, out_idx, frame)
        memo[key] = val
        return val

    def const_pin(self, expr, idx, frame, const_name):
        """Input idx if connected, else the node's constant property (engine behaviour)."""
        link = expr.inputs[idx]
        if link is not None:
            return self.out(link[0], link[1], frame)
        v = expr.get_editor_property(const_name)
        if v is None:
            raise CompileError("%s: %s has no value" % (expr, const_name))
        return (float(v),)

    def _eval(self, expr, out_idx, frame):
        s = expr._short
        g = expr.get_editor_property
        if s == "Constant":
            return (float(g("r")),)
        if s == "Constant2Vector":
            return (float(g("r")), float(g("g")))
        if s in ("Constant3Vector", "Constant4Vector"):
            c = g("constant")
            if c is None:
                raise CompileError("%s: constant not set" % expr)
            return (c.r, c.g, c.b) if s == "Constant3Vector" else (c.r, c.g, c.b, c.a)
        if s == "ScalarParameter":
            self._need_param_name(expr)
            return (self.scalar_param(expr),)
        if s == "VectorParameter":
            self._need_param_name(expr)
            v = self.vector_param(expr)
            names = expr.output_names()
            if names[out_idx] == "":
                return v[:3]
            return (v["RGBA".index(names[out_idx])],)
        if s == "StaticBoolParameter":
            self._need_param_name(expr)
            return self.static_value(expr)
        if s == "StaticSwitch":
            cond = self.inp(expr, 2, frame, required=False)
            if cond is None:
                cond = bool(g("default_value"))
            if not isinstance(cond, bool):
                raise CompileError("%s: Value must be a static bool" % expr)
            return self.inp(expr, 0 if cond else 1, frame)
        if s == "StaticSwitchParameter":
            return self.inp(expr, 0 if self.static_value(expr) else 1, frame)
        if s == "TextureCoordinate":
            idx = int(g("coordinate_index"))
            u, v = self.ctx.get("uv", {}).get(idx, (0.0, 0.0))
            return (u * float(g("u_tiling")), v * float(g("v_tiling")))
        if s == "VertexColor":
            vc = self.ctx.get("vertex_color", (1.0, 1.0, 1.0, 1.0))
            names = expr.output_names()
            return tuple(vc[:3]) if names[out_idx] == "" else (vc["RGBA".index(names[out_idx])],)
        if s == "PixelDepth":
            return (float(self.ctx.get("pixel_depth", 1000.0)),)
        if s == "WorldPosition":
            return tuple(self.ctx.get("world_pos", (0.0, 0.0, 0.0)))
        if s == "ObjectPositionWS":
            return tuple(self.ctx.get("object_pos", (0.0, 0.0, 0.0)))
        if s == "PerInstanceRandom":
            return (float(self.ctx.get("per_instance_random", 0.0)),)
        if s in ("Add", "Subtract", "Multiply", "Divide", "Min", "Max"):
            a = self.const_pin(expr, 0, frame, "const_a")
            b = self.const_pin(expr, 1, frame, "const_b")
            fn = {"Add": lambda x, y: x + y, "Subtract": lambda x, y: x - y, "Multiply": lambda x, y: x * y,
                  "Divide": _div, "Min": min, "Max": max}[s]
            return _arith(a, b, fn, s)
        if s == "LinearInterpolate":
            a = self.const_pin(expr, 0, frame, "const_a")
            b = self.const_pin(expr, 1, frame, "const_b")
            t = self.const_pin(expr, 2, frame, "const_alpha")
            a, b = _broadcast(a, b, "Lerp A/B")
            if len(t) not in (1, len(a)):
                raise CompileError("Lerp: Alpha dimension %d vs %d" % (len(t), len(a)))
            t = t * len(a) if len(t) == 1 else t
            return tuple(x + (y - x) * w for x, y, w in zip(a, b, t))
        if s == "Power":
            base = self.inp(expr, 0, frame)
            e = self.const_pin(expr, 1, frame, "const_exponent")
            return _arith(base, e, lambda x, y: (0.0 if x == 0 and y > 0 else abs(x) ** y), "Power")
        if s == "Clamp":
            x = self.inp(expr, 0, frame)
            lo = self.const_pin(expr, 1, frame, "min_default")
            hi = self.const_pin(expr, 2, frame, "max_default")
            return tuple(min(max(v, lo[0]), hi[0]) for v in x)
        if s in ("Saturate", "OneMinus", "Abs", "Floor", "Frac", "Sine", "Cosine", "SquareRoot"):
            x = self.inp(expr, 0, frame)
            if s == "Saturate":
                return _unary(x, _sat)
            if s == "OneMinus":
                return _unary(x, lambda v: 1.0 - v)
            if s == "Abs":
                return _unary(x, abs)
            if s == "Floor":
                return _unary(x, math.floor)
            if s == "Frac":
                return _unary(x, lambda v: v - math.floor(v))
            if s == "SquareRoot":
                return _unary(x, lambda v: math.sqrt(max(v, 0.0)))
            period = float(g("period"))
            f = math.sin if s == "Sine" else math.cos
            return _unary(x, lambda v: f(v * 2.0 * math.pi / period))
        if s == "ComponentMask":
            x = self.inp(expr, 0, frame)
            sel = [i for i, f in enumerate(("r", "g", "b", "a")) if g(f)]
            if not sel:
                raise CompileError("%s: no channel selected" % expr)
            if max(sel) >= len(x):
                raise CompileError("%s: mask selects channel %d of a %d-component value" % (expr, max(sel), len(x)))
            return tuple(x[i] for i in sel)
        if s == "AppendVector":
            a = self.inp(expr, 0, frame)
            b = self.inp(expr, 1, frame)
            if len(a) + len(b) > 4:
                raise CompileError("Append: %d + %d > 4 components" % (len(a), len(b)))
            return tuple(a) + tuple(b)
        if s == "DotProduct":
            a = self.inp(expr, 0, frame)
            b = self.inp(expr, 1, frame)
            if len(a) != len(b):
                raise CompileError("Dot: dimension mismatch %d vs %d" % (len(a), len(b)))
            return (sum(x * y for x, y in zip(a, b)),)
        if s == "Normalize":
            x = self.inp(expr, 0, frame)
            n = math.sqrt(sum(v * v for v in x))
            if n == 0.0:
                raise CompileError("Normalize of a zero vector at runtime")
            return tuple(v / n for v in x)
        if s == "Desaturation":
            x = self.inp(expr, 0, frame)
            f = self.inp(expr, 1, frame)
            if len(x) != 3 or len(f) != 1:
                raise CompileError("Desaturation expects float3 + float1, got %d/%d" % (len(x), len(f)))
            lf = g("luminance_factors")
            lum = x[0] * lf.r + x[1] * lf.g + x[2] * lf.b if lf else 0.3 * x[0] + 0.59 * x[1] + 0.11 * x[2]
            return tuple(c + (lum - c) * f[0] for c in x)
        if s == "Reroute":
            return self.inp(expr, 0, frame)
        if s == "TextureObjectParameter":
            self._need_param_name(expr)
            tex = self._param_texture(expr)
            return ("TEX", str(g("parameter_name")), tex, g("sampler_type"))
        if s in ("TextureSample", "TextureSampleParameter2D"):
            return self._eval_tex_sample(expr, out_idx, frame)
        if s == "FunctionInput":
            return self._eval_function_input(expr, frame)
        if s == "MaterialFunctionCall":
            return self._eval_call(expr, out_idx, frame)
        raise CompileError("graph_eval: node type %s not implemented" % s)

    # ------------------------------------------------------------------ helpers
    def _need_param_name(self, expr):
        name = expr.get_editor_property("parameter_name")
        if not name:
            raise CompileError("%s: parameter has no name" % expr)

    def _param_texture(self, expr):
        name = str(expr.get_editor_property("parameter_name"))
        override = self.ctx.get("texture_asset", {}).get(name)
        tex = override or expr.get_editor_property("texture")
        if tex is None:
            raise CompileError("Missing input texture on parameter '%s'" % name)
        return tex

    def _check_sampler(self, node_name, sampler_type, tex):
        if tex is None:
            return
        expected = tex.sampler_type_expected()
        if expected is not sampler_type:
            raise CompileError("Sampler type is %s, should be %s for %s (%s)"
                               % (sampler_type.name, expected.name, tex.path, node_name))

    def _eval_tex_sample(self, expr, out_idx, frame):
        g = expr.get_editor_property
        uv = self.inp(expr, 0, frame, required=False)
        if uv is None:
            uv = (0.0, 0.0)            # engine falls back to TexCoord0 - not used by the generator
        if len(uv) < 2:
            raise CompileError("%s: UVs must be float2 (got %d)" % (expr, len(uv)))
        uv = tuple(uv[:2])
        sampler_type = g("sampler_type")
        source = g("sampler_source")
        tex_link = expr.inputs[1]
        if tex_link is not None:
            tobj = self.out(tex_link[0], tex_link[1], frame)
            if not (isinstance(tobj, tuple) and tobj and tobj[0] == "TEX"):
                raise CompileError("%s: 'Tex' input is not a texture object" % expr)
            _, pname, tex, obj_sampler = tobj
            if obj_sampler is not sampler_type:
                raise CompileError("%s: sampler type %s differs from the texture object's %s"
                                   % (expr, sampler_type.name, obj_sampler.name))
            node_key = pname
        else:
            if expr._short == "TextureSampleParameter2D":
                self._need_param_name(expr)
                node_key = str(g("parameter_name"))
                tex = self._param_texture(expr)
            else:
                node_key = "<tex>"
                tex = g("texture")
                if tex is None:
                    raise CompileError("Missing input texture on %s" % expr)
        self._check_sampler(node_key, sampler_type, tex)
        sample_id = (id(expr), id(frame))
        if sample_id not in self._sample_ids:
            self._sample_ids.add(sample_id)
            self.tex_samples.append((expr, node_key, sampler_type, source))
        # --- value
        override = self.ctx.get("texture", {}).get(node_key)
        if callable(override):
            rgba = override(uv)
        elif override is not None:
            rgba = override
        else:
            rgba = self._decode_default(tex, sampler_type)
        rgba = tuple(rgba)
        names = expr.output_names()
        nm = names[out_idx]
        if nm == "RGB":
            return rgba[:3]
        if nm == "RGBA":
            return rgba
        return (rgba["RGBA".index(nm)],)

    @staticmethod
    def _decode_default(tex, sampler_type):
        r, g_, b, a = tex.mean_rgba()
        if sampler_type is U["MaterialSamplerType"].SAMPLERTYPE_NORMAL:
            x, y = r * 2 - 1, g_ * 2 - 1
            z = math.sqrt(max(0.0, 1.0 - x * x - y * y))
            return (x, y, z, 1.0)
        if sampler_type is U["MaterialSamplerType"].SAMPLERTYPE_COLOR:
            def lin(c):
                return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
            return (lin(r), lin(g_), lin(b), a)
        return (r, g_, b, a)

    # ------------------------------------------------------------------ functions
    def _eval_function_input(self, expr, frame):
        if frame is None:
            raise CompileError("FunctionInput evaluated outside of a function call")
        name = str(expr.get_editor_property("input_name"))
        call = frame.call
        names = call.input_names()
        idx = names.index(name)
        link = call.inputs[idx]
        if link is not None:
            val = self.out(link[0], link[1], frame.caller)
        elif expr.get_editor_property("use_preview_value_as_default"):
            pv = expr.get_editor_property("preview_value")
            t = expr.get_editor_property("input_type")
            n = {"FUNCTION_INPUT_SCALAR": 1, "FUNCTION_INPUT_VECTOR2": 2, "FUNCTION_INPUT_VECTOR3": 3,
                 "FUNCTION_INPUT_VECTOR4": 4}.get(t.name)
            if n is None:
                raise CompileError("function input '%s' (%s) cannot use a preview default" % (name, t.name))
            val = (pv.x, pv.y, pv.z, pv.w)[:n]
        else:
            raise CompileError("Missing function input '%s' on %s" % (name, call))
        # cast to declared type (engine: error if the cast fails)
        t = expr.get_editor_property("input_type")
        want = {"FUNCTION_INPUT_SCALAR": 1, "FUNCTION_INPUT_VECTOR2": 2, "FUNCTION_INPUT_VECTOR3": 3,
                "FUNCTION_INPUT_VECTOR4": 4}.get(t.name)
        if want is not None:
            if isinstance(val, bool) or (isinstance(val, tuple) and val and val[0] == "TEX"):
                raise CompileError("function input '%s' expects a number, got %r" % (name, val))
            if len(val) != want:
                if len(val) == 1:
                    val = val * want
                else:
                    raise CompileError("function input '%s' expects %d components, got %d" % (name, want, len(val)))
        elif t.name == "FUNCTION_INPUT_STATIC_BOOL":
            if not isinstance(val, bool):
                raise CompileError("function input '%s' expects a static bool" % name)
        elif t.name == "FUNCTION_INPUT_TEXTURE2D":
            if not (isinstance(val, tuple) and val and val[0] == "TEX"):
                raise CompileError("function input '%s' expects a texture object" % name)
        return val

    def _eval_call(self, expr, out_idx, frame):
        fn = expr.function
        if fn is None:
            raise CompileError("%s: no function assigned" % expr)
        outs = fn.function_outputs()
        node = outs[out_idx]
        fkey = (id(expr), id(frame))
        fr = self._frames.get(fkey)
        if fr is None:
            fr = self._frames[fkey] = Frame(expr, frame, self)
        link = node.inputs[0]
        if link is None:
            raise CompileError("function output '%s' of %s is not connected" % (node.get_editor_property("output_name"), fn.path))
        self.visited.add(node)
        return self.out(link[0], link[1], fr)


# ---------------------------------------------------------------------------- #
# Rough per-pixel cost proxy
# ---------------------------------------------------------------------------- #
def _frame_path(ev, frame):
    path = ()
    while frame is not None:
        path = (id(frame.call),) + path
        frame = frame.caller
    return path


def snapshot(ev):
    """{(frame path, expression id, output index): value} for everything the evaluator touched."""
    snap = {}
    root = ev.__dict__.get("_root_memo", {})
    for (eid, oidx), v in root.items():
        snap[((), eid, oidx)] = v
    for fr in ev._frames.values():
        path = _frame_path(ev, fr)
        for (eid, oidx), v in fr.memo.items():
            snap[(path, eid, oidx)] = v
    return snap


# approximate vector-ALU instruction weights per node type (swizzles / saturate / abs are free modifiers)
ALU_WEIGHT = {"Add": 1, "Subtract": 1, "Multiply": 1, "Divide": 2, "Min": 1, "Max": 1, "LinearInterpolate": 1,
              "OneMinus": 1, "Frac": 1, "Floor": 1, "DotProduct": 1, "Normalize": 2, "Desaturation": 1,
              "Sine": 4, "Cosine": 4, "Power": 3, "SquareRoot": 2}


def estimate_per_pixel_alu(material, contexts):
    """
    A node costs something per pixel only if its value changes with per-pixel inputs. Evaluate the material for several
    contexts (different UVs, vertex colours, textures ...) and count weighted nodes whose value differs between them.
    Parameter-only maths is folded by the engine's pre-shader and costs nothing per pixel.
    Returns (alu_estimate, texture_samples, {class: count}).
    """
    evs, snaps = [], []
    for ctx in contexts:
        ev = Evaluator(material, ctx)
        for prop in material.property_links:
            ev.property_value(prop)
        evs.append(ev)
        snaps.append(snapshot(ev))
    first = snaps[0]
    classes, alu = {}, 0.0
    by_id = {}
    for e in list(material.expressions) + [x for f in mu.REGISTRY.values() if isinstance(f, mu.MaterialFunction) for x in f.expressions]:
        by_id[id(e)] = e
    counted = set()
    for (path, eid, oidx), v in first.items():
        key = (path, eid)
        if key in counted:
            continue
        e = by_id.get(eid)
        if e is None or e._short not in ALU_WEIGHT:
            continue
        dynamic = any(sn.get((path, eid, oidx)) != v for sn in snaps[1:])
        if dynamic:
            counted.add(key)
            alu += ALU_WEIGHT[e._short]
            classes[e._short] = classes.get(e._short, 0) + 1
    return alu, len(evs[0].tex_samples), classes


# ---------------------------------------------------------------------------- #
# Convenience wrappers
# ---------------------------------------------------------------------------- #
MP = U["MaterialProperty"]


def evaluate_material(material, ctx=None, props=None):
    """Returns ({property_name: tuple}, Evaluator)."""
    ev = Evaluator(material, ctx)
    res = {}
    for prop in (props or list(material.property_links.keys())):
        res[prop.name] = ev.property_value(prop)
    return res, ev


def count_by_class(material):
    d = {}
    for e in material.expressions:
        d[type(e).__name__] = d.get(type(e).__name__, 0) + 1
    return d
