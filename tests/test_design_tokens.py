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
    "--color-accent-hover": "#a52a17",
    "--color-on-accent": "#fff", "--color-focus": "#1c1c1c", "--color-success": "#2e7d32",
    "--color-danger": "#c62828", "--color-warning": "#9a6400", "--color-on-conversation": "#fff",
    "--radius": "0", "--graph-cluster-0": "#d92416", "--color-cover-sand": "#f7f3ea",
    "--color-cover-rose": "#f3dcd5", "--color-cover-mint": "#d5e8e2", "--color-cover-aqua": "#cfe3e6",
}
DARK_EXPECTED = {
    "--color-bg": "#1c1c1c", "--color-surface": "#2a2622", "--color-text": "#e8e4de",
    "--color-text-muted": "#b0aaa2", "--color-border": "#3a3733", "--color-accent": "#f0604f",
    "--color-accent-hover": "#f4806f",
    "--color-on-accent": "#1c1c1c", "--color-focus": "#e8e4de", "--color-success": "#6cc070",
    "--color-danger": "#f07a6e", "--color-warning": "#e0a530", "--graph-cluster-0": "#f0604f", "--color-cover-sand": "#302b25",
    "--color-cover-rose": "#3a2b28", "--color-cover-mint": "#26342f", "--color-cover-aqua": "#263339",
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
] + [(fg, f"--color-cover-{c}") for c in ("sand", "rose", "mint", "aqua")
     for fg in ("--color-text", "--color-text-muted", "--color-accent-hover")]


@pytest.mark.parametrize("tokens", [_light, _dark], ids=["hell", "dunkel"])
def test_contrast_pairs_meet_aa(tokens):
    t = tokens()
    for fg, bg in PAIRS:
        assert contrast(t[fg], t[bg]) >= 4.5, (fg, bg)


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


def _rules():
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    return [(" ".join(m.group(1).split()), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)]


def _field_rule(sel):
    return next(b for s, b in _rules() if s == sel)


@pytest.mark.parametrize("sel", ["input, textarea", "select"])
def test_fields_have_ink_border_and_one_focus_indicator(sel):
    body = _field_rule(sel)
    assert re.search(r"border:\s*2px solid var\(--color-text\)", body)
    assert re.search(r"background:\s*var\(--color-bg\)", body)
    for s, b in _rules():
        if re.search(r":focus(?!-within)", s) and not s.startswith(".skip-link"):
            # Einzige Ausnahme: innerer Fokusring der Eingabeleiste (Tinte, kein Tint),
            # siehe test_question_bar_focus_is_single_ring_on_the_bar_frame.
            if s != "#question-form:has(textarea:focus)":
                assert "box-shadow" not in b, s
            assert not re.search(r"border(-color)?:[^;]*var\(--color-accent", b), s


# Rot (--color-accent) nur: Primaerknopf, Textlinks, Titel-/Linkkarten-Hover, Graph/Konversation.
ACCENT_ALLOWED = {
    'button[type="submit"], .send-button, #popover-load, #popover-upload, #term-merge-analyze',
    "button[type=\"submit\"]:hover, .send-button:hover, #popover-load:hover, #popover-upload:hover, #term-merge-analyze:hover",
    ".brand-dot", "#creative-sources .creative-disclaimer a", ".footer-panel a", ".legal-summary a", ".new-author-profile a",
    ".legal-page a", ".legal-page a:hover, .legal-page a:focus-visible",
    ".link-button", ".link-button:hover", "#embed-expand-button", "#embed-expand-button:hover",
    ".term-followup:hover", ".citation-ref", ".citation-ref:hover",
    "#chat-messages a", "#chat-messages a:hover, #chat-messages a:focus-visible",
    ".external-link", ".external-link:hover", ".source-open-link", ".source-open-link:hover",
    ".author-link", ".author-link:hover", "details a", ".creative-disclaimer a", "#creative-sources a",
    "#chat-messages .citation-card .citation-title-link:hover, #chat-messages .citation-card .citation-author-link:hover, #chat-messages .citation-card .external-link:hover", ".citation-author-link:hover", ".citation-title-link:hover", ".question-log-question-link:hover",
    ".question-log-answer-details summary:hover", ".site-footer a:hover",
    ".source-image a:hover img", ".inline-source-image a:hover img",
}


def test_accent_red_only_on_allowed_selectors():
    bad = []
    for s, b in _rules():
        if s.startswith("--") or re.fullmatch(r"(:root|[\d%, ]+)", s):
            continue
        if re.search(r"var\(--color-accent(-hover)?\)", b) and not any(
            s == a or s.startswith(a + ":hover") for a in ACCENT_ALLOWED
        ) and "conversation-color" not in b:
            bad.append(s[:80])
    assert not bad, bad


def test_tint_tokens_unused_and_removed():
    assert "--color-accent-tint" not in CSS
    assert "--color-accent-on-tint" not in CSS


# --- Eingabeleiste (C) ---
def test_question_form_expanded_never_keeps_buttons_beside_field():
    for sel, body in _rules():
        if "chat-started" in sel and "question-form--expanded" in sel:
            assert "flex-basis: 0" not in body and "justify-content: normal" not in body, sel


def test_question_form_bar_has_ink_frame_and_borderless_field():
    assert re.search(r"border:\s*2px solid var\(--color-text\)", _field_rule("#question-form"))
    assert re.search(r"border:\s*0\b", _field_rule("#question-form textarea"))
    for sel, body in _rules():
        if "#question-form" in sel and "textarea" not in sel:
            assert "border-top: none" not in body, sel


# --- Kreativ-Modus (D) ---
import json

CREATIVE = (STATIC / "creative.html").read_text(encoding="utf-8")
I18N = {l: json.loads((STATIC / "i18n" / f"{l}.json").read_text(encoding="utf-8")) for l in ("de", "en")}
STEP_KEYS = [f"creative.step{i}{part}" for i in (1, 2, 3) for part in ("Title", "Text")]
LABEL_KEYS = ["creative.draftEyebrow", "creative.sourcesEyebrow", "creative.sourcesPlaceholder", "creative.instructionLabel"]


def test_creative_steps_and_labels_in_html_and_both_languages():
    assert len(re.findall(r'class="creative-step"', CREATIVE)) == 3
    for key in STEP_KEYS + LABEL_KEYS:
        assert f'data-i18n="{key}"' in CREATIVE or key == "creative.instructionLabel", key
        for lang in ("de", "en"):
            assert I18N[lang].get(key), (lang, key)
    assert I18N["de"]["creative.step1Title"] == "Anweisung geben"
    assert I18N["de"]["creative.step2Text"] == "Lies den Entwurf und die Quellen."
    assert I18N["de"]["creative.sourcesPlaceholder"] == "Erscheint nach dem ersten Entwurf."
    assert I18N["en"]["creative.sourcesPlaceholder"] == "Appears after the first draft."
    assert 'for="creative-instruction" class="creative-field-label creative-eyebrow"' in CREATIVE
    assert CREATIVE.count('data-i18n="creative.instructionLabel"') == 1


def test_creative_steps_styled_like_bcx_steps():
    css = " ".join(CSS.split())
    assert re.search(r"\.creative-step \{[^}]*border-top: 4px solid var\(--color-text\)[^}]*padding-top: 20px", css)
    assert re.search(r"\.creative-step__no \{[^}]*font-family: var\(--font-display\)", css)
    assert re.search(r"\.creative-eyebrow[^{]*\{[^}]*letter-spacing: 0\.12em[^}]*text-transform: uppercase", css)


def test_creative_disclaimer_uses_cover_sand_and_ink_top_border():
    body = _field_rule(".creative-disclaimer")
    assert "background: var(--color-cover-sand)" in body
    assert "border-top: 4px solid var(--color-text)" in body


def test_creative_sources_placeholder_only_when_list_empty():
    assert CREATIVE.count('class="creative-sources-placeholder"') == 2
    css = " ".join(CSS.split())
    assert re.search(r"ul:not\(:empty\) \+ \.creative-sources-placeholder \{ display: none", css)


def test_brand_dot_stays_red():
    assert "background: var(--color-accent)" in _field_rule(".brand-dot")


# --- Farbband je Bereich (E-G) ---
def test_cover_tokens_distinct_in_both_schemes():
    for tokens in (_light(), _dark()):
        vals = [tokens[f"--color-cover-{c}"] for c in ("sand", "rose", "mint", "aqua")]
        assert len(set(vals)) == 4


def test_page_band_breaks_out_of_column_without_horizontal_scroll():
    body = _field_rule(".page-band")
    assert "margin-inline: calc(50% - 50vw)" in body and "padding-inline: calc(50vw - 50%)" in body
    assert re.search(r"padding-block:\s*(56px|3\.5rem)", body)
    assert any(s == "html" and "overflow-x: clip" in b for s, b in _rules())
    mobile = re.search(r"@media \(max-width: 640px\) \{\s*\.page-band \{[^}]*padding-block:\s*(32px|2rem)", CSS)
    assert mobile


@pytest.mark.parametrize("page,color", [("creative", "sand"), ("explore", "aqua"), ("import", "rose")])
def test_band_pages_wrap_title_in_colored_band(page, color):
    html = (STATIC / f"{page}.html").read_text(encoding="utf-8")
    m = re.search(rf'<div class="page-band page-band--{color}">(.*?)</div>\s*(?=<(?:div|form|section|aside|datalist|/section))', html, re.S)
    assert m and 'class="page-title' in m.group(1), page
    assert _field_rule(f".page-band--{color}").count(f"var(--color-cover-{color})") == 1
    if page == "creative":
        assert 'class="creative-steps"' in m.group(1)


@pytest.mark.parametrize("page", ["costs", "mcp", "users", "question-log", "changelog", "datenschutz", "privacy", "impressum", "legal-notice", "404", "early-access", "embed", "index"])
def test_other_pages_have_no_band_markup(page):
    assert "page-band" not in (STATIC / f"{page}.html").read_text(encoding="utf-8")


def test_home_start_state_band_is_mint_and_gone_in_chat():
    body = _field_rule("body:not(.chat-started) #frage-bereich")
    assert "background: var(--color-cover-mint)" in body
    assert "margin-inline: calc(50% - 50vw)" in body
    for sel, b in _rules():
        if sel.startswith("body.chat-started #frage-bereich"):
            assert "cover" not in b


def test_creative_disclaimer_not_on_sand_band():
    # Hinweisbox liegt in der Seitenspalte ausserhalb des Sand-Bands.
    html = (STATIC / "creative.html").read_text(encoding="utf-8")
    band = re.search(r'<div class="page-band page-band--sand">(.*?)</div>\s*(?=<div id="creative-layout")', html, re.S).group(1)
    assert "creative-disclaimer" not in band


# --- Zitat-Box (Cover-Sand) ---
def test_citation_card_is_mint_surface_without_frame():
    body = _field_rule(".citation-card")
    assert "background: var(--color-cover-mint)" in body
    assert re.search(r"border:\s*0\b", body)


# --- Footer-Bereiche (Feedback + Einbetten fahren nach oben aus) ---
FOOTER_JS = (STATIC / "footer.js").read_text(encoding="utf-8")


def test_footer_panels_share_base_class_and_embed_popover_is_gone():
    assert "footer-embed-panel" in FOOTER_JS and "footer-feedback-panel" in FOOTER_JS
    assert "embed-popover" not in FOOTER_JS and "popover-arrow" not in FOOTER_JS
    assert "embed-popover" not in CSS and "footer-feedback-panel" not in CSS
    assert ".footer-panel {" in CSS or re.search(r"\.footer-panel\s*\{", CSS)


def test_footer_panels_close_each_other_on_escape_and_return_focus():
    assert "function closeFooterPanels" in FOOTER_JS
    assert "'Escape'" in FOOTER_JS
    assert "trigger.focus()" in FOOTER_JS
    assert "scrollIntoView" in FOOTER_JS
    # Panels liegen im DOM VOR der Footer-Zeile.
    assert "footer.parentNode.insertBefore(panel, footer)" in FOOTER_JS


def test_footer_panel_rises_with_reduced_motion_fallback():
    assert "@keyframes footer-panel-rise" in CSS
    m = re.search(r"prefers-reduced-motion: reduce\) \{[^@]*\.footer-panel:not\(\.hidden\)\s*\{[^}]*animation:\s*none", CSS)
    assert m


def test_embed_copy_button_is_secondary_ink_button():
    css = " ".join(CSS.split())
    assert re.search(r"\.footer-embed-copy \{[^}]*border: 2px solid var\(--color-text\)", css)
    assert re.search(r"\.footer-embed-copy:hover \{[^}]*background: var\(--color-text\)", css)


def test_accent_red_forbidden_on_cover_surfaces_links_use_accent_hover():
    # Rot (#d92416) erreicht auf Cover-Farben nur ~3.8-4.5; Links dort in accent-hover.
    cover_links = {".creative-disclaimer a", ".citation-card a"}
    seen = set()
    for sel, body in _rules():
        if sel in cover_links:
            seen.add(sel)
            assert "var(--color-accent)" not in body, sel
            assert "var(--color-accent-hover)" in body, sel
    assert ".creative-disclaimer a" in seen


# --- Favicon von betacodex.org ---
import struct


def _png_size(path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    return struct.unpack(">II", data[16:24])


def test_every_html_page_links_svg_before_png_icon():
    for f in sorted(STATIC.glob("*.html")):
        html = f.read_text(encoding="utf-8")
        svg = html.find('<link rel="icon" href="/icons/favicon.svg" type="image/svg+xml">')
        png = html.find('<link rel="icon" type="image/png" href="/icons/favicon.png">')
        assert 0 <= svg < png, f.name


def test_icon_files_exist_with_expected_sizes_and_manifest_matches():
    assert (STATIC / "icons" / "favicon.svg").read_text(encoding="utf-8").lstrip().startswith("<svg")
    manifest = json.loads((STATIC / "manifest.json").read_text(encoding="utf-8"))
    by_src = {i["src"]: i for i in manifest["icons"]}
    for src in ("/icons/favicon.png", "/icons/apple-touch-icon.png"):
        w, h = _png_size(STATIC / src.lstrip("/"))
        assert by_src[src]["sizes"] == f"{w}x{h}", src
    assert (_png_size(STATIC / "icons/favicon.png")) == (32, 32)
    assert (_png_size(STATIC / "icons/apple-touch-icon.png")) == (180, 180)
    assert by_src["/icons/favicon.svg"] == {"src": "/icons/favicon.svg", "sizes": "any", "type": "image/svg+xml"}


def test_favicon_svg_reachable_with_early_access_gate(monkeypatch):
    monkeypatch.setenv("EARLY_ACCESS_PASSWORD", "geheim123")
    r = TestClient(main_module.app).get("/icons/favicon.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")


def test_citation_card_links_are_ink_underlined_with_accent_hover():
    ink = "#chat-messages .citation-card .citation-title-link, #chat-messages .citation-card .citation-author-link, #chat-messages .citation-card .external-link"
    body = _field_rule(ink)
    assert "color: var(--color-text)" in body
    assert "text-decoration: underline" in body and "text-underline-offset: 3px" in body
    assert "var(--color-accent-hover)" in _field_rule(
        "#chat-messages .citation-card .citation-title-link:hover, #chat-messages .citation-card .citation-author-link:hover, #chat-messages .citation-card .external-link:hover"
    )


def test_citation_card_has_no_extra_inline_indent():
    body = _field_rule(".citation-card")
    assert not re.search(r"margin(-inline|-left|-right)", body)
    assert re.search(r"margin:\s*0\.6rem 0 1rem", body)


def test_term_followup_is_ink_bold_thin_underline_hover_accent_hover():
    body = _field_rule(".term-followup")
    assert "color: var(--color-text)" in body and "font-weight: 700" in body
    assert "text-decoration: underline 1px" in body and "text-underline-offset: 3px" in body
    assert "var(--color-accent-hover)" in _field_rule(".term-followup:hover")
    assert "var(--color-accent)" in _field_rule(".citation-ref")


# --- Nachbesserung: Fokus, Startseite, Cover-Flaechen, Ueberlauf ---
def test_field_focus_outline_overlaps_border_single_line():
    found = False
    for sel, body in _rules():
        if sel == "#question-form textarea:focus-visible":
            continue  # Ausnahme: Ring liegt auf der Leiste (eigener Test)
        if re.search(r"(input|textarea|select)[^,]*:focus-visible", sel):
            m = re.search(r"outline-offset:\s*(-?\d+)(?:px)?", body)
            assert m and int(m.group(1)) == 0, sel
            found = True
    assert found


def test_home_start_state_footer_sits_at_bottom():
    assert "margin-top: auto" in _field_rule("body:not(.chat-started) .site-footer")


@pytest.mark.parametrize("sel", [".footer-panel", ".new-author-profile", ".legal-summary"])
def test_boxes_are_sand_surfaces_without_frame(sel):
    body = _field_rule(sel)
    assert "background: var(--color-cover-sand)" in body
    assert re.search(r"border:\s*0\b", body)


@pytest.mark.parametrize("sel", [".footer-panel a", ".legal-summary a", ".new-author-profile a"])
def test_links_on_sand_boxes_use_accent_hover(sel):
    body = _field_rule(sel)
    assert "var(--color-accent-hover)" in body and "var(--color-accent)" not in body


def test_unreachable_row_bleed_fits_mobile_body_padding():
    # Mobile-Body-Padding 0.75rem: der Warn-Hintergrund darf nicht weiter hinausragen.
    m = re.search(r"@media \(max-width: 640px\) \{(?:(?!\n\}).)*?source-row--unreachable(?:(?!\n\}).)*?margin-right:\s*-0\.75rem", CSS, re.S)
    assert m


def test_question_bar_focus_is_single_ring_on_the_bar_frame():
    # Einzige erlaubte Ausnahme von "kein outline: none" bei Feldern: das randlose
    # Textfeld der Eingabeleiste - nur zusammen mit dem Ring auf der Leiste selbst.
    assert "outline: none" in _field_rule("#question-form textarea:focus-visible")
    ring = _field_rule("#question-form:has(textarea:focus)")
    # #chat-column hat overflow: hidden und schneidet alles ab, was außerhalb
    # der Leiste liegt (auch Outline mit Offset 0) - deshalb innerer Ring per
    # inset-Schatten, bündig am 2px-Rand: eine durchgehende Linie.
    assert "box-shadow: inset 0 0 0 3px var(--color-focus)" in ring
    assert "outline:" not in ring
    for sel, body in _rules():
        if "outline: none" in body and re.search(r"(input|textarea|select)[^,]*:focus", sel):
            assert sel == "#question-form textarea:focus-visible", sel


def test_start_band_fills_desktop_height_like_google():
    # Nutzerwunsch: Startseite am Desktop wie google.com aufteilen - das Mint-Band
    # füllt den Platz zwischen Header und Footer, das Fragefeld sitzt etwas über
    # der Mitte statt in einem schmalen Streifen mit viel Weiß darunter.
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    m = re.search(r"@media \(min-width: 900px\) \{\s*body:not\(\.chat-started\) #frage-bereich \{([^}]*)\}", css)
    assert m, "Desktop-Regel für das Startband fehlt"
    body = m.group(1)
    assert re.search(r"flex:\s*1 0 auto", body)
    assert re.search(r"padding-bottom:\s*calc\(", body)
    # Band reicht bis an den Footer - dessen Haarlinie entfällt dort.
    f = re.search(r"@media \(min-width: 900px\) \{[^@]*?body:not\(\.chat-started\) \.site-footer \{([^}]*)\}", css)
    assert f and re.search(r"border-top:\s*0", f.group(1))


def test_citation_highlight_is_darker_mint_marker():
    # Nutzerentscheid (v0.93.1): die passende Stelle in der Mint-Zitat-Box ist ein
    # Textmarker im selben Farbton (Mint, 10 % Tinte beigemischt), keine Stein-Flicken.
    body = next(b for s, b in _rules() if s == ".citation-highlight")
    assert re.search(r"background:\s*color-mix\(in srgb, var\(--color-text\) 10%, var\(--color-cover-mint\)\)", body)
    assert "box-decoration-break: clone" in body
    for t in (_light(), _dark()):
        mint, text = _rgb(t["--color-cover-mint"]), _rgb(t["--color-text"])
        mark = tuple(0.1 * a + 0.9 * b for a, b in zip(text, mint))
        assert contrast(t["--color-text"], mark) >= 4.5


# --- v0.93.1: Audit-Befunde ---
QUESTION_JS = (STATIC / "question.js").read_text(encoding="utf-8")


def test_question_textarea_is_height_capped_and_js_respects_cap():
    assert "max-height: 40vh" in _field_rule("#question-form textarea")
    assert re.search(r"@media \(max-width: 640px\) \{[^@]*html #question-form textarea \{[^}]*max-height: 40dvh", CSS)
    fn = QUESTION_JS[QUESTION_JS.index("function autosizeQuestionInput"):]
    fn = fn[: fn.index("questionInput.addEventListener('input'")]
    assert "Math.min(" in fn and "maxHeight" in fn and "overflowY" in fn


def test_disclaimer_link_beats_sources_column_link_color():
    # '#creative-sources a' (ID-Spezifitaet) ueberstimmte '.creative-disclaimer a' -> Rot auf Sand.
    body = _field_rule("#creative-sources .creative-disclaimer a")
    assert "var(--color-accent-hover)" in body and "var(--color-accent)" not in body


@pytest.mark.parametrize("sel", [".lang-button", ".alphabet-jump-btn", "#creative-new-btn"])
def test_small_touch_targets_get_hit_area(sel):
    # WCAG 2.5.8: Trefferflaeche >= 24px per ::after, Optik unveraendert.
    body = _field_rule(f"{sel}::after")
    assert "content: ''" in body and re.search(r"inset:\s*-\d", body)
    assert re.search(r"position:\s*relative", _field_rule(sel))


def test_brand_name_scales_with_text_zoom():
    body = _field_rule(".brand-name")
    assert re.search(r"max-width:\s*\d+(\.\d+)?em", body) and "320px" not in body


@pytest.mark.parametrize("f", sorted(p.name for p in STATIC.glob("*.html")))
def test_every_page_has_main_landmark(f):
    assert len(re.findall(r"<main[\s>]", (STATIC / f).read_text(encoding="utf-8"))) == 1


def test_header_nav_landmark_and_labels_bilingual():
    hdr = (STATIC / "header.js").read_text(encoding="utf-8")
    assert "createElement('nav')" in hdr and "aria-label" in hdr and "nav.main" in hdr
    assert I18N["de"]["nav.main"] == "Hauptnavigation" and I18N["en"]["nav.main"] == "Main navigation"
    for k in ("index.questionAriaLabel", "footer.embedSnippetLabel"):
        assert I18N["de"].get(k) and I18N["en"].get(k), k
    assert "data-i18n-aria-label" in (STATIC / "i18n.js").read_text(encoding="utf-8")
    for page in ("index", "embed"):
        assert 'data-i18n-aria-label="index.questionAriaLabel"' in (STATIC / f"{page}.html").read_text(encoding="utf-8")
    assert "footer.embedSnippetLabel" in FOOTER_JS


def test_sticky_header_is_full_width_white_and_hairline_only_without_band():
    after = _field_rule("#site-header::after")
    assert "width: 100vw" in after and "background: var(--color-bg)" in after and "z-index: -1" in after
    # kein clip-path am Header: er wuerde Popover unter dem Header abschneiden
    assert "clip-path" not in _field_rule("#site-header")
    sel = "body:has(.page-band) #site-header, body:not(.chat-started):has(#frage-bereich) #site-header"
    assert re.search(r"border-bottom:\s*0\b", _field_rule(sel))


@pytest.mark.parametrize("page", sorted(p.name for p in STATIC.glob("*.html")))
def test_no_inline_scripts_blocked_by_csp(page):
    # Die CSP erlaubt kein 'unsafe-inline' für script-src - ein <script> ohne src
    # läuft im Browser nie (embed.html meldete so jahrelang keine Höhe, v0.93.1).
    html = (STATIC / page).read_text(encoding="utf-8")
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), page


def test_embed_reports_height_via_external_script():
    html = (STATIC / "embed.html").read_text(encoding="utf-8")
    assert '<script src="/embed-resize.js"></script>' in html
    js = (STATIC / "embed-resize.js").read_text(encoding="utf-8")
    assert "betacodex-chat-embed-resize" in js and "ResizeObserver" in js
