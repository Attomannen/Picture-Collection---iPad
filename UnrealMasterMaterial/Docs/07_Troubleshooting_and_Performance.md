# 07 - Troubleshooting and performance

Contents: [If the script fails or a node is red](#if-the-script-fails-or-a-node-is-red) - [Common problems](#common-problems) -
[What the material costs](#what-the-material-costs) - [Getting more speed](#getting-more-speed) - [Re-running and updating](#re-running-and-updating)

---

## If the script fails or a node is red

The generator could not be run inside Unreal while it was written. It was validated against the real Unreal 5.6 Python API *signatures and
property names* and a strict offline mock, but a few engine facts (exact pin and output names of some nodes) are from knowledge, not from a live editor.
The script is written to **explain itself** when one of them is off.

**1. Read the Output Log.** *Window > Output Log*, type `MasterMaterial` in the search box. Every line the script writes starts with `[MasterMaterial]`.

| Message | Meaning | What to do |
|---|---|---|
| `Function-based build failed: ... Retrying with everything expanded inline` | Material Function calls did not work on your engine version | **Nothing** - the script already rebuilt the master inline. It is identical in behaviour, just a bigger graph. |
| `Output 'A' of TextureSample was not accepted by name; taking it through a ComponentMask instead` | The alpha output has a different name on your version | **Nothing** - handled automatically. |
| `set_material_function is not available ... assigning the 'material_function' property instead` | Your version has no such helper on the call node | **Nothing** - the property route does the same. |
| `Could not read the Vertex Color alpha output: 'Use Vertex Alpha Dirt' will do nothing` | Your version does not hand out the vertex-colour alpha | **Nothing** - only the bonus "alpha dirt" is lost; vertex layers 1-3 work. |
| `MI_...: the parent has no scalar parameter called '...' - skipped` | A demo instance names a parameter that the master does not have (typo or renamed) | Harmless for the rest; fix the name in `make_demo_instances()`. |
| `MI_...: N scalar override(s) did not read back as set` | The engine's getter disagreed with what was set (Epic documents quirks in these functions) | Open the instance: if its parameters show the demo values, ignore it. |
| `Optional property '...' not set` | A cosmetic property (comment colour, description, slider range) does not exist in your version | Ignore. |
| `This Unreal version has no unreal.MaterialExpression...` / `... no unreal.X.Y` | A class or enum is missing (very old engine) | Use UE 5.x. |
| `connect_material_expressions failed: A[...] -> B.'pin' in ...` | A pin has a different **name** in your version | Copy the full line. Quick workaround: set `USE_MATERIAL_FUNCTIONS = False` at the top of the script and run again (or follow [08 Build it by hand](08_Build_It_By_Hand.md)). |
| `Could not set property '...' on ...` (stops the build) | A required property has another name in your version | Copy the line; use the hand-build guide as a fallback. |
| `Texture import failed` | The Python plugin cannot write to the temp folder, or the import was cancelled | Run Unreal as a normal user; try again. |

**2. Red nodes in the master.** Open `M_Master_Surface`. Red/orange nodes show an error; hover to read it, or open *Window > Message Log*.

* *`Sampler type is X, should be Y for ...`* - a **texture's import setting** does not match the parameter ([02 section 1](02_Textures_and_Masks.md#1-texture-roles-and-import-settings)).
  Inside the master this only happens if the placeholder textures were changed.
* *`Missing function input` / pin errors on a function call node* - the function assets are out of date: run the script again.

**3. Safe fallbacks, in order**

1. Run the script again (it is idempotent).
2. Set `USE_MATERIAL_FUNCTIONS = False` (top of the script) and run again - no function assets involved.
3. Delete `Content/MasterMaterial` and run again for a clean slate.
4. Follow [08 Build it by hand](08_Build_It_By_Hand.md) for a minimal master (all of the assignment's requirements, ~40 nodes).

---

## Common problems

| Symptom | Likely cause and fix |
|---|---|
| **A new instance looks flat blue-grey** | That is the default: every layer uses a flat placeholder colour and the mask is black, so only the Base layer shows. Assign textures; assign your RGB mask. |
| **Textures look tinted or too dark** | A layer `Tint` is not white. All tints default to white; a tinted instance (for example one you duplicated from a demo) multiplies the texture. |
| **Mask has no effect** | Mask imported with **sRGB** on or wrong compression (use *Masks (no sRGB)*); mask is on the wrong UV set (try `Swap UV Channels`, check Debug Mode 1-4); `Use Wear Layer / Dirt Layer / Scratches` is off; the mask texture parameter is still the default black one; the mask is too grey - values below about 0.3 reveal almost nothing at default settings (paint it whiter or raise `Wear Intensity`). |
| **Mask looks scrambled, as if it belonged to another mesh** | Unreal replaced UV channel 1 with an automatic lightmap unwrap on import. Static Mesh Editor > Details > Build Settings > untick **Generate Lightmap UVs** > Apply Changes, and re-import the mesh with it unticked. Debug Mode 14 shows the real UV1. |
| **The whole object is dark or dirty** | The alpha of the mask is not AO (transparent padding, nothing mapped to A): Debug Mode 4 should be mostly white. Re-export the mask, or turn off `Use Baked AO` and set `Dirt AO Boost` to 0. |
| **Mask is mirrored / shifted / smeared** | Unique UVs overlap, are mirrored, or leave 0-1. Check Debug Mode 14 on the mesh. |
| **Mask effects appear but in the wrong place on an engine cube/sphere** | Primitives have only one UV set: use an instance of `MI_Demo_Base` (it has the preview switch `Mask Uses Tiling UV`, group 99, on) - or, better, your own two-UV mesh. The other way round, on your own mesh the switch must be OFF. |
| **Wear/dirt edges are blurry** | Lower `... Softness`, raise `... Breakup`, give the layer a real **height** map in its ORMH alpha and raise `... Height Influence`, use a better `Breakup Texture`, add `Breakup Tiling`. |
| **Everything is too dirty** | Lower `Dirt Intensity`, `Dirt AO Boost`, or check that mask G is not mostly white. |
| **Tiling looks stretched or different sizes** | UV0 has inconsistent texel density (Debug Mode 13 shows it). Fix the UVs, or tune `Global Tiling` / per-layer `Tiling`. |
| **Visible texture repetition** | Rotate layers (`<Layer> Rotation`), enable `Use Macro Variation`, use `Use Instance Variation`, add `Global Tiling` variation per instance. |
| **Normal maps look inverted (bumps are dents)** | The normal map is OpenGL (green up). Tick **Flip Green Channel** in the texture's settings, or use a DirectX normal. |
| **Bumps are lit from the wrong side on some faces only** | The tiling UV set is UV1 (`Swap UV Channels` ON) and its islands are rotated or mirrored against UV0, where Unreal takes the tangents from. Put the tiling set in UV0, or keep island orientation identical in both sets ([01 section 1](01_How_It_Works.md#1-two-uv-sets)). |
| **The wear amount looks different far away** | Height and breakup textures are mip-mapped, so at a distance they average out and the edge becomes a smooth ramp. Raise that layer's `Softness` or lower its `Height Influence` / `Breakup`. |
| **Copies of an instanced mesh (HISM, foliage) all look alike** | `Use Instance Variation` needs `PerInstanceRandom`, which only instanced meshes have; for ordinary actors it hashes the object position. Change `Variation Seed` to re-roll. |
| **Seams between UV islands in the mask** | Export the mask with dilation / padding in Painter; give UV1 islands padding. |
| **Vertex paint does nothing** | See [04 section 5](04_Vertex_Painting.md#5-troubleshooting): Nanite, wrong channel, white-adds setting. |
| **Decal does not show** | [05 section 4](05_Mesh_Decals.md#4-in-unreal): DBuffer decals, offset from the surface, Nanite off. |
| **"Material uses more than 16 texture samplers"** | Should not occur (all samples use the shared sampler). If you added your own texture nodes, set their *Sampler Source* to **Shared: Wrap**. |
| **First shader compile takes a long time** | Normal. Every distinct combination of static switches is its own shader permutation; it compiles once and is cached. |
| **A parameter I changed in the instance has no effect** | The feature is switched off (`Use ...` in group 00), or a higher layer covers it. |
| **Opacity mask does nothing** | `Use Opacity Mask` ON **and** *Details > Blend Mode* = Masked in the instance's Base Property Overrides (override ticked). |
| **Everything is white / wrong after changing a parameter in the debug group** | `Debug View` is ON: it replaces the output by a flat colour. Turn it off. |
| **Instance parameters of an old instance vanished** | Parameters are matched by name; if you renamed one in the script, set it again. |

---

## What the material costs

The master is built so that **you pay only for what you switch on**. Offline estimate for the finished graph (a proxy:
weighted vector ALU operations that depend on per-pixel data, plus texture fetches; parameter-only maths is pre-computed by the engine and not counted):

| Configuration | Texture samples | Vector ALU (approx.) |
|---|---|---|
| **Minimal** - every layer off, only the Base layer, mask, detail off | 3 | ~30 |
| **Default switches** - Base + Wear + Dirt + Vertex 1, breakup, detail normal, scratches | **15** | **~215** |
| Default + Vertex Layers 2 and 3 | 21 | ~315 |
| **Everything on** (macro, emissive, opacity, all layers) | **24** | ~320 |

These are proxies from the offline interpreter, not Unreal's own counts. The editor's *Stats* window will show a bigger number for the default permutation (it also counts
shading, normal handling and the GBuffer output) - my estimate, **not measured in the editor**, is somewhere around 450-650 pixel-shader instructions; the script prints the engine's real figure at the end of a run
and the Stats window shows it for any instance. **Who it is for:** this is a *hero-prop / environment-kit master for desktop and console* (15-24 texture fetches per pixel). It is too heavy for
mobile or Switch, and for a whole terrain; for those build a reduced material (Base + Wear + Dirt, nothing else) or follow [08](08_Build_It_By_Hand.md).

Rules of thumb:

* **Each tiling layer = 3 texture samples** (albedo, normal, ORMH) + ~25 ALU for its adjustments + ~25 for its blend.
* **Each extra texture of the master** (mask, breakup, detail normal, macro, emissive, opacity) = 1 sample.
* All textures use the **shared Wrap sampler** (no 16-sampler limit; Unreal allows up to 128 textures).
* Compare with Unreal's own numbers: open the material, *Window > Stats* (or *Platform Stats*) for the instruction count of the current permutation.
  Use the *Shader Complexity* view mode in the viewport to see the real cost on screen.

---

## Getting more speed

* **Switch off what the asset does not need.** A background prop: Base + Wear + Dirt only (turn off `Use Vertex Layer 1`, `Use Detail Normal`, `Use Scratches`, `Use Mask Breakup`) -> about 9 samples and a fraction of the maths.
* **Share instances.** Instances with the same static-switch combination share the same compiled shader.
* **Lower texture sizes** for layers that cover small areas (Dirt, Vertex layers: 512-1024 is usually enough).
* **Detail normal fade distance:** the detail only costs maths where it is visible, but a short `Detail Fade End` removes it sooner (far objects get cheaper).
* **Keep static switch combinations few.** Every unique combination in your project is a separate shader to compile and keep in memory. The demo instances use four different combinations (plus the master's own default one).
* **Hero asset vs. background:** use the full stack for hero props and the minimal one (or a simpler dedicated material) for distant filler.

## Re-running and updating

* **Idempotent:** running the script again rebuilds the two master materials and the five functions. Your instances keep their values (parameters are matched by name), existing `T_MM_*` textures are **never overwritten** (unless you set `OVERWRITE_EXISTING_TEXTURES = True`), existing `MI_Demo_*` instances (including the parent `MI_Demo_Base`) are left untouched.
* **Change the defaults:** edit the parameter table at the top of `define_surface_params()` (defaults, ranges, groups) and run again.
* **Move it elsewhere:** change `ROOT_PATH` at the top of the script (e.g. `/Game/Materials/Master`).
* **Delete the demo content:** set `CREATE_DEMO_TEXTURES = False` and `CREATE_DEMO_INSTANCES = False` before running (the placeholder textures stay: parameters need them as defaults).
