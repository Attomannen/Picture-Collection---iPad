#!/usr/bin/env python3
"""
Extract *data only* facts about the Unreal Engine Python API from the community
"unreal-stub" package (generated from a real UE 5.6 editor) so the offline test
harness can validate property names, enum members and function signatures.

The stub file is NEVER imported or executed - it is only read as text.

Usage (one-off, only needed if you want to regenerate ue_api_facts.json):

    pip download unreal-stub==0.3 --no-deps -d /tmp/unreal_stub_dl
    python3 -c "import zipfile,glob; zipfile.ZipFile(glob.glob('/tmp/unreal_stub_dl/*.whl')[0]).extractall('/tmp/unreal_stub_dl/x')"
    python3 -I extract_ue_api_facts.py /tmp/unreal_stub_dl/x/unreal/unreal.py ue_api_facts.json
"""
import json
import re
import sys

# --------------------------------------------------------------------------- #
# What the build script (and the mock) need to know about
# --------------------------------------------------------------------------- #
EXPRESSION_CLASSES = [
    "Abs", "Add", "AppendVector", "Clamp", "Comment", "ComponentMask", "Constant",
    "Constant2Vector", "Constant3Vector", "Constant4Vector", "Cosine", "Desaturation",
    "Divide", "DotProduct", "Floor", "Frac", "FunctionInput", "FunctionOutput",
    "LinearInterpolate", "MaterialFunctionCall", "Max", "Min", "Multiply", "Normalize",
    "ObjectPositionWS", "OneMinus", "PerInstanceRandom", "PixelDepth", "Power", "Saturate", "ScalarParameter",
    "Sine", "SquareRoot", "StaticBoolParameter", "StaticSwitch", "StaticSwitchParameter",
    "Subtract", "TextureCoordinate", "TextureObjectParameter", "TextureSample",
    "TextureSampleParameter2D", "VectorParameter", "VertexColor", "WorldPosition",
    "SmoothStep", "Step", "Reroute", "If",
]
OTHER_CLASSES = [
    "Material", "MaterialFunction", "MaterialInstanceConstant", "Texture2D", "Texture",
    "MaterialFactoryNew", "MaterialFunctionFactoryNew", "MaterialInstanceConstantFactoryNew",
    "AssetImportTask", "MaterialEditingLibrary", "EditorAssetLibrary", "AssetToolsHelpers",
    "AssetTools", "MaterialInstanceBasePropertyOverrides", "MaterialStatistics",
    "LinearColor", "Vector4f", "Vector4", "EditorUtilityLibrary",
]
ENUMS = [
    "BlendMode", "MaterialDomain", "DecalBlendMode", "MaterialShadingModel", "MaterialProperty",
    "MaterialSamplerType", "SamplerSourceMode", "TextureMipValueMode", "TextureCompressionSettings",
    "TextureGroup", "TextureMipGenSettings", "TextureFilter", "TextureAddress", "FunctionInputType",
    "MaterialUsage", "MaterialParameterAssociation", "ClampMode", "MaterialDecalResponse",
]

PROP_RE = re.compile(r"^\s+- ``(\w+)`` \(([^)]*)\):\s*(\[[^\]]*\])?\s*(.*)$")
ENUM_RE = re.compile(r"^\s+([A-Z][A-Z0-9_]+): \w+ = \.\.\. #: ?(.*)$")
DEF_RE = re.compile(r"^    def (\w+)\((.*)\)\s*(?:->\s*(.*))?:\s*$")


def split_params(arglist):
    """Split a python parameter list on top-level commas."""
    out, depth, cur = [], 0, ""
    for ch in arglist:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def parse_param(p):
    """'name: Type = default' -> (name, has_default, default_text)"""
    m = re.match(r"^\*{0,2}(\w+)(?:\s*:\s*[^=]+?)?(?:\s*=\s*(.*))?$", p)
    if not m:
        return p, False, None
    return m.group(1), m.group(2) is not None, m.group(2)


def main(stub_path, out_path):
    lines = open(stub_path, encoding="utf-8", errors="replace").read().split("\n")
    starts = {}
    for i, l in enumerate(lines):
        m = re.match(r"^class (\w+)\(([^)]*)\)", l)
        if m:
            starts[m.group(1)] = (i, m.group(2))
    order = sorted(v[0] for v in starts.values())

    def chunk(name):
        s, _ = starts[name]
        e = next((x for x in order if x > s), len(lines))
        return lines[s:e]

    facts = {"source": "unreal-stub 0.3 (Unreal Engine 5.6.0 Python stub)", "classes": {}, "enums": {}}

    wanted = ["MaterialExpression" + n for n in EXPRESSION_CLASSES] + OTHER_CLASSES
    for name in wanted:
        if name not in starts:
            print("WARNING: class not found in stub:", name)
            continue
        parent = starts[name][1]
        props, methods, init = {}, {}, None
        pending_classmethod = False
        for l in chunk(name):
            m = PROP_RE.match(l)
            if m:
                props[m.group(1)] = {"type": m.group(2), "access": (m.group(3) or "").strip("[]")}
                continue
            if l.strip() == "@classmethod":
                pending_classmethod = True
                continue
            d = DEF_RE.match(l)
            if d:
                mname, arglist, ret = d.group(1), d.group(2), d.group(3)
                if mname == "__init__":                 # struct constructors: the mock checks its calls against this
                    params = [parse_param(p) for p in split_params(arglist)]
                    init = [{"name": n, "has_default": hd, "default": df} for n, hd, df in params if n != "self"]
                    pending_classmethod = False
                    continue
                if mname.startswith("_"):
                    pending_classmethod = False
                    continue
                params = [parse_param(p) for p in split_params(arglist)]
                # drop self / cls
                params = [p for p in params if p[0] not in ("self", "cls")]
                methods[mname] = {
                    "classmethod": pending_classmethod,
                    "params": [{"name": n, "has_default": hd, "default": df} for n, hd, df in params],
                    "returns": ret,
                }
                pending_classmethod = False
        facts["classes"][name] = {"parent": parent, "props": props, "methods": methods}
        if init is not None:
            facts["classes"][name]["init"] = init

    for name in ENUMS:
        if name not in starts:
            print("WARNING: enum not found in stub:", name)
            continue
        members = {}
        for l in chunk(name):
            m = ENUM_RE.match(l)
            if m:
                val = m.group(2).split(":")[0].strip()
                members[m.group(1)] = int(val) if re.fullmatch(r"-?\d+", val) else val
        facts["enums"][name] = members

    with open(out_path, "w") as f:
        json.dump(facts, f, indent=1, sort_keys=True)
    print(f"wrote {out_path}: {len(facts['classes'])} classes, {len(facts['enums'])} enums")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
