"""The files GitHub's community profile looks for, and what the templates must say."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_the_community_files_exist():
    for name in ("CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md", "LICENSE", "CHANGELOG.md",
                 ".github/pull_request_template.md", ".github/ISSUE_TEMPLATE/bug_report.yml",
                 ".github/ISSUE_TEMPLATE/feature_request.yml", ".github/ISSUE_TEMPLATE/config.yml"):
        assert (ROOT / name).is_file(), f"{name} is missing"


def test_the_pull_request_template_has_the_three_sections_the_pull_requests_use():
    template = read(".github/pull_request_template.md")
    for heading in ("## What changed", "## Verified", "## Not verified"):
        assert heading in template


def test_issue_templates_send_security_reports_to_private_reporting():
    config = read(".github/ISSUE_TEMPLATE/config.yml")
    assert "https://github.com/declankenny/northstar/security/advisories/new" in config
    for template in ("bug_report.yml", "feature_request.yml"):
        text = read(f".github/ISSUE_TEMPLATE/{template}")
        assert re.search(r"^name: .+$", text, re.M) and re.search(r"^description: .+$", text, re.M)
        assert "body:" in text


def test_the_bug_template_asks_for_the_version_and_for_synthetic_data_only():
    text = read(".github/ISSUE_TEMPLATE/bug_report.yml").lower()
    assert "version" in text and "synthetic" in text


def test_contributing_covers_branches_tests_the_spec_and_the_changelog():
    text = read("CONTRIBUTING.md")
    for needed in ("feature/", "fix/", "docs/spec.md", "docs/decisions.md", "CHANGELOG.md", "pytest", "npm test"):
        assert needed in text, f"CONTRIBUTING.md does not mention {needed}"


def test_the_code_of_conduct_has_a_contact_and_credits_the_contributor_covenant():
    text = read("CODE_OF_CONDUCT.md")
    assert "https://github.com/declankenny/northstar/security/advisories/new" in text
    assert "Contributor Covenant" in text and "https://www.contributor-covenant.org" in text
