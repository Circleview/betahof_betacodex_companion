import re
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

APPEND_CALL_RE = re.compile(
    r"\b(?:appendChild|append|insertBefore|prepend|replaceChild|insertAdjacentElement|appendTimelineRow)\s*\("
)
CREATE_ELEMENT_RE = re.compile(r"\bconst\s+(\w+)\s*=\s*document\.createElement\(")
FUNCTION_START_RE = re.compile(r"function\s+\w+\s*\([^)]*\)\s*\{")


def _extract_function_bodies(js_source: str) -> list[str]:
    """Gibt den Quelltext jeder Top-Level-`function NAME(...) { ... }`-Definition zurück."""
    bodies = []
    for match in FUNCTION_START_RE.finditer(js_source):
        start = match.end() - 1  # Position der öffnenden '{'
        depth = 0
        for i in range(start, len(js_source)):
            if js_source[i] == "{":
                depth += 1
            elif js_source[i] == "}":
                depth -= 1
                if depth == 0:
                    bodies.append(js_source[start : i + 1])
                    break
    return bodies


def _find_orphaned_elements(function_body: str) -> list[str]:
    """Findet Variablen aus document.createElement(...), die innerhalb dieser Funktion
    weder an ein appendChild/insertBefore/... übergeben noch per return weitergereicht werden."""
    orphaned = []
    for name in CREATE_ELEMENT_RE.findall(function_body):
        appended = re.search(
            rf"(?:appendChild|append|insertBefore|prepend|replaceChild|insertAdjacentElement|appendTimelineRow)\([^)]*\b{name}\b",
            function_body,
        )
        # Direkte Rückgabe (`return label;`) ODER als Objekt-Property zurückgegeben
        # (`return { label, input };`), z.B. bei buildFieldLabel().
        returned = re.search(rf"\breturn\s+{name}\b", function_body) or re.search(
            rf"\breturn\s*\{{[^}}]*\b{name}\b[^}}]*\}}", function_body
        )
        if not appended and not returned:
            orphaned.append(name)
    return orphaned


def _check_file_for_orphaned_dom_elements(filename: str) -> dict[str, list[str]]:
    js_source = (STATIC_DIR / filename).read_text()
    problems = {}
    for body in _extract_function_bodies(js_source):
        header_match = re.match(r"function\s+(\w+)", body)
        # Funktionskörper beginnt bei der '{', daher Namen aus dem Text davor holen.
        name_search = re.search(rf"function\s+(\w+)\s*\([^)]*\)\s*\{{{re.escape(body[1:20])}", "")
        orphaned = _find_orphaned_elements(body)
        if orphaned:
            problems[body[:40]] = orphaned
    return problems


def test_import_js_has_no_orphaned_dom_elements():
    js_source = (STATIC_DIR / "import.js").read_text()
    all_orphaned = []
    for match in FUNCTION_START_RE.finditer(js_source):
        fn_name_match = re.search(r"function\s+(\w+)", js_source[max(0, match.start() - 30) : match.end()])
        fn_name = fn_name_match.group(1) if fn_name_match else "?"
        start = match.end() - 1
        depth = 0
        for i in range(start, len(js_source)):
            if js_source[i] == "{":
                depth += 1
            elif js_source[i] == "}":
                depth -= 1
                if depth == 0:
                    body = js_source[start : i + 1]
                    orphaned = _find_orphaned_elements(body)
                    if orphaned:
                        all_orphaned.append((fn_name, orphaned))
                    break
    assert all_orphaned == [], (
        "Diese per document.createElement erzeugten Elemente werden in ihrer Funktion "
        f"weder angehängt noch zurückgegeben: {all_orphaned}"
    )


def test_question_js_has_no_orphaned_dom_elements():
    js_source = (STATIC_DIR / "question.js").read_text()
    all_orphaned = []
    for match in FUNCTION_START_RE.finditer(js_source):
        fn_name_match = re.search(r"function\s+(\w+)", js_source[max(0, match.start() - 30) : match.end()])
        fn_name = fn_name_match.group(1) if fn_name_match else "?"
        start = match.end() - 1
        depth = 0
        for i in range(start, len(js_source)):
            if js_source[i] == "{":
                depth += 1
            elif js_source[i] == "}":
                depth -= 1
                if depth == 0:
                    body = js_source[start : i + 1]
                    orphaned = _find_orphaned_elements(body)
                    if orphaned:
                        all_orphaned.append((fn_name, orphaned))
                    break
    assert all_orphaned == [], (
        "Diese per document.createElement erzeugten Elemente werden in ihrer Funktion "
        f"weder angehängt noch zurückgegeben: {all_orphaned}"
    )


def test_regression_edit_panel_form_is_appended():
    """Gezielter Regressionstest für den konkreten Bug: buildEditPanel baute ein <form>,
    hängte es aber nie ans zurückgegebene <li> an, wodurch das Bearbeiten-Panel leer blieb."""
    js_source = (STATIC_DIR / "import.js").read_text()
    match = re.search(r"function buildEditPanel\([^)]*\)\s*\{", js_source)
    assert match, "buildEditPanel wurde nicht gefunden."
    start = match.end() - 1
    depth = 0
    end = None
    for i in range(start, len(js_source)):
        if js_source[i] == "{":
            depth += 1
        elif js_source[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    body = js_source[start:end]
    assert re.search(r"\bli\.appendChild\(\s*form\s*\)", body), (
        "buildEditPanel() muss das gebaute <form>-Element per li.appendChild(form) "
        "an das zurückgegebene <li> anhängen, sonst bleibt das Bearbeiten-Panel leer."
    )


def test_regression_view_and_edit_source_links_are_mutually_exclusive():
    """Gezielter Regressionstest für Backlog #75: appendSourceLink() muss pro
    Quelle genau EINEN der beiden Links einhängen (Bearbeiten für Pfleger:innen,
    Ansehen für alle anderen) - nie direkt appendEditSourceLink(), sonst sähen
    anonyme Besucher:innen (und das Embed-Widget) gar keinen Quellenlink mehr."""
    js_source = (STATIC_DIR / "question.js").read_text()

    assert "appendSourceLink(excerpt, s.source_id)" in js_source
    assert "appendSourceLink(p, s.source_id)" in js_source
    assert "appendEditSourceLink(excerpt, s.source_id)" not in js_source
    assert "appendEditSourceLink(p, s.source_id)" not in js_source

    match = re.search(r"function appendSourceLink\([^)]*\)\s*\{", js_source)
    assert match, "appendSourceLink wurde nicht gefunden."
    start = match.end() - 1
    depth = 0
    end = None
    for i in range(start, len(js_source)):
        if js_source[i] == "{":
            depth += 1
        elif js_source[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    body = js_source[start:end]
    assert re.search(r"if\s*\(\s*hasPflegerRole\(\)\s*\)", body), (
        "appendSourceLink muss zwischen Pfleger:innen und allen anderen unterscheiden."
    )
    assert "appendEditSourceLink(container, sourceId)" in body
    assert "appendViewSourceLink(container, sourceId)" in body
