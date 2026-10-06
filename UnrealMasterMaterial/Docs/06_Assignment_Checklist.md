# 06 - Assignment checklist ("VG - Master Material")

Mapped from the assignment text (3D-grafik: Avancerad: Spelmotor). **Deadline in the brief: Wednesday 7 October, 14:00.**
Names in `monospace` are the file names the brief asks for (replace `FornamnEfternamn` with yours).

The master material is *one* part of the job. This page shows which parts the material covers and what you still do yourself.

---

## 1. Requirements -> where they are covered

### Grade G (pass)

| Requirement in the brief | Covered by | You still need to |
|---|---|---|
| **2 UV sheets** (one unique, one for tileables) | UV0 = tiling (Unreal builds the normal-map tangents from UV0), UV1 = unique (mask), `Swap UV Channels` for the other order, Debug modes 13/14 to verify | Make both UV sets on your own mesh ([02 section 4](02_Textures_and_Masks.md#4-the-two-uv-sheets)); untick *Generate Lightmap UVs* on import |
| **Wear and dirt masks from Substance Painter applied in an Unreal shader** | RGB mask: R = wear, G = dirt, B = scratches, A = AO | Paint/export the masks in Painter ([02 section 3](02_Textures_and_Masks.md#3-making-the-rgb-mask-in-substance-3d-painter)) |
| **>= 3 different material instances**, shown on the **given mesh and your own mesh** | Master with groups of art-direction parameters; recipes below; demo instances | Create the instances and assign your textures. The two meshes have **different masks**, so make one *parent* instance per mesh (mask + textures) and three child instances of it - see section 3 |
| **A simple mesh optimised for games** | - | Model it (few tris, sensible UVs, no Nanite if you want to vertex-paint) |
| **Your own decal sheet used on your own mesh** + **mesh decals** | `M_Master_MeshDecal` | Author the sheet and decal meshes ([05](05_Mesh_Decals.md)) |
| *Master Material in Unreal where RGB masks can be used and adjusted*, general shader parameters for variation and art direction | `M_Master_Surface` (groups 00-17; the ones marked *extra* are optional) | - |
| *Tiling textures and detail normals* | layer textures + group 11 | provide tileable textures |

### Grade VG (pass with distinction)

| Requirement | Covered by | You still need to |
|---|---|---|
| **Use of vertex painting in your shader** (paint at least one other material) | Vertex Layer 1 (red); optional 2, 3, alpha dirt | Paint it on your own mesh, record the GIF ([04](04_Vertex_Painting.md)) |

---

## 2. Deliverables (from the brief)

| # | File name | What to show | How |
|---|---|---|---|
| 1 | `FornamnEfternamn_Parameters` | Screenshot of your **master material instance showing its parameters** | Open an instance, expand the groups (Features, RGB Mask, Base, Wear, Dirt ...). A tall screenshot or two stitched ones are fine. |
| 2 | `FornamnEfternamn_ProvidedMesh` | Presentation image in Unreal: the **given mesh with >= 3 different instances** | Place 3 copies side by side, one instance each; Lit viewport, neutral lighting; or use a high-res screenshot. |
| 3 | `FornamnEfternamn_ProvidedMeshMask` | Screenshot of the **mask used on the given mesh in Substance Painter** | Painter viewport with the mask channel view. |
| 4 | `FornamnEfternamn_OwnMesh` | Presentation image: **your own mesh with >= 3 different instances** | As #2. |
| 5 | `FornamnEfternamn_OwnMeshMask` | Painter screenshot of **your mask** | As #3. |
| 6 | `FornamnEfternamn_OwnMeshDecals` | Screenshot of the **decal sheet** used on your mesh | The sheet texture, ideally next to the mesh with decals. |
| 7 (VG) | `FornamnEfternamn_VertexPainting` | **GIF** of vertex painting on your own mesh with **at least 2 materials** | [04 section 5](04_Vertex_Painting.md#5-troubleshooting) (recording tips). |

Supported file types in the hand-in form: png, gif, jpeg, jpg.

---

## 3. Instance recipes - three (or more) clearly different looks

**Make instances the efficient way.** Right-click `M_Master_Surface` > *Create Material Instance* once per mesh, call it e.g. `MI_Crate`, and give it everything that belongs to the *mesh*:
the `Mask Texture`, the layer textures, `Breakup Texture`, `Detail Normal Texture`. Then right-click `MI_Crate` > *Create Material Instance* three times (`MI_Crate_Red`, `MI_Crate_Blue`, `MI_Crate_Green`): a child
inherits everything from its parent and only changes the numbers and colours below. That is also exactly how the demos are built (`MI_Demo_Base` -> `MI_Demo_Crate_Red` ...).
**Do not duplicate a `MI_Demo_*` for your own mesh**: `MI_Demo_Base` has the preview switch `Mask Uses Tiling UV` on (the engine's cube has one UV set); on your own two-UV mesh the mask would land in the wrong place.

A *different look* needs more than a colour change. The biggest levers, in order of visual impact:
**Base Tint**, **which Wear texture** (rust vs bare steel vs primer), **Wear / Dirt amount**, **roughness**, **Dirt tint**.
Values below are starting points on top of the defaults; colours are rough descriptions - choose them with the colour picker.

| Look | Group 03 Base | Group 04 Wear | Group 05 Dirt / 06 Scratches / others |
|---|---|---|---|
| **A. Red, heavily chipped** (the red crate) | `Base Tint` saturated red | `Wear Intensity` 1.3, `Wear Softness` 0.05, `Wear Edge Strength` 0.8, Wear texture = **dark rust** | `Dirt Intensity` 0.6; `Scratch Intensity` 1 |
| **B. Blue, clean** (the blue crate) | `Base Tint` deep blue, `Base Roughness Max` 0.55 (glossier) | `Wear Intensity` 0.4 (only edges), texture = bare steel (or the rust texture with `Wear Saturation` 0 and `Wear Brightness` 1.8 for a quick grey-steel look) | `Dirt Intensity` 0.3; `Scratch Intensity` 1.2; `Global Roughness Offset` -0.1 |
| **C. Pale paint, grimy and weathered** (the pink/cream crate) | `Base Tint` pale cream / pink | `Wear Intensity` 1.0 | `Dirt Intensity` 1.3, `Dirt AO Boost` 0.8 (needs a real AO in the mask alpha), darker `Dirt Tint`; `Use Macro Variation` ON, `Macro Intensity` 0.4 |
| **D. Olive-green, aged** (the green vault door) | `Base Tint` olive green, `Base Rotation` 90 | `Wear Intensity` 1.5, `Wear Height Influence` 0.8, rust texture, `Wear Rotation` 45 | `Dirt Intensity` 1.0, `Use Wetness` ON, `Wetness` 0.3 |
| **E. Per-object variation** | any of the above | - | `Use Instance Variation` ON: every copy in the level gets slightly different brightness/saturation without a new instance |

Tips for the presentation image: three props side by side with the **same mask** but different instances is the clearest way to show that *one master* produces many looks.

---

## 4. Suggested order of work (if time is short)

(The helper scripts: `Scripts/fix_texture_settings.py` sets the import settings of your textures, `Tools/pack_channels.py` packs AO / roughness / metallic / height into one ORMH image.)

1. **Run the script** (10 min) and try the `MI_Demo_*` instances so you know what the material does.
2. **UVs on your own mesh** (tiling set + unique set) - check them with Debug modes 13/14.
3. **Painter**: bake, paint R/G/B + AO, export the RGB mask, take the Painter screenshots (provided mesh *and* own mesh).
4. **Import** the textures with the correct settings ([02 section 1](02_Textures_and_Masks.md#1-texture-roles-and-import-settings)).
5. **Instances** (3+) on both meshes; take the parameter screenshot and the two presentation images.
6. **Vertex paint** + GIF (VG).
7. **Decal sheet** + decal meshes + screenshot.

---

## 5. Final self-check

- [ ] Own mesh is optimised (no excessive triangles) and has **UV set 1 = tiling** and **UV set 2 = unique**; *Generate Lightmap UVs* is **off**
- [ ] Unique UV set: inside 0-1, no overlap, padded
- [ ] RGB mask imported as **Masks (no sRGB)** (run `Scripts/fix_texture_settings.py` if unsure); Debug view shows the mask where you expect it, and Debug Mode 4 shows a believable AO
- [ ] Your own instances do **not** have `Mask Uses Tiling UV` ticked (that is preview-only)
- [ ] >= 3 instances that look clearly different, on **both** meshes
- [ ] Vertex painting works with **Nanite off**, GIF shows >= 2 materials
- [ ] Decal sheet is your own; decals are on your mesh; screenshot taken
- [ ] File names follow the brief, file types png/gif/jpg
