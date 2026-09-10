"""Turning a rejected request body into diagnostics the form can act on.

FastAPI answers a body that does not parse with its own 422: `detail` is a list
of pydantic error dicts. That shape is unusable to this frontend twice over.

It cannot be *rendered*: the client knows one error envelope,
`detail.error.{kind,message,diagnostics}`, and anything else falls through to
"request failed (422)" - a status code and no action.

It cannot be *placed*: pydantic locates an error at
`["body","params","tray","profile","g2_quintic_obround","length"]`, and the form
addresses that input as `tray.profile.length`.

The second one is what makes a bad number so much worse than it looks. Every
endpoint takes the same `params` model, so a value outside its bounds fails
`POST /api/validate` in exactly the way it fails `POST /api/preview` - and
validate is the endpoint whose whole job is to explain what is wrong. The
browser is left with no diagnostics at all: nothing inline on the field, nothing
blocking the build button, and a stored document that reproduces it on reload.

So the handler here answers with the same envelope the rest of the API uses, and
names the field the way the form does.
"""

from __future__ import annotations

from typing import Any, Iterable

#: The request wrapper, not part of the parameter document.
_ENVELOPE = ("body", "params")

_CODES = {
    "greater_than": "E-RANGE",
    "greater_than_equal": "E-RANGE",
    "less_than": "E-RANGE",
    "less_than_equal": "E-RANGE",
    "multiple_of": "E-RANGE",
    "missing": "E-REQUIRED",
    "union_tag_invalid": "E-VARIANT",
    "union_tag_not_found": "E-VARIANT",
    "literal_error": "E-VARIANT",
}

#: `Input should be greater than 0` is pydantic explaining its own check. These
#: say the same thing as an instruction, with the bound in it, because the bound
#: is the only part the user can act on.
_PHRASING = {
    "greater_than": "must be greater than {gt}",
    "greater_than_equal": "must be at least {ge}",
    "less_than": "must be less than {lt}",
    "less_than_equal": "must be at most {le}",
    "multiple_of": "must be a multiple of {multiple_of}",
    "missing": "is required",
}


def variant_tags(schema: dict) -> frozenset[str]:
    """Every discriminated-union tag anywhere in a JSON schema.

    These are the segments pydantic adds to a path and the form leaves out: it
    shows one variant at a time, so a variant's fields hang directly off the
    union field. `test_request_errors` proves no tag is also a field name, which
    is what makes dropping them by name safe rather than a guess.
    """
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            mapping = node.get("discriminator", {}).get("mapping")
            if isinstance(mapping, dict):
                found.update(str(k) for k in mapping)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return frozenset(found)


def field_path(loc: Iterable[Any], tags: frozenset[str]) -> str:
    """A pydantic `loc` as the dotted path the form uses for that input."""
    parts = [str(p) for p in loc]
    while parts and parts[0] in _ENVELOPE:
        parts.pop(0)
    return ".".join(p for p in parts if p not in tags)


def _message(err: dict) -> str:
    kind = err.get("type", "")
    ctx = err.get("ctx") or {}
    phrase = _PHRASING.get(kind)
    if phrase:
        try:
            text = phrase.format(**{k: _plain(v) for k, v in ctx.items()})
        except (KeyError, IndexError):
            text = err.get("msg", "is not valid")
        if kind != "missing" and "input" in err:
            text += f" (this is {_plain(err['input'])})"
        return text
    # Anything else keeps pydantic's own wording, which is already a sentence.
    return str(err.get("msg", "is not valid"))


def _plain(value: Any) -> str:
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    if isinstance(value, (dict, list)):
        return "not a value this field accepts"
    return str(value)


def diagnostics_for(errors: Iterable[dict], tags: frozenset[str]) -> list[dict]:
    """Pydantic's errors as this API's diagnostics, one per offending field."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for err in errors:
        path = field_path(err.get("loc", ()), tags)
        code = _CODES.get(err.get("type", ""), "E-INVALID")
        if (code, path) in seen:
            continue
        seen.add((code, path))
        out.append({
            "code": code,
            "severity": "error",
            "field": path,
            "message": _message(err),
        })
    return out


def envelope(diagnostics: list[dict]) -> dict:
    """The one error shape every client of this API already knows how to read."""
    lead = diagnostics[0] if diagnostics else None
    message = (
        f"{lead['field']} {lead['message']}" if lead and lead["field"]
        else (lead["message"] if lead else "the request body is not valid")
    )
    return {"error": {"kind": "validation_error", "message": message,
                      "diagnostics": diagnostics}}
