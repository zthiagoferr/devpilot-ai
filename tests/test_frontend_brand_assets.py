"""Contract tests for the official DevPilot AI brand identity assets.

The identity is shipped as static raster assets under ``frontend/public`` and is
published to GitHub Pages, where every URL in ``index.html`` must resolve to a
file that exists in the build artifact. These tests pin:

* the icon/manifest links declared by ``frontend/src/index.html``;
* the ICO container (signature, three frames, and a new hash);
* the PNG headers of every derived icon (dimensions, mark budget);
* the web app manifest values and its icon references;
* the byte budget of the published assets and the absence of the raw logo;
* the shell template using the raster mark while the functional sparkles icons
  stay untouched.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "frontend" / "public"
INDEX_HTML = ROOT / "frontend" / "src" / "index.html"
SHELL_HTML = ROOT / "frontend" / "src" / "app" / "features" / "shell" / "app-shell.component.html"
MANIFEST = PUBLIC / "manifest.webmanifest"

LEGACY_FAVICON_MD5 = "05bcfe9a02b93e1c5a5da14bfda8c41f"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ICON_SIZES = {"icon-192.png": 192, "icon-512.png": 512, "apple-touch-icon.png": 180}
MARK = PUBLIC / "brand" / "mark-128.png"
FAVICON = PUBLIC / "favicon.ico"

# Templates that legitimately keep the inline `sparkles` icon (functional use).
FUNCTIONAL_SPARKLES_TEMPLATES = (
    "frontend/src/app/features/auth/auth-dialog.component.html",
    "frontend/src/app/features/analysis/new/analysis-new.component.html",
    "frontend/src/app/features/analysis/new/repository-analysis.component.html",
    "frontend/src/app/shared/components/issue-list/issue-list.component.html",
    "frontend/src/app/shared/components/correction-panel/correction-panel.component.html",
    "frontend/src/app/shared/components/correction-batch-panel/correction-batch-panel.component.html",
)


class _AssetCollector(HTMLParser):
    """Collect every ``<link>`` and ``<script>`` tag with its attributes."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"link", "script"}:
            self.tags.append((tag.lower(), {name: value for name, value in attrs}))


def _parse_assets() -> list[tuple[str, dict[str, str | None]]]:
    parser = _AssetCollector()
    parser.feed(INDEX_HTML.read_text(encoding="utf-8"))
    return parser.tags


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == PNG_SIGNATURE, f"{path.name} is not a PNG"
    length, chunk_type = struct.unpack(">I4s", data[8:16])
    assert chunk_type == b"IHDR", f"{path.name} has no IHDR chunk"
    assert length == 13
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def test_index_html_references_existing_relative_assets() -> None:
    tags = _parse_assets()
    assert tags, "index.html must reference the favicon, manifest and config.js"

    for _tag, attrs in tags:
        target = attrs.get("href") or attrs.get("src")
        if target is None:
            continue
        assert not target.lower().endswith(".svg"), f"SVG assets are not allowed: {target}"
        assert not re.match(r"^(?:[a-z][a-z0-9+.-]*:|//|/)", target, re.IGNORECASE), (
            f"index.html must use relative asset URLs: {target}"
        )
        resolved = (PUBLIC / target.split("?", 1)[0]).resolve()
        assert resolved.is_file(), f"missing published asset for {target}"
        assert str(resolved).startswith(str(PUBLIC.resolve()))


def test_index_html_declares_icon_touch_icon_and_manifest() -> None:
    tags = _parse_assets()
    rels = {
        (attrs.get("rel") or "").lower(): attrs
        for tag, attrs in tags
        if tag == "link" and attrs.get("rel")
    }

    assert rels["icon"].get("href") == "favicon.ico"
    assert rels["apple-touch-icon"].get("href") == "apple-touch-icon.png"
    assert rels["apple-touch-icon"].get("sizes") == "180x180"
    assert rels["manifest"].get("href") == "manifest.webmanifest"


def test_favicon_is_a_new_three_frame_ico() -> None:
    data = FAVICON.read_bytes()

    reserved, image_type, count = struct.unpack("<HHH", data[:6])
    assert reserved == 0
    assert image_type == 1
    assert count == 3

    sizes = set()
    for index in range(count):
        entry = data[6 + index * 16 : 6 + (index + 1) * 16]
        width_byte, height_byte = entry[0], entry[1]
        sizes.add((width_byte or 256, height_byte or 256))

    assert sizes == {(16, 16), (32, 32), (48, 48)}
    assert hashlib.md5(data).hexdigest() != LEGACY_FAVICON_MD5


def test_derived_icons_are_pngs_with_expected_dimensions() -> None:
    for name, expected in ICON_SIZES.items():
        assert _png_dimensions(PUBLIC / name) == (expected, expected), name

    assert _png_dimensions(MARK) == (128, 128)


def test_brand_mark_stays_within_its_budget() -> None:
    assert MARK.stat().st_size <= 20 * 1024


def test_manifest_is_valid_and_points_to_published_icons() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["theme_color"] == "#0A0A0A"
    assert manifest["background_color"] == "#0A0A0A"
    assert manifest["start_url"] == "./"
    assert manifest["scope"] == "./"
    assert manifest["lang"] == "pt-BR"

    icons = manifest["icons"]
    assert {icon["sizes"] for icon in icons} == {"192x192", "512x512"}
    for icon in icons:
        src = icon["src"]
        assert not re.match(r"^(?:[a-z][a-z0-9+.-]*:|//|/)", src, re.IGNORECASE), src
        assert (PUBLIC / src).resolve().is_file(), f"missing manifest icon {src}"
        assert icon["type"] == "image/png"
        assert icon["purpose"] == "any"


def test_published_assets_respect_the_size_budget() -> None:
    icon_files = [FAVICON, MARK, PUBLIC / "apple-touch-icon.png", *(
        PUBLIC / name for name in ICON_SIZES
    )]
    total = sum(path.stat().st_size for path in icon_files)
    assert total <= 500 * 1024, f"icon budget exceeded: {total} bytes"

    for path in PUBLIC.rglob("*"):
        if path.is_file():
            assert path.stat().st_size <= 300 * 1024, f"oversized published asset: {path.name}"

    raw_logo = "Logo futurista DevPilot AI.png"
    assert not (PUBLIC / raw_logo).exists()
    assert not [path for path in PUBLIC.rglob("*") if path.name == raw_logo]


def test_shell_uses_the_raster_mark_instead_of_the_sparkles_icon() -> None:
    template = SHELL_HTML.read_text(encoding="utf-8")

    img_mark = r'<img\b(?=[^>]*\bsrc="brand/mark-128\.png")(?=[^>]*\balt="")[^>]*>'
    brand_chip = re.search(
        r'<a\b[^>]*\bclass="[^"]*content__footer-chip--brand[^"]*"[^>]*>(.*?)</a>',
        template,
        re.S,
    )
    assert brand_chip, "top dock brand chip must use the mark"
    assert len(re.findall(img_mark, brand_chip.group(1))) == 1, (
        "top dock brand chip must use exactly one raster mark"
    )
    assert "DevPilot AI" in brand_chip.group(1)
    assert 'name="sparkles"' not in template

    for relative in FUNCTIONAL_SPARKLES_TEMPLATES:
        content = (ROOT / relative).read_text(encoding="utf-8")
        assert 'name="sparkles"' in content, f"functional sparkles icon removed from {relative}"

    functional_total = sum(
        (ROOT / relative).read_text(encoding="utf-8").count('name="sparkles"')
        for relative in FUNCTIONAL_SPARKLES_TEMPLATES
    )
    assert functional_total == 8
