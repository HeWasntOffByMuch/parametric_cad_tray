# print_study

The measurements behind [`docs/material-optimisation.md`](../../docs/material-optimisation.md).

```bash
python3 tools/print_study/study.py                 # every table, ~3 min
python3 tools/print_study/study.py baseline bug    # or one section at a time
```

| | |
|---|---|
| `material.py` | what a solid costs in filament: shell per face orientation, plus infill on what is left. Also the sandwich-section stiffness model |
| `study.py` | `baseline`, `sections`, `levers`, `outline`, `regions`, `ledger`, `bug` |

The 3MF prototype that once lived here has been superseded by the shipped
writer, `traymold/threemf.py`, and the solver beside it, `traymold/printplan.py`.
`material.py` is the same model `printplan` now carries; it stays here because
the study prices geometry the product never builds - a relieved female, a
profile-following plate - which the core has no business knowing about.

Nothing here is imported by `traymold`, the API or the frontend. `study.py`
stands down `E-MOLD-040` for its `levers` section, because whether that rule
should hold is one of the things being measured; it is stood down in one named
function and nowhere else.
