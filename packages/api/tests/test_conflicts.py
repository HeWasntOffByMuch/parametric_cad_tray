"""Combinations the kernel cannot build are kept out of reach, not reported.

The rule these replace: pick an ellipse with a root blend on, wait for the
request, and be told that an elliptical plug cannot take a root blend and that
you should go and set `mold.male_root_blend` to none. The app knew that before
the click landed, and made the user do its bookkeeping.

So `UNSUPPORTED_COMBINATIONS` is written as a constraint - `when` this, `field`
is limited to `allowed`, otherwise `fallback` - and served in the UI hints so
the form can apply it. The diagnostic stays, because the form is not the only
thing that can post a parameter document, but nobody using the app reaches it.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from trayapi.policy import UNSUPPORTED_COMBINATIONS, constrains, policy_diagnostics
from trayapi.ui_hints import UI_HINTS
from traymold.params import Params
from traymold.presets import REF_4X7

ROOT = Path(__file__).resolve().parents[3]


# --------------------------------------------------------------------------
# the rules themselves
# --------------------------------------------------------------------------
@pytest.mark.parametrize("rule", UNSUPPORTED_COMBINATIONS, ids=lambda r: r["code"])
def test_every_rule_is_expressible_as_a_constraint(rule):
    """A rule a UI cannot apply is a rule that becomes an error message."""
    assert rule["when"]["kind_in"], "a rule that is never in force"
    assert rule["allowed"], "a rule that leaves the field with nothing to be"
    assert rule["fallback"] in rule["allowed"], "the way out must itself be allowed"
    assert rule["reason"] and rule["message"]


def _document(rule, treatment: dict) -> dict:
    """The reference design on the constrained profile, with `field` set."""
    doc = copy.deepcopy(json.loads(REF_4X7.model_dump_json()))
    doc["tray"]["profile"] = {"kind": rule["when"]["kind_in"][0], "length": 175.0, "width": 105.0}
    group, _, name = rule["field"].partition(".")
    doc[group][name] = treatment
    return doc


@pytest.mark.parametrize("rule", UNSUPPORTED_COMBINATIONS, ids=lambda r: r["code"])
def test_the_fallback_actually_satisfies_the_rule(rule):
    """What the form will set the field to must leave the document buildable.

    Validated from JSON rather than assembled with `model_copy`, so the fallback
    goes through the same union resolution a posted document does.
    """
    settled = Params.model_validate(_document(rule, {"kind": rule["fallback"]}))
    assert constrains(rule, settled), "the rule should still be in force"
    codes = [d["code"] for d in policy_diagnostics(settled, allow_experimental=False)]
    assert rule["code"] not in codes


@pytest.mark.parametrize("rule", UNSUPPORTED_COMBINATIONS, ids=lambda r: r["code"])
def test_a_value_outside_allowed_is_what_trips_it(rule):
    """The other half of the pair: the rule has to actually fire on something,
    or the test above would pass against a rule that never applies."""
    tripped = Params.model_validate(_document(rule, json.loads(REF_4X7.mold.male_root_blend.model_dump_json())))
    assert tripped.mold.male_root_blend.kind not in rule["allowed"]
    codes = [d["code"] for d in policy_diagnostics(tripped, allow_experimental=False)]
    assert rule["code"] in codes


@pytest.mark.parametrize("rule", UNSUPPORTED_COMBINATIONS, ids=lambda r: r["code"])
def test_the_diagnostic_is_still_raised_for_a_caller_that_is_not_the_form(client, rule):
    """A script, a hand-edited link, an old client: they get told."""
    params = copy.deepcopy(json.loads(REF_4X7.model_dump_json()))
    params["tray"]["profile"] = {"kind": rule["when"]["kind_in"][0], "length": 175.0, "width": 105.0}
    body = client.post("/api/validate", json={"params": params}).json()
    assert rule["code"] in [d["code"] for d in body["diagnostics"]]


# --------------------------------------------------------------------------
# what the form is given
# --------------------------------------------------------------------------
def test_the_hints_carry_every_rule(client):
    served = client.get("/api/schema").json()["ui_hints"]["conflicts"]
    assert [c["code"] for c in served] == [r["code"] for r in UNSUPPORTED_COMBINATIONS]
    for conflict, rule in zip(served, UNSUPPORTED_COMBINATIONS):
        assert conflict["field"] == rule["field"]
        assert conflict["allowed"] == list(rule["allowed"])
        assert conflict["when"]["kind_in"] == list(rule["when"]["kind_in"])


def test_the_hints_are_json(client):
    """Tuples do not survive the wire; the reshaping in `ui_hints` is what makes
    these lists, and a tuple that slipped through would serialise as an array
    here and compare unequal in the frontend's own fixture check."""
    served = client.get("/api/schema").json()["ui_hints"]["conflicts"]
    assert served == json.loads(json.dumps(served))
    assert UI_HINTS["conflicts"] == served


def test_a_constrained_field_is_not_disabled_outright(client):
    """`disabled_values` gates a variant everywhere; a conflict gates it only
    while another field is set a certain way. Mixing them up would take the root
    blend away from every profile."""
    fields = client.get("/api/schema").json()["ui_hints"]["fields"]
    for rule in UNSUPPORTED_COMBINATIONS:
        assert "disabled_values" not in fields.get(rule["field"], {})


# --------------------------------------------------------------------------
# the frontend's copy of all this
# --------------------------------------------------------------------------
def test_fixtures_are_current():
    """`packages/web/tests/fixtures.json` is what every frontend test believes
    the backend serves. Captured by hand it drifts, and a stale fixture is worse
    than none: the suite passes against a schema the API stopped sending. It had
    drifted far enough to still carry `required` without defaults on every edge
    treatment - the shape of a bug that was already fixed, and that the frontend
    suite therefore could not have caught."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "dump_fixtures.py"), "--check"],
        capture_output=True, text=True, env={"TRAYMOLD_ANALYTICS_DB": "", "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr or result.stdout
