"""The parameter schema.  Pydantic v2 is the single definition; everything else
(JSON Schema, generated TypeScript, the CLI) is derived from it.

Three concepts are kept strictly separate and must never be mixed:

  1. tray / profile geometry   -> `TrayParams.profile`, `TrayParams.depth`
  2. forming gap               -> `LeatherParams`, `FitParams`  (see derive.py)
  3. 3D edge treatments        -> `MoldParams.mold.*_blend`

The female cavity is derived from the male *base* profile and the forming gap
alone.  No edge treatment may influence it.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .version import SCHEMA_VERSION


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------
# 1. base plan profiles - named for the curve construction they actually use
# --------------------------------------------------------------------------
class _RectProfileBase(_Model):
    # Defaulted, not merely constrained.  A schema-driven form builds a new
    # variant's document from the schema's defaults, carrying over only the
    # fields the previous variant also had - so a required field with no default
    # is emitted as nothing at all, and the switch fails validation before the
    # user has touched it.  The reference plan is the natural starting point.
    length: float = Field(default=175.0, gt=0, le=1000, description="plan length, X, mm")
    width: float = Field(default=105.0, gt=0, le=1000, description="plan width, Y, mm")


class G2QuinticRectProfile(_RectProfileBase):
    """Rectangle with the reference's G2 corner: non-rational quintic B-spline,
    zero curvature at both tangent points.  Recovered verbatim from the Onshape
    STEP; not a conic and not approximable by one within 0.23 mm at s = 52.5."""

    kind: Literal["g2_quintic_rect"] = "g2_quintic_rect"
    corner_setback: float = Field(default=25.0, ge=0,
                                  description="setback from the sharp corner, mm")

    @property
    def corner_style(self) -> str:
        return "g2_quintic"


class G2QuinticObroundProfile(_RectProfileBase):
    """The reference profile: G2 quintic corners at the maximum setback, so the
    short ends have no straight run at all."""

    kind: Literal["g2_quintic_obround"] = "g2_quintic_obround"

    @property
    def corner_setback(self) -> float:
        return self.width / 2.0

    @property
    def corner_style(self) -> str:
        return "g2_quintic"


class ConicRectProfile(_RectProfileBase):
    """Rectangle with rational-quadratic (conic) corners.  rho = 0.5 is the parabola."""

    kind: Literal["conic_rect"] = "conic_rect"
    corner_setback: float = Field(default=25.0, ge=0,
                                  description="setback from the sharp corner, mm")
    rho: float = Field(default=0.5, gt=0.0, lt=1.0)

    @property
    def corner_style(self) -> str:
        return "conic"


class ConicObroundProfile(_RectProfileBase):
    kind: Literal["conic_obround"] = "conic_obround"
    rho: float = Field(default=0.5, gt=0.0, lt=1.0)

    @property
    def corner_setback(self) -> float:
        return self.width / 2.0

    @property
    def corner_style(self) -> str:
        return "conic"


class CircularRectProfile(_RectProfileBase):
    """Conventional rounded rectangle: constant-radius circular corners."""

    kind: Literal["circular_rect"] = "circular_rect"
    corner_radius: float = Field(default=25.0, ge=0)

    @property
    def corner_setback(self) -> float:
        return self.corner_radius

    @property
    def corner_style(self) -> str:
        return "circular"


class CircularObroundProfile(_RectProfileBase):
    """Conventional stadium / obround: circular ends of radius width / 2."""

    kind: Literal["circular_obround"] = "circular_obround"

    @property
    def corner_setback(self) -> float:
        return self.width / 2.0

    @property
    def corner_style(self) -> str:
        return "circular"


class EllipseProfile(_RectProfileBase):
    kind: Literal["ellipse"] = "ellipse"

    @property
    def corner_setback(self) -> float:
        return min(self.length, self.width) / 2.0

    @property
    def corner_style(self) -> str:
        return "circular"


class SuperellipseProfile(_RectProfileBase):
    kind: Literal["superellipse"] = "superellipse"
    #: Bounded by what a single C2 spline can actually follow.  A superellipse
    #: has no exact NURBS form; past roughly 4.6 at this plan size the fit drifts
    #: outside the 10 um the profile is held to, and `superellipse_wire` refuses
    #: it with the measured error.  Larger plans reach ~5.8, which is why the
    #: schema stops at 6 rather than at the smaller number.
    exponent: float = Field(default=4.0, gt=1.0, le=6.0)

    @property
    def corner_setback(self) -> float:
        return min(self.length, self.width) / 2.0

    @property
    def corner_style(self) -> str:
        return "circular"


ProfileSpec = Annotated[
    Union[
        G2QuinticObroundProfile,
        G2QuinticRectProfile,
        ConicObroundProfile,
        ConicRectProfile,
        CircularObroundProfile,
        CircularRectProfile,
        EllipseProfile,
        SuperellipseProfile,
    ],
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------
# 1b. tray forming geometry
# --------------------------------------------------------------------------
class TrayParams(_Model):
    profile: ProfileSpec = Field(default_factory=lambda: G2QuinticObroundProfile(length=175.0, width=105.0))
    depth: float = Field(default=25.0, gt=0, le=300, description="draw depth, mm")
    datum: Literal["inner", "outer"] = "inner"
    draft_angle: float = Field(default=0.0, ge=0.0, le=15.0, description="degrees")
    draft_mode: Literal["both", "plug_only", "cavity_only"] = "both"


# --------------------------------------------------------------------------
# 2. forming gap inputs
# --------------------------------------------------------------------------
class LeatherParams(_Model):
    thickness: float = Field(default=3.0, gt=0, le=12.0)
    compression: float = Field(default=0.0, ge=0.0, le=0.4, description="fraction")


class FitParams(_Model):
    clearance: float = Field(default=0.0, ge=-0.5, le=2.0)
    gap_override: float | None = Field(default=None, gt=0.0, le=12.0)


# --------------------------------------------------------------------------
# 3. 3D edge treatments - applied AFTER the base profiles exist
# --------------------------------------------------------------------------
# Every edge treatment defaults its own size. A required field with no default
# is unreachable from a form: the variant switcher emits the discriminator plus
# whatever has a default, JSON.stringify drops the undefined, and the server
# answers 422 before the user has touched anything. That happened to the profile
# families once already; `test_schema.py` now asserts it for every variant of
# every union rather than for one union at a time.
class CircularFillet(_Model):
    """Constant-radius rolling-ball fillet.  The male root treatment in the
    reference: cylindrical faces on the straight runs, exact circular sweeps at
    the corners."""

    kind: Literal["circular_fillet"] = "circular_fillet"
    radius: float = Field(default=2.0, gt=0.0, le=100.0, description="fillet radius, mm")

    @property
    def size(self) -> float:
        return self.radius

    @property
    def blend_style(self) -> str:
        return "circular"

    @property
    def active(self) -> bool:
        return True


class G2QuinticBlend(_Model):
    """The reference's curvature-continuous blend, given by its setback."""

    kind: Literal["g2_quintic_blend"] = "g2_quintic_blend"
    setback: float = Field(default=3.0, gt=0.0, le=100.0,
                           description="setback from the sharp edge, mm")

    @property
    def size(self) -> float:
        return self.setback

    @property
    def blend_style(self) -> str:
        return "g2_quintic"

    @property
    def active(self) -> bool:
        return True


class ChamferTreatment(_Model):
    kind: Literal["chamfer"] = "chamfer"
    distance: float = Field(default=2.0, gt=0.0, le=100.0, description="chamfer distance, mm")

    @property
    def size(self) -> float:
        return self.distance

    @property
    def blend_style(self) -> str:
        return "chamfer"

    @property
    def active(self) -> bool:
        return True


class NoTreatment(_Model):
    kind: Literal["none"] = "none"

    @property
    def size(self) -> float:
        return 0.0

    @property
    def blend_style(self) -> str:
        return "none"

    @property
    def active(self) -> bool:
        return False


EdgeTreatmentSpec = Annotated[
    Union[CircularFillet, G2QuinticBlend, ChamferTreatment, NoTreatment],
    Field(discriminator="kind"),
]


class PartSelection(_Model):
    male: bool = True
    female: bool = True


class MoldParams(_Model):
    parts: PartSelection = PartSelection()
    flange_width: float = Field(default=30.0, gt=0, le=200)
    base_plate_thickness: float = Field(default=15.0, gt=0, le=100)
    cavity_plate_thickness: float = Field(default=25.0, gt=0, le=300)

    # each treatment is independent, semantically typed, and owns its own parameter
    male_root_blend: EdgeTreatmentSpec = CircularFillet(radius=1.2)
    male_floor_blend: EdgeTreatmentSpec = G2QuinticBlend(setback=5.0)
    #: `bottom` is z=0, the parting face: the mouth the plug enters and the
    #: leather is drawn across, so it is the one that has to be radiused. `top`
    #: is the outer face, where nothing bends - blend it only if you want the
    #: look. The reference files carry this blend on their other face because
    #: they are slicer exports of the part lying cavity-up; see `apply_features`.
    female_entry_blend_bottom: EdgeTreatmentSpec = G2QuinticBlend(setback=3.0)
    female_entry_blend_top: EdgeTreatmentSpec = NoTreatment()

    plate_edge_chamfer: float = Field(default=0.0, ge=0.0, le=10.0)
    flange_relief_depth: float = Field(default=0.0, ge=0.0, le=20.0)


# --------------------------------------------------------------------------
# 4. manufacturing features
# --------------------------------------------------------------------------
class ClampHoles(_Model):
    enabled: bool = False
    pattern: Literal["diagonal_pair", "four_corners"] = "diagonal_pair"
    diagonal: Literal["nw_se", "ne_sw"] = "nw_se"
    diameter: float = Field(default=6.0, gt=0, le=30)
    inset: float = Field(default=15.0, gt=0, le=200)
    top_chamfer: float = Field(default=2.0, ge=0.0, le=10.0)
    in_male: bool = False
    in_female: bool = True


class PryNotches(_Model):
    enabled: bool = False
    pattern: Literal["diagonal_pair", "four_corners"] = "diagonal_pair"
    diagonal: Literal["nw_se", "ne_sw"] = "ne_sw"
    size_x: float = Field(default=15.0, gt=0, le=100)
    size_y: float = Field(default=15.0, gt=0, le=100)
    depth: float = Field(default=8.0, gt=0, le=200)


class AlignmentPins(_Model):
    enabled: bool = False
    pattern: Literal["diagonal_pair", "four_corners"] = "four_corners"
    diameter: float = Field(default=6.0, gt=0, le=30)
    height: float = Field(default=8.0, gt=0, le=100)
    inset: float = Field(default=15.0, gt=0, le=200)


class Features(_Model):
    clamp_holes: ClampHoles = ClampHoles()
    pry_notches: PryNotches = PryNotches()
    alignment_pins: AlignmentPins = AlignmentPins()


class ManufacturingParams(_Model):
    pin_fit_clearance: float = Field(default=0.20, ge=0.0, le=1.0)
    min_wall: float = Field(default=2.0, gt=0, le=20)
    nozzle_diameter: float = Field(default=0.4, gt=0, le=2.0)


class QualityParams(_Model):
    """Preview and export describe the same geometry; they differ only in loft
    section density and tessellation tolerance.  Leave the overrides at None to
    take the mode's measured defaults from `traymold.quality.DEFAULTS`."""

    mode: Literal["preview", "export"] = "export"
    blend_sections: int | None = Field(default=None, ge=4, le=256,
                                       description="cap on loft sections per edge treatment")
    max_section_sagitta: float | None = Field(default=None, gt=0, le=1.0,
                                              description="target loft chord error, mm")
    linear_deflection: float | None = Field(default=None, gt=0, le=5.0)
    angular_deflection: float | None = Field(default=None, gt=0, le=1.5)


class Params(_Model):
    schema_version: str = SCHEMA_VERSION
    name: str = "untitled"
    tray: TrayParams = TrayParams()
    leather: LeatherParams = LeatherParams()
    fit: FitParams = FitParams()
    mold: MoldParams = MoldParams()
    features: Features = Features()
    manufacturing: ManufacturingParams = ManufacturingParams()
    quality: QualityParams = QualityParams()

    def with_quality(self, mode: str) -> "Params":
        return self.model_copy(update={"quality": self.quality.model_copy(update={"mode": mode})})

    @model_validator(mode="after")
    def _check_setback(self):
        p = self.tray.profile
        s = p.corner_setback
        if s > min(p.length, p.width) / 2.0 + 1e-9:
            raise ValueError(
                f"E-SHAPE-001: corner setback {s} exceeds half the smaller side "
                f"({min(p.length, p.width) / 2.0})"
            )
        return self
