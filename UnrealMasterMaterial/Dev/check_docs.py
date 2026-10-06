#!/usr/bin/env python3
"""Docs hygiene: relative links resolve, and backticked parameter-like names exist in the parameter tables."""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
os.environ["MM_NO_AUTORUN"] = "1"
import run_tests as rt            # noqa: E402

ALLOW = {"Debug Mode 13", "Debug Mode 14", "Dirt", "Scratches", "Wear", "Breakup", "Mask",
         "Dirt Color", "Dirt Roughness"}      # channel labels, pin names and the extra hand-build parameters
PREFIXES = ("Base", "Wear", "Dirt", "Vertex", "Use ", "Global", "Mask", "Breakup", "Detail", "Macro", "Variation",
            "Wetness", "Emissive", "Opacity", "Debug", "Scratch", "Decal", "Swap", "Vertex Paint")


def md_files():
    out = [os.path.join(ROOT, "README.md")]
    for d in ("Docs", "Dev"):
        for f in sorted(os.listdir(os.path.join(ROOT, d))):
            if f.endswith(".md"):
                out.append(os.path.join(ROOT, d, f))
    return out


def main():
    b = rt.build_all()
    names = set(b.params.items) | set(b.gen.define_decal_params().items)
    names_l = {n.lower() for n in names}
    layers = ["Base", "Wear", "Dirt", "Vertex 1", "Vertex 2", "Vertex 3"]
    problems = []
    for path in md_files():
        text = open(path, encoding="utf-8").read()
        rel = os.path.relpath(path, ROOT)
        # links
        for m in re.finditer(r"\]\(([^)#\s]+)(#[^)]*)?\)", text):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            full = os.path.normpath(os.path.join(os.path.dirname(path), target))
            if not os.path.exists(full):
                problems.append("%s: broken link -> %s" % (rel, target))
        # parameter-like names
        for m in re.finditer(r"`([^`\n]+)`", text):
            tok = m.group(1).strip()
            if not tok.startswith(PREFIXES) or "..." in tok or "<" in tok or "/" in tok or "." in tok or len(tok) > 40:
                continue
            if tok.lower() in names_l or tok in ALLOW or re.fullmatch(r"Debug Mode \d+( / \d+)*", tok):
                continue
            # allow "Wear Softness" style suffix of a layer parameter e.g. "Vertex N Softness"
            if re.fullmatch(r"(Base|Wear|Dirt|Vertex \d) [A-Za-z ]+", tok) and tok.lower() in names_l:
                continue
            if tok in ("Vertex Layer 1", "Vertex Layer 2", "Vertex Layer 3", "Debug Mode", "Debug View"):
                if tok.lower() in names_l:
                    continue
            problems.append("%s: `%s` is not a parameter name" % (rel, tok))
    if problems:
        print("\n".join(sorted(set(problems))))
        return 1
    print("docs OK: links resolve and parameter names match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
