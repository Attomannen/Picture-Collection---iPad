"""
================================================================================
 FIX TEXTURE SETTINGS  -  Unreal Engine 5.x  (Python Editor Script)
================================================================================
 Sets the import settings of textures from their NAME, so they match the sampler types
 of M_Master_Surface. It is the cure for the most common beginner error:

        "Sampler type is Normal, should be Masks"   (or Color / Linear Color ...)

 HOW TO USE
   1. In the Content Browser select the textures you imported
      (or select nothing and set FOLDER below to the folder that holds them).
   2. Tools > Execute Python Script...  and pick this file.
   3. Read the Output Log (filter on "FixTextures"): every change is listed.

 THE NAME IS READ FROM ITS LAST WORD   (case does not matter; _01 / _2k / _4K are skipped)
     colour, sRGB ON .............. A  Alb  Albedo  BC  BaseColor  Color  Col  D  Diff  Diffuse  Emissive  Emit  E
     normal map, sRGB OFF ......... N  Nrm  Norm  Normal  NM  (ending in GL / OpenGL: the green channel is flipped for you)
     data, "Masks", sRGB OFF ...... ORMH  ORM  ARM  Mask  Masks  RGBMask  Breakup  Macro  Opacity  Rough  Roughness
                                    Metal  Metallic  AO  Height
   e.g.  T_Brick_A   T_Brick_N   T_Brick_ORMH   T_Crate_Mask   T_Breakup_01
 Textures whose name matches nothing are listed and left alone.

 Nothing is changed except sRGB, compression (and the normal-map texture group / green flip for normal maps).
 Set DRY_RUN = True to only print what WOULD change.
================================================================================
"""
import os
import re

try:
    import unreal
except ImportError:                       # allows importing this file in plain Python (tests)
    unreal = None

FOLDER = "/Game"          # used only when nothing is selected in the Content Browser
DRY_RUN = False           # True = report only

TAG = "[FixTextures] "

WORDS = {
    "color": ("a", "alb", "albedo", "bc", "basecolor", "color", "colour", "col", "d", "diff", "diffuse", "emissive", "emit", "e"),
    "normal": ("n", "nrm", "norm", "normal", "nm", "normalgl", "normalopengl", "normaldx", "normaldirectx", "ngl", "nrmgl"),
    "masks": ("ormh", "orm", "arm", "mask", "masks", "rgbmask", "breakup", "macro", "opacity",
              "rough", "roughness", "metal", "metallic", "ao", "height", "h"),
}
OPENGL_WORDS = ("normalgl", "normalopengl", "ngl", "nrmgl")
SIZE_WORD = re.compile(r"^(\d+|\d+k|\d+x\d+)$")       # 01, 4k, 2048x2048 ...


def classify(name):
    """('color' | 'normal' | 'masks' | None, opengl_flag) from the last meaningful word of an asset name."""
    words = [w for w in re.split(r"[_.\- ]+", name.lower()) if w]
    while words and SIZE_WORD.match(words[-1]):
        words.pop()
    if not words:
        return None, False
    last = words[-1]
    for kind, vocabulary in WORDS.items():
        if last in vocabulary:
            return kind, last in OPENGL_WORDS
    return None, False


def log(msg):
    unreal.log(TAG + msg)


def _targets():
    """Textures to look at: the Content Browser selection, else everything under FOLDER."""
    assets = []
    try:
        assets = list(unreal.EditorUtilityLibrary.get_selected_assets())
    except Exception:                                   # noqa: BLE001 - the Editor Scripting Utilities plugin may be off
        assets = []
    if assets:
        return assets, "the %d selected asset(s)" % len(assets)
    eal = unreal.EditorAssetLibrary
    paths = eal.list_assets(FOLDER, True, False)
    return [eal.load_asset(p) for p in paths], "everything under %s" % FOLDER


def main():
    T = unreal.TextureCompressionSettings
    assets, where = _targets()
    log("Looking at %s%s" % (where, "  (DRY RUN - nothing will be changed)" if DRY_RUN else ""))
    checked = changed = 0
    unknown = []
    for tex in assets:
        if tex is None or not isinstance(tex, unreal.Texture2D):
            continue
        name = tex.get_name()
        kind, opengl = classify(name)
        if kind is None:
            unknown.append(name)
            continue
        checked += 1
        edits = []
        comp = tex.get_editor_property("compression_settings")
        srgb = bool(tex.get_editor_property("srgb"))
        if kind == "color":
            if comp in (T.TC_NORMALMAP, T.TC_MASKS, T.TC_GRAYSCALE, T.TC_ALPHA):
                edits.append(("compression_settings", T.TC_DEFAULT, "compression -> Default (colour)"))
            if not srgb:
                edits.append(("srgb", True, "sRGB -> on"))
        elif kind == "normal":
            if comp != T.TC_NORMALMAP:
                edits.append(("compression_settings", T.TC_NORMALMAP, "compression -> Normalmap"))
            if srgb:
                edits.append(("srgb", False, "sRGB -> off"))
            if opengl and not tex.get_editor_property("flip_green_channel"):
                edits.append(("flip_green_channel", True, "Flip Green Channel -> on (OpenGL normal map)"))
        else:
            if comp != T.TC_MASKS:
                edits.append(("compression_settings", T.TC_MASKS, "compression -> Masks (no sRGB)"))
            if srgb:
                edits.append(("srgb", False, "sRGB -> off"))
        if not edits:
            continue
        changed += 1
        log("%-34s %-6s %s" % (name, kind, "; ".join(e[2] for e in edits)))
        if not DRY_RUN:
            for prop, value, _ in edits:
                tex.set_editor_property(prop, value)
            unreal.EditorAssetLibrary.save_loaded_asset(tex)
    log("%d texture(s) recognised, %d %s." % (checked, changed, "would change" if DRY_RUN else "changed"))
    if unknown:
        log("Not recognised by name (left alone): %s" % ", ".join(sorted(unknown)[:30]) + (" ..." if len(unknown) > 30 else ""))
    return changed


# Runs when executed inside Unreal. The offline tests set MM_NO_AUTORUN=1 so they can import this file.
if unreal is not None and not os.environ.get("MM_NO_AUTORUN"):
    main()
