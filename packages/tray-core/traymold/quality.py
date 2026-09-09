"""Quality modes.

`preview` and `export` describe **the same geometry**: identical base profiles,
identical forming gap, identical edge-treatment semantics.  They differ only in
how finely the edge-treatment lofts are sectioned and how coarsely the result is
tessellated.  No correctness protection differs between them - the offset
verifier and the curvature limits are active in both.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Quality:
    mode: str
    blend_sections: int          # cap
    max_section_sagitta: float   # target chord error of an edge-treatment loft, mm
    linear_deflection: float
    angular_deflection: float

    def sections(self, law) -> int:
        return law.sections_for(self.max_section_sagitta, self.blend_sections)


#: Section counts chosen by measurement, not by feel.  See
#: docs/architecture.md 7.4 and tests/test_quality_modes.py.
DEFAULTS: dict[str, Quality] = {
    "export": Quality("export", blend_sections=48, max_section_sagitta=0.002,
                      linear_deflection=0.05, angular_deflection=0.20),
    "preview": Quality("preview", blend_sections=16, max_section_sagitta=0.05,
                       linear_deflection=0.25, angular_deflection=0.50),
}


def resolve(params) -> Quality:
    base = DEFAULTS[params.quality.mode]
    q = params.quality
    return Quality(
        mode=base.mode,
        blend_sections=q.blend_sections if q.blend_sections is not None else base.blend_sections,
        max_section_sagitta=(
            q.max_section_sagitta if q.max_section_sagitta is not None else base.max_section_sagitta
        ),
        linear_deflection=(
            q.linear_deflection if q.linear_deflection is not None else base.linear_deflection
        ),
        angular_deflection=(
            q.angular_deflection if q.angular_deflection is not None else base.angular_deflection
        ),
    )
