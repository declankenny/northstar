"""The checks the release workflow runs before it publishes anything (scripts/check_release.py)."""

import json
from pathlib import Path

import pytest

from scripts import check_release as cr

CHANGELOG = """# Changelog

## [Unreleased]

- Something new.

## [0.2.0] - 2026-12-01

### Breaking

Nothing.

### Added

- Two things.

## [0.1.0] - TODO release date

### Breaking

Nothing: first version.
"""


# -- reading a tag --

@pytest.mark.parametrize("tag, python, npm, docker, pre", [
    ("v0.1.0", "0.1.0", "0.1.0", "0.1.0", False),
    ("v12.3.45", "12.3.45", "12.3.45", "12.3.45", False),
    ("v0.1.0-rc.1", "0.1.0rc1", "0.1.0-rc.1", "0.1.0-rc.1", True),
    ("v1.2.3-rc.10", "1.2.3rc10", "1.2.3-rc.10", "1.2.3-rc.10", True),
])
def test_a_tag_gives_each_ecosystems_spelling_of_the_same_version(tag, python, npm, docker, pre):
    release = cr.parse_tag(tag)
    assert (release.python, release.npm, release.docker, release.is_prerelease) == (python, npm, docker, pre)


@pytest.mark.parametrize("tag", ["0.1.0", "v0.1", "v0.1.0.1", "v01.1.0", "v0.1.0-beta.1", "v0.1.0-rc1", "v0.1.0-rc.0",
                                 "v0.1.0+build", "latest", "", "vx.y.z", "v0.1.0-rc.1-extra"])
def test_a_tag_that_is_not_a_version_is_refused(tag):
    with pytest.raises(cr.ReleaseError, match="not a version tag"):
        cr.parse_tag(tag)


# -- the version must match --

def test_the_versions_in_the_files_must_equal_the_tag():
    release = cr.parse_tag("v0.1.0-rc.1")
    cr.check_versions(release, python="0.1.0rc1", npm="0.1.0-rc.1")
    with pytest.raises(cr.ReleaseError, match="pyproject.toml says 0.1.0"):
        cr.check_versions(release, python="0.1.0", npm="0.1.0-rc.1")
    with pytest.raises(cr.ReleaseError, match="package.json says 0.1.0"):
        cr.check_versions(release, python="0.1.0rc1", npm="0.1.0")


# -- the changelog is the release notes --

def test_the_notes_are_the_changelog_section_of_the_version_without_the_next_one():
    notes = cr.release_notes(CHANGELOG, cr.parse_tag("v0.2.0"))
    assert notes.startswith("### Breaking") and "Two things." in notes
    assert "Something new" not in notes and "first version" not in notes


def test_a_release_candidate_uses_the_section_of_its_final_version():
    assert "first version" in cr.release_notes(CHANGELOG, cr.parse_tag("v0.1.0-rc.2"))


def test_a_tag_without_a_changelog_section_is_refused():
    with pytest.raises(cr.ReleaseError, match="no section for 0.3.0"):
        cr.release_notes(CHANGELOG, cr.parse_tag("v0.3.0"))


def test_a_final_release_refuses_a_changelog_date_that_is_still_a_todo():
    with pytest.raises(cr.ReleaseError, match="TODO"):
        cr.release_notes(CHANGELOG, cr.parse_tag("v0.1.0"))


def test_a_release_candidate_may_have_a_changelog_date_that_is_still_a_todo():
    cr.release_notes(CHANGELOG, cr.parse_tag("v0.1.0-rc.1"))


def test_a_section_with_no_text_is_refused():
    empty = "## [Unreleased]\n\n## [0.4.0] - 2026-12-02\n\n## [0.3.0] - 2026-11-02\n\nText.\n"
    with pytest.raises(cr.ReleaseError, match="empty"):
        cr.release_notes(empty, cr.parse_tag("v0.4.0"))


# -- which image tags a release gets --

def tags(tag, existing):
    return cr.image_tags(cr.parse_tag(tag), existing)


def test_a_release_candidate_gets_only_its_own_tag():
    assert tags("v0.1.0-rc.1", []) == ["0.1.0-rc.1"]
    assert tags("v0.3.0-rc.1", ["v0.2.0"]) == ["0.3.0-rc.1"]


def test_the_first_release_gets_all_three_tags():
    assert tags("v0.1.0", []) == ["0.1.0", "0.1", "latest"]


def test_release_candidates_never_count_as_an_existing_release():
    assert tags("v0.1.0", ["v0.1.0-rc.1", "v0.2.0-rc.1"]) == ["0.1.0", "0.1", "latest"]


def test_a_new_patch_of_the_newest_minor_moves_the_minor_and_latest():
    assert tags("v0.2.1", ["v0.1.0", "v0.2.0"]) == ["0.2.1", "0.2", "latest"]


def test_a_late_patch_of_an_older_minor_does_not_move_latest():
    assert tags("v0.1.4", ["v0.1.3", "v0.2.0"]) == ["0.1.4", "0.1"]


def test_an_older_patch_never_moves_the_minor_tag_backwards():
    assert tags("v0.1.1", ["v0.1.3", "v0.2.0"]) == ["0.1.1"]


def test_versions_are_compared_as_numbers_and_not_as_text():
    assert tags("v0.10.0", ["v0.9.0"]) == ["0.10.0", "0.10", "latest"]
    assert tags("v0.9.1", ["v0.10.0"]) == ["0.9.1", "0.9"]


def test_other_tags_in_the_repository_are_ignored():
    assert tags("v0.1.0", ["nightly", "v1", "release-2"]) == ["0.1.0", "0.1", "latest"]


# -- the whole check, as the workflow runs it --

def project(tmp_path, python, npm, changelog=CHANGELOG):
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "northstar"\nversion = "{python}"\n', encoding="utf-8")
    (tmp_path / "package.json").write_text(json.dumps({"version": npm}), encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return tmp_path


def run(tag, root, existing=()):
    return cr.check(tag, pyproject=root / "pyproject.toml", package=root / "package.json",
                    changelog=root / "CHANGELOG.md", existing_tags=list(existing))


def test_a_good_release_gives_the_version_the_tags_and_the_notes(tmp_path):
    result = run("v0.2.0", project(tmp_path, "0.2.0", "0.2.0"), ["v0.1.0"])
    assert result.version == "0.2.0" and result.prerelease is False
    assert result.image_tags == ["0.2.0", "0.2", "latest"]
    assert "Two things." in result.notes


def test_a_tag_that_does_not_match_the_files_stops_the_release(tmp_path):
    with pytest.raises(cr.ReleaseError, match="does not match"):
        run("v0.2.1", project(tmp_path, "0.2.0", "0.2.0"))


def test_the_command_line_reports_a_problem_as_a_message_and_a_failure(tmp_path, capsys):
    root = project(tmp_path, "0.2.0", "0.2.0")
    code = cr.main(["v0.2.1", "--pyproject", str(root / "pyproject.toml"), "--package", str(root / "package.json"),
                    "--changelog", str(root / "CHANGELOG.md"), "--existing-tags", ""])
    assert code == 1 and "does not match" in capsys.readouterr().err


def test_the_command_line_writes_the_outputs_the_workflow_reads(tmp_path, monkeypatch):
    root = project(tmp_path, "0.2.0", "0.2.0")
    output, notes = tmp_path / "github_output", tmp_path / "notes.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    code = cr.main(["v0.2.0", "--pyproject", str(root / "pyproject.toml"), "--package", str(root / "package.json"),
                    "--changelog", str(root / "CHANGELOG.md"), "--existing-tags", "v0.1.0", "--notes-file", str(notes)])
    assert code == 0
    lines = output.read_text(encoding="utf-8").splitlines()
    assert "version=0.2.0" in lines and "prerelease=false" in lines
    assert "tags=0.2.0,0.2,latest" in lines
    assert "Two things." in notes.read_text(encoding="utf-8")
