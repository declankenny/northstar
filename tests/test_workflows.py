"""Rules every GitHub Actions workflow in the repository keeps. The workflows themselves can only run on GitHub, so
these read them as text."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def test_there_are_workflows_to_check():
    assert {path.name for path in WORKFLOWS} >= {"ci.yml", "release.yml"}


def test_every_action_is_pinned_to_a_commit_and_says_which_version_that_is():
    for path in WORKFLOWS:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.search(r"^\s*-?\s*uses:\s*(\S+)(.*)$", line)
            if not match or match.group(1).startswith("./"):
                continue
            assert re.search(r"@[0-9a-f]{40}$", match.group(1)), f"{path.name}: {match.group(1)} is not pinned to a commit"
            assert re.search(r"#\s*v\d", match.group(2)), f"{path.name}: {match.group(1)} does not name its version"


def test_no_script_step_puts_a_github_expression_in_the_shell_text():
    """An expression such as ${{ github.head_ref }} in a run block is pasted into the script before it runs, so whoever
    controls that text controls the script. Values reach scripts as environment variables instead."""
    for path in WORKFLOWS:
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, 1):
            if re.match(r"\s*run:\s*[|>]?-?\s*$", line) or re.match(r"\s*run:\s*\S", line):
                indent = len(line) - len(line.lstrip())
                block = [line]
                for following in lines[number:]:
                    if following.strip() and len(following) - len(following.lstrip()) <= indent:
                        break                  # the next key: the run block is over
                    block.append(following)
                assert not any("${{" in text for text in block), f"{path.name}:{number} has an expression in a run block"


def test_the_release_runs_only_for_version_tags_and_asks_for_the_least_it_needs():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert re.search(r'on:\n  push:\n    tags: \["v\*"\]', text)
    assert re.search(r"^permissions:\n  contents: read$", text, re.M)       # read-only unless a job says otherwise
    assert text.count("packages: write") == 1 and text.count("contents: write") == 1
    assert "pull_request" not in text


def test_the_release_runs_the_tests_and_publishes_only_after_the_checks_and_tests_pass():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "uses: ./.github/workflows/ci.yml" in text
    assert re.search(r"image:\n(?:.*\n)*?    needs: \[check, tests\]", text)
    assert re.search(r"release:\n(?:.*\n)*?    needs: \[check, image\]", text)


def test_the_release_builds_both_architectures_with_provenance_and_never_reuses_a_version():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "platforms: linux/amd64,linux/arm64" in text
    assert "provenance: mode=max" in text
    assert "gh release view" in text and "imagetools inspect" in text      # refuses a version that already exists


def test_ci_can_be_called_by_the_release_and_the_frontend_is_built_on_the_build_machine():
    assert "workflow_call:" in (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^FROM --platform=\$BUILDPLATFORM node:", dockerfile, re.M)
