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
    #: Floor on the edge length of a mesh triangle, mm.  See MIN_MESH_SIZE.
    min_mesh_size: float = 0.05

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
#: Those counts were measured before `MIN_MESH_SIZE` existed and shift a little
#: under it - the reference male reads 240k rather than 217k at the export row,
#: because the floor changes where the mesher spends. The ordering they were
#: chosen on is unaffected, which is what the row is for.
#:
#: Build time was flat across every row to within noise: meshing is a rounding
#: error next to the B-rep work, so the old settings bought nothing.  Bandwidth
#: is the only real cost, which is why preview stops where returns flatten and
#: export does not.
#:
#: `max_section_sagitta` is the other half of the story, and it moves the B-rep
#: rather than the mesh: it sets how many cross-sections an edge treatment is
#: lofted through.  Preview was 0.05 mm, which resolves to 4/8/7 sections on the
#: reference - the `blend_sections` cap of 16 never binds.  Measured, median of
#: three, deviation being the worst 3D surface drift from the *export* result
#: around the forming loop, against a 50 um budget:
#:
#:     preview sagitta 0.05   4/8/7 sections   4.86 s   2.5 um
#:     preview sagitta 0.20   4/5/4 sections   3.63 s   4.6 um
#:     preview sagitta 0.60   4/4/4 sections   3.66 s        (no faster)
#:
#: So preview is 0.20: a quarter off the build for 4.6 um, an eleven-fold margin
#: inside the budget.  It is not monotonic - 0.60 has fewer sections and is
#: slower - which is the same fact §8.4 of the architecture notes records, that
#: preview time is fixed-cost boolean work rather than section count.  Export is
#: unchanged and is never traded for latency.
#: The smallest triangle worth making, mm.
#:
#: OCC derives its own floor from the deflection - 0.1x it, so 1 um at export -
#: and then honours the angular deflection all the way down to it.  On a healthy
#: surface that costs nothing.  On a near-degenerate one it does not terminate
#: usefully: adjacent facet normals differ by numerical noise, the mesher keeps
#: subdividing to satisfy 0.05 rad against that noise, and a sliver face comes
#: out with tens of thousands of triangles per square centimetre.
#:
#: A conic-obround female found in the wild: 8 sliver faces of 0.43 cm2, left
#: over from the entry-blend cut, carrying 125 000 triangles *each* - 1.17 M
#: triangles and a 58 MB STL for a part whose honest mesh is 246 k.  The B-rep
#: was correct and every invariant passed; only the mesh was absurd.
#:
#: 0.05 mm is chosen physically rather than numerically: it is a ninth of a
#: 0.45 mm extrusion and a quarter of a 0.2 mm layer, so no printer can resolve
#: a triangle smaller than this and one describes noise rather than geometry.
#: It is also the largest floor measured to stay inside the export deflection
#: budget - worst sag over both halves of both profiles, 1500 sampled triangle
#: centroids against the exact surface:
#:
#:     MinSize   conic female   reference female   triangles (conic female)
#:     default        2.8 um         5.4 um         1 167 918
#:     0.05 mm        5.5 um         6.2 um           245 964   <- inside 10 um
#:     0.10 mm       13.6 um         4.7 um           182 762   <- over budget
#:     0.20 mm       27.2 um         6.7 um           109 644
#:
#: Preview is unaffected either way - its coarser deflection never reaches the
#: pathology - so both modes carry the same floor rather than two numbers with
#: one explanation between them.
MIN_MESH_SIZE = 0.05

DEFAULTS: dict[str, Quality] = {
    "export": Quality("export", blend_sections=48, max_section_sagitta=0.002,
                      linear_deflection=0.01, angular_deflection=0.05,
                      min_mesh_size=MIN_MESH_SIZE),
    "preview": Quality("preview", blend_sections=16, max_section_sagitta=0.20,
                       linear_deflection=0.10, angular_deflection=0.15,
                       min_mesh_size=MIN_MESH_SIZE),
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
        min_mesh_size=(
            q.min_mesh_size if q.min_mesh_size is not None else base.min_mesh_size
        ),
    )
