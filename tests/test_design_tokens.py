"""Designsystem von betacodex.org (Idee 51159895): Tokens, Fonts, Kontrast."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main as main_module

STATIC = Path(__file__).resolve().parent.parent / "static"
CSS = (STATIC / "style.css").read_text(encoding="utf-8")
FONTS_CSS = STATIC / "fonts" / "fonts.css"


def _block(text, start):
    """Inhalt des {...}-Blocks, der bei `start` (Index der '{') beginnt."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i]
    raise AssertionError("unbalanced")


def _tokens(block):
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", block)}


def _light():
    return _tokens(_block(CSS, CSS.index(":root")))


def _dark():
    media = CSS.index("@media (prefers-color-scheme: dark)")
    root = CSS.index(":root", media)
    return _tokens(_block(CSS, CSS.index("{", root)))


def _rgb(value):
    value = value.strip()
    if value.startswith("#"):
        if len(value) == 4:
            value = "#" + "".join(c * 2 for c in value[1:])
        return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))
    return tuple(float(x) for x in re.findall(r"[\d.]+", value)[:3])


def _alpha(value):
    return float(re.findall(r"[\d.]+", value)[3])


def _over(fg_rgba, bg_hex):
    a = _alpha(fg_rgba)
    return tuple(a * f + (1 - a) * b for f, b in zip(_rgb(fg_rgba), _rgb(bg_hex)))


def _lum(rgb):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = (_lum(x if isinstance(x, tuple) else _rgb(x)) for x in (a, b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


LIGHT_EXPECTED = {
    "--color-bg": "#ffffff", "--color-surface": "#f7f5f1", "--color-text": "#1c1c1c",
    "--color-text-muted": "#4a4640", "--color-border": "#e6e2dc", "--color-accent": "#d92416",
    "--color-accent-hover": "#a52a17", "--color-accent-on-tint": "#a52a17", "--color-accent-tint": "rgba(217, 36, 22, 0.08)",
    "--color-on-accent": "#fff", "--color-focus": "#1c1c1c", "--color-success": "#2e7d32",
    "--color-danger": "#c62828", "--color-warning": "#9a6400", "--color-on-conversation": "#fff",
    "--radius": "0", "--graph-cluster-0": "#d92416",
}
DARK_EXPECTED = {
    "--color-bg": "#1c1c1c", "--color-surface": "#2a2622", "--color-text": "#e8e4de",
    "--color-text-muted": "#b0aaa2", "--color-border": "#3a3733", "--color-accent": "#f0604f",
    "--color-accent-hover": "#f4806f", "--color-accent-on-tint": "#f4806f", "--color-accent-tint": "rgba(240, 96, 79, 0.14)",
    "--color-on-accent": "#1c1c1c", "--color-focus": "#e8e4de", "--color-success": "#6cc070",
    "--color-danger": "#f07a6e", "--color-warning": "#e0a530", "--graph-cluster-0": "#f0604f",
}


def _norm(v):
    v = v.lower().replace(" ", "")
    return {"#ffffff": "#fff"}.get(v, v)


@pytest.mark.parametrize("name,value", LIGHT_EXPECTED.items())
def test_light_tokens(name, value):
    assert _norm(_light().get(name, "")) == _norm(value)


@pytest.mark.parametrize("name,value", DARK_EXPECTED.items())
def test_dark_tokens(name, value):
    assert _norm(_dark().get(name, "")) == _norm(value)


def test_display_font_token_is_oswald():
    assert _light()["--font-display"].startswith("Oswald")


PAIRS = [
    ("--color-text", "--color-bg"), ("--color-text-muted", "--color-bg"),
    ("--color-text-muted", "--color-surface"), ("--color-accent", "--color-bg"),
    ("--color-on-accent", "--color-accent"), ("--color-focus", "--color-bg"),
    ("--color-success", "--color-bg"), ("--color-danger", "--color-bg"),
    ("--color-on-accent", "--color-warning"), ("--color-on-accent", "--color-accent-hover"),
    ("--color-accent", "--color-surface"),
]


@pytest.mark.parametrize("tokens", [_light, _dark], ids=["hell", "dunkel"])
def test_contrast_pairs_meet_aa(tokens):
    t = tokens()
    for fg, bg in PAIRS:
        assert contrast(t[fg], t[bg]) >= 4.5, (fg, bg)
    for base in ("--color-bg", "--color-surface"):
        tinted = _over(t["--color-accent-tint"], t[base])
        assert contrast(t["--color-accent-on-tint"], tinted) >= 4.5, base


def test_contrast_function_rejects_light_accent_on_dark():
    assert contrast("#d92416", "#1c1c1c") < 4.5
    assert contrast("#d92416", "#ffffff") >= 4.5


def _font_urls():
    return re.findall(r"url\(['\"]?([^)'\"]+)['\"]?\)", FONTS_CSS.read_text())


def test_fonts_css_urls_point_to_existing_files_and_licenses_exist():
    urls = _font_urls()
    assert len(urls) == 8
    for u in urls:
        f = FONTS_CSS.parent / u
        assert f.is_file(), u
        assert f.read_bytes()[:4] == b"wOF2", u
    for fam in ("Inter", "Oswald"):
        assert (FONTS_CSS.parent / fam / "OFL.txt").is_file()


def test_style_css_imports_fonts_first():
    assert CSS.lstrip().startswith('@import url("fonts/fonts.css");')


def test_fonts_served_over_http_even_with_early_access_gate(monkeypatch):
    monkeypatch.setenv("EARLY_ACCESS_PASSWORD", "geheim123")
    c = TestClient(main_module.app)
    css = c.get("/fonts/fonts.css")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    gate = c.get("/fonts/Inter/OFL.txt")
    assert gate.headers["content-type"].startswith("text/html")
    for u in _font_urls():
        r = c.get("/fonts/" + u.removeprefix("./"))
        assert r.status_code == 200, u
        assert r.headers["content-type"] == "font/woff2", u


def _declarations(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [d.strip() for d in re.split(r"[;{}]", css)]


def test_no_hard_coded_colors_outside_tokens():
    bad = []
    for d in _declarations(CSS):
        prop = d.split(":")[0].split()[-1] if ":" in d and d.split(":")[0].split() else ""
        if d.startswith("--") or re.match(r"(box-shadow|-webkit-mask|mask)", prop):
            continue
        d = re.sub(r"var\(--[\w-]+\s*,(?:[^()]|\([^()]*\))*\)", "", d)
        d = re.sub(r"rgba\(\s*0\s*,\s*0\s*,\s*0\s*,[^)]*\)", "", d)
        if re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", d):
            bad.append(d[:90])
    assert not bad, bad


PAGE_TITLE_FILES = ["import", "explore", "creative", "costs", "changelog", "question-log", "users", "mcp",
                    "404", "datenschutz", "privacy", "impressum", "legal-notice", "early-access"]


@pytest.mark.parametrize("name", PAGE_TITLE_FILES)
def test_page_title_h2_has_class(name):
    html = (STATIC / f"{name}.html").read_text(encoding="utf-8")
    assert re.search(r'<h2[^>]*class="[^"]*\bpage-title\b', html)


def test_display_font_applied_to_titles_and_brand():
    assert re.search(r"\.page-title[^{]*\{[^}]*font-family:\s*var\(--font-display\)", CSS, re.S)
    assert re.search(r"\.brand-name[^{]*\{[^}]*font-family:\s*var\(--font-display\)", CSS, re.S)


def test_global_focus_visible_and_inputs_keep_outline():
    assert re.search(r":focus-visible\s*\{[^}]*outline:\s*3px solid var\(--color-focus\)", CSS)
    assert not re.search(r"(select:focus|input:focus, textarea:focus)\s*\{[^}]*outline:\s*none", CSS)


def test_accent_text_on_tint_uses_on_tint_token():
    # Regel mit color:var(--color-accent) UND background:var(--color-accent-tint) -> on-tint-Token
    bad = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)):
        body = m.group(2)
        if re.search(r"(?<![-\w])color:\s*var\(--color-accent\)", body) and re.search(r"background(-color)?:\s*var\(--color-accent-tint\)", body):
            bad.append(m.group(1).strip())
    assert not bad, bad


def test_fonts_css_every_font_face_block_survives_comments():
    css = re.sub(r"/\*.*?\*/", "", FONTS_CSS.read_text(), flags=re.S)
    blocks = re.findall(r"@font-face\s*\{([^}]*)\}", css)
    # Nichts ausser den Bloecken: ein vorzeitig endender Kommentar hinterlaesst Text vor dem ersten Block.
    assert re.sub(r"@font-face\s*\{[^}]*\}", "", css).strip() == ""
    assert len(blocks) == len(_font_urls())
    for b in blocks:
        assert "font-family" in b and "src" in b


def test_only_used_font_weights_are_shipped():
    names = {u.split("/")[-1] for u in _font_urls()}
    assert not any(w in n for n in names for w in ("-500-", "oswald-latin-700", "oswald-latin-ext-700"))
    assert not re.search(r"font-weight:\s*800", CSS)
