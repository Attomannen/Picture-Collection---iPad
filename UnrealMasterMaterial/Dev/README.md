# Dev - offline verification harness

You do **not** need anything in this folder to use the material. It exists because the generator could not be run inside
Unreal Editor where it was written, so it was checked offline instead.

```
python3 Dev/run_tests.py             # 82 tests, ~45 s, plain Python 3.8+ (Pillow optional)
python3 Dev/generate_param_docs.py   # regenerates Docs/03_Parameter_Reference.md from the script
python3 Dev/estimate_cost.py         # rough per-pixel cost of a few configurations
python3 Dev/check_docs.py            # links resolve and every parameter name in the docs exists
python3 Dev/render_preview.py        # approximate pictures of the demo instances -> Docs/img (needs Pillow, ~2 minutes)
```

| File | Purpose |
|---|---|
| `ue_api_facts.json` | **Data only**, extracted from Epic's auto-generated UE 5.6 Python stub (class property names/types, enum members, function signatures). |
| `extract_ue_api_facts.py` | How that JSON was produced (reads the stub as text, never imports it). |
| `mock_unreal.py` | A strict fake `unreal` module. Property names, enums and call signatures are validated against the JSON; `connect_material_expressions` returns `False` for unknown pins like the engine; assets, textures (PNG decoded and CRC-checked), instances. |
| `graph_eval.py` | Interpreter: "compiles" the generated graph (dimension errors, missing inputs, sampler-type vs texture compression, static-switch pruning, function calls) and evaluates it for one pixel. Also a rough ALU estimator. |
| `run_tests.py` | The tests (see below). |
| `render_preview.py` | Evaluates the master for every pixel of a flat card (real demo PNG data, painted vertex colours, a tiny shading model) and writes `Docs/img/*.png`. An *approximation* for catching ugly numbers and illustrating the docs - not an Unreal render. |
| `check_docs.py`, `generate_param_docs.py`, `estimate_cost.py` | Docs hygiene, the generated parameter reference, a rough cost proxy. |

## What the tests prove (and what they do not)

**They check**

* the generator runs end-to-end in **function mode** and **inline mode**, and numerically gives identical results in both (80 random scenarios);
* the graph **compiles** in 60+ random static-switch permutations (no float2/float3 mixing, no missing inputs, sampler types match the placeholder textures);
* **behaviour**: an untouched mesh shows only the base layer; mask R/G/B/A, vertex R/G/B/alpha, invert, intensity, softness, height influence, breakup, layer order, UV pipeline (tiling, rotation, offset, swap), detail-normal blend and fade, macro, wetness, emissive, opacity, debug views, decal master;
* **invariants**: reveal weight is 0 at mask 0 and 1 at mask 1 for random heights/softness/breakup and monotonic; no NaN/INF at slider extremes; normals stay unit length;
* **structure**: one node per parameter, groups and priorities as in the table, all textures use the shared sampler, disabled layers are really not compiled (texture-sample budget: 15 default, 24 everything), no dead nodes, assets saved;
* **robustness**: no `get_material_expression_input_names`, no named single-channel texture outputs, function-call failure (-> inline fallback), failing node deletion, re-running keeps user edits;
* the **review findings** (two independent reviews, one of the engine API usage and one of the shading logic against the brief) each have a test: layer rotation turns the normal, tooltips are complete, tints default to white and empty layers show their own colour, the three breakup channels, invert as a blend,
  instance variation (range, independence, origin, seed, per-instance), no no-op scratch blends, the demo parent instance, the demo crates really differ, the tools (`pack_channels.py`, `fix_texture_settings.py`);
* **engine quirks emulated by the mock**: setters that return False although they worked (Epic UE-291403), texture assignment re-deriving the sampler type, struct constructors checked against the stub (`Vector4f()` takes no arguments, `preview_value` may be Vector4), a missing `set_material_function`, a Vertex Color node without the alpha output.

**They cannot prove** that Unreal accepts the graph: the *pin and output names* in `mock_unreal.py` (`PINS`) come from engine knowledge, not from the engine.
The generator resolves input pins at run time with `get_material_expression_input_names` (so input names are the engine's own) and addresses the main output of nodes by position (`""`),
which removes most of that risk. The remaining unverified assumptions, each with an automatic fallback: the named alpha output `A` of texture samples (fallback: a ComponentMask on `RGBA`),
the `A` output of the Vertex Color node (fallback: the "alpha dirt" bonus is switched off), and the behaviour of Material Function call nodes (fallback: assign the property, then expand everything inline).
Also unproven offline: Large World Coordinate type handling of `WorldPosition` / `ObjectPositionWS` (only used when `Macro Uses World Space` or `Use Instance Variation` is on), and the real shader instruction count.
**The first run in the editor is the real test** - which is why `Docs/08_Build_It_By_Hand.md` exists.

## Regenerating the API facts (optional)

```
pip download unreal-stub==0.3 --no-deps -d /tmp/unreal_stub_dl
python3 -c "import zipfile,glob; zipfile.ZipFile(glob.glob('/tmp/unreal_stub_dl/*.whl')[0]).extractall('/tmp/unreal_stub_dl/x')"
python3 -I Dev/extract_ue_api_facts.py /tmp/unreal_stub_dl/x/unreal/unreal.py Dev/ue_api_facts.json
```
