"""One version, in pyproject.toml, shown by the app and carried by the image. And the CHANGELOG that goes with it."""

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def declared_version():
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def test_the_app_reports_the_version_declared_in_pyproject():
    from northstar import version
    assert version.VERSION == declared_version()


def test_the_version_endpoint_gives_the_version_to_a_signed_in_user(client):
    response = client.get("/api/version")
    assert response.status_code == 200 and response.json() == {"version": declared_version()}


def test_the_version_endpoint_needs_a_signed_in_user(anon_client):
    assert anon_client.get("/api/version").status_code == 401


def test_the_frontend_package_declares_the_same_version():
    """The one other place a version is written, so it cannot drift from the real one. A release candidate is
    0.1.0rc1 in Python and 0.1.0-rc.1 in npm."""
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert package["version"] == re.sub(r"rc(\d+)$", r"-rc.\1", declared_version())


def test_the_image_carries_the_version_as_a_label():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^ARG VERSION=unknown$", dockerfile, re.M)
    assert re.search(r"^LABEL org\.opencontainers\.image\.version=\"\$\{VERSION\}\"", dockerfile, re.M)


# -- the changelog --

def changelog():
    return (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_the_changelog_has_an_unreleased_section_and_a_section_for_this_version():
    text = changelog()
    assert re.search(r"^## \[Unreleased\]$", text, re.M)
    # A release candidate (0.1.0rc1) is listed under the version it leads up to (0.1.0). Until the release is made
    # the date is a TODO, and the release workflow refuses a final tag while one remains.
    base = declared_version().split("rc")[0]
    assert re.search(rf"^## \[{re.escape(base)}\] - (\d{{4}}-\d{{2}}-\d{{2}}|TODO release date)$", text, re.M), \
        f"CHANGELOG.md has no section for {base}"


def test_the_changelog_says_what_is_breaking_in_each_released_version():
    """Migrations, environment variables and the backup format always count as breaking before 1.0."""
    sections = re.split(r"^## \[", changelog(), flags=re.M)[1:]
    for section in sections:
        if section.startswith("Unreleased"):
            continue
        assert "### Breaking" in section, f"the section starting {section[:12]!r} has no Breaking heading"
