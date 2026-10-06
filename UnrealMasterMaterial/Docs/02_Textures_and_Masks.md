# 02 - Textures, the RGB mask and the two UV sheets

Everything here is about **feeding** the master material correctly. Wrong import settings are the number-one cause of
"why does it look wrong / why is there a red error" - so the settings are listed exactly.

Contents: [1 Texture roles and import settings](#1-texture-roles-and-import-settings) - [2 Packing ORMH](#2-packing-the-ormh-map) -
[3 The RGB mask in Substance Painter](#3-making-the-rgb-mask-in-substance-3d-painter) - [4 The two UV sheets](#4-the-two-uv-sheets) -
[5 Checking it in Unreal](#5-checking-it-in-unreal) - [6 Naming](#6-suggested-naming)

**Two helpers that save time:** [`Scripts/fix_texture_settings.py`](../Scripts/fix_texture_settings.py) sets the import settings of section 1 for you
(from the texture names), and [`Tools/pack_channels.py`](../Tools/pack_channels.py) packs separate AO / roughness / metallic / height images into one ORMH png (section 2).

---

## 1. Texture roles and import settings

After importing a texture, double-click it and set these values, then **Save**.

| Role (parameter) | Channels | Compression Settings | sRGB | Notes |
|---|---|---|---|---|
| **Albedo** (`<Layer> Albedo`) | RGB | **Default** | **on** | Pure colour, no baked light or shadow. |
| **Normal map** (`<Layer> Normal Map`, `Detail Normal Texture`) | RGB | **Normalmap** | off (automatic) | **DirectX / Unreal convention (green points down).** An OpenGL normal map looks inside-out: tick *Flip Green Channel* in the texture, or export the DirectX variant. |
| **ORMH** (`<Layer> ORMH Map`) | R = AO, G = Roughness, B = Metallic, **A = Height** | **Masks (no sRGB)** | **off** | Needs the alpha channel: leave *Compress Without Alpha* **unticked**. |
| **RGB mask** (`Mask Texture`) | R = Wear, G = Dirt, B = Scratches, **A = baked AO** | **Masks (no sRGB)** | **off** | Unique UVs. Leave *Compress Without Alpha* unticked if you use the AO in alpha. |
| **Breakup / Macro** noise (`Breakup Texture`, `Macro Texture`) | R used | **Masks (no sRGB)** | **off** | Tileable greyscale noise, ~50 % grey on average. |
| **Emissive** (`Emissive Texture`) | RGB | **Default** | **on** | Unique UVs. |
| **Opacity** (`Opacity Texture`) | R used | **Masks (no sRGB)** | **off** | Cut-outs (fences, leaves). |
| **Decal colour** (`Decal Color Map`) | RGB + **A = opacity** | **Default** | **on** | Alpha must survive: *Compress Without Alpha* **unticked**. |
| **Decal normal / ORM** | | Normalmap / Masks (no sRGB) | | Same rules as above. |

**The "Sampler type" error.** Each texture parameter has a *sampler type* and Unreal checks that the assigned texture
matches it. If you see `Sampler type is Color, should be Masks for ...` the **texture's import setting** is wrong, not the material.
The table above is the fix: Color <-> sRGB colour textures, Masks <-> packed/greyscale data, Normal <-> Normalmap.
Quickest way: select the textures in the Content Browser and run `Scripts/fix_texture_settings.py` (*Tools > Execute Python Script*). It reads the **last word
of the name** - `T_Brick_A`, `T_Brick_N`, `T_Brick_ORMH`, `T_Crate_Mask`, `T_Breakup_01` are all understood - and prints every change it makes.

Resolutions that work well: tiling layers 1024-2048 (the tile repeats, so keep it modest), RGB mask 1024-2048 per prop
(the breakup noise adds the fine detail), decal sheet 2048-4096.

---

## 2. Packing the ORMH map

Each layer wants **one** packed map instead of four:

```
R  Ambient Occlusion      (white = open, dark = cavity)
G  Roughness              (0 = mirror, 1 = rough)       <- remapped per layer by Roughness Min / Max
B  Metallic               (0 = dielectric, 1 = metal)   <- scaled per layer by Metallic
A  Height                 (0.5 = neutral)               <- drives the chipped / painted edges
```

* **Substance 3D Painter / Designer**: the stock *Unreal Engine (Packed)* export preset gives `OcclusionRoughnessMetallic` (RGB). Duplicate the preset and add **Height** to the alpha of that map.
* **Downloaded PBR sets** (for example from ambientCG or Poly Haven, both CC0): they ship separate *Color*, *AO*, *Roughness*, *Metalness* (sometimes), *Displacement/Height* and *Normal GL/DX*. Take the **DX** normal (or the GL one with *Flip Green Channel* ticked). Combine AO, Roughness, Metalness and Height into R, G, B, A with the channel panel in Photoshop or GIMP (or a channel-shuffle node in Substance Designer) - or with the small script that comes with this project (needs Python and `pip install pillow`):

  ```
  python Tools/pack_channels.py --r Brick_AO.png --g Brick_Roughness.png --b 0 --a Brick_Height.png -o T_Brick_ORMH.png
  ```

  A number instead of a file is a constant: `--b 0` = no metal, `--r 1` = no AO map, `--a 0.5` = no height map. A set with *Glossiness* instead of roughness: add `--invert-g`. 16-bit height maps are fine.
* **No height map?** Fill A with 50 % grey. Everything still works - edges are then driven only by the mask and the breakup noise (set `Wear Height Influence` to 0).
* Always double-check the **tileability** (seamless on both axes); the master repeats it.

---

## 3. Making the RGB mask in Substance 3D Painter

Goal: one RGBA PNG per asset, painted on the **unique UV set**:

| Channel | Paint / generate with |
|---|---|
| **R** Wear | edge wear: the *Metal Edge Wear* generator / smart mask, driven by the baked curvature; add hand-painted chips |
| **G** Dirt | the *Dirt* generator (uses baked AO), *Dust*, drips and leaks, hand-painted grime |
| **B** Scratches | a scratch grunge in the mask of a fill layer, or hand-painted lines |
| **A** AO | the baked **Ambient Occlusion** |

Because Painter's generators need baked mesh maps, the order is: bake -> paint three grey masks -> export.

1. **Mesh setup.** Painter bakes and paints on the mesh's **first UV set**. Export a copy of the mesh for Painter in which the **unique UVs are the first UV set**
   (in Maya/Blender simply reorder the UV sets or delete the tiling set in that copy). For Unreal keep the version with the **tiling set first (UV0)** and the unique set second (UV1):
   no switch needed, and the normal maps are read in the right tangent frame (see [01 section 1](01_How_It_Works.md#1-two-uv-sets)).
   If you only have *one* FBX with the unique set first, import that and tick **`Swap UV Channels`** - it works, with the small caveat explained there.
2. **Bake mesh maps** (*Texture Set Settings > Bake Mesh Maps*) at 2048 or 4096: at least *Ambient Occlusion*, *Curvature*, *World space normals*, *Position*, *Thickness*. Use your high-poly mesh if you have one.
3. **Add three user channels** (*Texture Set Settings > Channels > +*): `User0`, `User1`, `User2` (grayscale, 8 or 16 bit). They will hold Wear, Dirt, Scratches.
4. **Paint each mask into its channel.** Create a *Fill layer*, enable **only** the matching user channel in the fill's channel list and give it value 1.0; add a **black mask** to the layer and put a generator/smart mask (or paint strokes) on that mask.
   One fill layer per effect keeps them separate: `Wear` -> User0, `Dirt` -> User1, `Scratches` -> User2.
5. **Export** (*File > Export Textures*): create a custom output template with one map named e.g. `$mesh_$textureSet_Mask` and set **R <- User0, G <- User1, B <- User2, A <- Ambient Occlusion**
   (grayscale source for each). Format PNG, 2048, 8-bit is enough. Set *Padding* to **Dilation infinite** (not "transparent"): the alpha channel holds AO, and transparent padding would
   leave black AO and seams at the island borders.
6. **Screenshot for the assignment:** the grading asks for "a screenshot of the mask used on the mesh in Substance Painter" - take it in the viewport with the channel view set to the mask.

> The exact menu wording differs a little between Painter versions. **Fallback that always works:** export the three masks and the AO as four separate
> greyscale images and combine them in Photoshop/GIMP (paste each into its channel R, G, B and the alpha channel) or in a small Substance Designer graph.

**Check the file before you blame the material:** in Unreal, `Debug View` with `Debug Mode` **4** shows the alpha channel. It must look like a plausible AO bake (mostly white).
Solid black or a flat cut-out of the UV islands means the alpha is not AO (transparent padding, or nothing was mapped to A): re-export, or switch `Use Baked AO` off.
An RGB-only png (no alpha channel at all) is fine - Unreal then reads alpha = 1 = "no occlusion".

**Quality tips**

* Paint **soft**. The master sharpens edges with height and breakup noise; a crisp 1k mask only fights it. But paint clearly **white** where the effect must show: values below about 0.3 reveal almost nothing at the default settings ([01 section 4](01_How_It_Works.md#4-height-aware-blending-the-important-trick)).
* **Compression bleed.** *Masks (no sRGB)* is a block-compressed format (DXT1/DXT5): inside each 4x4 block the R, G and B channels share one small colour palette, so a thin scratch line in B can leave a faint trace in R or G. 2048 px or more keeps it invisible.
  If you still see it, import the mask with compression **BC7** (sRGB off) and, in the master, set the *Sampler Type* of the `Mask Texture` node to **Linear Color** (one drop-down; re-running the script resets it).
* Keep **A** (AO) as a clean, low-frequency bake. It darkens the surface *and* is read by dirt-in-crevices.
* Leave **R** at 0 where the base paint must stay intact - that is why a new instance (black mask) shows only the base layer.
* You can **invert** any channel in the instance (`Wear Invert` ...) or scale it (`Wear Intensity` ...) without re-exporting.

---

## 4. The two UV sheets

The assignment requires two UV sets per mesh. Build them in Maya / Blender / 3ds Max as **UV set 1 and UV set 2**, export to FBX with both, and Unreal imports them as UV0 and UV1.

### UV0 - tiling (texel density)

* One consistent **texel density** across the whole mesh and across your props. A practical rule: **1 UV unit = 1 metre** for a 1k-2k tileable texture (about 1000-2000 px/m).
  Use the *Texel Density* tool of your DCC (Maya has one; Blender's free *Texel Density Checker* add-on does it).
* Islands may **overlap and mirror** freely and may sit **outside 0-1**; that is the point.
* **Straighten** islands and align them with the grain/stripe direction of the texture (wood grain, brushed metal, brick courses).
* Cut seams where the material changes so that tile seams are hidden by edges.

### UV1 - unique (for the RGB mask)

* Everything inside **0-1**, **no overlap, no mirroring**.
* **Padding** between islands: at least 4-8 px at 2k, so mip-maps do not bleed.
* Give the visible faces more space, hidden faces (bottom, back) less.
* The set can double as the **lightmap UV** (Static Mesh Editor > *Light Map Coordinate Index* = 1) if you use baked lighting; with Lumen no lightmap UVs are needed.
* **Never rotate or flip** an island of the unique set relative to the same island in the tiling set - copy the first set and only scale and move islands. Unreal reads normal maps in the tangent frame of UV0; identical orientation keeps the bumps correct whichever set is first.

### Importing into Unreal

> **Untick *Generate Lightmap UVs*.** This is on by default and **overwrites UV channel 1** with an automatic lightmap unwrap - your unique UVs would silently disappear, and the mask would look
> scrambled. In the FBX import dialog (*Static Mesh* section) untick it; for a mesh that is already in the project open the Static Mesh Editor > Details > *Build Settings* > untick
> **Generate Lightmap UVs** > *Apply Changes*. Then re-check with Debug Mode 14.

*FBX Import > Static Mesh*: also keep the mesh **non-Nanite** if you will vertex-paint, and set *Vertex Color Import Option* to **Replace** or **Ignore** unless you painted vertex colours in your DCC on purpose
(any non-white imported vertex colour lights up Vertex Layer 1 straight away - Debug Mode 5 shows it).
Tick **`Swap UV Channels`** in the material instance only if your unique UVs ended up in UV0.

---

## 5. Checking it in Unreal

Do this once per mesh; it takes a minute and saves hours:

1. Open the Static Mesh Editor, *Show > UV* (or the *UV Channel* drop-down in the viewport) and look at **Channel 0** and **Channel 1**.
2. Create an instance of `M_Master_Surface`, switch on **`Debug View`**:
   * `Debug Mode 13` - **tiling UV checker.** Every square is one tile. Squares should look **the same size everywhere**. Different sizes = different texel density.
   * `Debug Mode 14` - **unique UV gradient** (red = U, green = V). It should be smooth and continuous on every island; no mirroring.
   * `Debug Mode 1 / 2 / 3 / 4` - **your mask channels** (R wear / G dirt / B scratches / A AO) as white-on-black on the mesh. If they appear in the wrong place, the mask is on the wrong UV set (try `Swap UV Channels`).
3. Turn `Debug View` off again.

`MI_Demo_Debug_Masks` is a ready-made instance for this.

---

## 6. Suggested naming

```
T_<Asset>_Mask          RGB(A) mask          T_Crate_Mask
T_<Material>_A          albedo               T_PaintedMetal_A
T_<Material>_N          normal               T_PaintedMetal_N
T_<Material>_ORMH       packed AO/Rough/Metal/Height   T_PaintedMetal_ORMH
T_Breakup_01            tileable noise (R = wear edges, G = dirt edges, B = scratch + vertex edges; grey is fine)
T_DecalSheet_C / _N / _ORM
M_Master_Surface  ->  MI_Crate (parent: mask + textures) -> MI_Crate_Red, MI_Crate_Blue, MI_Crate_Green ...
```

The last word of each texture name is what `Scripts/fix_texture_settings.py` reads, so `_A`, `_N`, `_ORMH` and `_Mask` are not just style.
