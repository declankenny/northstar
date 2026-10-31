"""The files a user runs Northstar from: the Dockerfile health check, the user compose file, the developer
compose file and the sample .env. They are plain text here; CI starts the real image (see ci.yml)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def variables(text):
    """The names Compose substitutes, from ${NAME} and ${NAME:-default}."""
    return set(re.findall(r"\$\{([A-Z_]+)", text))


# -- the health check --

def test_the_sign_in_page_is_public_and_answers_200(anon_client):
    """The health check asks for it with no cookie, so it must not redirect or need a user."""
    assert anon_client.get("/login").status_code == 200


def test_the_image_has_a_health_check_that_asks_the_sign_in_page_without_curl():
    dockerfile = read("Dockerfile")
    check = re.search(r"^HEALTHCHECK\b.*?(?=^\S|\Z)", dockerfile, re.M | re.S)
    assert check, "the Dockerfile has no HEALTHCHECK"
    assert "/login" in check.group(0) and "urllib" in check.group(0) and "curl" not in check.group(0)


def test_the_image_runs_as_a_non_root_user():
    assert re.search(r"^USER northstar$", read("Dockerfile"), re.M)


# -- the user compose file --

def test_the_user_compose_file_uses_the_published_image_and_never_builds():
    compose = read("compose.yaml")
    assert re.search(r"^\s+image: ghcr\.io/declankenny/northstar:latest$", compose, re.M)
    assert not re.search(r"^\s+build:", compose, re.M)


def test_the_user_compose_file_binds_to_this_machine_only_and_keeps_data_in_a_volume():
    compose = read("compose.yaml")
    assert '"127.0.0.1:${NORTHSTAR_PORT:-8000}:8000"' in compose
    assert "northstar-data:/data" in compose


def test_the_user_compose_file_is_secure_by_default():
    """The cookie flag defaults to 1, also when .env sets it to nothing, and the container is locked down."""
    compose = read("compose.yaml")
    assert "NORTHSTAR_COOKIE_SECURE: ${NORTHSTAR_COOKIE_SECURE:-1}" in compose
    assert "no-new-privileges:true" in compose
    assert re.search(r"cap_drop:\s*\n\s*- ALL", compose)


def test_the_timezone_defaults_to_utc():
    assert "TZ: ${TZ:-UTC}" in read("compose.yaml")


def test_every_setting_the_compose_file_reads_is_in_the_sample_env_with_a_value():
    sample = {}
    for line in read(".env.example").splitlines():
        name, separator, value = line.partition("=")
        assert separator and value, f"{line!r} in .env.example has no value"
        sample[name] = value
    assert variables(read("compose.yaml")) == set(sample)


def test_the_sample_env_holds_only_values_and_no_secrets():
    for line in read(".env.example").splitlines():
        assert re.fullmatch(r"[A-Z_]+=[^\s#]+", line), f"{line!r} is not a plain NAME=value line"


def test_the_sample_env_agrees_with_the_compose_defaults():
    compose, sample = read("compose.yaml"), dict(line.split("=") for line in read(".env.example").splitlines())
    for name, value in sample.items():
        assert f"${{{name}:-{value}}}" in compose, f"{name} defaults differently in compose.yaml and .env.example"


# -- the developer compose file --

def test_the_developer_compose_file_builds_from_source_with_the_same_service_and_volume():
    user, dev = read("compose.yaml"), read("compose.dev.yaml")
    assert re.search(r"^\s+build: \.$", dev, re.M)
    assert "image: ghcr.io" not in dev
    for shared in ("  northstar:\n", "northstar-data:/data", "127.0.0.1:${NORTHSTAR_PORT:-8000}:8000"):
        assert shared in user and shared in dev
