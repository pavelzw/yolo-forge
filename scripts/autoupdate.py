"""Check recipes for new upstream versions and bump them.

Usage:
    python scripts/autoupdate.py check
        Print (and write to $GITHUB_OUTPUT as `updates`) a JSON list of
        {"recipe", "package", "current", "version"} for outdated recipes.
    python scripts/autoupdate.py bump <recipe-dir> <version>
        Set the new version, reset the build number, update `build_version`
        (if present) and recompute the sha256 of every source on every platform.

The upstream tag format is derived from the source URLs in the recipe, e.g.
`.../archive/refs/tags/v${{ version }}-pixi.tar.gz` only matches tags of the
form `v<version>-pixi`. Only plain numeric versions (`1.2.3`) are considered.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PLATFORMS = ["linux-64", "linux-aarch64", "osx-arm64", "win-64"]
VERSION_PLACEHOLDER = "${{ version }}"
NUMERIC_VERSION = re.compile(r"\d+(?:\.\d+)*")

# (forge, regex matching a source URL template; group 1-2 = owner/repo, group 3 = tag)
TAG_URL_PATTERNS = [
    ("github", r"github\.com/([^/]+)/([^/]+)/releases/download/([^/]+)/"),
    ("github", r"github\.com/([^/]+)/([^/]+)/archive/refs/tags/(.+?)\.(?:tar\.gz|zip)"),
    ("github", r"raw\.githubusercontent\.com/([^/]+)/([^/]+)/refs/tags/([^/]+)/"),
    ("codeberg", r"codeberg\.org/([^/]+)/([^/]+)/archive/(.+?)\.(?:tar\.gz|zip)"),
    ("codeberg", r"codeberg\.org/([^/]+)/([^/]+)/raw/tag/([^/]+)/"),
]


def api_get(url: str):
    headers = {"Accept": "application/json", "User-Agent": "yolo-forge-autoupdate"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as resp:
        return json.load(resp)


def parse_version(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def load_context(recipe: Path) -> dict:
    return yaml.safe_load(recipe.read_text()).get("context", {})


def upstream(recipe: Path) -> tuple[str, str, str, str, str]:
    """Return (forge, owner, repo, tag prefix, tag suffix) of the recipe's first versioned source."""
    text = recipe.read_text()
    for forge, pattern in TAG_URL_PATTERNS:
        for owner, repo, tag in re.findall(pattern, text):
            if VERSION_PLACEHOLDER in tag:
                prefix, _, suffix = tag.partition(VERSION_PLACEHOLDER)
                return forge, owner, repo, prefix, suffix
    raise ValueError(f"no versioned GitHub/Codeberg source URL found in {recipe}")


def list_tags(forge: str, owner: str, repo: str) -> list[str]:
    if forge == "github":
        releases = api_get(f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=100")
        if releases:
            return [r["tag_name"] for r in releases if not r["draft"] and not r["prerelease"]]
        return [t["name"] for t in api_get(f"https://api.github.com/repos/{owner}/{repo}/tags?per_page=100")]
    return [t["name"] for t in api_get(f"https://codeberg.org/api/v1/repos/{owner}/{repo}/tags?limit=50")]


def latest_version(recipe: Path) -> str | None:
    forge, owner, repo, prefix, suffix = upstream(recipe)
    tag_re = re.compile(re.escape(prefix) + f"({NUMERIC_VERSION.pattern})" + re.escape(suffix))
    versions = [m.group(1) for tag in list_tags(forge, owner, repo) if (m := tag_re.fullmatch(tag))]
    return max(versions, key=parse_version, default=None)


def check() -> list[dict]:
    updates = []
    for recipe in sorted(ROOT.glob("*/recipe.yaml")):
        name = recipe.parent.name
        try:
            current = str(load_context(recipe)["version"])
            latest = latest_version(recipe)
        except Exception as e:  # keep checking the other recipes
            print(f"::warning::{name}: could not determine latest version: {e}", file=sys.stderr)
            continue
        print(f"{name}: current={current} latest={latest}", file=sys.stderr)
        if latest is None:
            print(f"::warning::{name}: no upstream tag matches the source URL template", file=sys.stderr)
        elif parse_version(latest) > parse_version(current):
            package = yaml.safe_load(recipe.read_text())["package"]["name"]
            updates.append({"recipe": name, "package": package, "current": current, "version": latest})
    return updates


def render_sources(recipe: Path, platform: str) -> list[dict]:
    out = subprocess.run(
        ["rattler-build", "build", "--render-only", "--recipe", str(recipe), "--target-platform", platform],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    sources = []
    for variant in json.loads(out):
        sources.extend(variant["recipe"].get("source", []))
    return sources


def sha256_of_url(url: str) -> str:
    digest = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": "yolo-forge-autoupdate"})
    with urllib.request.urlopen(req) as resp:
        while chunk := resp.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def replace_once(text: str, pattern: str, repl: str, what: str) -> str:
    text, n = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE)
    if n != 1:
        raise ValueError(f"could not find {what} in recipe")
    return text


def build_version_for(recipe: Path, version: str) -> str:
    """Find the four-part build version in the release asset names (e.g. `web3270-4.3.1.5-linux-amd64`)."""
    forge, owner, repo, prefix, suffix = upstream(recipe)
    if forge != "github":
        raise ValueError("build_version is only supported for GitHub releases")
    release = api_get(f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{prefix}{version}{suffix}")
    found = {m for asset in release["assets"] for m in re.findall(r"-(\d+\.\d+\.\d+\.\d+)-", asset["name"])}
    if len(found) != 1:
        raise ValueError(f"expected exactly one build version in release assets, found {sorted(found)}")
    return found.pop()


def bump(recipe_dir: str, version: str) -> None:
    if not NUMERIC_VERSION.fullmatch(version):
        raise ValueError(f"invalid version {version!r}")
    recipe = ROOT / recipe_dir / "recipe.yaml"
    context = load_context(recipe)
    text = recipe.read_text()

    current = re.escape(str(context["version"]))
    text = replace_once(text, rf"^(  version: )([\"']?){current}\2$", rf"\g<1>\g<2>{version}\g<2>", "context version")
    text = replace_once(text, r"^(  number: )\d+$", r"\g<1>0", "build number")
    if "build_version" in context:
        build_version = build_version_for(recipe, version)
        text = replace_once(text, r"^(  build_version: ).*$", rf"\g<1>{build_version}", "build_version")
    recipe.write_text(text)

    # the rendered sources contain the new URLs but still the old hashes
    new_hashes: dict[str, str] = {}
    for platform in PLATFORMS:
        for source in render_sources(recipe, platform):
            old, url = source.get("sha256"), source.get("url")
            if not old or not url:
                continue
            print(f"hashing {url}", file=sys.stderr)
            new = sha256_of_url(url)
            if new_hashes.setdefault(old, new) != new:
                raise ValueError(f"sha256 {old} is shared by sources that now differ")

    text = recipe.read_text()
    for old, new in new_hashes.items():
        text = text.replace(old, new)
    recipe.write_text(text)


def main() -> None:
    match sys.argv[1:]:
        case ["check"]:
            updates = json.dumps(check())
            print(updates)
            if output := os.environ.get("GITHUB_OUTPUT"):
                with open(output, "a") as f:
                    f.write(f"updates={updates}\n")
        case ["bump", recipe_dir, version]:
            try:
                bump(recipe_dir, version)
            except urllib.error.HTTPError as e:
                sys.exit(f"failed to download {e.url}: {e}")
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main()
