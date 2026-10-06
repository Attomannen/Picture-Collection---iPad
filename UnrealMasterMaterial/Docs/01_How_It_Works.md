# 01 - How the master material works

This page explains the *ideas*. If you only want to use the material, read the README quick start and
[02 Textures and masks](02_Textures_and_Masks.md); come back here when you want to know **why** a parameter does what it does.

Contents: [1 Two UV sets](#1-two-uv-sets) - [2 The RGB mask](#2-the-rgb-mask) - [3 The layer stack](#3-the-layer-stack) -
[4 Height-aware blending](#4-height-aware-blending-the-important-trick) - [5 Vertex painting](#5-vertex-painting-inside-the-shader) -
[6 Everything after the stack](#6-everything-after-the-stack) - [7 Tour of the graph](#7-tour-of-the-graph-in-the-material-editor) -
[8 The five Material Functions](#8-the-five-material-functions) - [9 Design decisions](#9-design-decisions-and-why) - [10 Extending it](#10-extending-it)

---

## 1. Two UV sets

The assignment asks for **two UV sheets per mesh**. They solve opposite problems:

| | UV0 - *tiling* UVs | UV1 - *unique* UVs |
|---|---|---|
| Layout | Constant **texel density**; islands may overlap, be mirrored, and run far outside 0-1 | Every face has its **own place** inside 0-1, **no overlap**, padding between islands |
| Used for | Tileable PBR layers, detail normal, breakup noise, macro noise | The **RGB mask** (wear, dirt, scratches, baked AO) and emissive |
| Why | A 1k brick texture should look equally sharp on a big wall and on a small crate | Dirt on the left side of *this* crate must not appear on the right side |

```
 tiling UV (UV0)                         unique UV (UV1)
 +---+---+---+  tile 1 tile 2 ...        +------------------+
 |###|###|###|  islands overlap and      |[side][top ][side]|   each face has its own
 +---+---+---+  repeat - great for       |[side][fron][back]|   patch -> masks are
 | tile grid |  tileable textures         +------------------+   individual per face
```

In the engine UV0 is the first UV channel (Maya `map1`, Blender first UV map) and UV1 is the second.
If your mesh came out the other way round, switch on **`Swap UV Channels`** (group 00) instead of re-exporting.
Use **Debug View** modes **13** (tiling UV checker: every square = one tile, all squares should look the same size on the mesh)
and **14** (unique UV gradient) to check your UV sets in seconds.

> **Why the tiling set is UV0 by default.** Unreal builds the *tangents* - the frame a tangent-space normal map is read in - from
> **UV channel 0 only**. The tiling layers carry normal maps, so they read best when they use the very UV set the tangents come
> from. If you swap (tiling = UV1), the normal maps still work, but anywhere the two sets are rotated or mirrored against each other
> the bumps are lit from the wrong side. **Rule of thumb: when you make the second UV set, copy the first and only scale/move
> islands - never rotate or flip them.** Then either order looks right. (The assignment text does not say which set is "first";
> use whichever your workflow needs and the debug modes to check.)

The master multiplies the tiling UVs by **`Global Tiling`**, and every layer then applies its own
**Tiling / Rotation / Offset** on top (rotating a layer a few degrees is the cheapest way to stop two layers from repeating in step).

---

## 2. The RGB mask

One texture, four channels, painted in Substance Painter on the **unique** UVs:

| Channel | Meaning | Controlled by |
|---|---|---|
| **R** | **Wear** - where the top coat is damaged and the *Wear layer* shows (chipped paint, bare metal, rust, brick) | group 04 |
| **G** | **Dirt** - grime/dust/mud/soot *on top of everything* | group 05 |
| **B** | **Scratches** - thin lines revealing bright bare metal | group 06 |
| **A** | **Ambient occlusion**, baked. Multiplied into AO and also pushes extra dirt into crevices (`Dirt AO Boost`) | group 02 + 05 |

Import it as **Masks (no sRGB)**. A fresh instance has a black mask with AO = 1, i.e. *no* wear/dirt/scratches, so the base layer is all you see until you assign a mask.

**How white is "white enough"?** The reveal (section 4) needs a mask value *above about 0.3* before anything shows at the default settings
(0.5 shows roughly half of the pixels, 0.7 almost all). So paint wear and dirt clearly white; a faint grey brush stroke will look empty.
If you cannot repaint, raise `Wear Intensity` / `Dirt Intensity` (up to 2).

Why pack four things in one texture? One texture sample and one file per asset - the same trick used in the *Far Cry 6* image in the assignment.

---

## 3. The layer stack

Everything you see is built from **tiling layers**. Each layer is a small PBR set - **Albedo**, **Normal map**, and one
packed **ORMH** map (R = Ambient **O**cclusion, G = **R**oughness, B = **M**etallic, A = **H**eight) - plus a block of
adjustments (tint, brightness, saturation, tiling, rotation, offset, normal strength, roughness min/max, metallic, AO strength,
height contrast/offset).

```
 top      Scratches   mask B             thin lines of bare metal
          Dirt        mask G (+ AO, + vertex alpha)   grime over everything
          Vertex 3    vertex colour B    painted by hand   (optional)
          Vertex 2    vertex colour G    painted by hand   (optional)
          Vertex 1    vertex colour R    painted by hand   <- the assignment's VG layer
          Wear        mask R             what is under the paint
 bottom   Base        always visible     the main surface / the paint
```

Blending is done bottom to top, each step is `MF_LayerBlend(previous result, next layer, weight)`.

**Why this order?**

* **Wear sits right above Base** because wear is "the paint chipped off *the base*". The Wear layer is revealed *through the base only*.
* **Vertex layers sit above Wear**: a patch you painted by hand (e.g. exposed brick) is a different material and is shown in full - the asset's baked wear does not chew into it.
* **Dirt covers everything below** (grime lies on whatever surface is there) and **scratches are on top** (a scratch cuts through dirt, too).
* Normals follow the same order; AO, roughness and metallic are blended like colour.

The stack is where you art-direct: turn a layer off with its static switch, change its tint, or swap its textures in an instance.

Two details worth knowing: a layer's **rotation** turns its *normal map* with it (otherwise the bumps would be lit from the wrong side),
and the **tints are all white** - a texture you assign shows exactly as authored. A layer with *no* texture yet shows a flat placeholder
colour (blue-grey base, rust-orange wear, dark-brown dirt, brick-red / moss-green / sand vertex layers) so you can see the stack working
before you have any textures.

---

## 4. Height-aware blending (the important trick)

A 1k-2k mask is *soft and low-resolution*. Blend two layers with it directly and you get a blurry fade. Games like the
ones in the assignment get **sharp, organic chipped edges** instead. The master does it with a small function,
**`MF_RevealWeight`**, used for the wear, dirt, scratches and every vertex-painted layer.

Think of it as a **flood**:

* The **mask** is the *water level* (0 = dry, 1 = everything under water).
* The layer's **height map** (ORMH alpha) and a tiling **breakup noise** are the *terrain*.
* A pixel shows the layer when the water covers its terrain. Low spots flood first, so the edge follows the texture's own detail.

```
 weight = saturate( (mask*(1+2W) - T) / (2W) )

 mask   after Invert and Intensity                             0..1
 T      "when does this pixel flood"  =  0.5
                                         - HeightInfluence * (Height - 0.5)
                                         + BreakupStrength * (0.5 - Breakup)       (clamped to 0..1)
 W      Softness = how wide the transition is
```

Properties of this formula (they are checked by the automated tests for random inputs):

* mask = 0 gives weight **0**, mask = 1 gives weight **1** (up to floating-point rounding), for *any* height / breakup / softness, so no leaks and no surprises at the extremes;
* weight rises monotonically with the mask;
* height, breakup and softness only change *where in between* the pixels switch on.

**Softness** (`Wear Softness` ...) sets the width of the transition. It is not literally the mask width: for T = 0.5 the weight goes
from 0 to 1 over `2W / (1 + 2W)` of the mask range, centred a little below 0.5:

| Softness W | mask range where weight goes 0 -> 1 | Look |
|---|---|---|
| 0.02 | 0.48 - 0.52 | razor-sharp stencil edge |
| 0.08 *(default wear)* | 0.43 - 0.57 | crisp chipped paint |
| 0.25 | 0.33 - 0.67 | soft grime |
| 0.50 | 0.25 - 0.75 | broad, linear-looking fade |

Height and breakup make T vary from pixel to pixel (typically 0.5 plus or minus 0.1), so in practice different pixels switch on at different
mask values and the *coverage* grows smoothly with the mask - roughly 3 % of the pixels at mask 0.3, 18 % at 0.4, half at 0.5, 83 % at 0.6, almost all at 0.7
(default settings, typical textures). That is exactly what produces the organic, chipped look.

**Distance.** Textures are mip-mapped, so far away the height and breakup noise average out to grey and the edge becomes a clean, smooth ramp: the amount
of wear can look a little different at a distance than up close. If it bothers you on a hero prop, raise the layer's Softness or lower its Height Influence / Breakup.

**Height Influence** (-1..1): how strongly the layer's own height map decides who floods first. `+` = high spots of the layer appear first
(raised rust bumps), `-` = low spots first (dirt settling in dents), `0` = ignore height (then only the mask and breakup decide).

**Breakup** (0..1): how strongly the shared *Breakup Texture* (tileable greyscale noise, scaled by `Breakup Tiling`) erodes the edge. Bright noise floods first. 50 % grey is neutral.

**Wear Edge Color / Strength**: where the weight is between 0 and 1 (`4 * w * (1-w)` peaks at 0.5) the pixel is tinted
toward the edge colour: the thin dark rim you see around chipped paint in the assignment images.

---

## 5. Vertex painting inside the shader

Vertex colour channels paint **three more layers** (and one dirt amount):

| Vertex channel | Paints | Switch |
|---|---|---|
| **R** | Vertex Layer 1 | `Use Vertex Layer 1` (on by default) |
| **G** | Vertex Layer 2 | `Use Vertex Layer 2` |
| **B** | Vertex Layer 3 | `Use Vertex Layer 3` |
| **A** | extra dirt on top of the mask dirt | `Use Vertex Alpha Dirt` |

A mesh with no painted vertex colours is **white (1,1,1,1)**. The assignment's screenshot paints **black** into the **Red** channel (Erase
colour white), so the default is **"black adds a layer"**: the shader uses `1 - channel` as the paint amount. If you prefer painting white, switch on
`Vertex Paint White Adds` and **Fill the mesh black first**.

Vertex colours are coarse (one value per vertex), so their painted gradient is soft - and then `MF_RevealWeight` turns it into a sharp, height-driven edge,
the same trick as for the mask. Tune it per layer with `Vertex N Softness / Height Influence / Breakup`.
See [04 Vertex painting](04_Vertex_Painting.md) for the practical steps.

---

## 6. Everything after the stack

In this order (each is a *static switch*, so unused parts cost nothing):

1. **Macro variation** - one big, low-contrast noise multiplied over colour and roughness (UV or world space) to hide repetition.
2. **Instance variation** - a random brightness/saturation shift per object (a hash of the object position, plus `PerInstanceRandom` so every instance of an instanced mesh differs too; `Variation Seed` re-rolls all of them); duplicates stop looking identical.
3. **Global grade** - `Global Tint / Brightness / Saturation`.
4. **Wetness** - darkens albedo, lowers roughness.
5. **Global Roughness Offset**.
6. **Ambient occlusion** - layer AO x baked AO (`Mask AO Strength`) x `Global AO Strength`.
7. **Detail normal** - a fine tiling normal blended with *whiteout* blending onto the layer normal; fades out between `Detail Fade Start` and `Detail Fade End` (distance in cm).
8. **Emissive** and **Opacity Mask** - for signs/lights and cut-outs.
9. **Debug View** - replaces the output with a mask / weight / UV colour (unlit), free when switched off.

---

## 7. Tour of the graph in the Material Editor

Open `M_Master_Surface`. The graph is laid out in horizontal **bands**, one per numbered section; a small banner at the left edge of each band names it.
(Unreal's Python API cannot resize comment boxes, so the banners are small and the bands are what group the nodes.)
Inside a band, **parameters are on the left** and the **function call in the middle**.

| Band | What you see |
|---|---|
| 1 UV SETS | two Texture Coordinate nodes (0 and 1), the `Swap UV Channels` / `Mask Uses Tiling UV` (preview) switches, `Global Tiling` |
| 2 RGB MASK | `Mask Texture` sampled on the unique UVs; R, G, B split out; alpha = baked AO |
| 3 BREAKUP NOISE | `Breakup Texture` on the tiling UVs; R drives wear edges, G dirt edges, B scratch and vertex-paint edges |
| 4 VERTEX COLOUR | Vertex Color node, the "white adds" switch, four paint amounts |
| 5 BASE LAYER | the Base layer's parameters feeding **MF_TilingLayer** |
| 6 WEAR LAYER | its parameters, **MF_TilingLayer**, and the **MF_RevealWeight** for mask R |
| 7 DIRT LAYER | same, with mask G + AO crevices + vertex alpha |
| 8 SCRATCHES | the **MF_RevealWeight** for mask B |
| 9 / 10 / 11 VERTEX LAYERS 1-3 | layer + reveal weight for vertex R / G / B |
| 12 LAYER STACK | seven **MF_LayerBlend** nodes in a row: Wear, Vertex 1-3, Dirt, Scratches |
| 13 POST | macro, instance variation, global grade, wetness |
| 14 / 15 / 16 | AO, normal + detail normal, emissive + opacity |
| 17 DEBUG VIEW | **MF_DebugSelect** with the 16 debug colours (the band's banner lists what each number shows) |
| 18 MATERIAL OUTPUTS | static switches (debug on/off) feeding the material's output pins |

Double-click any function node (or open it in `MasterMaterial/Functions/`) to see how it works inside - each is small enough for one screen.

---

## 8. The five Material Functions

| Function | Inputs (main ones) | Outputs | Job |
|---|---|---|---|
| `MF_TilingLayer` | 3 texture objects, UV, tiling, rotation, offset, tint, brightness, saturation, normal strength, roughness min/max, metallic, AO strength, height contrast/offset | BaseColor, Normal, Roughness, Metallic, AO, Height | Samples one layer and applies all its adjustments |
| `MF_RevealWeight` | Mask, Height, Intensity, Invert, HeightInfluence, Breakup, BreakupStrength, Softness | Weight | Mask + height + noise -> crisp 0..1 weight (section 4) |
| `MF_LayerBlend` | UseLayer (static), colour/normal/rough/metal/AO of A and B, Weight, EdgeColor, EdgeStrength | the five channels | Blends B over A; **UseLayer = false returns A and B is never compiled** |
| `MF_NormalBlend` | Base, Detail, Intensity | Normal | Whiteout blend; intensity 0 returns Base |
| `MF_DebugSelect` | Mode, C01..C16 | Color | Picks one of 16 colours by index |

If creating or calling functions ever fails on your engine version, the script automatically rebuilds the master with the
same logic **expanded inline** (about 1000 nodes instead of about 370). The result is identical; only the graph is bigger.

---

## 9. Design decisions (and why)

* **Parameters live in the master, not in the functions.** A function used six times cannot own six different parameters, so the textures/numbers are exposed once in the master and passed in. That is why the master has many parameter nodes.
* **Shared wrap samplers on every texture.** Each texture normally uses a sampler slot and a shader may only have 16; with `Shared: Wrap` the layers + mask + noise + detail + macro (up to 24 samples) never run out.
* **ORMH packing.** One texture for AO/roughness/metal/height instead of four: fewer samples, and the height rides along for the edge blending.
* **Base layer has no height parameters.** Only the layer being *revealed* needs height; adding unused parameters would be confusing, so they do not exist.
* **"Black adds" for vertex paint** matches the screenshot in the assignment and avoids a Fill step on a fresh mesh.
* **Static switches instead of dynamic toggles** so that switching a feature off removes its code *and its texture samples*.
* **Everything that has a range has a slider range** set on the parameter, so the Material Instance editor shows sensible sliders.
* **White tints, coloured placeholders.** If the tints carried the layer colours, every real texture you assigned would be darkened by them. Now the *placeholder texture* of an empty layer carries the colour and the tint is a neutral multiplier.
* **One breakup texture, three noises.** R, G and B of the breakup texture feed wear, dirt, and scratches + vertex paint, so the edges of the different effects do not share identical blobs (a greyscale texture still works - it just repeats one noise).
* **Invert is a blend, not a switch.** `lerp(mask, 1 - mask, Invert)`: dragging the slider to 0.5 flattens the mask instead of folding it.
* **"Extra" groups.** Macro, instance variation, wetness, emissive, opacity and vertex layers 2-3 are labelled *extra* in the instance editor: not needed for the assignment, there when you want them. Switched off they cost nothing.
* **Preview switch on a parent instance.** `Mask Uses Tiling UV` only exists so the demo cubes (one UV set) can show a mask; it lives in `MI_Demo_Base`, never in your own instances.

## 10. Extending it

* **A fourth vertex layer / more mask channels:** add layer rows in `LAYERS`, a call of `layer(...)`/`reveal(...)`/`blend(...)` in `build_surface_master()` - the pattern repeats.
* **Triplanar / world-aligned projection or parallax:** replace `tiling_uv` (section 1 of the master) with a different UV source; layers only need a float2 UV.
* **Different mask packing:** the four mask channels are split in section 2; swap channels there (one-node change) or add channel-select parameters.
* **Run the tests** after any change: `python3 Dev/run_tests.py` ([Dev/README.md](../Dev/README.md)).
