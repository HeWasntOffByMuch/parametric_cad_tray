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
#:
#: The deflections are set by the worst *crease* they leave - the angle between
#: adjacent facet normals around the wall - because that is what the eye reads as
#: faceting, and what a slicer's flat shading exaggerates.  A linear deflection
#: alone does not bound it: 0.05 mm of sagitta on this profile's ~52 mm radius is
#: still a 4.6 mm chord.  Measured on the reference male, per part:
#:
#:     preview  0.25 / 0.50   2.5k tri   7.23 deg   0.10 MB glb   <- visibly faceted
#:     preview  0.10 / 0.15    22k tri   1.33 deg   0.58 MB glb
#:     export   0.05 / 0.20    15k tri   2.57 deg   0.76 MB stl   <- visible in a slicer
#:     export   0.02 / 0.10    54k tri   0.96 deg   2.72 MB stl
#:     export   0.01 / 0.05   217k tri   0.21 deg  10.84 MB stl
#:
#: Build time was flat across every row to within noise: meshing is a rounding
#: error next to the B-rep work, so the old settings bought nothing.  Bandwidth
#: is the only real cost, which is why preview stops where returns flatten and
#: export does not.
DEFAULTS: dict[str, Quality] = {
    "export": Quality("export", blend_sections=48, max_section_sagitta=0.002,
                      linear_deflection=0.01, angular_deflection=0.05),
    "preview": Quality("preview", blend_sections=16, max_section_sagitta=0.05,
                       linear_deflection=0.10, angular_deflection=0.15),
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
