#!/usr/bin/env python3
"""Build workspace portable bundle with transitive allowlist (Fase 3B)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

DENY_NAMES = {".env", ".git", ".DS_Store", "__pycache__", "node_modules", ".venv"}
DENY_PARTS = ("sun/runtime", "backups")

SKILL_REF = re.compile(
    r"(?:invoke\s+skill\s+['\"]([^'\"]+)['\"]|"
    r"skills/([a-zA-Z0-9_-]+)/|"
    r"core/skills/([a-zA-Z0-9_-]+)/)",
    re.I,
)
SCRIPT_REF = re.compile(
    r"(?:bash\s+|source\s+)(?:[^\s'\"]*?(?:core/)?(?:skills/[^/]+/)?scripts/[^\s'\"]+|"
    r"core/scripts/[^\s'\"]+)",
    re.I,
)
REL_SCRIPT = re.compile(r"scripts/[^\s'\"`]+")


def denied(rel: str) -> bool:
    parts = Path(rel).parts
    if parts and parts[-1] in DENY_NAMES:
        return True
    joined = rel.replace("\\", "/")
    return any(p in joined for p in DENY_PARTS)


def discover_skills(core: Path, planets: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    skills_root = core / "skills"
    if skills_root.is_dir():
        for item in sorted(skills_root.iterdir()):
            if item.is_dir() and (item / "SKILL.md").is_file():
                found[item.name] = item
    if planets.is_dir():
        for skill_md in sorted(planets.glob("*/skills/*/SKILL.md")):
            planet = skill_md.parts[-4]
            name = skill_md.parent.name
            found[f"{planet}:{name}"] = skill_md.parent
    return found


def discover_md_resources(core: Path, planets: Path, kind: str) -> dict[str, Path]:
    store: dict[str, Path] = {}
    root = core / kind
    if root.is_dir():
        for f in sorted(root.glob("*.md")):
            store[f.name] = f
    if planets.is_dir():
        for f in sorted(planets.glob(f"*/{kind}/*.md")):
            planet = f.parts[-3]
            store[f"{planet}:{f.name}"] = f
    return store


def refs_from_text(text: str, skill_dir: Path, core: Path) -> tuple[set[str], set[Path]]:
    deps_skills: set[str] = set()
    scripts: set[Path] = set()
    for m in SKILL_REF.finditer(text):
        for g in m.groups():
            if g:
                deps_skills.add(g)
    for m in SCRIPT_REF.finditer(text):
        token = m.group(0).split()[-1]
        if not token:
            continue
        cand = skill_dir / token if "scripts/" in token else core / token.lstrip("/")
        if not cand.is_file() and "core/" in token:
            cand = core / token.split("core/", 1)[-1]
        if cand.is_file():
            scripts.add(cand.resolve())
    for m in REL_SCRIPT.finditer(text):
        cand = skill_dir / m.group(0)
        if cand.is_file():
            scripts.add(cand.resolve())
    return deps_skills, scripts


def expand_allowlist(all_skills: dict[str, Path], core: Path) -> tuple[dict[str, Path], set[Path]]:
    selected = dict(all_skills)
    queue = list(all_skills.keys())
    seen = set(queue)
    extra_scripts: set[Path] = set()
    for rel in (
        "scripts/sync-clients.sh",
        "skills/solar-interface/scripts/resolve_solar_paths.sh",
        "skills/solar-interface/scripts/client_lib.sh",
        "scripts/sun-workspace-doctor.sh",
    ):
        p = core / rel
        if p.is_file():
            extra_scripts.add(p.resolve())

    while queue:
        name = queue.pop(0)
        skill_dir = selected.get(name) or all_skills.get(name)
        if not skill_dir:
            continue
        skill_path = Path(skill_dir)
        texts: list[str] = []
        skill_md = skill_path / "SKILL.md"
        if skill_md.is_file():
            texts.append(skill_md.read_text(encoding="utf-8", errors="replace"))
        scripts_dir = skill_path / "scripts"
        if scripts_dir.is_dir():
            for sf in scripts_dir.rglob("*"):
                if sf.is_file() and sf.suffix in {".sh", ".py", ".md"}:
                    try:
                        texts.append(sf.read_text(encoding="utf-8", errors="replace"))
                    except OSError:
                        pass
        for text in texts:
            deps, scripts = refs_from_text(text, skill_path, core)
            for dep in deps:
                if dep not in seen and dep in all_skills:
                    seen.add(dep)
                    selected[dep] = all_skills[dep]
                    queue.append(dep)
            extra_scripts.update(scripts)
    return selected, extra_scripts


def add_file(src: Path, bundle: Path, rel: str, files_meta: list[dict]) -> None:
    if denied(rel) or not src.is_file():
        return
    dest = bundle / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    size = dest.stat().st_size
    h = hashlib.sha256()
    with open(dest, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    files_meta.append({"path": rel, "size": size, "sha256": h.hexdigest()})


def build(workspace: Path, core: Path, bundle: Path, check_only: bool) -> dict:
    planets = workspace / "planets"
    all_skills = discover_skills(core, planets)
    agents = discover_md_resources(core, planets, "agents")
    commands = discover_md_resources(core, planets, "commands")
    selected_skills, extra_scripts = expand_allowlist(all_skills, core)

    if check_only:
        return {
            "check": True,
            "skills": len(selected_skills),
            "agents": len(agents),
            "commands": len(commands),
            "extra_scripts": len(extra_scripts),
        }

    core = core.resolve()
    bundle = bundle.resolve()
    try:
        core.relative_to(bundle)
        print(
            "ERROR: --core-src must not be inside --bundle-dir (use global framework core/)",
            file=sys.stderr,
        )
        sys.exit(1)
    except ValueError:
        pass

    if bundle.exists():
        shutil.rmtree(bundle)
    (bundle / "core").mkdir(parents=True)

    files_meta: list[dict] = []

    for name, path in sorted(selected_skills.items()):
        safe = name.replace(":", "__")
        if path.is_dir():
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if d not in DENY_NAMES]
                for fn in files:
                    if fn in DENY_NAMES:
                        continue
                    full = Path(root) / fn
                    rel = f"core/skills/{safe}/{full.relative_to(path).as_posix()}"
                    add_file(full, bundle, rel, files_meta)

    for _name, path in sorted(agents.items()):
        add_file(path, bundle, f"core/agents/{path.name}", files_meta)

    for _name, path in sorted(commands.items()):
        add_file(path, bundle, f"core/commands/{path.name}", files_meta)

    for script in sorted(extra_scripts):
        try:
            rel = script.relative_to(core)
            add_file(script, bundle, f"core/{rel.as_posix()}", files_meta)
        except ValueError:
            add_file(script, bundle, f"core/scripts/{script.name}", files_meta)

    capabilities = sorted(selected_skills.keys())
    index = {
        "layout": "solar-workspace-bundle-v1",
        "snapshot_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "skills": capabilities,
        "files": files_meta,
    }
    with open(bundle / "index.json", "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=2)
        fh.write("\n")

    with open(bundle / "checksums.sha256", "w", encoding="utf-8") as fh:
        for item in files_meta:
            fh.write(f"{item['sha256']}  {item['path']}\n")

    bundle_hash = hashlib.sha256()
    for item in sorted(files_meta, key=lambda x: x["path"]):
        bundle_hash.update(item["path"].encode())
        bundle_hash.update(item["sha256"].encode())

    return {
        "checksum": bundle_hash.hexdigest(),
        "file_count": len(files_meta),
        "skill_count": len(capabilities),
        "skills": capabilities,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--core-src", required=True)
    parser.add_argument("--bundle-dir", required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    result = build(
        Path(args.workspace),
        Path(args.core_src),
        Path(args.bundle_dir),
        args.check_only,
    )
    if args.check_only:
        print(
            f"CHECK: would bundle {result['skills']} skills, "
            f"{result['agents']} agents, {result['commands']} commands "
            f"(extra scripts={result['extra_scripts']})"
        )
        return 0
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
