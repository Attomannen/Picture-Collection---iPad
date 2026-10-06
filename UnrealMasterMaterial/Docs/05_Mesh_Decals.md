# 05 - Mesh decals and the decal sheet

The assignment asks for **mesh decals** and for **your own decal sheet** applied to your own mesh
(*"Skapa en egen decal sheet som anvands pa din egen mesh"*, deliverable `..._OwnMeshDecals`). The reference images show them
clearly: the warning stickers on the crates, the "Achtung!" sign and "verboten!" plate on the vault door.

---

## 1. What a mesh decal is

A **mesh decal** is an ordinary little mesh - a plane, a strip, a slightly bent card - that is **UV-mapped to one cell of a decal sheet** and sits on top of a
surface (a few millimetres in front of it). Its material uses the **Deferred Decal domain** with a **DBuffer** blend mode, so Unreal draws it *into the surface*
like a projected decal: the surface keeps its lighting, shadows and roughness, and the sticker only changes colour / normal / roughness underneath.
You get the precision of a hand-placed mesh (exact shape, exact UVs, no projection stretching) with decal-quality integration.

* `M_Master_MeshDecal` (created by the script) is that material: *Material Domain* = **Deferred Decal**, *Blend Mode* = **Translucent**,
  *Decal Blend Mode* = **DBuffer Translucent Color, Normal, Roughness**.
* It reads three decal-sheet textures: **Color (RGB + alpha opacity)**, **Normal**, **ORM** (G = roughness, B = metallic).

---

## 2. Building your decal sheet

One texture set (same cell layout in all three maps), e.g. 2048 x 2048 or 4096 x 4096:

```
+---------+---------+---------+---------+
| hazard  | warning | arrow   | text    |   Each cell = one decal (or a family of them)
| stripes | sticker | sign    | plate   |   * transparent background (alpha 0) around every decal
+---------+---------+---------+---------+   * 8-16 px padding between cells so mip-maps do not bleed
| number  | stain 1 | stain 2 | crack   |   * grime stains/cracks have SOFT alpha, signs have a CRISP alpha
| stencil |  (soft) |  (soft) |         |
+---------+---------+---------+---------+
```

* **Color map (sRGB, with alpha).** Import with *Compress Without Alpha* **off**. Alpha = opacity of the decal. **Dilate** the colour a few pixels past the edge of every decal (fill the fully transparent area with the neighbouring colour instead of black or white): mip-mapping and filtering blend that hidden colour in, and a mismatch shows up as a dark or white halo around the decal.
* **Normal map** (Normalmap compression): flat (128,128,255) where nothing is raised; relief for embossed text, rivets, tape edges.
* **ORM map** (Masks, no sRGB): G = roughness (stickers: low, grime: high), B = metallic (usually 0). R and A are unused.
* Make it in Photoshop / Substance Designer / Painter (paint on a flat plane). Keep **one** sheet per set of props so many decals share one material and one draw call.
* **Screenshot for the assignment:** the sheet itself (the three maps or just the colour map) - name it `..._OwnMeshDecals`.

---

## 3. Making the decal meshes (DCC)

1. Create a plane per decal (a few subdivisions if it must follow a curved surface). Place it **0.2-1 cm in front of** the surface it sits on, normal facing out.
2. **UV-map** each plane to **its cell** of the sheet (UV channel 0). Zoom the UV island exactly onto the cell, keep the aspect ratio.
3. Put all decals of one prop in **one mesh** (a decal kit) with **one material slot**.
4. Export with the prop or as a separate mesh; a separate mesh is more flexible.

You can move a decal to another cell **in Unreal** without re-UVing: in the decal's material instance set **`Decal UV Tiling`** (0.5 for a 2 x 2 sheet) and **`Decal UV Offset`**
(0 or 0.5 in R/G). That is how the demo instances `MI_Demo_Decal_Hazard / _Sticker / _Stain` work.

---

## 4. In Unreal

1. Create a **material instance of `M_Master_MeshDecal`** (`MI_Decal_...`) and assign your decal sheet textures (`Decal Color Map`, `Decal Normal Map`, `Decal ORM Map`).
2. Assign the instance to the decal mesh's material slot. Place it over the surface (or parent it to the prop).
3. Tune it: `Decal Tint / Brightness / Saturation`, **`Decal Opacity`** (fade it in and out), **`Decal Opacity Contrast`** (>1 makes edges crisper),
   `Decal Normal Strength`, `Decal Roughness Min/Max`, `Decal Metallic` (1 = use the sheet's metallic channel as authored), and **`Decal Use Emissive`** for glowing signs.
   *Emissive depends on the decal blend mode:* if nothing glows in your engine version, open `M_Master_MeshDecal`, set **Decal Blend Mode = Translucent** in the Details panel and press Apply.
4. On the decal **mesh component** (Details panel): **Nanite off** (Nanite does not render this kind of material), **Cast Shadow off**, **collision off**, and leave *Receives Decals* alone on the surface underneath (it is on by default).

**Requirements and gotchas**

| Issue | What to do |
|---|---|
| Decal does not show at all | *Project Settings > Engine > Rendering*: **DBuffer Decals** must be on (it is by default in UE5 projects). The surface under it must receive decals (default; the master surface uses *Material Decal Response = Color, Normal, Roughness* by default). |
| Decal flickers / z-fights | Lift it 0.1-0.5 cm off the surface (the mesh must not sit exactly in the same plane). |
| Two decals overlap in the wrong order | Give the one that should be on top a higher **Translucency Sort Priority** on its mesh component (Rendering section; the label can differ slightly by version). |
| Edges look blurry | Raise `Decal Opacity Contrast`; make sure alpha is crisp in the sheet and *Compress Without Alpha* is off. |
| Decal is the wrong colour | The colour map must be **sRGB (Default compression)** - not Masks. |
| Dark or white halo around the decal | The colour under the transparent pixels was black/white: dilate the colour past the edge of each decal (section 2) and keep 8-16 px between cells. |
| Using a renderer without DBuffer (e.g. mobile) | Use a normal **Surface** material with Blend Mode *Masked* instead. |

---

## 5. Decals inside the surface master?

The surface master does not need decals of its own: the stickers are separate meshes (this is the industry-standard *mesh decal* workflow that the assignment
references). The *wear*, *dirt* and *scratches* from the RGB mask still apply to the surface **underneath**, so a decal can look as if paint chipped around it.
