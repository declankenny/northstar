"""The operator guide and the README must keep up with the code: every setting is explained, every command names a
real module, and every link goes somewhere."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = (ROOT / "docs" / "operating.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_guide_explains_every_setting_the_compose_file_and_the_code_read():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    code = "".join(path.read_text(encoding="utf-8") for path in (ROOT / "northstar").rglob("*.py"))
    settings = set(re.findall(r"\$\{([A-Z_]+)", compose)) | set(re.findall(r"environ(?:\.get)?\(\"([A-Z_]+)\"", code))
    settings |= {"FORWARDED_ALLOW_IPS"}     # read by the web server, not by our code
    assert {"TZ", "NORTHSTAR_PORT", "NORTHSTAR_COOKIE_SECURE", "NORTHSTAR_DB", "FORWARDED_ALLOW_IPS"} <= settings
    for setting in settings:
        assert re.search(rf"^\| `{setting}` \|", GUIDE, re.M), f"docs/operating.md does not explain {setting}"


def test_every_command_in_the_docs_runs_a_module_that_exists():
    for text in (GUIDE, README):
        for module in re.findall(r"python -m (northstar(?:\.\w+)*)", text):
            assert (ROOT / (module.replace(".", "/") + ".py")).is_file(), f"{module} does not exist"


def test_the_commands_name_real_subcommands():
    assert set(re.findall(r"northstar\.users (\w[\w-]*)", GUIDE + README)) <= {"create", "list", "set-password"}
    assert set(re.findall(r"northstar\.backup (\w+)", GUIDE)) <= {"create", "restore"}


def test_links_between_the_documents_point_at_files_that_exist():
    for name, text, base in (("README.md", README, ROOT), ("docs/operating.md", GUIDE, ROOT / "docs")):
        for target in re.findall(r"\]\(([^)#]+?)(?:#[^)]*)?\)", text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            assert (base / target).exists(), f"{name} links to {target}, which does not exist"


def test_the_traefik_example_keeps_names_as_placeholders_and_publishes_no_port():
    example = re.search(r"```yaml\n(services:.*?)```", GUIDE, re.S).group(1)
    assert "ports:" not in example
    for placeholder in ("NETWORK", "ENTRYPOINT", "CERT_RESOLVER"):
        assert placeholder in example
    assert 'NORTHSTAR_COOKIE_SECURE: "1"' in example and "FORWARDED_ALLOW_IPS" in example


def test_the_backup_script_in_the_guide_never_reuses_a_file_name():
    """The tool refuses an existing file, so a manual backup and the nightly one on the same day must differ."""
    script = re.search(r"```sh\n(#!/bin/sh.*?)```", GUIDE, re.S).group(1)
    assert "$(date +%F-%H%M)" in script
