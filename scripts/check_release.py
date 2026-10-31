"""The checks the release workflow runs before it publishes anything.

    python scripts/check_release.py TAG [--notes-file FILE]

Given the pushed tag (v0.1.0, or v0.1.0-rc.1 for a release candidate) it checks that the version in
pyproject.toml and frontend/package.json is the tag's version, that CHANGELOG.md has a section to publish as the
release notes, and works out which image tags the release gets. It fails with a message when something is wrong,
and otherwise writes version, prerelease and tags to the workflow's outputs.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-rc\.([1-9]\d*))?$")


class ReleaseError(Exception):
    """Something is wrong with the release. The message says what and is written to be read in the workflow log."""


@dataclass(frozen=True)
class Release:
    tag: str
    numbers: tuple[int, int, int]
    candidate: int | None

    @property
    def base(self) -> str:
        return ".".join(map(str, self.numbers))

    @property
    def is_prerelease(self) -> bool:
        return self.candidate is not None

    @property
    def python(self) -> str:
        """The spelling in pyproject.toml: 0.1.0rc1."""
        return self.base + (f"rc{self.candidate}" if self.is_prerelease else "")

    @property
    def npm(self) -> str:
        """The spelling in package.json: 0.1.0-rc.1."""
        return self.base + (f"-rc.{self.candidate}" if self.is_prerelease else "")

    @property
    def docker(self) -> str:
        """The image tag: the tag without its v."""
        return self.npm


def parse_tag(tag: str) -> Release:
    match = TAG.match(tag)
    if not match:
        raise ReleaseError(f"{tag!r} is not a version tag. Use vX.Y.Z, or vX.Y.Z-rc.N for a release candidate.")
    major, minor, patch, candidate = match.groups()
    return Release(tag, (int(major), int(minor), int(patch)), int(candidate) if candidate else None)


def check_versions(release: Release, python: str, npm: str) -> None:
    for name, found, wanted in (("pyproject.toml", python, release.python), ("package.json", npm, release.npm)):
        if found != wanted:
            raise ReleaseError(f"The tag {release.tag} does not match {name}: {name} says {found}, "
                               f"and the tag means {wanted}. Change the version in a pull request first, then tag.")


def release_notes(changelog: str, release: Release) -> str:
    """The text of the changelog section for the release's version. A release candidate uses the section of the
    version it leads up to, and may still have a TODO date. A final release may not."""
    headings = list(re.finditer(r"^## \[(.+?)\](.*)$", changelog, re.M))
    for index, heading in enumerate(headings):
        if heading.group(1) != release.base:
            continue
        if "TODO" in heading.group(2) and not release.is_prerelease:
            raise ReleaseError(f"CHANGELOG.md still says {heading.group(2).strip(' -')!r} for {release.base}. "
                               "Put in the real release date in a pull request first.")
        end = headings[index + 1].start() if index + 1 < len(headings) else len(changelog)
        notes = changelog[heading.end():end].strip()
        if not notes:
            raise ReleaseError(f"The CHANGELOG.md section for {release.base} is empty.")
        return notes
    raise ReleaseError(f"CHANGELOG.md has no section for {release.base}.")


def _stable_numbers(tags: list[str]) -> list[tuple[int, int, int]]:
    """The versions of the final releases among the tags. Release candidates and other tags do not count."""
    found = []
    for tag in tags:
        match = TAG.match(tag.strip())
        if match and match.group(4) is None:
            found.append(tuple(int(number) for number in match.groups()[:3]))
    return found


def image_tags(release: Release, existing_tags: list[str]) -> list[str]:
    """A release candidate gets only its own tag. A final release gets X.Y.Z, and also X.Y and latest unless a higher
    version already holds them, so a late patch of an older version never moves latest backwards. Numbers are
    compared as numbers, so 0.10.0 is higher than 0.9.0."""
    if release.is_prerelease:
        return [release.docker]
    others = [numbers for numbers in _stable_numbers(existing_tags) if numbers != release.numbers]
    mine = release.numbers
    tags = [release.docker]
    if all(mine > other for other in others if other[:2] == mine[:2]):
        tags.append(f"{mine[0]}.{mine[1]}")
    if all(mine > other for other in others):
        tags.append("latest")
    return tags


@dataclass(frozen=True)
class Result:
    version: str
    prerelease: bool
    image_tags: list[str]
    notes: str


def check(tag: str, pyproject: Path, package: Path, changelog: Path, existing_tags: list[str]) -> Result:
    release = parse_tag(tag)
    python = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    npm = json.loads(package.read_text(encoding="utf-8"))["version"]
    check_versions(release, python, npm)
    notes = release_notes(changelog.read_text(encoding="utf-8"), release)
    return Result(python, release.is_prerelease, image_tags(release, existing_tags), notes)


def _git_tags() -> list[str]:
    done = subprocess.run(["git", "tag", "--list", "v*"], capture_output=True, text=True, check=True)
    return done.stdout.split()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a release tag before the release workflow publishes it.")
    parser.add_argument("tag")
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--package", type=Path, default=Path("frontend/package.json"))
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    parser.add_argument("--existing-tags", help="comma-separated tags already in the repository (default: ask git)")
    parser.add_argument("--notes-file", type=Path, help="write the release notes here")
    args = parser.parse_args(argv)
    try:
        existing = _git_tags() if args.existing_tags is None else [t for t in args.existing_tags.split(",") if t]
        result = check(args.tag, args.pyproject, args.package, args.changelog, existing)
    except ReleaseError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    if args.notes_file:
        args.notes_file.write_text(result.notes + "\n", encoding="utf-8")
    print(f"{args.tag}: version {result.version}, {'pre-release' if result.prerelease else 'final release'}, "
          f"image tags {', '.join(result.image_tags)}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"version={result.version}\nprerelease={str(result.prerelease).lower()}\n"
                         f"tags={','.join(result.image_tags)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
