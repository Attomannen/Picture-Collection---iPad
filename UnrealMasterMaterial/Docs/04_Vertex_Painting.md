# 04 - Vertex painting (the VG part)

The assignment's VG requirement: *"a simple vertex painting setup that lets you paint at least one other material in your shader"*.
In this master that is **Vertex Layer 1** (paint **Red**), with Vertex Layer 2 (Green), Vertex Layer 3 (Blue) and "extra dirt" (Alpha) as bonuses.

The screenshot in the assignment shows exactly this: **Mesh Paint Mode > Vertex Color tab**, **Paint Color = black, Erase Color = white, Channels: only Red ticked**.
That is the default of this material: *painting black in the red channel adds Vertex Layer 1*.

---

## 1. What you need

| Requirement | Why |
|---|---|
| A **static mesh with enough vertices** where you want to paint | Paint is stored **per vertex** and interpolated across triangles. A flat wall made of 2 triangles can only fade across the whole wall. Subdivide to roughly one vertex every 10-25 cm (or every few cm for detailed edges). In Unreal, *Modeling Mode > Create* can make a plane/rectangle with many subdivisions (for example 32 x 32) for testing. |
| **Nanite OFF** on that mesh | Per-instance painted vertex colours are not supported on Nanite meshes (Unreal only shows *asset* vertex colours there). Static Mesh Editor > Details > *Nanite Settings* > untick **Enable Nanite Support**. Your "simple, game-optimised mesh" for the assignment is normally not Nanite anyway. |
| A material instance of `M_Master_Surface` with **textures in the Vertex 1 slots** | Otherwise the painted layer is just a flat tint (still visible, but boring). |
| `Use Vertex Layer 1` **ON** (default) | Static switch in group *00 Features*. |

---

## 2. Step by step

1. Put the mesh in the level and assign your material instance. In the instance, fill group **08 Vertex Layer 1 (paint R)**:
   `Vertex 1 Albedo / Normal Map / ORMH Map` (e.g. brick), `Vertex 1 Tint`, `Vertex 1 Tiling` ...
2. Select the mesh. Switch the editor to **Mesh Paint mode** (mode drop-down at the top-left of the viewport toolbar; shortcut Shift+5).
3. Choose the **Vertex Color** tab and the **Paint** tool.
4. Under **Color Painting** set
   * **Paint Color:** black
   * **Erase Color:** white
   * **Channels:** tick **Red** only (so Green/Blue/Alpha stay untouched). *Check this every time:* the tool may start with several channels ticked, and then one stroke paints Vertex Layers 2 and 3 as well (if they are switched on).
   * Use **pure black and white** - the brush blends the raw values, and in-between colours only make it harder to see what was painted.
5. Under **Brush** pick a **Size** that matches your vertex spacing, **Strength** 0.2-0.5 for soft build-up (1.0 for a hard stamp) and **Falloff** around 1.
6. **Hold the left mouse button** and drag over the surface: the base layer is replaced by Vertex Layer 1 where you paint. **Hold Ctrl and paint** to erase (back to the base).
7. To see what you painted: *Color View Mode* in the Mesh Paint panel (choose the Red channel) shows white = nothing, black = painted.
8. **Fill** paints the whole mesh with the Paint Color on the ticked channels; **Swap** swaps Paint/Erase colours.
9. Painted colours are stored on the **actor in the level**. Use the **ToMesh** button (propagate to the mesh asset) if every copy of the mesh should share them, and **Save** the modified assets/level.
10. **Paint last.** Re-importing the mesh or changing its vertices afterwards can throw the painted colours away (the panel then offers *Fix*). Finish modelling, UVs and the Nanite setting first.

> Selecting the **Erase** colour as black and Paint as white (or the reverse) is just a swap. If you prefer painting white, switch on **`Vertex Paint White Adds`** in group 00 and **Fill the mesh with black first**
> (Paint Color black, the channel(s) you will use ticked, press **Fill**; then set Paint Color white and paint), otherwise the whole mesh shows the painted layer.

---

## 3. The four channels

| Channel (tick in *Channels*) | Paints | Switch to turn on | Parameters |
|---|---|---|---|
| **Red** | **Vertex Layer 1** (the assignment's second material) | `Use Vertex Layer 1` (default on) | group 08 |
| **Green** | Vertex Layer 2 | `Use Vertex Layer 2` | group 09 |
| **Blue** | Vertex Layer 3 | `Use Vertex Layer 3` | group 10 |
| **Alpha** | **extra dirt** on top of the mask dirt | `Use Vertex Alpha Dirt` | group 07 + 05 |

Painting more than one layer on the same spot: the higher layer wins (Vertex 3 over 2 over 1); you can blend them by painting several channels with low strength.
For the GIF in the assignment ("at least 2 materials") painting Vertex Layer 1 over the base layer is enough; painting Layer 2 as well is a nice extra.

---

## 4. Getting a *good-looking* edge

A raw vertex gradient is a soft smear. The master sharpens it with **height + breakup noise** (see [01 How it works](01_How_It_Works.md#4-height-aware-blending-the-important-trick)).
Tune these per layer in the instance:

| Goal | Change |
|---|---|
| Crisp, plaster-chipping edge | `Vertex 1 Softness` **0.03 - 0.08** |
| Edge follows the brick/stone shape | `Vertex 1 Height Influence` **0.7 - 1.0** (needs a real height map in the layer's ORMH alpha) |
| Irregular, eroded border | `Vertex 1 Breakup` **0.4 - 0.7**, and a good tileable `Breakup Texture` |
| Layer should appear sooner/later | paint more/less; or change the layer's `Height Offset` |
| Plain soft blend (no height) | `Vertex 1 Height Influence` 0, `Softness` 0.4-0.5, `Breakup` 0 |

The demo instance **`MI_Demo_Plaster_Brick_VertexPaint`** is set up like this (plaster base, brick under it = paint **Red**, moss as Vertex Layer 2 = paint **Green**; the wear layer is switched off so the painted layers are what you see) - apply it to a subdivided plane and try it.

---

## 5. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Painting does nothing | The mesh is **Nanite** (turn it off), or `Use Vertex Layer 1` is off, or you painted the wrong *channel*, or you painted **white** while *Vertex Paint White Adds* is off. Use *Color View Mode* to see the data. |
| The whole mesh shows the painted layer | Mesh was **filled black**, or `Vertex Paint White Adds` is ON with an unpainted (white) mesh, or **the FBX brought its own vertex colours** (anything not white lights up Vertex Layer 1; `Debug Mode 5` shows them). Re-import with *Vertex Color Import Option* = Replace or Ignore, or **Fill** the Red channel with white. |
| Paint looks blocky / only fades over a huge area | Not enough vertices. Subdivide the mesh (or paint on a denser mesh). |
| Edge is blurry | Lower `Vertex 1 Softness`, raise `Height Influence` and `Breakup`, give the layer a real height map. |
| Paint disappears after re-importing the mesh | Instance colours belong to the level, not the asset. Use **ToMesh**, or repaint (and paint last). |
| The painted layer is a flat colour | Assign textures to the `Vertex 1 ...` parameters; `Vertex 1 Tint` multiplies the albedo. |
| Debug | `Debug View` ON + **Debug Mode 5** (vertex RGB), **6** (vertex alpha), **10 / 11 / 12** (the resulting layer weights). |

**Recording the GIF** the assignment asks for: use any screen recorder that exports GIF (for example ScreenToGif on Windows, LICEcap or Kap) -
show the viewport in Mesh Paint mode, paint across the mesh so the second material appears, and keep it under a few seconds.
