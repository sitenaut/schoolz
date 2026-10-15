"""The API's shape, saved. A route, parameter or field that appears, vanishes
or changes type fails this test until the snapshot is regenerated on purpose:

    UPDATE_SNAPSHOTS=1 pytest tests/test_openapi_snapshot.py

Review the diff of tests/snapshots/openapi.txt like any other change: a
removed or retyped line is a breaking change for the frontend, the MCP
connector and anything holding an API key."""
import os
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "openapi.txt"


def _type(schema: dict | None) -> str:
    if not schema:
        return "any"
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            return " | ".join(_type(s) for s in schema[key])
    if "enum" in schema:
        return "enum(" + ",".join(str(v) for v in schema["enum"]) + ")"
    if "const" in schema:
        return f"const({schema['const']})"
    kind = schema.get("type")
    if kind == "array":
        return f"list[{_type(schema.get('items'))}]"
    if kind == "object":
        extra = schema.get("additionalProperties")
        return f"dict[{_type(extra)}]" if isinstance(extra, dict) else "object"
    if kind and schema.get("format"):
        return f"{kind}({schema['format']})"
    return kind or "any"


def _content(content: dict | None) -> str:
    if not content:
        return "-"
    return ", ".join(
        f"{media}: {_type(body.get('schema'))}" if media != "application/json" else _type(body.get("schema"))
        for media, body in sorted(content.items())
    )


def _fields(schema: dict) -> str:
    required = set(schema.get("required", []))
    return ", ".join(
        f"{name}{'' if name in required else '?'}: {_type(prop)}"
        for name, prop in sorted(schema.get("properties", {}).items())
    )


def render(spec: dict) -> str:
    lines = ["# Generated. See tests/test_openapi_snapshot.py.", "", "## Routes"]
    for path, methods in sorted(spec["paths"].items()):
        for method, op in sorted(methods.items()):
            lines.append(f"{method.upper()} {path}")
            for param in sorted(op.get("parameters", []), key=lambda p: (p["in"], p["name"])):
                mark = "" if param.get("required") else "?"
                lines.append(f"  {param['in']} {param['name']}{mark}: {_type(param.get('schema'))}")
            if "requestBody" in op:
                mark = "" if op["requestBody"].get("required") else "?"
                lines.append(f"  body{mark}: {_content(op['requestBody'].get('content'))}")
            for status, response in sorted(op.get("responses", {}).items()):
                if status != "422":
                    lines.append(f"  -> {status}: {_content(response.get('content'))}")
    lines += ["", "## Schemas"]
    for name, schema in sorted(spec.get("components", {}).get("schemas", {}).items()):
        if "properties" in schema:
            lines.append(f"{name} {{ {_fields(schema)} }}")
        else:
            lines.append(f"{name} = {_type(schema)}")
    return "\n".join(lines) + "\n"


def test_the_api_shape_matches_the_snapshot():
    from main import app

    current = render(app.openapi())
    if os.environ.get("UPDATE_SNAPSHOTS"):
        SNAPSHOT.write_text(current)
    assert SNAPSHOT.exists(), "No snapshot yet: run with UPDATE_SNAPSHOTS=1"
    saved = SNAPSHOT.read_text()
    if current != saved:
        import difflib

        diff = "\n".join(list(difflib.unified_diff(
            saved.splitlines(), current.splitlines(), "snapshot", "app", lineterm="", n=1
        ))[:80])
        raise AssertionError(
            "The API's shape changed. If that is intended, regenerate with UPDATE_SNAPSHOTS=1 "
            f"and commit tests/snapshots/openapi.txt.\n{diff}"
        )
