# traymold — parametric leather wet-mold geometry

Deterministic CadQuery core. No web framework, no UI; those come later and are
deliberately not started yet.

## The rule this package exists to enforce

```
female_base_profile = offset(male_base_profile, forming_gap)
```

`male_base_profile` is the 2D profile **before** any of the male's 3D edge
treatments. The finished male solid is never offset, and no male fillet or blend
is an input to the female cavity. See `docs/architecture.md` §2.

Three concepts are kept apart everywhere — schema, code and tests:

| concept | lives in |
|---|---|
| tray / profile geometry | `params.tray.profile`, `params.tray.depth` |
| forming gap | `params.leather`, `params.fit` → `derive.forming_gap` |
| 3D edge treatments | `params.mold.*_blend` |

## Quality modes

`preview` and `export` describe the same geometry — same base profile, same
forming gap, same treatment semantics, same correctness protections. They differ
only in loft section density and tessellation tolerance.

| | export | preview | 
|---|---|---|
| deviation vs the reference STEP | ≤ 4.2 µm | ≤ 29.9 µm |
| build, both parts (median of 5) | 5.43 s | 2.51 s |

## Usage

```bash
python3 -m traymold.cli presets
python3 -m traymold.cli derive  --preset ref-4x7
python3 -m traymold.cli validate --preset ref-4x7
python3 -m traymold.cli build   --preset ref-4x7 -o out
python3 -m traymold.cli build   --preset ref-4x7 --quality preview -o out
python3 -m traymold.cli schema > schema.json
```

```python
import traymold
result = traymold.build(traymold.PRESETS["ref-4x7"])
result.male, result.female        # cq.Solid
result.male_profile, result.female_profile
```

## Tests

```bash
python3 -m pytest packages/tray-core/tests -q          # everything
python3 -m pytest packages/tray-core/tests -q -m "not slow"   # skip STEP comparison
```

`test_dependency_boundary.py` is the load-bearing suite: it asserts the rule
above and that no edge treatment, plate dimension or manufacturing feature can
reach the female base profile.

## Reference evidence

```bash
python3 tools/reference_probe/verify_offset.py     # the offset relationship
python3 tools/reference_probe/draft_analysis.py    # what draft holds constant
python3 tools/reference_probe/benchmark.py 5       # build timings
```
