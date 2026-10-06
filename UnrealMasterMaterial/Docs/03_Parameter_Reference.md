# Parameter reference

> **Generated file** - produced by `Dev/generate_param_docs.py` from the parameter table in `Scripts/build_master_material.py`, so it always matches the material. Do not edit by hand.

The Material Instance editor lists parameters in **groups** (numbered so they sort in the order below) and, inside a group, by sort priority (the order of the tables). Hover a parameter in the editor to see the same description that is printed here. Groups marked **extra** are not needed for the assignment - ignore them until you want them.

`M_Master_Surface` has **175 parameters** (115 scalars, 16 colours, 24 textures, 20 static switches).

**Layer parameter sets.** The six layers (Base, Wear, Dirt, Vertex 1-3) share the same set of parameters (textures, tint, then the layer's own effect knobs, then brightness, saturation, tiling, rotation, offset, normal strength, roughness range, metallic, AO strength, height contrast/offset - the Base layer has no height parameters because its height is never used). They are written out in full for each layer so you can search for a parameter by name. All tints default to **white**: a texture you assign shows exactly as authored; an empty layer shows a flat placeholder colour so the stack is visible before you have textures.

## M_Master_Surface

#### 00 Features (static switches)

| Switch | Default | Texture samples when ON | What it does |
|---|---|---|---|
| `Use Wear Layer` | On | +3 | Reveal the Wear layer (rust, bare metal, brick ...) where mask R says so. OFF removes the layer and its 3 texture samples from the shader. |
| `Use Dirt Layer` | On | +3 | Blend the Dirt layer where mask G says so. OFF removes its 3 texture samples. |
| `Use Scratches` | On | - | Apply scratches where mask B says so (changes colour, roughness and metallic). |
| `Use Baked AO` | On | - | Multiply the baked ambient occlusion stored in the ALPHA channel of the RGB mask. Turn OFF if your mask alpha is not AO. |
| `Use Mask Breakup` | On | +1 | Erode the soft, low-resolution mask edges with the tiling Breakup texture so wear and dirt stay crisp up close. |
| `Use Vertex Layer 1` | On | +3 | Vertex colour RED paints Vertex Layer 1 over everything below it (the assignment's vertex painting). |
| `Use Vertex Layer 2` | Off | +3 | Vertex colour GREEN paints Vertex Layer 2. |
| `Use Vertex Layer 3` | Off | +3 | Vertex colour BLUE paints Vertex Layer 3. |
| `Use Vertex Alpha Dirt` | Off | - | Vertex colour ALPHA paints extra dirt on top of the mask-driven dirt (needs Use Dirt Layer). |
| `Vertex Paint White Adds` | Off | - | OFF (default): paint BLACK to add a layer (an unpainted mesh is white). ON: paint WHITE - fill the mesh with black first (Mesh Paint > Fill). |
| `Use Detail Normal` | On | +1 | Add the tiling detail normal on top of the layer normals (it fades out with distance). |
| `Use Macro Variation` | Off | +1 | Multiply a very large, low-contrast noise over colour and roughness to hide tiling repetition. |
| `Macro Uses World Space` | Off | - | Project the macro noise top-down in world X/Y so neighbouring props differ. OFF uses the tiling UVs (better on walls). |
| `Use Instance Variation` | Off | - | Random brightness and saturation per object (from its position, and per instance on HISM or foliage) so copies do not look identical. |
| `Use Wetness` | Off | - | Enable the Wetness parameters (darker albedo, lower roughness). |
| `Use Emissive` | Off | +1 | Add an emissive texture (signs, lights, screens) on the unique UV set. |
| `Use Opacity Mask` | Off | +1 | Cut-out transparency from the Opacity Texture. Also needs Blend Mode = Masked: Details > Base Property Overrides in your instance. |
| `Swap UV Channels` | Off | - | OFF: tiling = UV0, unique mask = UV1. ON: tiling = UV1, unique mask = UV0. Use it if your mesh has the sets the other way round (debug 13/14 shows which). |
| `Debug View` | Off | -3 | Show a mask, weight or UV as an unlit colour instead of the material. Pick it with Debug Mode. |

#### 01 Global

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Global Tiling` | Scalar | 1 | 0.05 .. 16 | Multiplies the tiling of every tiling texture (layers, breakup, detail, macro). Your texel-density knob. |
| `Global Tint` | Colour | (1, 1, 1) |  | Colour multiplied over the final albedo (after all layers). |
| `Global Brightness` | Scalar | 1 | 0 .. 3 | Final albedo multiplier. |
| `Global Saturation` | Scalar | 1 | 0 .. 2 | Final saturation: 0 = greyscale, 1 = unchanged. |
| `Global Roughness Offset` | Scalar | 0 | -1 .. 1 | Added to the final roughness (negative = glossier). |
| `Global AO Strength` | Scalar | 1 | 0 .. 1 | Strength of the combined ambient occlusion. |

#### 02 RGB Mask and Breakup

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Mask Texture` | Texture | black mask (no wear/dirt/scratches), AO 1 | Masks (no sRGB) | RGBA mask on the UNIQUE UV set: R wear, G dirt, B scratches, A baked AO. Import with compression 'Masks (no sRGB)'. |
| `Mask AO Strength` | Scalar | 1 | 0 .. 1 | How strongly the baked AO (mask alpha) darkens the surface. |
| `Breakup Texture` | Texture | 50% grey (neutral) | Masks (no sRGB) | Tileable noise: R = wear edges, G = dirt edges, B = scratch and vertex-paint edges (greyscale is fine). 50% grey = neutral. Import as 'Masks (no sRGB)'. |
| `Breakup Tiling` | Scalar | 2 | 0.1 .. 32 | Tiling of the breakup noise on the tiling UVs. |

#### 03 Base Layer

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Base Albedo` | Texture | flat blue-grey placeholder | Color (sRGB) | Tileable colour map, imported as sRGB colour. Empty = a flat placeholder colour, so the layer is visible before you have textures. |
| `Base Normal Map` | Texture | flat normal | Normalmap | Tileable normal map, DirectX/Unreal style (green = down). Import with compression 'Normalmap'. Lighting inverted? Tick Flip Green Channel on the texture. |
| `Base ORMH Map` | Texture | flat ORMH (AO 1, rough 0.5, metal 0, height 0.5) | Masks (no sRGB) | Packed: R = AO, G = roughness, B = metallic, A = height (drives the blend edges). Import with compression 'Masks (no sRGB)'. |
| `Base Tint` | Colour | (1, 1, 1) |  | Multiplies the albedo. White = texture unchanged. The main art-direction knob: recolour paint, rust or dirt. |
| `Base Brightness` | Scalar | 1 | 0 .. 3 | Albedo multiplier (applied after the tint). |
| `Base Saturation` | Scalar | 1 | 0 .. 2 | 0 = greyscale, 1 = as authored, 2 = double saturation. |
| `Base Tiling` | Scalar | 1 | 0.05 .. 16 | UV scale of this layer, on top of Global Tiling. Different values per layer hide repetition. |
| `Base Rotation` | Scalar | 0 | 0 .. 360 | UV rotation in degrees about the tile centre (the normal map is rotated with it). |
| `Base Offset` | Colour | (0, 0, 0) |  | UV shift: R = U, G = V. Type the numbers instead of using the colour picker. |
| `Base Normal Strength` | Scalar | 1 | 0 .. 3 | 0 = flat, 1 = as authored, above 1 = exaggerated bumps. |
| `Base Roughness Min` | Scalar | 0 | 0 .. 1 | Roughness where the ORMH green channel is 0 (together with Max it remaps the roughness range). |
| `Base Roughness Max` | Scalar | 1 | 0 .. 1 | Roughness where the ORMH green channel is 1. |
| `Base Metallic` | Scalar | 1 | 0 .. 1 | Multiplier on the ORMH blue channel (metallic). 0 forces a non-metal. |
| `Base AO Strength` | Scalar | 1 | 0 .. 1 | How much the ORMH red channel (AO) darkens. |

#### 04 Wear Layer (mask R)

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Wear Albedo` | Texture | flat rust-orange placeholder | Color (sRGB) | Tileable colour map, imported as sRGB colour. Empty = a flat placeholder colour, so the layer is visible before you have textures. |
| `Wear Normal Map` | Texture | flat normal | Normalmap | Tileable normal map, DirectX/Unreal style (green = down). Import with compression 'Normalmap'. Lighting inverted? Tick Flip Green Channel on the texture. |
| `Wear ORMH Map` | Texture | flat ORMH (AO 1, rough 0.5, metal 0, height 0.5) | Masks (no sRGB) | Packed: R = AO, G = roughness, B = metallic, A = height (drives the blend edges). Import with compression 'Masks (no sRGB)'. |
| `Wear Tint` | Colour | (1, 1, 1) |  | Multiplies the albedo. White = texture unchanged. The main art-direction knob: recolour paint, rust or dirt. |
| `Wear Intensity` | Scalar | 1 | 0 .. 2 | Scales mask R before the reveal. Above 1 the worn area grows, below 1 it shrinks, 0 = no wear. |
| `Wear Softness` | Scalar | 0.08 | 0.005 .. 0.5 | Edge width. 0.005 = razor-sharp chipping, 0.08 = default, 0.5 = very soft fade. |
| `Wear Height Influence` | Scalar | 0.5 | -1 .. 1 | How much the Wear layer's height map decides where wear shows first. 0 = ignore height, negative flips it. |
| `Wear Breakup` | Scalar | 0.4 | 0 .. 1 | How much the Breakup texture (R) erodes the wear edge. 0 = clean mask edge. |
| `Wear Edge Color` | Colour | (0.06, 0.03, 0.02) |  | Colour of the thin rim where the top coat meets the exposed layer. |
| `Wear Edge Strength` | Scalar | 0.5 | 0 .. 1 | Visibility of that rim (0 = off). |
| `Wear Invert` | Scalar | 0 | 0 .. 1 | 0 = use mask R as painted, 1 = invert it. |
| `Wear Brightness` | Scalar | 1 | 0 .. 3 | Albedo multiplier (applied after the tint). |
| `Wear Saturation` | Scalar | 1 | 0 .. 2 | 0 = greyscale, 1 = as authored, 2 = double saturation. |
| `Wear Tiling` | Scalar | 1 | 0.05 .. 16 | UV scale of this layer, on top of Global Tiling. Different values per layer hide repetition. |
| `Wear Rotation` | Scalar | 0 | 0 .. 360 | UV rotation in degrees about the tile centre (the normal map is rotated with it). |
| `Wear Offset` | Colour | (0, 0, 0) |  | UV shift: R = U, G = V. Type the numbers instead of using the colour picker. |
| `Wear Normal Strength` | Scalar | 1 | 0 .. 3 | 0 = flat, 1 = as authored, above 1 = exaggerated bumps. |
| `Wear Roughness Min` | Scalar | 0 | 0 .. 1 | Roughness where the ORMH green channel is 0 (together with Max it remaps the roughness range). |
| `Wear Roughness Max` | Scalar | 1 | 0 .. 1 | Roughness where the ORMH green channel is 1. |
| `Wear Metallic` | Scalar | 1 | 0 .. 1 | Multiplier on the ORMH blue channel (metallic). 0 forces a non-metal. |
| `Wear AO Strength` | Scalar | 1 | 0 .. 1 | How much the ORMH red channel (AO) darkens. |
| `Wear Height Contrast` | Scalar | 1 | 0 .. 4 | Contrast of the ORMH alpha (height) used for the blend edges. |
| `Wear Height Offset` | Scalar | 0 | -1 .. 1 | Shifts the height up or down (which areas count as 'high'). |

#### 05 Dirt Layer (mask G)

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Dirt Albedo` | Texture | flat dark-brown placeholder | Color (sRGB) | Tileable colour map, imported as sRGB colour. Empty = a flat placeholder colour, so the layer is visible before you have textures. |
| `Dirt Normal Map` | Texture | flat normal | Normalmap | Tileable normal map, DirectX/Unreal style (green = down). Import with compression 'Normalmap'. Lighting inverted? Tick Flip Green Channel on the texture. |
| `Dirt ORMH Map` | Texture | flat ORMH (AO 1, rough 0.5, metal 0, height 0.5) | Masks (no sRGB) | Packed: R = AO, G = roughness, B = metallic, A = height (drives the blend edges). Import with compression 'Masks (no sRGB)'. |
| `Dirt Tint` | Colour | (1, 1, 1) |  | Multiplies the albedo. White = texture unchanged. The main art-direction knob: recolour paint, rust or dirt. |
| `Dirt Intensity` | Scalar | 1 | 0 .. 2 | Scales mask G before the reveal. Above 1 more dirt, below 1 less, 0 = none. |
| `Dirt Softness` | Scalar | 0.2 | 0.005 .. 0.5 | Edge width of the dirt. 0.005 = hard stains, 0.5 = very soft. |
| `Dirt Height Influence` | Scalar | 0.3 | -1 .. 1 | How much the Dirt layer's height map decides where dirt shows first. 0 = ignore height. |
| `Dirt Breakup` | Scalar | 0.4 | 0 .. 1 | How much the Breakup texture (G) erodes the dirt edge. |
| `Dirt AO Boost` | Scalar | 0.5 | 0 .. 1 | Adds extra dirt in crevices using the baked AO (mask alpha). 0 = off. |
| `Dirt Invert` | Scalar | 0 | 0 .. 1 | 0 = use mask G as painted, 1 = invert it. |
| `Dirt Brightness` | Scalar | 1 | 0 .. 3 | Albedo multiplier (applied after the tint). |
| `Dirt Saturation` | Scalar | 1 | 0 .. 2 | 0 = greyscale, 1 = as authored, 2 = double saturation. |
| `Dirt Tiling` | Scalar | 1 | 0.05 .. 16 | UV scale of this layer, on top of Global Tiling. Different values per layer hide repetition. |
| `Dirt Rotation` | Scalar | 0 | 0 .. 360 | UV rotation in degrees about the tile centre (the normal map is rotated with it). |
| `Dirt Offset` | Colour | (0, 0, 0) |  | UV shift: R = U, G = V. Type the numbers instead of using the colour picker. |
| `Dirt Normal Strength` | Scalar | 1 | 0 .. 3 | 0 = flat, 1 = as authored, above 1 = exaggerated bumps. |
| `Dirt Roughness Min` | Scalar | 0 | 0 .. 1 | Roughness where the ORMH green channel is 0 (together with Max it remaps the roughness range). |
| `Dirt Roughness Max` | Scalar | 1 | 0 .. 1 | Roughness where the ORMH green channel is 1. |
| `Dirt Metallic` | Scalar | 1 | 0 .. 1 | Multiplier on the ORMH blue channel (metallic). 0 forces a non-metal. |
| `Dirt AO Strength` | Scalar | 1 | 0 .. 1 | How much the ORMH red channel (AO) darkens. |
| `Dirt Height Contrast` | Scalar | 1 | 0 .. 4 | Contrast of the ORMH alpha (height) used for the blend edges. |
| `Dirt Height Offset` | Scalar | 0 | -1 .. 1 | Shifts the height up or down (which areas count as 'high'). |

#### 06 Scratches (mask B)

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Scratch Intensity` | Scalar | 1 | 0 .. 2 | Scales mask B before the reveal. |
| `Scratch Softness` | Scalar | 0.05 | 0.005 .. 0.5 | Edge width of the scratch lines. |
| `Scratch Breakup` | Scalar | 0.2 | 0 .. 1 | How much the Breakup texture (B) erodes the scratch lines. |
| `Scratch Color` | Colour | (0.78, 0.78, 0.8) |  | Colour of the exposed material inside a scratch. |
| `Scratch Roughness` | Scalar | 0.35 | 0 .. 1 | Roughness inside scratches. |
| `Scratch Metallic` | Scalar | 1 | 0 .. 1 | Metallic inside scratches (1 = bare metal showing through the paint). |
| `Scratch Invert` | Scalar | 0 | 0 .. 1 | 0 = use mask B as painted, 1 = invert it. |

#### 07 Vertex Paint

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Vertex Alpha Dirt Strength` | Scalar | 1 | 0 .. 1 | How much dirt painted into vertex ALPHA adds (needs Use Vertex Alpha Dirt). |

#### 08 Vertex Layer 1 (paint R)

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Vertex 1 Albedo` | Texture | flat brick-red placeholder | Color (sRGB) | Tileable colour map, imported as sRGB colour. Empty = a flat placeholder colour, so the layer is visible before you have textures. |
| `Vertex 1 Normal Map` | Texture | flat normal | Normalmap | Tileable normal map, DirectX/Unreal style (green = down). Import with compression 'Normalmap'. Lighting inverted? Tick Flip Green Channel on the texture. |
| `Vertex 1 ORMH Map` | Texture | flat ORMH (AO 1, rough 0.5, metal 0, height 0.5) | Masks (no sRGB) | Packed: R = AO, G = roughness, B = metallic, A = height (drives the blend edges). Import with compression 'Masks (no sRGB)'. |
| `Vertex 1 Tint` | Colour | (1, 1, 1) |  | Multiplies the albedo. White = texture unchanged. The main art-direction knob: recolour paint, rust or dirt. |
| `Vertex 1 Softness` | Scalar | 0.1 | 0.005 .. 0.5 | Softness of the painted edge. Small = crisp and height-driven, large = a plain fade. |
| `Vertex 1 Height Influence` | Scalar | 0.5 | -1 .. 1 | How much this layer's height map shapes the painted edge. 0 = plain gradient. |
| `Vertex 1 Breakup` | Scalar | 0.3 | 0 .. 1 | How much the Breakup texture (B) erodes the painted edge. |
| `Vertex 1 Brightness` | Scalar | 1 | 0 .. 3 | Albedo multiplier (applied after the tint). |
| `Vertex 1 Saturation` | Scalar | 1 | 0 .. 2 | 0 = greyscale, 1 = as authored, 2 = double saturation. |
| `Vertex 1 Tiling` | Scalar | 1 | 0.05 .. 16 | UV scale of this layer, on top of Global Tiling. Different values per layer hide repetition. |
| `Vertex 1 Rotation` | Scalar | 0 | 0 .. 360 | UV rotation in degrees about the tile centre (the normal map is rotated with it). |
| `Vertex 1 Offset` | Colour | (0, 0, 0) |  | UV shift: R = U, G = V. Type the numbers instead of using the colour picker. |
| `Vertex 1 Normal Strength` | Scalar | 1 | 0 .. 3 | 0 = flat, 1 = as authored, above 1 = exaggerated bumps. |
| `Vertex 1 Roughness Min` | Scalar | 0 | 0 .. 1 | Roughness where the ORMH green channel is 0 (together with Max it remaps the roughness range). |
| `Vertex 1 Roughness Max` | Scalar | 1 | 0 .. 1 | Roughness where the ORMH green channel is 1. |
| `Vertex 1 Metallic` | Scalar | 1 | 0 .. 1 | Multiplier on the ORMH blue channel (metallic). 0 forces a non-metal. |
| `Vertex 1 AO Strength` | Scalar | 1 | 0 .. 1 | How much the ORMH red channel (AO) darkens. |
| `Vertex 1 Height Contrast` | Scalar | 1 | 0 .. 4 | Contrast of the ORMH alpha (height) used for the blend edges. |
| `Vertex 1 Height Offset` | Scalar | 0 | -1 .. 1 | Shifts the height up or down (which areas count as 'high'). |

#### 09 Vertex Layer 2 (paint G) - extra

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Vertex 2 Albedo` | Texture | flat moss-green placeholder | Color (sRGB) | Tileable colour map, imported as sRGB colour. Empty = a flat placeholder colour, so the layer is visible before you have textures. |
| `Vertex 2 Normal Map` | Texture | flat normal | Normalmap | Tileable normal map, DirectX/Unreal style (green = down). Import with compression 'Normalmap'. Lighting inverted? Tick Flip Green Channel on the texture. |
| `Vertex 2 ORMH Map` | Texture | flat ORMH (AO 1, rough 0.5, metal 0, height 0.5) | Masks (no sRGB) | Packed: R = AO, G = roughness, B = metallic, A = height (drives the blend edges). Import with compression 'Masks (no sRGB)'. |
| `Vertex 2 Tint` | Colour | (1, 1, 1) |  | Multiplies the albedo. White = texture unchanged. The main art-direction knob: recolour paint, rust or dirt. |
| `Vertex 2 Softness` | Scalar | 0.1 | 0.005 .. 0.5 | Softness of the painted edge. Small = crisp and height-driven, large = a plain fade. |
| `Vertex 2 Height Influence` | Scalar | 0.5 | -1 .. 1 | How much this layer's height map shapes the painted edge. 0 = plain gradient. |
| `Vertex 2 Breakup` | Scalar | 0.3 | 0 .. 1 | How much the Breakup texture (B) erodes the painted edge. |
| `Vertex 2 Brightness` | Scalar | 1 | 0 .. 3 | Albedo multiplier (applied after the tint). |
| `Vertex 2 Saturation` | Scalar | 1 | 0 .. 2 | 0 = greyscale, 1 = as authored, 2 = double saturation. |
| `Vertex 2 Tiling` | Scalar | 1 | 0.05 .. 16 | UV scale of this layer, on top of Global Tiling. Different values per layer hide repetition. |
| `Vertex 2 Rotation` | Scalar | 0 | 0 .. 360 | UV rotation in degrees about the tile centre (the normal map is rotated with it). |
| `Vertex 2 Offset` | Colour | (0, 0, 0) |  | UV shift: R = U, G = V. Type the numbers instead of using the colour picker. |
| `Vertex 2 Normal Strength` | Scalar | 1 | 0 .. 3 | 0 = flat, 1 = as authored, above 1 = exaggerated bumps. |
| `Vertex 2 Roughness Min` | Scalar | 0 | 0 .. 1 | Roughness where the ORMH green channel is 0 (together with Max it remaps the roughness range). |
| `Vertex 2 Roughness Max` | Scalar | 1 | 0 .. 1 | Roughness where the ORMH green channel is 1. |
| `Vertex 2 Metallic` | Scalar | 1 | 0 .. 1 | Multiplier on the ORMH blue channel (metallic). 0 forces a non-metal. |
| `Vertex 2 AO Strength` | Scalar | 1 | 0 .. 1 | How much the ORMH red channel (AO) darkens. |
| `Vertex 2 Height Contrast` | Scalar | 1 | 0 .. 4 | Contrast of the ORMH alpha (height) used for the blend edges. |
| `Vertex 2 Height Offset` | Scalar | 0 | -1 .. 1 | Shifts the height up or down (which areas count as 'high'). |

#### 10 Vertex Layer 3 (paint B) - extra

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Vertex 3 Albedo` | Texture | flat sand placeholder | Color (sRGB) | Tileable colour map, imported as sRGB colour. Empty = a flat placeholder colour, so the layer is visible before you have textures. |
| `Vertex 3 Normal Map` | Texture | flat normal | Normalmap | Tileable normal map, DirectX/Unreal style (green = down). Import with compression 'Normalmap'. Lighting inverted? Tick Flip Green Channel on the texture. |
| `Vertex 3 ORMH Map` | Texture | flat ORMH (AO 1, rough 0.5, metal 0, height 0.5) | Masks (no sRGB) | Packed: R = AO, G = roughness, B = metallic, A = height (drives the blend edges). Import with compression 'Masks (no sRGB)'. |
| `Vertex 3 Tint` | Colour | (1, 1, 1) |  | Multiplies the albedo. White = texture unchanged. The main art-direction knob: recolour paint, rust or dirt. |
| `Vertex 3 Softness` | Scalar | 0.1 | 0.005 .. 0.5 | Softness of the painted edge. Small = crisp and height-driven, large = a plain fade. |
| `Vertex 3 Height Influence` | Scalar | 0.5 | -1 .. 1 | How much this layer's height map shapes the painted edge. 0 = plain gradient. |
| `Vertex 3 Breakup` | Scalar | 0.3 | 0 .. 1 | How much the Breakup texture (B) erodes the painted edge. |
| `Vertex 3 Brightness` | Scalar | 1 | 0 .. 3 | Albedo multiplier (applied after the tint). |
| `Vertex 3 Saturation` | Scalar | 1 | 0 .. 2 | 0 = greyscale, 1 = as authored, 2 = double saturation. |
| `Vertex 3 Tiling` | Scalar | 1 | 0.05 .. 16 | UV scale of this layer, on top of Global Tiling. Different values per layer hide repetition. |
| `Vertex 3 Rotation` | Scalar | 0 | 0 .. 360 | UV rotation in degrees about the tile centre (the normal map is rotated with it). |
| `Vertex 3 Offset` | Colour | (0, 0, 0) |  | UV shift: R = U, G = V. Type the numbers instead of using the colour picker. |
| `Vertex 3 Normal Strength` | Scalar | 1 | 0 .. 3 | 0 = flat, 1 = as authored, above 1 = exaggerated bumps. |
| `Vertex 3 Roughness Min` | Scalar | 0 | 0 .. 1 | Roughness where the ORMH green channel is 0 (together with Max it remaps the roughness range). |
| `Vertex 3 Roughness Max` | Scalar | 1 | 0 .. 1 | Roughness where the ORMH green channel is 1. |
| `Vertex 3 Metallic` | Scalar | 1 | 0 .. 1 | Multiplier on the ORMH blue channel (metallic). 0 forces a non-metal. |
| `Vertex 3 AO Strength` | Scalar | 1 | 0 .. 1 | How much the ORMH red channel (AO) darkens. |
| `Vertex 3 Height Contrast` | Scalar | 1 | 0 .. 4 | Contrast of the ORMH alpha (height) used for the blend edges. |
| `Vertex 3 Height Offset` | Scalar | 0 | -1 .. 1 | Shifts the height up or down (which areas count as 'high'). |

#### 11 Detail Normal

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Detail Normal Texture` | Texture | flat normal | Normalmap | Fine tileable normal map layered over everything. Import with compression 'Normalmap'. |
| `Detail Normal Tiling` | Scalar | 8 | 0.1 .. 64 | Tiling of the detail normal on the tiling UVs. |
| `Detail Normal Intensity` | Scalar | 1 | 0 .. 3 | Strength of the detail normal. |
| `Detail Fade Start` | Scalar | 400 | 0 .. 5000 | Distance (cm) where the detail starts to fade out. |
| `Detail Fade End` | Scalar | 1500 | 1 .. 10000 | Distance (cm) where the detail is gone. |

#### 12 Macro Variation - extra

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Macro Texture` | Texture | 50% grey (neutral) | Masks (no sRGB) | Large-scale greyscale noise (R channel); 50% grey = no change. Import as 'Masks (no sRGB)'. |
| `Macro Tiling` | Scalar | 0.2 | 0.01 .. 4 | UV mode: tiles per tiling-UV unit. World mode: tiles per metre. |
| `Macro Intensity` | Scalar | 0.3 | 0 .. 1 | Brightness variation strength. |
| `Macro Roughness Variation` | Scalar | 0.2 | 0 .. 1 | Roughness variation strength. |

#### 13 Instance Variation - extra

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Variation Brightness` | Scalar | 0.15 | 0 .. 0.5 | Max random brightness change per object (0.15 = plus or minus 15%). |
| `Variation Saturation` | Scalar | 0.15 | 0 .. 0.5 | Max random saturation change per object. |
| `Variation Seed` | Scalar | 0 | 0 .. 100 | Re-rolls every object's random look at once, without moving the props. |

#### 14 Wetness - extra

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Wetness` | Scalar | 0 | 0 .. 1 | 0 = dry, 1 = soaked. |
| `Wetness Darken` | Scalar | 0.35 | 0 .. 1 | How much a soaked surface darkens. |
| `Wetness Roughness` | Scalar | 0.08 | 0 .. 1 | Roughness of a soaked surface. |

#### 15 Emissive - extra

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Emissive Texture` | Texture | flat black | Color (sRGB) | Emissive colour (sRGB) on the UNIQUE UV set. |
| `Emissive Color` | Colour | (1, 1, 1) |  | Tint multiplied onto the emissive texture. |
| `Emissive Intensity` | Scalar | 1 | 0 .. 50 | Emissive brightness multiplier. |

#### 16 Opacity Mask - extra

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Opacity Texture` | Texture | white (fully opaque) | Masks (no sRGB) | Opacity (R channel) for cut-outs such as fences or leaves. Import as 'Masks (no sRGB)'. |
| `Opacity Uses Tiling UV` | Scalar | 0 | 0 .. 1 | 0 = sample on the unique UV set, 1 = on the tiling UV set (values snap to 0 or 1). |

#### 17 Debug

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Debug Mode` | Scalar | 1 | 1 .. 16 | View shown by Debug View (1-16): 1-4 mask R G B A, 5-6 vertex RGB / alpha, 7-12 layer weights, 13-14 UV checks, 15 breakup, 16 normal. |

#### 99 Preview (demo only)

| Switch | Default | Texture samples when ON | What it does |
|---|---|---|---|
| `Mask Uses Tiling UV` | Off | - | PREVIEW ONLY: samples the RGB mask with the tiling UVs so the demo instances work on meshes with ONE UV set. Leave OFF on your own meshes. |

### Debug modes

Turn on **Debug View** (group 00) and set **Debug Mode** (group 17) to a number:

| Mode | Shows |
|---|---|
| 1 | Mask R (wear) |
| 2 | Mask G (dirt) |
| 3 | Mask B (scratches) |
| 4 | Mask A (baked AO) |
| 5 | Vertex colour RGB |
| 6 | Vertex colour alpha |
| 7 | Wear weight (after height + breakup) |
| 8 | Dirt weight |
| 9 | Scratch weight |
| 10 | Vertex layer 1 weight |
| 11 | Vertex layer 2 weight |
| 12 | Vertex layer 3 weight |
| 13 | Tiling UV checker (1 square = 1 tile) |
| 14 | Unique UV gradient (U=red, V=green) |
| 15 | Breakup noise |
| 16 | Final normal (n*0.5+0.5) |

## M_Master_MeshDecal

Material Domain **Deferred Decal**, Blend Mode **Translucent**, Decal Blend Mode **DBuffer Translucent Color, Normal, Roughness**. Put the decal mesh's UVs on the cells of your decal sheet; use *Decal UV Tiling/Offset* to move to another cell without re-UVing.

#### 01 Decal Sheet

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Decal Color Map` | Texture | flat white | Color (sRGB) | Decal sheet colour (sRGB). The ALPHA channel is the decal's opacity, so import the PNG with its alpha and pad the cells. |
| `Decal Normal Map` | Texture | flat normal | Normalmap | Decal sheet normal map. Import with compression 'Normalmap'. |
| `Decal ORM Map` | Texture | flat ORMH (AO 1, rough 0.5, metal 0, height 0.5) | Masks (no sRGB) | Decal sheet packed map: G = roughness, B = metallic (R and A unused). Import with compression 'Masks (no sRGB)'. |

#### 02 Decal UV

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Decal UV Tiling` | Scalar | 1 | 0.1 .. 8 | Scales the mesh UVs (1 = use the UVs as modelled). |
| `Decal UV Offset` | Colour | (0, 0, 0) |  | Shifts the UVs (R = U, G = V) - slide to another cell of the sheet. |

#### 03 Look

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Decal Tint` | Colour | (1, 1, 1) |  | Colour multiplied onto the decal. |
| `Decal Brightness` | Scalar | 1 | 0 .. 3 | Colour multiplier. |
| `Decal Saturation` | Scalar | 1 | 0 .. 2 | Colour saturation. |
| `Decal Opacity` | Scalar | 1 | 0 .. 1 | Overall opacity (fade the decal in/out). |
| `Decal Opacity Contrast` | Scalar | 1 | 0.1 .. 8 | Sharpens the alpha edge (>1 = crisper stickers / stencils). |
| `Decal Normal Strength` | Scalar | 1 | 0 .. 3 | Normal map strength. |
| `Decal Roughness Min` | Scalar | 0 | 0 .. 1 | Roughness at ORM.G = 0. |
| `Decal Roughness Max` | Scalar | 1 | 0 .. 1 | Roughness at ORM.G = 1. |
| `Decal Metallic` | Scalar | 1 | 0 .. 1 | Multiplier for the sheet's ORM blue channel (metallic). 1 = as authored, 0 = force non-metal. |

#### 04 Emissive

| Parameter | Type | Default | Range / import setting | What it does |
|---|---|---|---|---|
| `Decal Use Emissive` | Switch | Off |  | Make the decal glow with its own colour. Nothing glows? Set Decal Blend Mode = Translucent in the master's Details (see Docs/05). |
| `Decal Emissive Intensity` | Scalar | 1 | 0 .. 50 | Glow strength. |

