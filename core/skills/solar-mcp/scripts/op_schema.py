"""Strict argument validation for tools and operations.

A small JSON-Schema subset, closed by default: every object refuses keys its
schema does not name, types are exact (a boolean is not an integer), and the
first problem is reported with its path. No coercion, no defaults, no free-form
objects. This is what keeps `solar_execute` from becoming a generic channel.
"""
from __future__ import annotations

import re

_TYPES = {"string": str, "boolean": bool, "integer": int, "object": dict, "array": list}


def check(value, schema: dict, path: str = "arguments") -> str | None:
    """Return a description of the first violation, or None when valid."""
    kind = schema.get("type")
    expected = _TYPES.get(kind)
    if expected is None:
        return f"{path}: unsupported schema type {kind!r}"
    if type(value) is not expected:
        return f"{path}: expected {kind}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path}: must be one of {', '.join(map(str, schema['enum']))}"
    if kind == "string":
        if "\x00" in value:
            return f"{path}: contains a NUL character"
        if len(value) < schema.get("minLength", 0):
            return f"{path}: shorter than {schema['minLength']}"
        if len(value) > schema.get("maxLength", 1_000_000):
            return f"{path}: longer than {schema['maxLength']}"
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            return f"{path}: does not match the allowed format"
    elif kind == "integer":
        if value < schema.get("minimum", value):
            return f"{path}: below {schema['minimum']}"
        if value > schema.get("maximum", value):
            return f"{path}: above {schema['maximum']}"
    elif kind == "array":
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 10_000):
            return f"{path}: wrong number of items"
        if schema.get("uniqueItems") and len(set(map(repr, value))) != len(value):
            return f"{path}: items must be unique"
        for index, item in enumerate(value):
            problem = check(item, schema["items"], f"{path}[{index}]")
            if problem:
                return problem
    elif kind == "object":
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                return f"{path}.{key}: required"
        for key, item in value.items():
            if key not in properties:
                return f"{path}.{key}: not accepted"
            problem = check(item, properties[key], f"{path}.{key}")
            if problem:
                return problem
    return None
