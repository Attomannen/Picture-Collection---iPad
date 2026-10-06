# 08 - Build a minimal version by hand (learning path and fallback)

The generated master has about 175 parameters. **Everything the assignment requires fits in about 40 nodes.** This page builds that minimal master
yourself, in the Material Editor, with the same names and the same maths as the full one - good for understanding it, for explaining it to a teacher, or as
a fallback if the script cannot run. Time: about 45 minutes.

**What you will build** `M_Master_Min`

```
 UV0 (tiling) ---> Base layer  (albedo, normal, ORMH)  --+
                   Wear layer  (albedo, normal, ORMH)  --+--> blended by weight_wear  --+
 UV1 (unique) ---> RGB mask: R = wear, G = dirt        --+                              |
                   Dirt = flat colour overlay by mask G --------------------------------+--> Base Color / Roughness / Metallic / Normal
 Vertex colour R (paint black) ---> Vertex layer 1 (albedo, normal, ORMH) blended by weight_vertex (height-aware)
```

**Material Editor basics**

* Create: Content Browser > right-click > **Material**, name it `M_Master_Min`, double-click.
* Add a node: right-click in the graph and search by name - or **hold a key and left-click** on empty space:
  `S` scalar parameter, `V` vector parameter, `T` texture sample, `U` texture coordinates, `L` lerp, `M` multiply, `A` add, `D` divide, `O` one-minus, `N` normalize, `1` / `2` / `3` constant (1 / 2 / 3 values).
* Make something a parameter: right-click the node > **Convert to Parameter**, then type the *Parameter Name* and *Group* in the Details panel.
* Texture sample nodes: pick the texture in **Details > Texture** and set **Sampler Type** to match (Color / Normal / Masks) - and set **Sampler Source = Shared: Wrap** so you never hit the 16-sampler limit.
* Pin colours: the `Mask` node of a RGB texture gives white (RGB) and R, G, B, A pins; use the single-channel pins directly.
* Apply and Save often (top-left).

---

## Part A - UV sets

1. **TextureCoordinate** node, *Coordinate Index* 0 -> this is the **tiling UV**.
2. Scalar parameter **`Tiling`** (default 1). **Multiply** (UV0 x `Tiling`) -> call this *tilingUV*.
3. Another **TextureCoordinate**, *Coordinate Index* **1** -> *uniqueUV* (for the RGB mask).

## Part B - the three layers' textures (Base, Wear, Vertex 1)

For **each** layer `L` in {Base, Wear, Vertex 1} (copy-paste the group of nodes):

4. **Texture Sample Parameter 2D** `L Albedo` (Sampler Type *Color*), UVs = *tilingUV*.
5. **Texture Sample Parameter 2D** `L Normal Map` (Sampler Type *Normal*), UVs = *tilingUV*.
6. **Texture Sample Parameter 2D** `L ORMH Map` (Sampler Type *Masks*), UVs = *tilingUV*. Its pins give **R = AO, G = Roughness, B = Metallic, A = Height**.
7. Vector parameter `L Tint` (default white) and **Multiply** (`L Albedo` RGB x `L Tint`) -> *colour L*.

Import settings for the textures: [02 section 1](02_Textures_and_Masks.md#1-texture-roles-and-import-settings).

## Part C - the RGB mask

8. **Texture Sample Parameter 2D** `Mask Texture` (Sampler Type *Masks*), UVs = *uniqueUV*. Use its **R** pin as *mask wear*, **G** pin as *mask dirt*, **A** pin as *baked AO*.

## Part D - the reveal weight (the heart of it)

The weight turns a soft mask into a crisp, height-driven blend. Build it **once as a Material Function** and reuse it for wear and vertex paint:

* Content Browser > right-click > *Materials & Textures* > **Material Function**, name it `MF_RevealWeight`.
* Add four **Function Input** nodes (right-click > search *Function Input*): `Mask`, `Height`, `HeightInfluence`, `Softness` (type *Scalar* each; give them *Preview Values* 0.5, 0.5, 0.5, 0.1). One **Function Output** named `Weight`.
* Wire these nodes:

```
 a  = Subtract( Height , 0.5 )                  (set the B constant to 0.5)
 b  = Multiply( a , HeightInfluence )
 T  = Saturate( Subtract( 0.5 , b ) )           (set the A constant to 0.5; Saturate node)
 W2 = Multiply( Max( Softness , 0.001 ) , 2 )   (Max with B = 0.001, then x 2)
 n  = Subtract( Multiply( Mask , Add( W2 , 1 ) ) , T )
 Weight = Saturate( Divide( n , W2 ) )          -> Function Output
```

What it means (full explanation in [01 section 4](01_How_It_Works.md#4-height-aware-blending-the-important-trick)): the *mask* is a water level, the *height* is the terrain,
`Softness` is how wide the shoreline is, `HeightInfluence` how much the terrain matters. Mask 0 -> weight 0, mask 1 -> weight 1, always.

Save the function. Add its parameters to your master by calling it (next steps).

## Part E - wear (RGB mask R) and dirt (G)

9. Drag **`MF_RevealWeight`** into the master. Inputs: `Mask` = *mask wear*, `Height` = `Wear ORMH Map` **A** pin, `HeightInfluence` = scalar param **`Wear Height Influence`** (0.5), `Softness` = scalar param **`Wear Softness`** (0.08).
   Output = *weight wear*.
10. **Lerp** for colour: A = *colour Base*, B = *colour Wear*, Alpha = *weight wear* -> *colour 1*.
11. **Lerp** roughness: A = `Base ORMH Map` **G**, B = `Wear ORMH Map` **G**, Alpha = *weight wear* -> *rough 1*. Same for metallic (**B** pins) and AO (**R** pins).
12. **Lerp** normals: A = `Base Normal Map` RGB, B = `Wear Normal Map` RGB, Alpha = *weight wear* -> **Normalize** -> *normal 1*.
13. **Dirt** (simple version): vector parameter `Dirt Color` (dark brown), scalar `Dirt Intensity` (1), scalar `Dirt Roughness` (0.9).
    *weight dirt* = **Saturate**( *mask dirt* x `Dirt Intensity` ).
    **Lerp**(A = *colour 1*, B = `Dirt Color`, Alpha = *weight dirt*) -> *colour 2*; **Lerp**(*rough 1*, `Dirt Roughness`, *weight dirt*) -> *rough 2*.
    (For a textured dirt layer repeat Part B for "Dirt" and blend it with *weight dirt* exactly like the wear layer.)

## Part F - vertex painting (VG)

14. **Vertex Color** node (right-click > search *Vertex Color*). Take its **R** pin.
    An unpainted mesh is white (1); you paint **black** (0) to add the layer, so *paint* = **OneMinus**(R).
15. Drag **`MF_RevealWeight`** again: `Mask` = *paint*, `Height` = `Vertex 1 ORMH Map` **A**, `HeightInfluence` = param **`Vertex 1 Height Influence`** (0.7), `Softness` = param **`Vertex 1 Softness`** (0.06). Output = *weight vertex*.
16. **Lerp** colour: A = *colour 2*, B = *colour Vertex 1*, Alpha = *weight vertex* -> *colour 3*. Same for roughness (-> *rough 3*), metallic, AO and normals (Lerp then Normalize) with the Vertex 1 ORMH/Normal pins.

   *(This is precisely the assignment's VG requirement: a second material that you paint with the Red channel of the vertex colour.)*

## Part G - outputs

17. *colour 3* -> **Base Color**.
18. *rough 3* -> **Roughness**; metallic result -> **Metallic**; *normal* result -> **Normal**; AO result x *baked AO* (Mask **A**) -> **Ambient Occlusion**.
19. Apply, Save. Create an instance (right-click > *Create Material Instance*), assign your textures, tweak the parameters.

Check in the viewport with the Lit view; use **Buffer Visualization > Base Color** to see the albedo only.

---

## What the full master adds on top

| In the hand-built version | In `M_Master_Surface` |
|---|---|
| Wear, simple dirt, vertex layer 1 | + textured dirt layer, scratches, vertex layers 2 and 3, vertex alpha dirt |
| Height from the layer's ORMH alpha | + **breakup noise** (R wear, G dirt, B scratches and vertex paint) to erode edges, height contrast/offset, softness per effect, edge rim colour, Invert as a blend |
| Fixed UV tiling | + per-layer tiling, rotation (the normal map is rotated with the UVs), offset, `Swap UV Channels`, debug views |
| Tint only | + brightness, saturation, roughness min/max, metallic scale, AO strength, normal strength per layer |
| - | + detail normal, macro variation, instance variation, wetness, global grade, emissive, opacity mask |
| - | + static switches that strip unused layers (and their texture samples) from the shader |
| - | + a separate **mesh decal** master |
