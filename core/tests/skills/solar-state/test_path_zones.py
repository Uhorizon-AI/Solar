"""Zone of a declared path: the hard cases (links, prefixes, `..`, case, missing targets, nesting)."""
from __future__ import annotations

import os
import sys

import pytest

import path_zones as z


@pytest.fixture
def tree(tmp_path):
    ws = tmp_path / "ws"
    planet = ws / "planets" / "acme"
    inst_copy = ws / "planets" / "solar" / "core"
    glob_inst = tmp_path / "home" / ".local" / "share" / "solar" / "core"
    for d in (planet, inst_copy, glob_inst, tmp_path / "outside"):
        d.mkdir(parents=True)
    return dict(ws=ws, planet=planet, inst_copy=inst_copy, glob_inst=glob_inst, out=tmp_path / "outside",
                tmp=tmp_path,
                roots=dict(workspace=str(ws), installation_roots=[str(inst_copy), str(glob_inst)],
                           planet_roots=[str(planet), str(ws / "planets" / "solar")]))


def zone(tree, path):
    return z.zone_of(str(path), **tree["roots"])


def test_each_zone(tree):
    assert zone(tree, tree["glob_inst"] / "skills") == z.INSTALLATION
    assert zone(tree, tree["planet"] / "kb") == z.PLANET
    assert zone(tree, tree["ws"] / "sun" / "plans") == z.WORKSPACE
    assert zone(tree, tree["out"]) == z.OUTSIDE


def test_installation_inside_a_planet_inside_the_workspace_is_installation(tree):
    assert zone(tree, tree["inst_copy"] / "skills") == z.INSTALLATION
    assert zone(tree, tree["ws"] / "planets" / "solar" / "docs") == z.PLANET


def test_whole_directory_not_text_prefix(tree):
    sibling = tree["ws"].parent / (tree["ws"].name + "-evil")
    sibling.mkdir()
    assert zone(tree, sibling) == z.OUTSIDE
    lookalike = tree["ws"] / "planets" / "acme-other"
    lookalike.mkdir()
    assert zone(tree, lookalike) == z.WORKSPACE


def test_a_folder_called_planets_is_not_a_planet(tree):
    fake = tree["ws"] / "sun" / "planets" / "acme"
    fake.mkdir(parents=True)
    assert zone(tree, fake) == z.WORKSPACE


def test_dotdot_cannot_escape_or_fake_a_zone(tree):
    assert zone(tree, tree["ws"] / "sun" / ".." / ".." / "outside") == z.OUTSIDE
    assert zone(tree, tree["ws"] / "planets" / "acme" / ".." / "..") == z.WORKSPACE


def test_symlink_inside_pointing_outside_is_outside(tree):
    link = tree["ws"] / "innocent"
    os.symlink(tree["out"], link)
    assert zone(tree, link / "secret") == z.OUTSIDE


def test_symlink_outside_pointing_inside_is_inside(tree):
    link = tree["out"] / "shortcut"
    os.symlink(tree["planet"], link)
    assert zone(tree, link) == z.PLANET


def test_missing_target_uses_nearest_existing_ancestor(tree):
    assert zone(tree, tree["planet"] / "not" / "yet" / "there.md") == z.PLANET
    assert zone(tree, tree["out"] / "not" / "yet") == z.OUTSIDE


def test_missing_target_below_a_symlink_follows_the_link(tree):
    link = tree["ws"] / "ln"
    os.symlink(tree["out"], link)
    assert zone(tree, link / "new" / "file") == z.OUTSIDE


@pytest.mark.skipif(sys.platform != "darwin", reason="case-insensitive filesystem convention of macOS")
def test_case_differences_do_not_change_the_zone_on_macos(tree):
    upper = str(tree["ws"]).upper() + "/SUN"
    assert z.zone_of(upper, **tree["roots"]) == z.WORKSPACE


def test_case_is_significant_when_not_case_insensitive(tree):
    upper = str(tree["planet"]).upper()
    assert z.zone_of(upper, case_insensitive=False, **tree["roots"]) == z.OUTSIDE


def test_aggregate_is_the_outermost(tree):
    assert z.aggregate_zone([z.INSTALLATION, z.PLANET]) == z.PLANET
    assert z.aggregate_zone([z.PLANET, z.OUTSIDE, z.INSTALLATION]) == z.OUTSIDE
    assert z.aggregate_zone([z.WORKSPACE]) == z.WORKSPACE


def test_no_paths_defaults_to_workspace():
    assert z.aggregate_zone([]) == z.WORKSPACE


def test_mixed_paths_show_aggregate_and_each_path(tree):
    mixed = [str(tree["glob_inst"] / "a"), str(tree["out"] / "b")]
    got = z.describe(mixed, **tree["roots"])
    assert got["zone"] == z.OUTSIDE
    assert got["paths"] == [(mixed[0], z.INSTALLATION), (mixed[1], z.OUTSIDE)]


def test_impact_uses_physical_containment_not_zone_name(tree):
    ws = str(tree["ws"])
    assert not z.physically_inside_workspace(str(tree["glob_inst"]), ws)
    assert z.physically_inside_workspace(str(tree["inst_copy"]), ws)
    assert z.physically_inside_workspace(str(tree["planet"]), ws)


def test_global_installation_plus_workspace_aggregates_to_outside(tree):
    got = z.describe([str(tree["ws"] / "sun"), str(tree["glob_inst"])], **tree["roots"])
    assert got["zone"] == z.OUTSIDE
    assert [zone for _, zone in got["paths"]] == [z.WORKSPACE, z.INSTALLATION]


def test_a_planet_linked_outside_the_workspace_is_outside(tree):
    linked = tree["ws"] / "planets" / "linked"
    os.symlink(tree["out"], linked)
    roots = dict(tree["roots"], planet_roots=tree["roots"]["planet_roots"] + [str(linked)])
    assert z.zone_of(str(linked / "kb"), **roots) == z.OUTSIDE
