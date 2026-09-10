"""The shape picker's icons must cover the shapes the core can actually build.

`packages/web/src/form/profileShapes.ts` is generated from this package by
`tools/generate_profile_icons.py`. Adding a profile family without regenerating
it would leave the picker with a nameless, pictureless option - so the drift is
caught here, in the package that would cause it, rather than in the front end
that would suffer from it.
"""

import re
import typing
from pathlib import Path

import pytest

from traymold.params import ProfileSpec

GENERATED = Path(__file__).resolve().parents[3] / "packages/web/src/form/profileShapes.ts"


def core_kinds() -> set[str]:
    return {
        typing.get_args(model.model_fields["kind"].annotation)[0]
        for model in typing.get_args(typing.get_args(ProfileSpec)[0])
    }


@pytest.mark.skipif(not GENERATED.exists(), reason="the front end is not checked out")
def test_every_profile_family_has_a_generated_icon():
    drawn = set(re.findall(r"^  '([a-z0-9_]+)':", GENERATED.read_text(), re.M))
    missing = core_kinds() - drawn
    stale = drawn - core_kinds()
    assert not missing, (
        f"no icon for {sorted(missing)} - run:\n"
        "    PYTHONPATH=packages/tray-core python3 tools/generate_profile_icons.py"
    )
    assert not stale, f"{sorted(stale)} is drawn but no longer exists in the core"


@pytest.mark.skipif(not GENERATED.exists(), reason="the front end is not checked out")
def test_each_icon_is_a_closed_path_in_the_declared_box():
    text = GENERATED.read_text()
    assert "export const PROFILE_VIEWBOX = '0 0 24 16'" in text
    for kind, path in re.findall(r"^  '([a-z0-9_]+)': '([^']+)'", text, re.M):
        assert path.startswith("M"), kind
        assert path.endswith("Z"), f"{kind} is not closed"
        numbers = [float(n) for n in re.findall(r"-?\d+\.\d+", path)]
        xs, ys = numbers[0::2], numbers[1::2]
        assert 0 <= min(xs) and max(xs) <= 24, (kind, min(xs), max(xs))
        assert 0 <= min(ys) and max(ys) <= 16, (kind, min(ys), max(ys))
