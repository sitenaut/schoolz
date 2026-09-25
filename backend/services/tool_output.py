"""Reading a forced tool call's arguments without trusting their shape.

A tool schema is a strong hint, not a contract the API enforces (see also
the missing-`title` note in CLAUDE.md). Confirmed real: Cherry Hill West's
activities-site scan failed every run for a day because the model returned
`items` - declared as an array of objects - as a JSON *string*. Iterating a
string yields characters, so the first `item.get(...)` raised and the whole
run was lost, including every page already parsed in it.

These helpers turn whatever came back into the declared shape, and report
what they had to throw away so the caller can `record_parse_issue` it.
"""
from __future__ import annotations

import json
from typing import Any


def _decode(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def object_list(value: Any, _depth: int = 0) -> tuple[list[dict], list[Any]]:
    """(the dict entries, everything else that had to be dropped). A list
    serialized as a JSON string is decoded first, and so is each entry. An
    entry that is itself a list is flattened in - also confirmed real, same
    site: `items` came back as a one-entry list holding the whole array as a
    JSON string. Dropping that entry lost the page's items, and the scan
    then retired every one of them as vanished from the site."""
    value = _decode(value)
    if value is None:
        return [], []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return [], [value]
    kept: list[dict] = []
    dropped: list[Any] = []
    for entry in value:
        entry = _decode(entry)
        if isinstance(entry, dict):
            kept.append(entry)
        elif isinstance(entry, list) and _depth < 2:
            more, junk = object_list(entry, _depth + 1)
            kept += more
            dropped += junk
        else:
            dropped.append(entry)
    return kept, dropped


def recover_spilled_input(data: Any, list_key: str = "items") -> dict:
    """A tool input where `list_key` swallowed the rest of the call.

    Confirmed real (West's class-of-2027 page): `items` came back as the
    string `[ {...}, ... ],\n"class_year_facts": {...}` - the array and then
    the *following* argument, all inside one string. That's not valid JSON on
    its own, but it is exactly the tail of the intended object, so it parses
    once wrapped back as `{"items": <string>}`. The recovered keys fill in
    only what the call didn't already carry properly.
    """
    data = dict(data) if isinstance(data, dict) else {}
    raw = data.get(list_key)
    if not isinstance(raw, str):
        return data
    try:
        json.loads(raw)
        return data  # a plain JSON-encoded list - object_list handles it
    except ValueError:
        pass
    try:
        rebuilt = json.loads("{" + json.dumps(list_key) + ": " + raw.strip().rstrip(",") + "}")
    except ValueError:
        return data
    if not isinstance(rebuilt, dict):
        return data
    data[list_key] = rebuilt[list_key]
    for key, value in rebuilt.items():
        if key != list_key and not data.get(key):
            data[key] = value
    return data


def object_value(value: Any) -> dict:
    """A declared-object argument as a dict, or {} if it isn't one."""
    value = _decode(value)
    return value if isinstance(value, dict) else {}
