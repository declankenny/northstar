"""The browser tab icon. It must load on the sign-in page too, where the browser has no session."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PAGES = [ROOT / "frontend" / "index.html", ROOT / "northstar" / "web" / "templates" / "login.html"]
ICONS = ["favicon.ico", "favicon.svg", "favicon-32x32.png", "favicon-16x16.png", "apple-touch-icon.png"]


@pytest.mark.parametrize("name", ICONS)
def test_every_icon_is_served_to_a_signed_out_browser_as_an_image(anon_client, name):
    response = anon_client.get(f"/static/{name}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")
    assert len(response.content) > 100


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_both_entry_points_link_the_icons_that_are_served(page):
    html = page.read_text(encoding="utf-8")
    linked = set(re.findall(r'<link rel="(?:icon|apple-touch-icon)" href="/static/([^"]+)"', html))
    assert linked == set(ICONS), page.name


def test_the_sign_in_page_names_its_icons(anon_client):
    page = anon_client.get("/login").text
    assert 'href="/static/favicon.svg"' in page
