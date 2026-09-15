# print_study

The measurements behind [`docs/material-optimisation.md`](../../docs/material-optimisation.md),
and a prototype of the 3MF export that document proposes.

```bash
python3 tools/print_study/study.py                 # every table, ~3 min
python3 tools/print_study/study.py baseline bug    # or one section at a time
python3 tools/print_study/threemf_prototype.py out # writes out/tray-mold.3mf
```

| | |
|---|---|
| `material.py` | what a solid costs in filament: shell per face orientation, plus infill on what is left. Also the sandwich-section stiffness model |
| `study.py` | `baseline`, `sections`, `levers`, `outline`, `regions`, `ledger`, `bug` |
| `threemf_prototype.py` | a PrusaSlicer/Orca-readable project 3MF carrying modifier volumes |

Nothing here is imported by `traymold`, the API or the frontend. `study.py`
stands down `E-MOLD-040` for its `levers` section, because whether that rule
should hold is one of the things being measured; it is stood down in one named
function and nowhere else.
