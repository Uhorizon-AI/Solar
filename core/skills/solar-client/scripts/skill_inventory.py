"""Read-only, shared inventory for native publication and MCP discovery."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ID = re.compile(r"[A-Za-z0-9_.-]+(?::[A-Za-z0-9_.-]+)?\Z")
MAX_FILE = 1024 * 1024


def settings(workspace: Path) -> dict:
    path = workspace / ".solar/settings.json"
    if not path.exists():
        path = workspace / ".solar/manifest.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError("Workspace settings must be an object")
    for key in ("sync_exclude_planets", "sync_exclude_skills"):
        values = data.get(key, [])
        if not isinstance(values, list) or any(
                not isinstance(v, str) or not ID.fullmatch(v) for v in values):
            raise ValueError(f"Invalid {key}")
    return data


def read_unit(path: Path, root: Path) -> bytes:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise ValueError("Capability path escapes its approved root")
    with resolved.open("rb") as stream:
        value = stream.read(MAX_FILE + 1)
    if len(value) > MAX_FILE:
        raise ValueError("Capability source exceeds the inventory size limit")
    return value


def metadata(text: str) -> dict:
    """Read the scalar skill frontmatter convention; no YAML execution."""
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        raise ValueError("Unclosed skill frontmatter")
    lines = text[4:end].splitlines()
    result = {}
    for i, line in enumerate(lines):
        match = re.match(r"^(name|description|sync):\s*(.*)$", line)
        if not match:
            continue
        key, value = match.groups()
        if value[:1] in (">", "|"):
            block = []
            for following in lines[i + 1:]:
                if following and not following[0].isspace():
                    break
                block.append(following.strip())
            value = " ".join(block)
        elif value.startswith('"'):
            try:
                value = json.loads(value)
            except ValueError:
                value = value.strip('"')
        elif value.startswith("'"):
            value = value[1:-1].replace("''", "'")
        result[key] = value
    return result


def inventory(workspace: Path, core: Path) -> dict[str, dict]:
    workspace, core = workspace.resolve(), core.resolve()
    config = settings(workspace)
    excluded = set(config.get("sync_exclude_skills", []))
    excluded_planets = set(config.get("sync_exclude_planets", []))
    candidates = [(p.parent.name, "core", p, core / "skills")
                  for p in sorted((core / "skills").glob("*/SKILL.md"))]
    planets = workspace / "planets"
    for planet in sorted(planets.glob("*")):
        if not planet.is_dir() or planet.name in excluded_planets:
            continue
        if not planet.resolve().is_relative_to(planets.resolve()):
            print(f"WARNING: skipping planet {planet.name!r}: outside workspace root", file=sys.stderr)
            continue
        for path in sorted(planet.rglob("SKILL.md")):
            parts = path.relative_to(planet).parts
            if "skills" in parts and parts.index("skills") < len(parts) - 2:
                candidates.append((f"{planet.name}:{path.parent.name}", planet.name,
                                   path, planet))
    found = {}
    for key, namespace, path, root in candidates:
        if not ID.fullmatch(key):
            print(f"WARNING: skipping invalid capability ID {key!r}", file=sys.stderr)
            continue
        if key in excluded:
            continue
        try:
            raw = read_unit(path, root)
            front = metadata(raw.decode("utf-8"))
            if any(c in str(path.resolve().parent) for c in ("|", "\n", "\r")):
                raise ValueError("Unsupported inventory path")
        except (OSError, ValueError, UnicodeError):
            print(f"WARNING: skipping unavailable or unsafe capability {key!r}", file=sys.stderr)
            continue
        if front.get("sync", "").lower() == "false":
            continue
        # Legacy sync resolves duplicate nested names in sorted first-match order.
        if key in found:
            continue
        found[key] = dict(id=key, namespace=namespace, type="instruction",
                          description=str(front.get("description", "")),
                          path=str(path.resolve()), root=str(root.resolve()),
                          revision=hashlib.sha256(raw).hexdigest())
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--core", type=Path, required=True)
    args = parser.parse_args()
    for key, entry in inventory(args.workspace, args.core).items():
        source = str(Path(entry["path"]).parent)
        if any(c in source for c in ("|", "\n", "\r")):
            raise ValueError("Unsupported inventory path")
        print(f"{key}|{source}")


if __name__ == "__main__":
    main()
