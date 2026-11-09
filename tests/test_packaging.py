"""Every package of the application is in the installed image. `packages` in pyproject.toml is an explicit list, so a new package
that is not added to it works from a checkout and then fails in the image with "No module named"."""

import pathlib
import tomllib

ROOT = pathlib.Path(__file__).parent.parent


def test_every_package_in_the_source_is_listed_for_installation():
    listed = set(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]["packages"])
    found = {".".join(path.parent.relative_to(ROOT).parts) for path in (ROOT / "northstar").rglob("__init__.py")
             if "__pycache__" not in path.parts and "spa" not in path.parts}
    assert found == listed, f"packages in the source but not in pyproject.toml: {sorted(found - listed)}; listed but missing: {sorted(listed - found)}"
