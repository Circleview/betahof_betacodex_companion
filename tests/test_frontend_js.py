import json
import re
import subprocess
from pathlib import Path

import pytest

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _run_strip_markdown_for_speech(text: str) -> str:
    """Führt static/speech.js#stripMarkdownForSpeech per Node aus (statt die
    Regeln in Python nachzubauen) - die Funktion importiert selbst /i18n.js
    (absoluter Browser-Pfad, in Node nicht auflösbar), daher wird hier nur
    ihr eigener Funktionskörper extrahiert und isoliert ausgeführt."""
    js_source = (STATIC_DIR / "speech.js").read_text()
    match = re.search(r"export function stripMarkdownForSpeech.*?\n\}", js_source, re.S)
    assert match, "stripMarkdownForSpeech wurde in speech.js nicht gefunden."
    func_source = match.group(0).replace("export function", "function")
    script = f"{func_source}\nconsole.log(JSON.stringify(stripMarkdownForSpeech({json.dumps(text)})));"
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def _run_speech_rate_cycle(num_clicks: int) -> list[float]:
    """Führt speech.js#createSpeechController().cyclePlaybackRate() per Node
    real aus (statt SPEECH_RATES/die Wraparound-Logik in Python
    nachzubauen). Die Datei importiert /i18n.js (in Node nicht auflösbar)
    und nutzt ES-Module-`export` - beides wird hier durch einen simplen
    Textersatz entfernt, der Rest der Datei läuft unverändert als
    CommonJS-Skript mit minimalen Browser-API-Stubs (localStorage, window)."""
    js_source = (STATIC_DIR / "speech.js").read_text()
    lines = js_source.split("\n")
    assert lines[0] == "import { getLang } from '/i18n.js';"
    body = "\n".join(lines[1:]).replace("export ", "")
    script = f"""
function getLang() {{ return 'de'; }}
const store = {{}};
global.localStorage = {{
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => {{ store[k] = v; }},
}};
global.window = {{}};

{body}

const controller = createSpeechController({{}});
const rates = [];
for (let i = 0; i < {num_clicks}; i++) {{
  rates.push(controller.cyclePlaybackRate());
}}
console.log(JSON.stringify(rates));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)

def _run_find_highlight_range(text, highlight):
    """Führt static/question.js#findHighlightRange per Node real aus - reine
    Funktion ohne DOM-Abhängigkeit, bisher OHNE jede Testabdeckung, obwohl
    sie allein entscheidet, ob überhaupt ein Highlight-<mark> erscheint."""
    js_source = (STATIC_DIR / "question.js").read_text()
    match = re.search(r"function findHighlightRange.*?\n\}", js_source, re.S)
    assert match, "findHighlightRange wurde in question.js nicht gefunden."
    func_source = match.group(0)
    script = f"""
{func_source}
console.log(JSON.stringify(findHighlightRange({json.dumps(text)}, {json.dumps(highlight)})));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_find_highlight_range_returns_exact_match():
    text = "Jede Liste besitzt einen List-Owner."
    highlight = "einen List-Owner"
    range_ = _run_find_highlight_range(text, highlight)
    assert range_ == [text.index(highlight), text.index(highlight) + len(highlight)]


def test_find_highlight_range_tolerates_non_breaking_space_difference():
    """Regressionstest (Bug 2026-08-20): das Original enthält ein
    geschütztes Leerzeichen (\xa0, typisch bei aus Websites gecrawltem
    Text), das LLM-Zitat ein normales - die whitespace-tolerante Regex
    muss trotzdem greifen, statt gar kein Highlight zu zeigen."""
    text = "Jede Liste besitzt einen\xa0List-Owner. Diese Rolle endet mit der Liste."
    highlight = "Jede Liste besitzt einen List-Owner."
    range_ = _run_find_highlight_range(text, highlight)
    assert range_ is not None
    assert text[range_[0] : range_[1]] == "Jede Liste besitzt einen\xa0List-Owner."


def test_find_highlight_range_escapes_regex_special_characters():
    """Ein Zitat mit Markdown-Sternchen (**fett**) oder anderen Regex-
    Sonderzeichen darf die whitespace-tolerante Suche nicht zum Absturz
    bringen oder falsch (leer) matchen lassen."""
    text = "Der **List-Owner** (kurz LO) ist zentral."
    highlight = "Der **List-Owner** (kurz LO)"
    range_ = _run_find_highlight_range(text, highlight)
    assert range_ is not None
    assert text[range_[0] : range_[1]] == highlight


def test_find_highlight_range_returns_null_when_nothing_matches():
    """Graceful Degradation: findet sich das Highlight nirgends (auch nicht
    tolerant), gibt es null zurück statt zu crashen - appendTextWithHighlight
    zeigt dann den vollen Text ohne Hervorhebung, statt Inhalt zu verlieren."""
    range_ = _run_find_highlight_range("Ein völlig anderer Satz.", "Kommt hier gar nicht vor")
    assert range_ is None


def _run_append_title_text(source_obj):
    """Führt static/question.js#appendTitleText per Node real aus, mit
    minimalen DOM-Stubs (kein volles jsdom nötig - die Funktion nutzt nur
    createElement/createTextNode/appendChild/addEventListener)."""
    js_source = (STATIC_DIR / "question.js").read_text()
    match = re.search(r"function appendTitleText.*?\n\}", js_source, re.S)
    assert match, "appendTitleText wurde in question.js nicht gefunden."
    func_source = match.group(0)
    script = f"""
function t(key) {{ return key; }}
class FakeNode {{
  constructor(type, value) {{
    this.type = type;
    this.value = value;
    this.children = [];
  }}
  appendChild(child) {{ this.children.push(child); return child; }}
  addEventListener() {{}}
}}
const document = {{
  createElement: (tag) => new FakeNode('element:' + tag, null),
  createTextNode: (text) => new FakeNode('text', text),
}};

{func_source}

const container = new FakeNode('container', null);
appendTitleText(container, {json.dumps(source_obj)});
console.log(JSON.stringify(container.children.map((c) => ({{
  type: c.type,
  value: c.value,
  href: c.href || null,
  className: c.className || null,
  textContent: c.textContent || null,
}}))));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_append_title_text_links_title_when_url_present():
    children = _run_append_title_text({"title": "Ein Artikel", "url": "https://beispiel.org/artikel"})
    assert len(children) == 1
    assert children[0]["type"] == "element:a"
    assert children[0]["href"] == "https://beispiel.org/artikel"
    assert children[0]["textContent"] == "Ein Artikel"
    assert children[0]["className"] == "citation-title-link"


def test_append_title_text_prefers_listen_url_over_url():
    children = _run_append_title_text(
        {"title": "Ein Podcast", "url": "https://beispiel.org/seite", "listen_url": "https://beispiel.org/audio.mp3"}
    )
    assert children[0]["href"] == "https://beispiel.org/audio.mp3"


def test_append_title_text_renders_plain_text_without_url():
    children = _run_append_title_text({"title": "Ein Buch ohne URL", "url": None})
    assert len(children) == 1
    assert children[0]["type"] == "text"
    assert children[0]["value"] == "Ein Buch ohne URL"


def _run_append_exclude_web_page_button(*, is_pfleger, source_obj, fetch_ok=True):
    """Führt static/question.js#appendExcludeWebPageButton per Node real aus,
    inkl. simuliertem Klick (ruft den registrierten click-Listener direkt
    auf) - mit minimalen Stubs für hasPflegerRole/fetch/t/getLang (kein
    volles jsdom nötig, siehe _run_append_title_text)."""
    js_source = (STATIC_DIR / "question.js").read_text()
    match = re.search(r"function appendExcludeWebPageButton.*?\n\}", js_source, re.S)
    assert match, "appendExcludeWebPageButton wurde in question.js nicht gefunden."
    func_source = match.group(0)
    script = f"""
function t(key) {{ return key; }}
function getLang() {{ return 'de'; }}
function hasPflegerRole() {{ return {json.dumps(is_pfleger)}; }}
const EDIT_ICON = '<svg></svg>';
let fetchCalls = [];
global.fetch = async (url, options) => {{
  fetchCalls.push({{ url, options }});
  return {{ ok: {json.dumps(fetch_ok)} }};
}};
class FakeNode {{
  constructor(type) {{
    this.type = type;
    this.children = [];
    this.className = '';
    this.disabled = false;
    this.listeners = {{}};
    this.classList = {{ add: (cls) => {{ this.className += ' ' + cls; }} }};
  }}
  appendChild(child) {{ this.children.push(child); return child; }}
  addEventListener(evt, fn) {{ this.listeners[evt] = fn; }}
  setAttribute() {{}}
}}
const document = {{ createElement: (tag) => new FakeNode('element:' + tag) }};

{func_source}

const container = new FakeNode('container');
appendExcludeWebPageButton(container, {json.dumps(source_obj)});
async function main() {{
  const btn = container.children[0];
  if (btn && btn.listeners.click) {{
    await btn.listeners.click({{ stopPropagation: () => {{}} }});
  }}
  console.log(JSON.stringify({{
    appended: !!btn,
    className: btn ? btn.className : null,
    disabled: btn ? btn.disabled : null,
    title: btn ? btn.title : null,
    fetchCalls,
  }}));
}}
main();
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def _run_citations_click_sequence(paragraph_text, sources, click_sequence):
    """Wie _run_make_citations_clickable, führt zusätzlich eine feste Klick-
    Sequenz (Liste von Button-Indizes, in Auftrittsreihenfolge im Text) aus
    und gibt die Kartenanzahl nach JEDEM Klick zurück."""
    js_source = (STATIC_DIR / "question.js").read_text()
    match = re.search(r"function makeCitationsClickable.*?\n\}", js_source, re.S)
    assert match, "makeCitationsClickable wurde in question.js nicht gefunden."
    func_source = match.group(0)
    script = f"""
class FakeNode {{
  constructor(nodeType, tag) {{
    this.nodeType = nodeType;
    this.tag = tag || null;
    this.children = [];
    this.parentNode = null;
    this.className = '';
    this.textContent = '';
    this.listeners = {{}};
  }}
  appendChild(child) {{ child.parentNode = this; this.children.push(child); return child; }}
  removeChildNode(child) {{
    const i = this.children.indexOf(child);
    if (i !== -1) this.children.splice(i, 1);
  }}
  remove() {{ if (this.parentNode) this.parentNode.removeChildNode(this); }}
  closest(tag) {{
    let n = this;
    while (n) {{
      if (n.tag === tag) return n;
      n = n.parentNode;
    }}
    return null;
  }}
  insertAdjacentElement(where, el) {{
    if (!this.parentNode) return;
    const siblings = this.parentNode.children;
    const i = siblings.indexOf(this);
    el.parentNode = this.parentNode;
    siblings.splice(where === 'afterend' ? i + 1 : i, 0, el);
  }}
  replaceChild(newNode, oldNode) {{
    const i = this.children.indexOf(oldNode);
    if (i === -1) return;
    const replacement = newNode.nodeType === 'fragment' ? newNode.children : [newNode];
    replacement.forEach((c) => {{ c.parentNode = this; }});
    this.children.splice(i, 1, ...replacement);
  }}
  addEventListener(evt, fn) {{ this.listeners[evt] = fn; }}
}}
const document = {{
  createElement: (tag) => new FakeNode('element', tag),
  createTextNode: (text) => {{ const n = new FakeNode('text'); n.textContent = text; return n; }},
  createDocumentFragment: () => new FakeNode('fragment'),
  createTreeWalker: (root) => {{
    const stack = [];
    (function collect(node) {{
      node.children.forEach((child) => {{
        if (child.nodeType === 'text') stack.push(child);
        else collect(child);
      }});
    }})(root);
    let i = 0;
    return {{ nextNode: () => (i < stack.length ? stack[i++] : null) }};
  }},
}};
const NodeFilter = {{ SHOW_TEXT: 4 }};

function buildSourceInfo(source, highlight) {{
  const marker = document.createElement('div');
  marker.textContent = 'CARD:' + source.chunk_id + '::' + (highlight || '');
  return marker;
}}

{func_source}

const container = new FakeNode('element', 'div');
const p = document.createElement('p');
container.appendChild(p);
p.appendChild(document.createTextNode({json.dumps(paragraph_text)}));

makeCitationsClickable(container, {json.dumps(sources)});

function findButtons(node, acc) {{
  if (node.tag === 'button') acc.push(node);
  node.children.forEach((c) => findButtons(c, acc));
  return acc;
}}
const buttons = findButtons(container, []);

function countCards(node) {{
  let n = node.tag === 'div' && node.className === 'citation-card' ? 1 : 0;
  node.children.forEach((c) => {{ n += countCards(c); }});
  return n;
}}

const results = [];
for (const index of {json.dumps(click_sequence)}) {{
  buttons[index].listeners.click();
  results.push(countCards(container));
}}
console.log(JSON.stringify(results));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def _run_citations_click_all_and_read_markers(paragraph_text, sources):
    """Wie _run_citations_click_sequence, klickt aber JEDEN Button genau
    einmal (in Textreihenfolge) und gibt pro Klick den Marker-Text der
    dabei geöffneten Karte zurück - damit prüfbar ist, dass jedes Vorkommen
    wirklich SEIN EIGENES highlighted_texts[occurrence] bekommt, auch wenn
    zwischendurch andere Zitatnummern auftauchen (z.B. [1]...[2]...[1])."""
    js_source = (STATIC_DIR / "question.js").read_text()
    match = re.search(r"function makeCitationsClickable.*?\n\}", js_source, re.S)
    assert match, "makeCitationsClickable wurde in question.js nicht gefunden."
    func_source = match.group(0)
    script = f"""
class FakeNode {{
  constructor(nodeType, tag) {{
    this.nodeType = nodeType;
    this.tag = tag || null;
    this.children = [];
    this.parentNode = null;
    this.className = '';
    this.textContent = '';
    this.listeners = {{}};
  }}
  appendChild(child) {{ child.parentNode = this; this.children.push(child); return child; }}
  removeChildNode(child) {{
    const i = this.children.indexOf(child);
    if (i !== -1) this.children.splice(i, 1);
  }}
  remove() {{ if (this.parentNode) this.parentNode.removeChildNode(this); }}
  closest(tag) {{
    let n = this;
    while (n) {{
      if (n.tag === tag) return n;
      n = n.parentNode;
    }}
    return null;
  }}
  insertAdjacentElement(where, el) {{
    if (!this.parentNode) return;
    const siblings = this.parentNode.children;
    const i = siblings.indexOf(this);
    el.parentNode = this.parentNode;
    siblings.splice(where === 'afterend' ? i + 1 : i, 0, el);
  }}
  replaceChild(newNode, oldNode) {{
    const i = this.children.indexOf(oldNode);
    if (i === -1) return;
    const replacement = newNode.nodeType === 'fragment' ? newNode.children : [newNode];
    replacement.forEach((c) => {{ c.parentNode = this; }});
    this.children.splice(i, 1, ...replacement);
  }}
  addEventListener(evt, fn) {{ this.listeners[evt] = fn; }}
}}
const document = {{
  createElement: (tag) => new FakeNode('element', tag),
  createTextNode: (text) => {{ const n = new FakeNode('text'); n.textContent = text; return n; }},
  createDocumentFragment: () => new FakeNode('fragment'),
  createTreeWalker: (root) => {{
    const stack = [];
    (function collect(node) {{
      node.children.forEach((child) => {{
        if (child.nodeType === 'text') stack.push(child);
        else collect(child);
      }});
    }})(root);
    let i = 0;
    return {{ nextNode: () => (i < stack.length ? stack[i++] : null) }};
  }},
}};
const NodeFilter = {{ SHOW_TEXT: 4 }};

function buildSourceInfo(source, highlight) {{
  const marker = document.createElement('div');
  marker.textContent = 'CARD:' + source.chunk_id + '::' + (highlight || '');
  return marker;
}}

{func_source}

const container = new FakeNode('element', 'div');
const p = document.createElement('p');
container.appendChild(p);
p.appendChild(document.createTextNode({json.dumps(paragraph_text)}));

makeCitationsClickable(container, {json.dumps(sources)});

function findButtons(node, acc) {{
  if (node.tag === 'button') acc.push(node);
  node.children.forEach((c) => findButtons(c, acc));
  return acc;
}}
const buttons = findButtons(container, []);

function findCard(node) {{
  if (node.tag === 'div' && node.className === 'citation-card') return node;
  for (const c of node.children) {{
    const found = findCard(c);
    if (found) return found;
  }}
  return null;
}}

const markers = buttons.map((btn) => {{
  btn.listeners.click();
  const card = findCard(container);
  const marker = card ? card.children[0].textContent : null;
  btn.listeners.click(); // gleich wieder schliessen, damit sich Karten nicht ueberlappen
  return marker;
}});
console.log(JSON.stringify(markers));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_citation_click_maps_each_occurrence_to_its_own_highlight_across_interleaved_numbers():
    """Stellt sicher, dass myOccurrence korrekt PRO ZITATNUMMER zählt, auch
    wenn zwischen zwei [1]-Vorkommen ein [2] eines anderen Chunks liegt -
    das zweite [1] darf nicht versehentlich das Highlight des [2] oder das
    globale dritte Vorkommen bekommen."""
    sources = [
        {"chunk_id": "chunk-1", "highlighted_texts": ["Erstes Zitat A", "Zweites Zitat A"]},
        {"chunk_id": "chunk-2", "highlighted_texts": ["Einziges Zitat B"]},
    ]
    markers = _run_citations_click_all_and_read_markers(
        "Aussage eins [1]. Aussage zwei [2]. Aussage drei [1].", sources
    )
    assert markers == [
        "CARD:chunk-1::Erstes Zitat A",
        "CARD:chunk-2::Einziges Zitat B",
        "CARD:chunk-1::Zweites Zitat A",
    ]


def test_citation_click_reopens_card_after_two_occurrences_share_a_highlight():
    """Regressionstest (Bug 2026-08-20, per Screenshot gemeldet): zwei
    [1]-Vorkommen mit demselben Highlight teilten sich denselben
    contentKey. Klick auf das ERSTE öffnete die Karte, Klick auf das ZWEITE
    schloss sie wieder (geteilte Karte) - ein erneuter Klick auf das ZWEITE
    Vorkommen blieb danach aber wirkungslos (das Highlighting "verschwand"
    dauerhaft), weil der alte Code den Offen/Zu-Zustand redundant in einer
    lokalen Variable JE BUTTON hielt, statt ihn einzig in openCards
    nachzuschlagen."""
    sources = [{"chunk_id": "chunk-1", "highlighted_texts": ["Gleiches Zitat", "Gleiches Zitat"]}]
    # Klickreihenfolge: Button 0 auf, Button 1 (geteilte Karte) zu, Button 1
    # erneut auf - genau der Schritt, der vorher hängen blieb.
    counts = _run_citations_click_sequence(
        "Erste Aussage [1]. Zweite Aussage [1].", sources, [0, 1, 1]
    )
    assert counts == [1, 0, 1]


def test_citation_click_opens_independent_cards_for_different_highlights():
    sources = [{"chunk_id": "chunk-1", "highlighted_texts": ["Zitat A", "Zitat B"]}]
    counts = _run_citations_click_sequence("Erste Aussage [1]. Zweite Aussage [1].", sources, [0, 1])
    assert counts == [1, 2]


def test_exclude_web_page_button_not_shown_for_non_pfleger():
    output = _run_append_exclude_web_page_button(
        is_pfleger=False,
        source_obj={"source_id": "page-1", "allowlist_entry_id": "entry-1"},
    )
    assert output["appended"] is False


def test_exclude_web_page_button_not_shown_without_allowlist_entry_id():
    output = _run_append_exclude_web_page_button(
        is_pfleger=True, source_obj={"source_id": "page-1", "allowlist_entry_id": None}
    )
    assert output["appended"] is False


def test_exclude_web_page_button_click_calls_exclude_endpoint():
    output = _run_append_exclude_web_page_button(
        is_pfleger=True,
        source_obj={"source_id": "page-1", "allowlist_entry_id": "entry-1"},
    )
    assert output["appended"] is True
    assert len(output["fetchCalls"]) == 1
    assert output["fetchCalls"][0]["url"] == "/api/web-allowlist/entry-1/pages/page-1/exclude"
    assert output["fetchCalls"][0]["options"]["method"] == "POST"
    assert output["disabled"] is True
    assert output["title"] == "common.webPageExcluded"


def test_exclude_web_page_button_reenables_on_failed_request():
    output = _run_append_exclude_web_page_button(
        is_pfleger=True,
        source_obj={"source_id": "page-1", "allowlist_entry_id": "entry-1"},
        fetch_ok=False,
    )
    assert output["disabled"] is False
    assert output["title"] == "common.excludeWebPage"


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


def _run_load_full_source_text(*, initial_sources, fetched_sources, active_filter):
    """Führt static/import.js#loadFullSourceText per Node aus (Nutzerwunsch
    2026-08-31: Ladereihenfolge - Volltext wird erst NACH der sichtbaren
    Liste nachgeladen und hier per Mock-fetch/allSources/activeFilter/
    applySearchFilter isoliert getestet, kein DOM nötig)."""
    js_source = (STATIC_DIR / "import.js").read_text()
    match = re.search(r"async function loadFullSourceText.*?\n\}", js_source, re.S)
    assert match, "loadFullSourceText wurde in import.js nicht gefunden."
    func_source = match.group(0)
    script = f"""
let allSources = {json.dumps(initial_sources)};
let activeFilter = {json.dumps(active_filter)};
let appliedSearchQuery = null;
function getLang() {{ return 'de'; }}
function applySearchFilter(query) {{ appliedSearchQuery = query; }}
global.fetch = async () => ({{ json: async () => ({json.dumps(fetched_sources)}) }});

{func_source}

(async () => {{
  await loadFullSourceText();
  console.log(JSON.stringify({{ allSources, appliedSearchQuery }}));
}})();
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_load_full_source_text_merges_text_into_existing_sources_by_id():
    output = _run_load_full_source_text(
        initial_sources=[{"id": "a", "title": "Eins", "text": ""}, {"id": "b", "title": "Zwei", "text": ""}],
        fetched_sources=[{"id": "a", "text": "Volltext Eins"}, {"id": "b", "text": "Volltext Zwei"}],
        active_filter=None,
    )
    assert output["allSources"] == [
        {"id": "a", "title": "Eins", "text": "Volltext Eins"},
        {"id": "b", "title": "Zwei", "text": "Volltext Zwei"},
    ]


def test_load_full_source_text_reapplies_active_search_filter():
    output = _run_load_full_source_text(
        initial_sources=[{"id": "a", "text": ""}],
        fetched_sources=[{"id": "a", "text": "Volltext"}],
        active_filter={"type": "search", "value": "merrelyn"},
    )
    assert output["appliedSearchQuery"] == "merrelyn"


def test_load_full_source_text_does_not_reapply_non_search_filter():
    output = _run_load_full_source_text(
        initial_sources=[{"id": "a", "text": ""}],
        fetched_sources=[{"id": "a", "text": "Volltext"}],
        active_filter={"type": "author", "value": "Someone"},
    )
    assert output["appliedSearchQuery"] is None


def test_regression_edit_entry_points_wait_for_full_source_text_before_opening():
    """Gezielter Regressionstest (2026-08-31): seit der zweiphasigen
    Ladereihenfolge (loadSources lädt zuerst ohne Volltext, loadFullSourceText
    nach) muss JEDER Weg ins Bearbeiten-Formular (editBtn-Klick UND der
    ?edit=<id>-Deep-Link) zuerst `fullTextReady` abwarten - sonst könnte das
    Formular mit leerem Volltext geöffnet und dieser leere Stand beim
    Speichern über den echten Volltext der Quelle geschrieben werden."""
    js_source = (STATIC_DIR / "import.js").read_text()

    edit_btn_match = re.search(
        r"editBtn\.addEventListener\('click', async \(\) => \{.*?\n\s*\}\);", js_source, re.S
    )
    assert edit_btn_match, "editBtn-Click-Handler wurde in import.js nicht gefunden."
    assert "await fullTextReady" in edit_btn_match.group(0)

    deep_link_match = re.search(
        r"const deepLinkEditId = new URLSearchParams.*?\n\}", js_source, re.S
    )
    assert deep_link_match, "?edit=-Deep-Link-Block wurde in import.js nicht gefunden."
    assert "await fullTextReady" in deep_link_match.group(0)


def test_strip_markdown_for_speech_removes_list_markers():
    """Regression: Listenmarker ('- ', '1. ') wurden vor der Sprachausgabe
    bislang nicht entfernt, wodurch Aufzählungen unnatürlich mit Ziffern/
    Strichen vorgelesen wurden (siehe Vergleich mit dem CRT-Tool)."""
    text = "Vorteile:\n- Erster Punkt\n- Zweiter Punkt\n\n1. Eins\n2. Zwei"
    result = _run_strip_markdown_for_speech(text)
    assert result == "Vorteile: Erster Punkt Zweiter Punkt Eins Zwei"


def test_strip_markdown_for_speech_removes_headings_and_emphasis_and_citations():
    text = "## Überschrift\n\nEin **fetter** und *kursiver* Text mit `code` und [1] Zitat."
    result = _run_strip_markdown_for_speech(text)
    assert result == "Überschrift Ein fetter und kursiver Text mit code und Zitat."


def test_speech_rate_cycles_through_all_stages_and_wraps_around():
    rates = _run_speech_rate_cycle(6)
    assert rates == [1.25, 1.5, 1.75, 2, 1, 1.25]


def test_start_listening_unlocks_audio_context_for_later_automatic_speak():
    """Regression-Test (2026-08-01): automatisches Vorlesen nach einer per
    Mikrofon gestellten Frage blieb stumm, weil die AudioContext-
    Freischaltung bisher NUR in speak() passierte - für eine Sprachfrage
    läuft speak() aber automatisch erst am Ende einer langen asynchronen
    Kette (Aufnahme stoppen -> Transkription -> Absenden -> Antwort
    abwarten), zu weit weg von der ursprünglichen Klick-Geste. startListening
    (direkt im Klick-Handler des Mikrofon-Buttons aufgerufen) muss die
    Freischaltung deshalb selbst anstoßen."""
    js_source = (STATIC_DIR / "speech.js").read_text()
    lines = js_source.split("\n")
    body = "\n".join(lines[1:]).replace("export ", "")
    script = f"""
function getLang() {{ return 'de'; }}
global.localStorage = {{ getItem: () => null, setItem: () => {{}} }};

class FakeRecognition {{
  start() {{}}
  stop() {{}}
}}

let resumeCalls = 0;
let constructedCount = 0;
class FakeAudioContext {{
  constructor() {{ constructedCount += 1; this.state = 'suspended'; }}
  resume() {{ resumeCalls += 1; this.state = 'running'; }}
}}
global.window = {{
  SpeechRecognition: FakeRecognition,
  AudioContext: FakeAudioContext,
}};

{body}

const controller = createSpeechController({{}});
controller.startListening();
console.log(JSON.stringify({{ constructedCount, resumeCalls }}));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    output = json.loads(result.stdout)
    assert output == {"constructedCount": 1, "resumeCalls": 1}


def test_speak_fetches_all_sentences_in_parallel_instead_of_sequentially():
    """Regression: die komplette Antwort wurde bisher in EINEM Google-TTS-
    Aufruf synthetisiert - spürbare Verzögerung bei längeren, mehrsätzigen
    Antworten, da nichts abspielbar war, bevor der ganze Text fertig war.
    Jetzt müssen alle Sätze SOFORT (parallel) angefragt werden, statt erst
    nacheinander, sobald der jeweils vorherige fertig ist."""
    js_source = (STATIC_DIR / "speech.js").read_text()
    lines = js_source.split("\n")
    assert lines[0] == "import { getLang } from '/i18n.js';"
    body = "\n".join(lines[1:]).replace("export ", "")
    script = f"""
function getLang() {{ return 'de'; }}
global.localStorage = {{ getItem: () => null, setItem: () => {{}} }};

class FakeAudioContext {{
  constructor() {{ this.state = 'running'; this.destination = {{}}; }}
  resume() {{ this.state = 'running'; }}
  decodeAudioData(buf) {{ return Promise.resolve(buf); }}
  createBufferSource() {{
    const node = {{
      buffer: null,
      playbackRate: {{ value: 1 }},
      onended: null,
      connect() {{}},
      start() {{ setTimeout(() => node.onended?.(), 0); }},
      stop() {{}},
    }};
    return node;
  }}
}}
global.window = {{ AudioContext: FakeAudioContext }};

const fetchCalls = [];
global.fetch = (url, opts) => {{
  const requestedText = JSON.parse(opts.body).text;
  fetchCalls.push(requestedText);
  return new Promise((resolve) => {{
    setTimeout(
      () => resolve({{
        ok: true,
        blob: () => Promise.resolve({{ arrayBuffer: () => Promise.resolve('buf:' + requestedText) }}),
      }}),
      5
    );
  }});
}};

{body}

const controller = createSpeechController({{}});
controller.speak('Erster Satz. Zweiter Satz. Dritter Satz.');
// Direkt nach speak() (noch bevor irgendein setTimeout/Promise aufgelöst
// wurde) müssen bereits ALLE drei Sätze angefragt worden sein.
console.log(JSON.stringify(fetchCalls));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    calls = json.loads(result.stdout)
    assert calls == ["Erster Satz.", "Zweiter Satz.", "Dritter Satz."]


def test_speak_plays_sentences_in_order_despite_out_of_order_fetch_completion():
    """Auch wenn ein späterer Satz schneller antwortet als ein früherer
    (unterschiedliche Google-TTS-Latenz pro Anfrage), muss die Wiedergabe-
    Reihenfolge trotzdem der Satzreihenfolge der Antwort entsprechen."""
    js_source = (STATIC_DIR / "speech.js").read_text()
    lines = js_source.split("\n")
    body = "\n".join(lines[1:]).replace("export ", "")
    script = f"""
function getLang() {{ return 'de'; }}
global.localStorage = {{ getItem: () => null, setItem: () => {{}} }};

const playedOrder = [];
class FakeAudioContext {{
  constructor() {{ this.state = 'running'; this.destination = {{}}; }}
  resume() {{ this.state = 'running'; }}
  decodeAudioData(buf) {{ return Promise.resolve(buf); }}
  createBufferSource() {{
    const node = {{
      buffer: null,
      playbackRate: {{ value: 1 }},
      onended: null,
      connect() {{}},
      start() {{
        playedOrder.push(node.buffer);
        setTimeout(() => node.onended?.(), 0);
      }},
      stop() {{}},
    }};
    return node;
  }}
}}
global.window = {{ AudioContext: FakeAudioContext }};

const DELAY_BY_TEXT = {{ 'Erster Satz.': 15, 'Zweiter Satz.': 1 }};
global.fetch = (url, opts) => {{
  const requestedText = JSON.parse(opts.body).text;
  return new Promise((resolve) => {{
    setTimeout(
      () => resolve({{
        ok: true,
        blob: () => Promise.resolve({{ arrayBuffer: () => Promise.resolve('buf-for:' + requestedText) }}),
      }}),
      DELAY_BY_TEXT[requestedText] ?? 1
    );
  }});
}};

{body}

const controller = createSpeechController({{}});
controller.speak('Erster Satz. Zweiter Satz.');
setTimeout(() => console.log(JSON.stringify(playedOrder)), 50);
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    played_order = json.loads(result.stdout)
    assert played_order == ["buf-for:Erster Satz.", "buf-for:Zweiter Satz."]


def test_speak_gives_first_sentence_high_fetch_priority_and_rest_low():
    """Der erste Satz blockiert den Beginn der Wiedergabe und darf deshalb
    bei echter Ressourcen-Konkurrenz (Browser-Verbindungslimit, Bandbreite)
    nicht von den gleichzeitig abgeschickten späteren Sätzen eingeholt
    werden - dafür bekommt er 'high' statt 'low' als Fetch-Priority-Hint."""
    js_source = (STATIC_DIR / "speech.js").read_text()
    lines = js_source.split("\n")
    body = "\n".join(lines[1:]).replace("export ", "")
    script = f"""
function getLang() {{ return 'de'; }}
global.localStorage = {{ getItem: () => null, setItem: () => {{}} }};

class FakeAudioContext {{
  constructor() {{ this.state = 'running'; this.destination = {{}}; }}
  resume() {{ this.state = 'running'; }}
  decodeAudioData(buf) {{ return Promise.resolve(buf); }}
  createBufferSource() {{
    return {{ buffer: null, playbackRate: {{ value: 1 }}, onended: null, connect() {{}}, start() {{}}, stop() {{}} }};
  }}
}}
global.window = {{ AudioContext: FakeAudioContext }};

const priorityByText = {{}};
global.fetch = (url, opts) => {{
  const requestedText = JSON.parse(opts.body).text;
  priorityByText[requestedText] = opts.priority;
  return new Promise(() => {{}}); // nie auflösen - reicht für diesen Test
}};

{body}

const controller = createSpeechController({{}});
controller.speak('Erster Satz. Zweiter Satz. Dritter Satz.');
console.log(JSON.stringify(priorityByText));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    priorities = json.loads(result.stdout)
    assert priorities == {
        "Erster Satz.": "high",
        "Zweiter Satz.": "low",
        "Dritter Satz.": "low",
    }


def test_speak_requests_audio_in_selected_rate_instead_of_resampling_client_side():
    """Regression-Test (2026-07-31): schnellere Wiedergabe ließ die Stimme
    höher klingen ("Micky-Maus-Effekt"). Zwei Ursachen wurden nacheinander
    ausgeschlossen (siehe Git-Historie): (1) client-seitiges Resampling per
    AudioBufferSourceNode.playbackRate ohne Tonhöhenkorrektur, (2) ein
    wiederverwendetes <audio>-Element - verursachte stattdessen ein
    hörbares Knacken zwischen Sätzen (kein gapless MP3-Playback). Die
    Lösung: die gewählte Rate wird an /api/speech mitgeschickt, Google TTS
    synthetisiert selbst schneller/langsamer, source.playbackRate bleibt
    unangetastet (Standardwert 1) UND die Wiedergabe bleibt über
    decodeAudioData/AudioBufferSourceNode gapless."""
    js_source = (STATIC_DIR / "speech.js").read_text()
    lines = js_source.split("\n")
    body = "\n".join(lines[1:]).replace("export ", "")
    script = f"""
function getLang() {{ return 'de'; }}
const store = {{ speechRate: '1.75' }};
global.localStorage = {{
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => {{ store[k] = v; }},
}};

let createdSourcePlaybackRate = null;
class FakeAudioContext {{
  constructor() {{ this.state = 'running'; this.destination = {{}}; }}
  resume() {{ this.state = 'running'; }}
  decodeAudioData(buf) {{ return Promise.resolve(buf); }}
  createBufferSource() {{
    const node = {{
      buffer: null,
      playbackRate: {{ value: 1 }},
      onended: null,
      connect() {{}},
      start() {{
        createdSourcePlaybackRate = node.playbackRate.value;
        setTimeout(() => node.onended?.(), 0);
      }},
      stop() {{}},
    }};
    return node;
  }}
}}
global.window = {{ AudioContext: FakeAudioContext }};

const fetchBodies = [];
global.fetch = (url, opts) => {{
  fetchBodies.push(JSON.parse(opts.body));
  return new Promise((resolve) => {{
    setTimeout(
      () => resolve({{ ok: true, blob: () => Promise.resolve({{ arrayBuffer: () => Promise.resolve('buf') }}) }}),
      5
    );
  }});
}};

{body}

const controller = createSpeechController({{}});
controller.speak('Einziger Satz.');
setTimeout(() => console.log(JSON.stringify({{ fetchBodies, createdSourcePlaybackRate }})), 20);
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    output = json.loads(result.stdout)
    assert output["fetchBodies"] == [{"text": "Einziger Satz.", "rate": 1.75}]
    # Der Wert bleibt bei der FakeAudioContext-Standardvorgabe (1) - der Code
    # darf ihn nicht anfassen, sonst käme die Tonhöhenverzerrung zurück.
    assert output["createdSourcePlaybackRate"] == 1


def test_playcloud_resumes_audio_context_if_browser_suspended_it_between_sentences():
    """Regression-Test (2026-08-01): auf Produktion blieb die Vorlesung bei
    längeren, mehrsätzigen Antworten manchmal nach dem ersten Satz stumm
    hängen. Ursache: der AudioContext wurde nur EINMAL zu Beginn von speak()
    entsperrt - versetzt der Browser ihn zwischen zwei Sätzen (Netzwerk-
    Roundtrip + Decodieren, auf Produktion langsamer als lokal) von sich aus
    wieder in "suspended", lief die Zeitachse des nächsten source.start()
    nie an, "onended" feuerte nie, die Wiedergabe hing fest. Jetzt muss vor
    JEDEM Satz erneut geprüft/aufgeweckt werden."""
    js_source = (STATIC_DIR / "speech.js").read_text()
    lines = js_source.split("\n")
    body = "\n".join(lines[1:]).replace("export ", "")
    script = f"""
function getLang() {{ return 'de'; }}
global.localStorage = {{ getItem: () => null, setItem: () => {{}} }};

let resumeCalls = 0;
let startCalls = 0;
class FakeAudioContext {{
  constructor() {{ this.state = 'running'; this.destination = {{}}; }}
  resume() {{ resumeCalls += 1; this.state = 'running'; }}
  decodeAudioData(buf) {{ return Promise.resolve(buf); }}
  createBufferSource() {{
    const ctx = this;
    const node = {{
      buffer: null,
      playbackRate: {{ value: 1 }},
      onended: null,
      connect() {{}},
      start() {{
        startCalls += 1;
        // Simuliert den Browser, der den Context nach dem ERSTEN Satz von
        // sich aus wieder schlafen legt, während der nächste Satz noch
        // angefragt/dekodiert wird.
        if (startCalls === 1) ctx.state = 'suspended';
        setTimeout(() => node.onended?.(), 0);
      }},
      stop() {{}},
    }};
    return node;
  }}
}}
global.window = {{ AudioContext: FakeAudioContext }};

global.fetch = (url, opts) => {{
  const requestedText = JSON.parse(opts.body).text;
  return Promise.resolve({{
    ok: true,
    blob: () => Promise.resolve({{ arrayBuffer: () => Promise.resolve('buf:' + requestedText) }}),
  }});
}};

{body}

const controller = createSpeechController({{}});
controller.speak('Erster Satz. Zweiter Satz.');
setTimeout(() => console.log(JSON.stringify({{ startCalls, resumeCalls }})), 50);
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    output = json.loads(result.stdout)
    # Beide Sätze müssen tatsächlich gestartet worden sein (kein Hängenbleiben
    # nach dem ersten) UND resume() muss (mindestens) für den zweiten Satz
    # erneut aufgerufen worden sein.
    assert output["startCalls"] == 2
    assert output["resumeCalls"] >= 1


def _run_speech_recognition_script(scenario_js: str) -> dict:
    """Führt ein Testszenario gegen createSpeechController mit einer
    FakeRecognition aus, deren Instanz (recognitionInstances[0]) im
    scenario_js direkt angesteuert wird (onresult/onend manuell auslösen) -
    Web Speech API ist in Node nicht verfügbar, daher wird sie hier komplett
    simuliert statt (wie im echten Browser) vom Betriebssystem geliefert."""
    js_source = (STATIC_DIR / "speech.js").read_text()
    lines = js_source.split("\n")
    body = "\n".join(lines[1:]).replace("export ", "")
    script = f"""
function getLang() {{ return 'de'; }}
global.localStorage = {{ getItem: () => null, setItem: () => {{}} }};

const recognitionInstances = [];
class FakeRecognition {{
  constructor() {{ recognitionInstances.push(this); }}
  start() {{}}
  stop() {{}}
}}
global.window = {{ SpeechRecognition: FakeRecognition }};

const interimCalls = [];
const transcriptCalls = [];

{body}

const speechController = createSpeechController({{
  onInterimTranscript: (text) => interimCalls.push(text),
  onTranscript: (text) => transcriptCalls.push(text),
}});
const recognition = recognitionInstances[0];

{scenario_js}
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_interim_transcript_fires_before_recording_ends():
    """Regression-Test (Backlog #190): der erkannte Text soll schon WÄHREND
    des Sprechens gemeldet werden, nicht erst wenn die Aufnahme endet."""
    output = _run_speech_recognition_script(
        """
speechController.startListening();
recognition.onresult({ resultIndex: 0, results: [{ 0: { transcript: 'Hallo' }, isFinal: false }] });
console.log(JSON.stringify({ interimCalls, transcriptCalls }));
"""
    )
    assert output == {"interimCalls": ["Hallo"], "transcriptCalls": []}


def test_interim_transcript_reflects_growing_and_finalized_text():
    output = _run_speech_recognition_script(
        """
speechController.startListening();
recognition.onresult({ resultIndex: 0, results: [{ 0: { transcript: 'Hallo' }, isFinal: false }] });
recognition.onresult({ resultIndex: 0, results: [{ 0: { transcript: 'Hallo Welt' }, isFinal: false }] });
recognition.onresult({ resultIndex: 0, results: [{ 0: { transcript: 'Hallo Welt.' }, isFinal: true }] });
console.log(JSON.stringify({ interimCalls }));
"""
    )
    assert output == {"interimCalls": ["Hallo", "Hallo Welt", "Hallo Welt."]}


def test_final_transcript_on_end_matches_last_interim_even_without_final_flag():
    """Kernszenario: manche Browser markieren das letzte, beim Stoppen noch
    laufende Wort nie als isFinal - onTranscript muss trotzdem exakt das
    liefern, was zuletzt live im Eingabefeld sichtbar war."""
    output = _run_speech_recognition_script(
        """
speechController.startListening();
recognition.onresult({ resultIndex: 0, results: [{ 0: { transcript: 'Hallo Welt' }, isFinal: false }] });
recognition.onend();
console.log(JSON.stringify({ transcriptCalls }));
"""
    )
    assert output == {"transcriptCalls": ["Hallo Welt"]}


def test_start_listening_resets_live_text_for_a_new_recording():
    output = _run_speech_recognition_script(
        """
speechController.startListening();
recognition.onresult({ resultIndex: 0, results: [{ 0: { transcript: 'Hallo.' }, isFinal: true }] });
recognition.onend();
speechController.startListening();
recognition.onresult({ resultIndex: 0, results: [{ 0: { transcript: 'Welt' }, isFinal: false }] });
console.log(JSON.stringify({ interimCalls }));
"""
    )
    assert output == {"interimCalls": ["Hallo.", "Welt"]}


def _run_update_broken_links_badge(*, visible: bool, fetch_response) -> dict:
    """Führt static/header.js#updateBrokenLinksBadge per Node aus. Die
    Funktion ist nicht exportiert (reines Modul-Innenleben) - daher wird
    hier, wie schon bei stripMarkdownForSpeech in speech.js, nur ihr eigener
    Funktionskörper per Regex extrahiert und mit einem minimalen
    document/fetch-Stub isoliert ausgeführt."""
    js_source = (STATIC_DIR / "header.js").read_text()
    match = re.search(r"async function updateBrokenLinksBadge.*?\n\}", js_source, re.S)
    assert match, "updateBrokenLinksBadge wurde in header.js nicht gefunden."
    func_source = match.group(0)
    fetch_stub = (
        "() => Promise.reject(new Error('fetch sollte hier nicht aufgerufen werden'))"
        if fetch_response is None
        else f"() => Promise.resolve({{ ok: true, json: () => Promise.resolve({json.dumps(fetch_response)}) }})"
    )
    script = f"""
let hidden = true;
const badgeEl = {{
  classList: {{
    add: (cls) => {{ if (cls === 'hidden') hidden = true; }},
    toggle: (cls, force) => {{ if (cls === 'hidden') hidden = force; }},
  }},
}};
global.document = {{ getElementById: (id) => (id === 'import-link-badge' ? badgeEl : null) }};
global.fetch = {fetch_stub};

{func_source}

updateBrokenLinksBadge({json.dumps(visible)}).then(() => {{
  console.log(JSON.stringify({{ hidden }}));
}});
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_update_broken_links_badge_shown_when_pfleger_has_broken_sources():
    output = _run_update_broken_links_badge(visible=True, fetch_response={"count": 2})
    assert output == {"hidden": False}


def test_update_broken_links_badge_hidden_when_pfleger_has_no_broken_sources():
    output = _run_update_broken_links_badge(visible=True, fetch_response={"count": 0})
    assert output == {"hidden": True}


def test_update_broken_links_badge_hidden_without_fetch_for_non_pfleger():
    """Regression-Schutz: für nicht-berechtigte Nutzer:innen darf gar nicht
    erst gegen den rollen-geschützten Endpoint gefetcht werden (liefert für
    sie ohnehin 403) - das Badge wird stattdessen sofort ausgeblendet."""
    output = _run_update_broken_links_badge(visible=False, fetch_response=None)
    assert output == {"hidden": True}


def _run_sticky_header_collapse(steps: list[tuple[int, float]]) -> list[bool]:
    """Führt static/header.js#initStickyHeaderCollapse per Node aus. Jeder
    Schritt in `steps` ist (scrollY, headerRectTop) - simuliert ein
    scroll-Event samt aktuellem getBoundingClientRect().top des Headers
    (steuert, ob er gerade "geklebt" ist). requestAnimationFrame wird
    synchron gestubbt (kein echtes Throttling nötig, um die reine Logik zu
    testen). Rückgabe: ob die Klasse 'site-header--compact' nach jedem
    Schritt gesetzt ist."""
    js_source = (STATIC_DIR / "header.js").read_text()
    match = re.search(r"function initStickyHeaderCollapse.*?\n\}", js_source, re.S)
    assert match, "initStickyHeaderCollapse wurde in header.js nicht gefunden."
    func_source = match.group(0)
    steps_js = json.dumps([{"scrollY": s[0], "top": s[1]} for s in steps])
    script = f"""
let headerRectTop = 0;
let classes = new Set();
const header = {{
  classList: {{
    add: (c) => classes.add(c),
    remove: (c) => classes.delete(c),
  }},
  getBoundingClientRect: () => ({{ top: headerRectTop }}),
}};
global.document = {{ getElementById: (id) => (id === 'site-header' ? header : null) }};
global.getComputedStyle = () => ({{ top: '8px' }});
global.requestAnimationFrame = (fn) => fn();
let scrollHandler = null;
global.window = {{
  scrollY: 0,
  addEventListener: (evt, fn, opts) => {{ if (evt === 'scroll') scrollHandler = fn; }},
}};

{func_source}

initStickyHeaderCollapse();

const results = [];
for (const step of {steps_js}) {{
  headerRectTop = step.top;
  window.scrollY = step.scrollY;
  scrollHandler();
  results.push(classes.has('site-header--compact'));
}}
console.log(JSON.stringify(results));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_sticky_header_stays_expanded_while_scrolling_down_before_it_sticks():
    """Solange der Header seinen Sticky-Versatz (CSS top) noch nicht erreicht
    hat (rect.top deutlich größer), ist er noch nicht "geklebt" - der Titel
    darf trotz Scrollens nach unten noch nicht ausgeblendet werden."""
    results = _run_sticky_header_collapse([(20, 40), (60, 20)])
    assert results == [False, False]


def test_sticky_header_collapses_once_stuck_while_scrolling_down():
    results = _run_sticky_header_collapse([(20, 40), (300, 8)])
    assert results == [False, True]


def _run_sticky_header_collapse_with_fake_timer(actions: list[tuple]) -> list[bool]:
    """Wie _run_sticky_header_collapse, aber mit einem steuerbaren Fake-Timer
    statt echtem setTimeout/clearTimeout - damit Tests die Wiedereinblenden-
    Verzögerung (Nutzerwunsch 2026-08-31) gezielt "vorspulen" können, ohne
    echte Zeit verstreichen zu lassen. `actions` ist eine Liste aus entweder
    ("scroll", scrollY, headerRectTop) oder ("fire_timer",) - liefert nach
    JEDER Aktion, ob 'site-header--compact' gerade gesetzt ist. Es wird
    bewusst nur EIN Timer-Slot verwaltet (kein Array), da
    initStickyHeaderCollapse nie mehr als einen ausstehenden Timer gleichzeitig
    hält (jeder neue Aufruf löscht den vorherigen zuerst, siehe dort)."""
    js_source = (STATIC_DIR / "header.js").read_text()
    match = re.search(r"function initStickyHeaderCollapse.*?\n\}", js_source, re.S)
    assert match, "initStickyHeaderCollapse wurde in header.js nicht gefunden."
    func_source = match.group(0)
    actions_js = json.dumps(actions)
    script = f"""
let headerRectTop = 0;
let classes = new Set();
const header = {{
  classList: {{
    add: (c) => classes.add(c),
    remove: (c) => classes.delete(c),
  }},
  getBoundingClientRect: () => ({{ top: headerRectTop }}),
}};
global.document = {{ getElementById: (id) => (id === 'site-header' ? header : null) }};
global.getComputedStyle = () => ({{ top: '8px' }});
global.requestAnimationFrame = (fn) => fn();
let pendingTimer = null;
global.setTimeout = (fn) => {{ pendingTimer = fn; return 1; }};
global.clearTimeout = () => {{ pendingTimer = null; }};
let scrollHandler = null;
global.window = {{
  scrollY: 0,
  addEventListener: (evt, fn) => {{ if (evt === 'scroll') scrollHandler = fn; }},
}};

{func_source}

initStickyHeaderCollapse();

const results = [];
for (const action of {actions_js}) {{
  if (action[0] === 'scroll') {{
    headerRectTop = action[2];
    window.scrollY = action[1];
    scrollHandler();
  }} else if (action[0] === 'fire_timer') {{
    const fn = pendingTimer;
    pendingTimer = null;
    if (fn) fn();
  }}
  results.push(classes.has('site-header--compact'));
}}
console.log(JSON.stringify(results));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_sticky_header_expand_is_delayed_and_cancelable_to_avoid_flicker():
    """Nutzerwunsch (2026-08-31): auf dem Handy meldet der Browser beim
    Scrollen mit aufliegendem Finger oft einzelne Pixel-Ticks in beide
    Richtungen - ein einzelner Aufwärts-Tick darf den Header deshalb NICHT
    mehr sofort wieder einblenden (das verursachte sichtbares Flackern in
    kurzer Folge), sondern erst, wenn für eine kurze Verzögerung
    ununterbrochen nach oben gescrollt wurde. Ein dazwischenkommender
    Abwärts-Tick verwirft die anstehende Einblendung wieder."""
    results = _run_sticky_header_collapse_with_fake_timer(
        [
            ("scroll", 300, 8),  # nach unten, geklebt -> sofort ausgeblendet
            ("scroll", 280, 8),  # ein Tick nach oben -> noch NICHT sofort eingeblendet
            ("fire_timer",),  # Verzögerung "vorgespult", kein Tick dazwischen -> jetzt eingeblendet
        ]
    )
    assert results == [True, True, False]


def test_sticky_header_expand_delay_is_reset_by_an_intervening_downward_tick():
    results = _run_sticky_header_collapse_with_fake_timer(
        [
            ("scroll", 300, 8),  # nach unten, geklebt -> ausgeblendet
            ("scroll", 280, 8),  # Tick nach oben -> Wiedereinblenden vorgemerkt
            ("scroll", 320, 8),  # Tick nach unten dazwischen -> verwirft die Vormerkung, bleibt ausgeblendet
            ("fire_timer",),  # die (bereits verworfene) alte Vormerkung feuert absichtlich ins Leere
        ]
    )
    assert results == [True, True, True, True]


def test_sticky_header_never_collapses_at_page_top():
    results = _run_sticky_header_collapse([(0, 8), (0, 8)])
    assert results == [False, False]


def _run_source_suggestion_row_click(action: str, *, fetch_ok: bool = True) -> dict:
    """Führt static/import.js#renderSourceSuggestionRow per Node aus und
    simuliert einen Klick auf "Annehmen" oder "Ablehnen" - mit minimalen
    Stubs für fetch/t/devUserHeaders (kein volles jsdom nötig, siehe
    _run_append_title_text). openUrlPopoverWithUrl (separate Funktion,
    siehe import.js) wird durch einen Spy ersetzt, der nur festhält, ob und
    mit welcher URL er aufgerufen wurde - hier geht es um die Annehmen/
    Ablehnen-Logik selbst, nicht um den Popover-Mechanismus (der bereits
    über extractAndFillFromUrl/den bestehenden #popover-load-Test-Pfad
    abgedeckt ist)."""
    js_source = (STATIC_DIR / "import.js").read_text()
    match = re.search(r"function renderSourceSuggestionRow.*?\n\}", js_source, re.S)
    assert match, "renderSourceSuggestionRow wurde in import.js nicht gefunden."
    func_source = match.group(0)
    script = f"""
function t(key) {{ return key; }}
function devUserHeaders() {{ return {{}}; }}
let openUrlPopoverCalledWith = null;
function openUrlPopoverWithUrl(url) {{ openUrlPopoverCalledWith = url; }}
// removeSourceSuggestionRow (Nachrücken samt Fade-Transitionen) hat eine
// eigene, dedizierte Testabdeckung weiter unten - hier interessiert nur,
// ob decide() sie mit der richtigen Zeile/ID aufruft.
let removeSourceSuggestionRowCalledWith = null;
function removeSourceSuggestionRow(li, id) {{
  removeSourceSuggestionRowCalledWith = id;
  li.remove();
}}
let fetchCalls = [];
global.fetch = async (url, options) => {{
  fetchCalls.push({{ url, options }});
  return {{ ok: {json.dumps(fetch_ok)} }};
}};

class FakeNode {{
  constructor(tag) {{
    this.tag = tag;
    this.children = [];
    this.parentNode = null;
    this.className = '';
    this.textContent = '';
    this.disabled = false;
    this.listeners = {{}};
    this.classList = {{
      add: (cls) => {{ this.className += ' ' + cls; }},
      toggle: (cls, force) => {{}},
    }};
  }}
  appendChild(child) {{ child.parentNode = this; this.children.push(child); return child; }}
  addEventListener(evt, fn) {{ this.listeners[evt] = fn; }}
  remove() {{ this.removed = true; }}
}}
const document = {{ createElement: (tag) => new FakeNode(tag) }};

{func_source}

const suggestion = {{
  id: 'sug-1',
  url: 'https://beispiel.org/artikel',
  title: 'Ein Artikel',
  reason: 'Passt gut.',
}};
const row = renderSourceSuggestionRow(suggestion);

function findButtons(node, acc) {{
  node.children.forEach((c) => {{
    if (c.tag === 'button') acc.push(c);
    findButtons(c, acc);
  }});
  return acc;
}}
const buttons = findButtons(row, []);
const acceptBtn = buttons[0];
const rejectBtn = buttons[1];

async function main() {{
  await ({json.dumps(action)} === 'accept' ? acceptBtn : rejectBtn).listeners.click();
  console.log(JSON.stringify({{
    fetchUrl: fetchCalls[0] ? fetchCalls[0].url : null,
    fetchMethod: fetchCalls[0] ? fetchCalls[0].options.method : null,
    rowRemoved: !!row.removed,
    removeSourceSuggestionRowCalledWith,
    openUrlPopoverCalledWith,
    acceptDisabled: acceptBtn.disabled,
    rejectDisabled: rejectBtn.disabled,
  }}));
}}
main();
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_source_suggestion_row_accept_calls_accept_endpoint_and_opens_url_popover():
    output = _run_source_suggestion_row_click("accept")
    assert output["fetchUrl"] == "/api/source-suggestions/sug-1/accept"
    assert output["fetchMethod"] == "POST"
    assert output["rowRemoved"] is True
    assert output["removeSourceSuggestionRowCalledWith"] == "sug-1"
    assert output["openUrlPopoverCalledWith"] == "https://beispiel.org/artikel"


def test_source_suggestion_row_reject_calls_reject_endpoint_without_opening_popover():
    output = _run_source_suggestion_row_click("reject")
    assert output["fetchUrl"] == "/api/source-suggestions/sug-1/reject"
    assert output["rowRemoved"] is True
    assert output["removeSourceSuggestionRowCalledWith"] == "sug-1"
    assert output["openUrlPopoverCalledWith"] is None


def test_source_suggestion_row_reenables_buttons_on_failed_request():
    output = _run_source_suggestion_row_click("reject", fetch_ok=False)
    assert output["rowRemoved"] is False
    assert output["acceptDisabled"] is False
    assert output["rejectDisabled"] is False


def _run_render_jobs_list_error_job_click(button_index: int, *, clicks: int = 1) -> dict:
    """Führt static/import.js#renderJobsListInto per Node aus und simuliert
    Klicks auf den Retry- oder den neuen Abbrechen-Button eines
    fehlgeschlagenen Jobs - mit minimalen Stubs für fetch/t/devUserHeaders/
    fetchImportJobs/loadSources (kein volles jsdom nötig, siehe
    _run_append_title_text)."""
    js_source = (STATIC_DIR / "import.js").read_text()
    match = re.search(r"function renderJobsListInto.*?\n\}", js_source, re.S)
    assert match, "renderJobsListInto wurde in import.js nicht gefunden."
    func_source = match.group(0)
    script = f"""
function t(key) {{ return key; }}
function devUserHeaders() {{ return {{}}; }}
function jobStepLabel() {{ return ''; }}
let fetchImportJobsCalled = false;
async function fetchImportJobs() {{ fetchImportJobsCalled = true; }}
let loadSourcesCalled = false;
async function loadSources() {{ loadSourcesCalled = true; }}
let fetchCalls = [];
global.fetch = async (url, options) => {{
  fetchCalls.push({{ url, options }});
  return {{ ok: true }};
}};

class FakeNode {{
  constructor(tag) {{
    this.tag = tag;
    this.children = [];
    this.className = '';
    this.textContent = '';
    this.disabled = false;
    this.listeners = {{}};
  }}
  set innerHTML(v) {{ this.children = []; }}
  appendChild(child) {{ this.children.push(child); return child; }}
  addEventListener(evt, fn) {{ this.listeners[evt] = fn; }}
}}
const document = {{ createElement: (tag) => new FakeNode(tag) }};
const cancelConfirmPendingJobIds = new Set();

{func_source}

const jobs = [
  {{ id: 'job-1', title: 'Kaputte Quelle', processing_status: 'error', processing_error: 'Fehler.' }},
];

function findButtons(node, acc) {{
  if (node.tag === 'button') acc.push(node);
  node.children.forEach((c) => findButtons(c, acc));
  return acc;
}}

let list = new FakeNode('ul');
renderJobsListInto(list, jobs);
let buttons = findButtons(list, []);

async function main() {{
  for (let i = 0; i < {clicks}; i++) {{
    await buttons[{button_index}].listeners.click();
    // Regressionstest: der 3-Sekunden-Poll-Takt baut die Liste bei JEDEM
    // Tick neu auf, auch wenn sich nichts geaendert hat (siehe
    // fetchImportJobs). Simuliert hier zwischen jedem Klick, damit ein
    // zurueckgesetzter Bestaetigungsstatus nicht unbemerkt bliebe.
    list = new FakeNode('ul');
    renderJobsListInto(list, jobs);
    buttons = findButtons(list, []);
  }}
  console.log(JSON.stringify({{
    buttonCount: buttons.length,
    fetchUrl: fetchCalls[0] ? fetchCalls[0].url : null,
    fetchMethod: fetchCalls[0] ? fetchCalls[0].options.method : null,
    fetchCallCount: fetchCalls.length,
    buttonText: buttons[{button_index}].textContent,
    fetchImportJobsCalled,
    loadSourcesCalled,
  }}));
}}
main();
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_error_job_shows_retry_and_cancel_buttons():
    output = _run_render_jobs_list_error_job_click(0, clicks=0)
    assert output["buttonCount"] == 2


def test_error_job_retry_button_calls_reprocess_endpoint():
    output = _run_render_jobs_list_error_job_click(0, clicks=1)
    assert output["fetchUrl"] == "/api/sources/job-1/reprocess"
    assert output["fetchMethod"] == "POST"


def test_error_job_cancel_button_requires_second_click_to_confirm():
    """Regressionstest (Nutzerwunsch 2026-08-23): "Erneut versuchen" kann
    einen endgültig fehlgeschlagenen Import (z.B. Datei/URL nie erreichbar)
    nicht retten - ohne einen Abbrechen-Weg blieb so ein Job für immer in
    der Liste hängen. Erster Klick darf noch NICHTS auslösen (nur die
    Bestätigung anzeigen), erst der zweite Klick löscht wirklich."""
    output = _run_render_jobs_list_error_job_click(1, clicks=1)
    assert output["fetchCallCount"] == 0
    assert output["buttonText"] == "import.cancelImportConfirmButton"


def test_error_job_cancel_button_deletes_source_on_second_click():
    output = _run_render_jobs_list_error_job_click(1, clicks=2)
    assert output["fetchUrl"] == "/api/sources/job-1"
    assert output["fetchMethod"] == "DELETE"
    assert output["fetchImportJobsCalled"] is True
    assert output["loadSourcesCalled"] is True


# Backlog (2026-08-03): der Broken-Links-Filter-Button in der Quellen-
# übersicht soll komplett verschwinden (nicht nur sein Zähler-Badge), sobald
# keine Quelle mehr einen defekten Link hat.


def _run_update_broken_links_button(*, is_pfleger: bool, sources: list[dict]) -> dict:
    js_source = (STATIC_DIR / "import.js").read_text()
    match = re.search(r"function updateBrokenLinksButton\(\) \{.*?\n\}", js_source, re.S)
    assert match, "updateBrokenLinksButton wurde in import.js nicht gefunden."
    func_source = match.group(0)
    script = f"""
function hasPflegerRole() {{ return {json.dumps(is_pfleger)}; }}
const allSources = {json.dumps(sources)};

function makeElement() {{
  let hidden = false;
  let text = '';
  return {{
    classList: {{
      toggle(cls, force) {{ if (cls === 'hidden') hidden = force; }},
      get hidden() {{ return hidden; }},
    }},
    set textContent(value) {{ text = value; }},
    get textContent() {{ return text; }},
  }};
}}

const badgeEl = makeElement();
const btnEl = makeElement();
const brokenLinksBtn = btnEl;
global.document = {{
  getElementById: (id) => (id === 'broken-links-count-badge' ? badgeEl : null),
}};

{func_source}

updateBrokenLinksButton();
console.log(JSON.stringify({{
  badgeHidden: badgeEl.classList.hidden,
  badgeText: badgeEl.textContent,
  btnHidden: btnEl.classList.hidden,
}}));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_update_broken_links_button_hidden_when_no_broken_sources():
    output = _run_update_broken_links_button(
        is_pfleger=True, sources=[{"url_reachable": True}, {"url_reachable": None}]
    )
    assert output == {"badgeHidden": True, "badgeText": "0", "btnHidden": True}


def test_update_broken_links_button_shown_when_pfleger_has_broken_sources():
    output = _run_update_broken_links_button(
        is_pfleger=True, sources=[{"url_reachable": False}, {"url_reachable": True}]
    )
    assert output == {"badgeHidden": False, "badgeText": "1", "btnHidden": False}


def test_update_broken_links_button_hidden_for_non_pfleger_even_with_broken_sources():
    output = _run_update_broken_links_button(is_pfleger=False, sources=[{"url_reachable": False}])
    assert output == {"badgeHidden": False, "badgeText": "1", "btnHidden": True}


# Backlog #201 (2026-08-03): klickbarer Link zu youtube-transcript.io + kurze
# Anleitung, wenn die automatische YouTube-Transkript-Extraktion fehlschlägt.


def _run_youtube_transcript_fallback_script(action_js: str) -> dict:
    js_source = (STATIC_DIR / "import.js").read_text()
    extract_id_match = re.search(r"function extractYoutubeVideoId\(url\) \{.*?\n\}", js_source, re.S)
    hint_match = re.search(
        r"function setYoutubeTranscriptFallbackHintVisible\(visible\) \{.*?\n\}", js_source, re.S
    )
    assert extract_id_match, "extractYoutubeVideoId wurde in import.js nicht gefunden."
    assert hint_match, "setYoutubeTranscriptFallbackHintVisible wurde in import.js nicht gefunden."

    script = f"""
function t(key) {{
  const dict = {{
    'import.youtubeTranscriptFallbackHint': 'Hinweistext.',
    'import.youtubeTranscriptFallbackLinkLabel': 'Link-Label',
  }};
  return dict[key] || key;
}}

function makeElement() {{
  const children = [];
  return {{
    classList: {{
      hidden: true,
      toggle(cls, force) {{ if (cls === 'hidden') this.hidden = force; }},
    }},
    get childNodes() {{ return children; }},
    appendChild(el) {{ children.push(el); return el; }},
    append(text) {{ children.push({{ textNode: text }}); }},
  }};
}}

const hintEl = makeElement();
global.document = {{
  getElementById: (id) => (id === 'youtube-transcript-fallback-hint' ? hintEl : null),
  createElement: (tag) => ({{ tagName: tag }}),
}};

{extract_id_match.group(0)}

{hint_match.group(0)}

{action_js}
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_youtube_transcript_fallback_hint_hidden_by_default():
    output = _run_youtube_transcript_fallback_script(
        "setYoutubeTranscriptFallbackHintVisible(false);"
        "console.log(JSON.stringify({ hidden: hintEl.classList.hidden, childCount: hintEl.childNodes.length }));"
    )
    assert output == {"hidden": True, "childCount": 0}


def test_youtube_transcript_fallback_hint_shows_instructions_and_link():
    output = _run_youtube_transcript_fallback_script(
        "setYoutubeTranscriptFallbackHintVisible(true);"
        "console.log(JSON.stringify({"
        "  hidden: hintEl.classList.hidden,"
        "  childCount: hintEl.childNodes.length,"
        "  linkHref: hintEl.childNodes[1].href,"
        "  linkTarget: hintEl.childNodes[1].target,"
        "  linkText: hintEl.childNodes[1].textContent,"
        "}));"
    )
    assert output["hidden"] is False
    assert output["childCount"] == 2
    assert output["linkHref"] == "https://www.youtube-transcript.io/"
    assert output["linkTarget"] == "_blank"
    assert output["linkText"] == "Link-Label"


def test_youtube_transcript_fallback_hint_does_not_duplicate_link_on_repeated_calls():
    output = _run_youtube_transcript_fallback_script(
        "setYoutubeTranscriptFallbackHintVisible(true);"
        "setYoutubeTranscriptFallbackHintVisible(false);"
        "setYoutubeTranscriptFallbackHintVisible(true);"
        "console.log(JSON.stringify({ childCount: hintEl.childNodes.length }));"
    )
    assert output == {"childCount": 2}


def test_extract_youtube_video_id_handles_watch_and_short_urls():
    output = _run_youtube_transcript_fallback_script(
        "console.log(JSON.stringify({"
        "  watch: extractYoutubeVideoId('https://www.youtube.com/watch?v=abc123&t=42s'),"
        "  short: extractYoutubeVideoId('https://youtu.be/abc123'),"
        "  other: extractYoutubeVideoId('https://example.org/artikel'),"
        "}));"
    )
    assert output == {"watch": "abc123", "short": "abc123", "other": None}


def _run_photo_credit_domain(call_expr: str):
    js_source = (STATIC_DIR / "import.js").read_text()
    match = re.search(r"const PHOTO_HOST_LABELS.*?function photoCreditDomain.*?\n\}", js_source, re.S)
    assert match, "PHOTO_HOST_LABELS/photoCreditDomain wurden in import.js nicht gefunden."
    script = f"""
{match.group(0)}
console.log(JSON.stringify({call_expr}));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_photo_credit_domain_maps_known_cdn_hosts_to_platform_name():
    """Nutzerfeedback (2026-08-26): media.licdn.com & Co. sind als
    Bildquellennachweis technisch korrekt, aber für Leser:innen kaum
    erkennbar - auf den bekannten Plattformnamen abbilden."""
    result = _run_photo_credit_domain(
        "[photoCreditDomain('https://media.licdn.com/dms/image/abc123/profile.jpg?query=1'),"
        " photoCreditDomain('https://i1.rgstatic.net/some/path.jpg'),"
        " photoCreditDomain('https://yt3.googleusercontent.com/abc'),"
        " photoCreditDomain('https://m.media-amazon.com/images/x.jpg'),"
        " photoCreditDomain('https://2.gravatar.com/avatar/x'),"
        " photoCreditDomain('https://i0.wp.com/example.org/photo.jpg')]"
    )
    assert result == ["LinkedIn", "ResearchGate", "Google", "Amazon", "Gravatar", "WordPress"]


def test_photo_credit_domain_leaves_unmapped_domains_as_is():
    """Eigene Websites (z.B. betacodex.org) sind bereits als Rohdomain
    aussagekräftig - keine Abbildung nötig. Google-Bilder-Thumbnails
    (gstatic.com) bleiben bewusst unverändert (siehe Kommentar bei
    PHOTO_HOST_LABELS) - die eigentliche Quelle wird stattdessen direkt in
    den Profilen korrigiert."""
    result = _run_photo_credit_domain(
        "[photoCreditDomain('https://www.example.org/photos/x.jpg'),"
        " photoCreditDomain('https://encrypted-tbn0.gstatic.com/images?q=x')]"
    )
    assert result == ["example.org", "encrypted-tbn0.gstatic.com"]


def test_photo_credit_domain_returns_null_when_missing_or_invalid():
    result = _run_photo_credit_domain(
        "[photoCreditDomain(''), photoCreditDomain(null), photoCreditDomain('not a url')]"
    )
    assert result == [None, None, None]


def _run_import_js_functions(patterns: list[str], call_expr: str):
    """Wie _run_photo_credit_domain, aber für Fälle, die mehrere, nicht
    zusammenhängende Definitionen aus import.js kombinieren müssen (z.B.
    resolveSocialPlatform() ruft sowohl detectSocialPlatform() als auch das
    an anderer Stelle definierte extractHostname() auf)."""
    js_source = (STATIC_DIR / "import.js").read_text()
    parts = []
    for pattern in patterns:
        match = re.search(pattern, js_source, re.S)
        assert match, f"Muster {pattern!r} wurde in import.js nicht gefunden."
        parts.append(match.group(0))
    script = "\n".join(parts) + f"\nconsole.log(JSON.stringify({call_expr}));\n"
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


# Nutzerwunsch (2026-08-26): kein manuelles Plattform-Feld mehr im Social-
# Links-Formular - resolveSocialPlatform() ermittelt die Plattform beim
# Speichern automatisch aus der URL (siehe buildSocialLinksField).
_RESOLVE_SOCIAL_PLATFORM_PATTERNS = [
    r"const SOCIAL_PLATFORM_HOSTS.*?\n\];",
    r"function detectSocialPlatform.*?\n\}",
    r"function extractHostname.*?\n\}",
    r"function resolveSocialPlatform.*?\n\}",
]


def test_resolve_social_platform_detects_known_platform_from_url():
    result = _run_import_js_functions(
        _RESOLVE_SOCIAL_PLATFORM_PATTERNS,
        "resolveSocialPlatform('https://www.linkedin.com/in/someone')",
    )
    assert result == "LinkedIn"


def test_resolve_social_platform_falls_back_to_hostname_for_unrecognized_platform():
    """Ein Link zu einer nicht in SOCIAL_PLATFORM_HOSTS gelisteten Plattform
    (z.B. eine persönliche Website) darf nicht verloren gehen, nur weil sie
    keinen erkannten Namen hat - die Domain ist ein sinnvoller Ersatz."""
    result = _run_import_js_functions(
        _RESOLVE_SOCIAL_PLATFORM_PATTERNS,
        "resolveSocialPlatform('https://www.example.org/profil')",
    )
    assert result == "example.org"


def test_resolve_social_platform_falls_back_to_raw_input_for_invalid_url():
    result = _run_import_js_functions(_RESOLVE_SOCIAL_PLATFORM_PATTERNS, "resolveSocialPlatform('not a url')")
    assert result == "not a url"


def _run_source_toolbar_overflow(steps: list[dict]) -> list[bool]:
    """Führt static/import.js#initSourceToolbarOverflow per Node aus. Jeder
    Schritt setzt actions.clientWidth neu und feuert den (gestubbten)
    ResizeObserver-Callback - simuliert damit ein Breiter-/Schmaler-Ziehen
    des Fensters. Rückgabe: ob .sort-toolbar nach jedem Schritt via
    'sort-toolbar--hidden-for-space' ausgeblendet ist. Icon-Gruppe (200px)
    und Suche (53px) sind immer sichtbar, Sortierung (93px) ist das
    einzige Element, das die Funktion selbst ein-/ausblendet."""
    js_source = (STATIC_DIR / "import.js").read_text()
    match = re.search(r"function initSourceToolbarOverflow.*?\n\}", js_source, re.S)
    assert match, "initSourceToolbarOverflow wurde in import.js nicht gefunden."
    func_source = match.group(0)
    steps_js = json.dumps([s["clientWidth"] for s in steps])
    script = f"""
class FakeNode {{
  constructor(width) {{
    this._width = width;
    this._classes = new Set(['sort-toolbar']);
    this.children = [];
    this.classList = {{
      add: (c) => this._classes.add(c),
      remove: (c) => this._classes.delete(c),
      toggle: (c, force) => {{
        const has = this._classes.has(c);
        const next = force === undefined ? !has : force;
        if (next) this._classes.add(c); else this._classes.delete(c);
      }},
      contains: (c) => this._classes.has(c),
    }};
  }}
  getBoundingClientRect() {{ return {{ width: this._width }}; }}
}}

const iconGroup = new FakeNode(200);
const sortToolbar = new FakeNode(93);
const searchToolbar = new FakeNode(53);
const actions = new FakeNode(0);
actions.children = [iconGroup, sortToolbar, searchToolbar];
actions.clientWidth = 1000;
const row = new FakeNode(0);

global.document = {{
  querySelector: (sel) => {{
    if (sel === '.section-heading-row') return row;
    if (sel === '.section-heading-actions') return actions;
    if (sel === '.sort-toolbar') return sortToolbar;
    return null;
  }},
}};
global.getComputedStyle = (el) => ({{
  columnGap: '20px',
  display: el === sortToolbar
    ? (el._classes.has('sort-toolbar') && el._classes.has('sort-toolbar--hidden-for-space') ? 'none' : 'flex')
    : 'flex',
}});
let resizeCallback = null;
global.ResizeObserver = class {{
  constructor(cb) {{ resizeCallback = cb; }}
  observe() {{}}
}};

{func_source}

initSourceToolbarOverflow();

const results = [];
for (const clientWidth of {steps_js}) {{
  actions.clientWidth = clientWidth;
  resizeCallback();
  results.push(sortToolbar._classes.has('sort-toolbar--hidden-for-space'));
}}
console.log(JSON.stringify(results));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_source_toolbar_hides_sort_toolbar_when_too_narrow_for_all_icons():
    results = _run_source_toolbar_overflow([{"clientWidth": 300}])
    assert results == [True]


def test_source_toolbar_shows_sort_toolbar_when_search_still_fits():
    results = _run_source_toolbar_overflow([{"clientWidth": 400}])
    assert results == [False]


def test_source_toolbar_reshows_sort_toolbar_after_widening_again():
    """Regressionstest (Nutzerwunsch 2026-08-23): ein ResizeObserver direkt
    auf .section-heading-actions haette hier NICHT ausgereicht - sobald
    .sort-toolbar einmal ausgeblendet ist, schrumpft die Box auf die
    verbleibenden Icons und aendert sich beim Wiederverbreitern des Fensters
    nicht mehr von selbst (kein neues Resize-Ereignis). initSourceToolbar
    Overflow() beobachtet daher bewusst .section-heading-row statt
    .section-heading-actions."""
    results = _run_source_toolbar_overflow([{"clientWidth": 300}, {"clientWidth": 400}])
    assert results == [True, False]


def _run_remove_source_suggestion_row(*, reserve_ids: list[str], visible_ids: list[str] = None) -> dict:
    """Führt static/import.js#removeSourceSuggestionRow per Node aus -
    prüft sowohl den SOFORTIGEN Zustand (Fade-Out-Klasse, Entfernung aus
    sourceSuggestionsVisible) als auch den Zustand NACH Ablauf von
    SOURCE_SUGGESTION_LEAVE_MS (tatsächliche DOM-Entfernung, Nachrücken aus
    sourceSuggestionsReserve samt Fade-In-Klasse). renderSourceSuggestionRow
    wird durch einen Spy ersetzt - hier geht es nur um die Nachrück-
    Choreographie selbst, nicht um den Zeilenaufbau (separat abgedeckt).
    Entfernt wird immer die Zeile mit id 'a'."""
    js_source = (STATIC_DIR / "import.js").read_text()
    match = re.search(r"function removeSourceSuggestionRow.*?\n\}", js_source, re.S)
    assert match, "removeSourceSuggestionRow wurde in import.js nicht gefunden."
    func_source = match.group(0)
    reserve_js = json.dumps([{"id": rid} for rid in reserve_ids])
    visible_js = json.dumps([{"id": rid} for rid in (visible_ids if visible_ids is not None else ["a", "b"])])
    script = f"""
class FakeNode {{
  constructor() {{
    this._classes = new Set();
    this.classList = {{ add: (c) => this._classes.add(c) }};
    this.removed = false;
  }}
  remove() {{ this.removed = true; }}
}}

const SOURCE_SUGGESTION_LEAVE_MS = 5;
let sourceSuggestionsVisible = {visible_js};
let sourceSuggestionsReserve = {reserve_js};
const listChildren = [];
const sourceSuggestionsList = {{ appendChild: (el) => {{ listChildren.push(el); }} }};
const emptyHiddenCalls = [];
const sourceSuggestionsEmpty = {{ classList: {{ toggle: (cls, force) => emptyHiddenCalls.push(force) }} }};
let buttonVisibilityCalls = 0;
function updateSourceSuggestionsButtonVisibility() {{ buttonVisibilityCalls++; }}
let renderCalledWith = null;
function renderSourceSuggestionRow(s) {{
  renderCalledWith = s;
  return new FakeNode();
}}

{func_source}

const li = new FakeNode();
removeSourceSuggestionRow(li, 'a');
const immediate = {{
  hasLeavingClass: li._classes.has('web-allowlist-candidate--leaving'),
  removedImmediately: li.removed,
  visibleRightAfter: sourceSuggestionsVisible.map((s) => s.id),
}};

async function main() {{
  await new Promise((resolve) => setTimeout(resolve, SOURCE_SUGGESTION_LEAVE_MS + 20));
  console.log(JSON.stringify({{
    immediate,
    removedAfterTimeout: li.removed,
    visibleAfterTimeout: sourceSuggestionsVisible.map((s) => s.id),
    reserveAfterTimeout: sourceSuggestionsReserve.map((s) => s.id),
    promotedCount: listChildren.length,
    promotedHasEnteringClass: listChildren[0] ? listChildren[0]._classes.has('web-allowlist-candidate--entering') : null,
    renderCalledWith,
    emptyHiddenCalls,
    buttonVisibilityCalls,
  }}));
}}
main();
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_remove_source_suggestion_row_fades_out_immediately_without_removing():
    """Regressionstest: der Fade-Out darf nicht abrupt sein - die Zeile
    bekommt sofort die Übergangs-Klasse, wird aber erst nach Ablauf der
    Transition tatsächlich aus dem DOM entfernt."""
    output = _run_remove_source_suggestion_row(reserve_ids=[])
    assert output["immediate"]["hasLeavingClass"] is True
    assert output["immediate"]["removedImmediately"] is False
    assert output["immediate"]["visibleRightAfter"] == ["b"]


def test_remove_source_suggestion_row_promotes_next_reserve_item_with_entering_class():
    """Regressionstest (Nutzerwunsch 2026-08-23): rückt sofort (ohne neue
    Websuche) den nächsten Vorschlag aus dem bereits geladenen Vorrat nach,
    sobald einer entschieden wurde - mit Fade-In-Klasse am Ende der Liste."""
    output = _run_remove_source_suggestion_row(reserve_ids=["c", "d"])
    assert output["removedAfterTimeout"] is True
    assert output["visibleAfterTimeout"] == ["b", "c"]
    assert output["reserveAfterTimeout"] == ["d"]
    assert output["promotedCount"] == 1
    assert output["promotedHasEnteringClass"] is True
    assert output["renderCalledWith"] == {"id": "c"}
    assert output["buttonVisibilityCalls"] == 1


def test_remove_source_suggestion_row_shows_empty_state_when_nothing_left():
    """War 'a' die letzte sichtbare Zeile und der Vorrat ebenfalls leer,
    muss der Empty-State-Hinweis nach dem Entfernen sichtbar werden (toggle
    'hidden' mit force=false)."""
    output = _run_remove_source_suggestion_row(reserve_ids=[], visible_ids=["a"])
    assert output["promotedCount"] == 0
    assert output["visibleAfterTimeout"] == []
    assert output["emptyHiddenCalls"][-1] is False


def _run_explore_js_function(function_pattern: str, call_expr: str):
    """Führt eine einzelne reine Funktion aus static/explore.js per Node
    aus - gleiches Extraktions-Muster wie an anderer Stelle in dieser Datei
    (z.B. _run_find_highlight_range). explore.js selbst bindet u.a. an das
    globale d3-Objekt und den DOM - hier geht es nur um die eigenständigen,
    reinen Hilfsfunktionen (nodeUrl/radiusFor/normalizeSearch), die keine
    dieser Abhängigkeiten brauchen."""
    js_source = (STATIC_DIR / "explore.js").read_text()
    match = re.search(function_pattern, js_source, re.S)
    assert match, f"Muster {function_pattern!r} wurde in explore.js nicht gefunden."
    func_source = match.group(0)
    script = f"""
{func_source}
console.log(JSON.stringify({call_expr}));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_node_url_links_author_nodes_to_the_author_filter():
    result = _run_explore_js_function(
        r"function nodeUrl.*?\n\}",
        "nodeUrl({ type: 'author', label: 'Niels Pflaeging' })",
    )
    assert result == "/import.html?author=Niels%20Pflaeging"


def test_node_url_links_term_nodes_to_the_term_filter():
    result = _run_explore_js_function(
        r"function nodeUrl.*?\n\}",
        "nodeUrl({ type: 'term', label: 'Beyond Budgeting' })",
    )
    assert result == "/import.html?term=Beyond%20Budgeting"


def test_radius_for_scales_with_weight_but_is_capped():
    low = _run_explore_js_function(r"function radiusFor.*?\n\}", "radiusFor({ type: 'term', weight: 1 })")
    high = _run_explore_js_function(r"function radiusFor.*?\n\}", "radiusFor({ type: 'term', weight: 3 })")
    capped_at_25 = _run_explore_js_function(r"function radiusFor.*?\n\}", "radiusFor({ type: 'term', weight: 25 })")
    capped_above_25 = _run_explore_js_function(
        r"function radiusFor.*?\n\}", "radiusFor({ type: 'term', weight: 500 })"
    )
    assert high > low
    # Nutzerwunsch (implizit über die Bug-Historie dieser Session): ein
    # extrem häufiges Schlagwort darf die Simulation nicht durch einen
    # unbegrenzt wachsenden Radius dominieren - gedeckelt bei weight=25.
    assert capped_at_25 == capped_above_25


def test_radius_for_authors_and_terms_use_different_base_size():
    author = _run_explore_js_function(r"function radiusFor.*?\n\}", "radiusFor({ type: 'author', weight: 0 })")
    term = _run_explore_js_function(r"function radiusFor.*?\n\}", "radiusFor({ type: 'term', weight: 0 })")
    assert author > term


def test_normalize_search_is_case_insensitive_and_trims():
    result = _run_explore_js_function(r"function normalizeSearch.*?\n\}", "normalizeSearch('  Dezentralisierung  ')")
    assert result == "dezentralisierung"


def test_neighbor_ids_includes_the_node_itself_and_direct_neighbors():
    result = _run_explore_js_function(
        r"function neighborIds.*?\n\}",
        "[...neighborIds('a', [{ source: 'a', target: 'b' }, { source: 'c', target: 'd' }])].sort()",
    )
    assert result == ["a", "b"]


# Nutzerwunsch (2026-08-26): Autor:innen/Schlagworte im Explore-Netzwerk
# unabhängig voneinander ein-/ausblendbar - deriveAuthorOnlyEdges() bildet
# dabei fehlende Autor-Autor-Kanten über geteilte (jetzt ausgeblendete)
# Schlagworte nach. filterGraphForToggles() ruft diese Funktion intern auf,
# daher hier ein Muster, das BEIDE Funktionsdefinitionen extrahiert.
_DERIVE_AND_FILTER_PATTERN = r"function deriveAuthorOnlyEdges.*?function filterGraphForToggles.*?\n\}"


def test_derive_author_only_edges_connects_authors_sharing_one_term():
    result = _run_explore_js_function(
        r"function deriveAuthorOnlyEdges.*?\n\}",
        """deriveAuthorOnlyEdges(
          [{ id: 'author:A', type: 'author' }, { id: 'author:B', type: 'author' }, { id: 'term:X', type: 'term' }],
          [{ source: 'author:A', target: 'term:X', weight: 1 }, { source: 'author:B', target: 'term:X', weight: 1 }]
        )""",
    )
    assert result == [{"source": "author:A", "target": "author:B", "weight": 1}]


def test_derive_author_only_edges_sums_weight_across_shared_terms():
    result = _run_explore_js_function(
        r"function deriveAuthorOnlyEdges.*?\n\}",
        """deriveAuthorOnlyEdges(
          [{ id: 'author:A', type: 'author' }, { id: 'author:B', type: 'author' },
            { id: 'term:X', type: 'term' }, { id: 'term:Y', type: 'term' }],
          [
            { source: 'author:A', target: 'term:X', weight: 1 },
            { source: 'author:B', target: 'term:X', weight: 1 },
            { source: 'author:A', target: 'term:Y', weight: 1 },
            { source: 'author:B', target: 'term:Y', weight: 1 },
          ]
        )[0].weight""",
    )
    assert result == 2


def test_derive_author_only_edges_keeps_existing_direct_author_edge():
    """Eine bereits vorhandene direkte Autor-Autor-Kante (z.B. durch den
    Keyword-Autor:innen-Merge, siehe app/main.py:_build_knowledge_graph)
    bleibt unverändert erhalten, statt beim Ausblenden der Schlagworte zu
    verschwinden."""
    result = _run_explore_js_function(
        r"function deriveAuthorOnlyEdges.*?\n\}",
        """deriveAuthorOnlyEdges(
          [{ id: 'author:A', type: 'author' }, { id: 'author:B', type: 'author' }],
          [{ source: 'author:A', target: 'author:B', weight: 3 }]
        )""",
    )
    assert result == [{"source": "author:A", "target": "author:B", "weight": 3}]


def test_filter_graph_for_toggles_returns_full_data_when_both_shown():
    data = {
        "nodes": [{"id": "author:A", "type": "author"}, {"id": "term:X", "type": "term"}],
        "edges": [{"source": "author:A", "target": "term:X", "weight": 1}],
    }
    result = _run_explore_js_function(
        _DERIVE_AND_FILTER_PATTERN,
        f"filterGraphForToggles({json.dumps(data)}, true, true)",
    )
    assert result == data


def test_filter_graph_for_toggles_returns_empty_when_both_hidden():
    data = {
        "nodes": [{"id": "author:A", "type": "author"}],
        "edges": [],
    }
    result = _run_explore_js_function(
        _DERIVE_AND_FILTER_PATTERN,
        f"filterGraphForToggles({json.dumps(data)}, false, false)",
    )
    assert result == {"nodes": [], "edges": []}


def test_filter_graph_for_toggles_hiding_terms_keeps_only_authors_and_derived_edges():
    data = {
        "nodes": [
            {"id": "author:A", "type": "author"},
            {"id": "author:B", "type": "author"},
            {"id": "term:X", "type": "term"},
        ],
        "edges": [
            {"source": "author:A", "target": "term:X", "weight": 1},
            {"source": "author:B", "target": "term:X", "weight": 1},
        ],
    }
    result = _run_explore_js_function(
        _DERIVE_AND_FILTER_PATTERN,
        f"filterGraphForToggles({json.dumps(data)}, true, false)",
    )
    assert result["nodes"] == [{"id": "author:A", "type": "author"}, {"id": "author:B", "type": "author"}]
    assert result["edges"] == [{"source": "author:A", "target": "author:B", "weight": 1}]


def test_filter_graph_for_toggles_hiding_authors_keeps_only_terms_and_their_edges():
    data = {
        "nodes": [
            {"id": "author:A", "type": "author"},
            {"id": "term:X", "type": "term"},
            {"id": "term:Y", "type": "term"},
        ],
        "edges": [
            {"source": "author:A", "target": "term:X", "weight": 1},
            {"source": "term:X", "target": "term:Y", "weight": 2},
        ],
    }
    result = _run_explore_js_function(
        _DERIVE_AND_FILTER_PATTERN,
        f"filterGraphForToggles({json.dumps(data)}, false, true)",
    )
    assert result["nodes"] == [{"id": "term:X", "type": "term"}, {"id": "term:Y", "type": "term"}]
    assert result["edges"] == [{"source": "term:X", "target": "term:Y", "weight": 2}]


def test_neighbor_ids_matches_regardless_of_source_or_target_position():
    """Eine Kante kann den gesuchten Knoten sowohl als source als auch als
    target führen - beide Richtungen müssen den jeweils anderen Knoten als
    Nachbarn liefern."""
    result = _run_explore_js_function(
        r"function neighborIds.*?\n\}",
        "[...neighborIds('b', [{ source: 'a', target: 'b' }, { source: 'b', target: 'c' }])].sort()",
    )
    assert result == ["a", "b", "c"]


def test_neighbor_ids_accepts_resolved_node_objects_like_after_force_link():
    """D3s forceLink ersetzt source/target nach der Initialisierung durch
    echte Knoten-Objekte statt roher IDs - neighborIds muss beides
    verarbeiten können."""
    result = _run_explore_js_function(
        r"function neighborIds.*?\n\}",
        "[...neighborIds('a', [{ source: { id: 'a' }, target: { id: 'b' } }])].sort()",
    )
    assert result == ["a", "b"]


def test_neighbor_ids_excludes_unconnected_nodes():
    result = _run_explore_js_function(
        r"function neighborIds.*?\n\}",
        "[...neighborIds('a', [{ source: 'c', target: 'd' }])].sort()",
    )
    assert result == ["a"]


def _run_highlight_terms_in_element(key_terms, authors, text="Vor Dezentralisierung Max Muster danach."):
    """Führt static/import.js#highlightTermsInElement per Node aus, mit
    minimalen DOM-Stubs (kein volles jsdom nötig - die Funktion nutzt nur
    createTreeWalker/createDocumentFragment/replaceChild). Regressionstest
    dafür, dass Autor:innen-Namen unter den Schlagworten NICHT mehr
    hervorgehoben werden (2026-08-23, Nutzerfeedback: Namensabgleich war zu
    fehleranfällig)."""
    js_source = (STATIC_DIR / "import.js").read_text()
    highlight_match = re.search(r"function highlightTermsInElement.*?\n\}", js_source, re.S)
    escape_match = re.search(r"function escapeRegExp.*?\n\}", js_source, re.S)
    assert highlight_match, "highlightTermsInElement wurde in import.js nicht gefunden."
    assert escape_match, "escapeRegExp wurde in import.js nicht gefunden."
    script = f"""
class FakeNode {{
  constructor(nodeType, tag) {{
    this.nodeType = nodeType;
    this.tag = tag || null;
    this.children = [];
    this.parentNode = null;
    this.className = '';
    this.textContent = '';
    this.listeners = {{}};
  }}
  appendChild(child) {{ child.parentNode = this; this.children.push(child); return child; }}
  replaceChild(newNode, oldNode) {{
    const i = this.children.indexOf(oldNode);
    if (i === -1) return;
    const replacement = newNode.nodeType === 'fragment' ? newNode.children : [newNode];
    replacement.forEach((c) => {{ c.parentNode = this; }});
    this.children.splice(i, 1, ...replacement);
  }}
  addEventListener(evt, fn) {{ this.listeners[evt] = fn; }}
  setAttribute() {{}}
  get textContentDeep() {{
    if (this.nodeType === 'text') return this.textContent;
    if (this.children.length === 0) return this.textContent;
    return this.children.map((c) => c.textContentDeep).join('');
  }}
}}
const document = {{
  createElement: (tag) => new FakeNode('element', tag),
  createTextNode: (text) => {{ const n = new FakeNode('text'); n.textContent = text; return n; }},
  createDocumentFragment: () => new FakeNode('fragment'),
  createTreeWalker: (root) => {{
    const stack = [];
    (function collect(node) {{
      node.children.forEach((child) => {{
        if (child.nodeType === 'text') stack.push(child);
        else collect(child);
      }});
    }})(root);
    let i = 0;
    return {{ nextNode: () => (i < stack.length ? stack[i++] : null) }};
  }},
}};
const NodeFilter = {{ SHOW_TEXT: 4 }};
const allAuthors = {json.dumps(authors)};
function t() {{ return 'Nach diesem Schlagwort filtern'; }}
function filterByTerm() {{}}
function filterByAuthor() {{}}

{escape_match.group(0)}
{highlight_match.group(0)}

const container = new FakeNode('element', 'div');
container.appendChild(document.createTextNode({json.dumps(text)}));
highlightTermsInElement(container, {json.dumps(key_terms)});

function findButtons(node, acc) {{
  if (node.tag === 'button') acc.push({{ className: node.className, text: node.textContentDeep }});
  node.children.forEach((c) => findButtons(c, acc));
  return acc;
}}
console.log(JSON.stringify(findButtons(container, [])));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_highlight_terms_does_not_highlight_a_matching_author_name():
    buttons = _run_highlight_terms_in_element(
        key_terms=["Dezentralisierung", "Max Muster"],
        authors=[{"name": "Max Muster"}],
    )
    texts = [b["text"] for b in buttons]
    assert "Max Muster" not in texts
    assert "Dezentralisierung" in texts


def test_highlight_terms_matches_author_name_case_insensitively():
    buttons = _run_highlight_terms_in_element(
        key_terms=["Dezentralisierung", "max muster"],
        authors=[{"name": "Max Muster"}],
        text="Vor Dezentralisierung max muster danach.",
    )
    texts = [b["text"] for b in buttons]
    assert "max muster" not in texts
    assert "Dezentralisierung" in texts


def test_highlight_terms_still_highlights_generic_terms_as_term_highlight_button():
    buttons = _run_highlight_terms_in_element(
        key_terms=["Dezentralisierung"],
        authors=[{"name": "Max Muster"}],
    )
    assert buttons == [{"className": "term-highlight-button", "text": "Dezentralisierung"}]


def test_highlight_terms_no_op_when_all_terms_are_author_names():
    buttons = _run_highlight_terms_in_element(
        key_terms=["Max Muster"],
        authors=[{"name": "Max Muster"}],
    )
    assert buttons == []


# --- Kreativ-Modus (2026-08-26) ---


def _run_creative_source_label(source):
    js_source = (STATIC_DIR / "creative.js").read_text()
    match = re.search(r"export function creativeSourceLabel.*?\n\}", js_source, re.S)
    assert match, "creativeSourceLabel wurde in creative.js nicht gefunden."
    script = f"{match.group(0)}\nconsole.log(JSON.stringify(creativeSourceLabel({json.dumps(source)})));"
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_creative_source_label_appends_hostname_when_url_present():
    label = _run_creative_source_label({"title": "Beispieltitel", "url": "https://example.org/a/b"})
    assert label == "Beispieltitel (example.org)"


def test_creative_source_label_falls_back_to_title_without_url():
    label = _run_creative_source_label({"title": "Beispieltitel", "url": None})
    assert label == "Beispieltitel"


def test_creative_source_label_shows_authors_instead_of_hostname_when_present():
    label = _run_creative_source_label(
        {"title": "Beispieltitel", "url": "https://example.org/a/b", "authors": ["Niels Pflaeging"]}
    )
    assert label == "Beispieltitel — Niels Pflaeging"


def test_creative_source_label_joins_multiple_authors():
    label = _run_creative_source_label(
        {"title": "Beispieltitel", "url": "https://example.org/a/b", "authors": ["Autor A", "Autor B"]}
    )
    assert label == "Beispieltitel — Autor A, Autor B"


def test_creative_source_label_falls_back_to_hostname_when_authors_empty():
    label = _run_creative_source_label(
        {"title": "Beispieltitel", "url": "https://example.org/a/b", "authors": []}
    )
    assert label == "Beispieltitel (example.org)"


def _run_apply_markdown_to_selection(value, selection_start, selection_end, action):
    js_source = (STATIC_DIR / "creative.js").read_text()
    match = re.search(r"export function applyMarkdownToSelection.*?\n\}", js_source, re.S)
    assert match, "applyMarkdownToSelection wurde in creative.js nicht gefunden."
    script = (
        f"{match.group(0)}\n"
        f"console.log(JSON.stringify(applyMarkdownToSelection("
        f"{json.dumps(value)}, {selection_start}, {selection_end}, {json.dumps(action)})));"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_apply_markdown_bold_wraps_selection():
    result = _run_apply_markdown_to_selection("Hallo Welt", 6, 10, "bold")
    assert result["value"] == "Hallo **Welt**"
    assert (result["selectionStart"], result["selectionEnd"]) == (8, 12)


def test_apply_markdown_italic_wraps_selection():
    result = _run_apply_markdown_to_selection("Hallo Welt", 6, 10, "italic")
    assert result["value"] == "Hallo *Welt*"
    assert (result["selectionStart"], result["selectionEnd"]) == (7, 11)


def test_apply_markdown_bold_without_selection_places_cursor_between_markers():
    result = _run_apply_markdown_to_selection("Hallo Welt", 5, 5, "bold")
    assert result["value"] == "Hallo**** Welt"
    assert (result["selectionStart"], result["selectionEnd"]) == (7, 7)


def test_apply_markdown_heading_prefixes_single_line():
    result = _run_apply_markdown_to_selection("Titel", 0, 5, "heading")
    assert result["value"] == "## Titel"
    assert (result["selectionStart"], result["selectionEnd"]) == (3, 8)


def test_apply_markdown_list_prefixes_multiple_selected_lines():
    value = "Erste Zeile\nZweite Zeile\nDritte Zeile"
    # Selektion umfasst nur "Erste Zeile\nZweite" - beide betroffenen Zeilen
    # bekommen trotzdem vollständig das Präfix.
    result = _run_apply_markdown_to_selection(value, 0, 18, "list")
    assert result["value"] == "- Erste Zeile\n- Zweite Zeile\nDritte Zeile"


def test_apply_markdown_heading_does_not_duplicate_existing_prefix():
    result = _run_apply_markdown_to_selection("## Titel", 0, 8, "heading")
    assert result["value"] == "## Titel"
    assert (result["selectionStart"], result["selectionEnd"]) == (0, 8)


# --- creative.js: parseCreativeSections/spliceCreativeSection (2026-08-30) ---


def _run_parse_creative_sections(markdown):
    js_source = (STATIC_DIR / "creative.js").read_text()
    match = re.search(r"export function parseCreativeSections.*?\n\}", js_source, re.S)
    assert match, "parseCreativeSections wurde in creative.js nicht gefunden."
    script = f"{match.group(0)}\nconsole.log(JSON.stringify(parseCreativeSections({json.dumps(markdown)})));"
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_parse_creative_sections_returns_empty_list_for_empty_document():
    assert _run_parse_creative_sections("") == []


def test_parse_creative_sections_single_section_without_heading():
    sections = _run_parse_creative_sections("Nur Fließtext, keine Überschrift.")
    assert len(sections) == 1
    assert sections[0]["heading"] is None
    assert sections[0]["text"] == "Nur Fließtext, keine Überschrift."


def test_parse_creative_sections_splits_on_each_heading_regardless_of_level():
    markdown = "# Eins\n\nText eins.\n\n## Zwei\n\nText zwei.\n\n### Drei\n\nText drei."
    sections = _run_parse_creative_sections(markdown)
    assert [s["heading"] for s in sections] == ["Eins", "Zwei", "Drei"]


def test_parse_creative_sections_keeps_leading_text_before_first_heading():
    markdown = "Einleitung ohne Überschrift.\n\n# Erster Abschnitt\n\nText."
    sections = _run_parse_creative_sections(markdown)
    assert sections[0]["heading"] is None
    assert sections[0]["text"] == "Einleitung ohne Überschrift.\n\n"
    assert sections[1]["heading"] == "Erster Abschnitt"


def test_parse_creative_sections_offsets_round_trip_to_original_text():
    markdown = "# Eins\n\nText eins.\n\n## Zwei\n\nText zwei."
    sections = _run_parse_creative_sections(markdown)
    for section in sections:
        assert markdown[section["start"] : section["end"]] == section["text"]


def _run_splice_creative_section(document, start, end, replacement):
    js_source = (STATIC_DIR / "creative.js").read_text()
    match = re.search(r"export function spliceCreativeSection.*?\n\}", js_source, re.S)
    assert match, "spliceCreativeSection wurde in creative.js nicht gefunden."
    script = (
        f"{match.group(0)}\n"
        f"console.log(JSON.stringify(spliceCreativeSection("
        f"{json.dumps(document)}, {start}, {end}, {json.dumps(replacement)})));"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_splice_creative_section_replaces_middle_section():
    document = "# Eins\n\nAlt.\n\n# Zwei\n\nText zwei."
    result = _run_splice_creative_section(document, 0, 14, "# Eins\n\nNeu.")
    assert result == "# Eins\n\nNeu.\n\n# Zwei\n\nText zwei."


def test_splice_creative_section_replacing_last_section_adds_no_trailing_whitespace():
    document = "# Eins\n\nAlt.\n\n# Zwei\n\nText zwei."
    result = _run_splice_creative_section(document, 14, len(document), "# Zwei\n\nNeuer Text.")
    assert result == "# Eins\n\nAlt.\n\n# Zwei\n\nNeuer Text."


def test_splice_creative_section_replaces_only_section_in_single_section_document():
    document = "Nur ein Abschnitt ohne Überschrift."
    result = _run_splice_creative_section(document, 0, len(document), "Neuer Text.")
    assert result == "Neuer Text."


# --- markdown.js: renderMarkdown (2026-08-28) ---


def _run_render_markdown(text):
    js_source = (STATIC_DIR / "markdown.js").read_text()
    match = re.search(
        r"function escapeHtml.*?\nexport function renderMarkdown\(text\) \{.*?\n\}",
        js_source,
        re.S,
    )
    assert match, "renderMarkdown (+ escapeHtml) wurde in markdown.js nicht gefunden."
    script = f"{match.group(0)}\nconsole.log(JSON.stringify(renderMarkdown({json.dumps(text)})));"
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_render_markdown_escapes_html():
    html = _run_render_markdown("<script>alert('x')</script> & Co")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp; Co" in html


def test_render_markdown_bold_and_italic():
    html = _run_render_markdown("**fett** und *kursiv*")
    assert html == "<p><strong>fett</strong> und <em>kursiv</em></p>"


def test_render_markdown_renders_internal_link():
    html = _run_render_markdown("Schau mal im [Kreativ-Modus](/creative.html?instruction=Test) vorbei.")
    assert '<a href="/creative.html?instruction=Test">Kreativ-Modus</a>' in html


def test_render_markdown_renders_https_link():
    html = _run_render_markdown("Siehe [BetaCodex](https://betacodex.org).")
    assert '<a href="https://betacodex.org">BetaCodex</a>' in html


def test_render_markdown_does_not_render_non_http_link_targets():
    html = _run_render_markdown("[Klick mich](javascript:alert(1))")
    assert "<a href" not in html
    assert "javascript:alert(1)" in html


def test_render_markdown_link_text_may_not_contain_brackets():
    # Bewusste Einschränkung der Regex (kein verschachteltes [...]) - ein
    # Zitatverweis wie "[1]" direkt vor einer Klammer darf nicht versehentlich
    # als Linkstart fehlinterpretiert werden.
    html = _run_render_markdown("Siehe [1] (Zusatzinfo).")
    assert "<a href" not in html
    assert "[1] (Zusatzinfo)" in html


def test_creative_js_has_no_orphaned_dom_elements():
    js_source = (STATIC_DIR / "creative.js").read_text()
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


# --- index.html/embed.html: geteilte Eingabezeilen-Struktur (2026-08-30) ---


@pytest.mark.parametrize("filename", ["index.html", "embed.html"])
def test_question_form_does_not_contain_turnstile_container(filename):
    # Regression (2026-08-30): der "Mikrofon-Icon springt"-Fix (Backlog
    # 2026-08-09) zog #turnstile-container aus #question-form heraus - wurde
    # damals nur in index.html gemacht, embed.html (eigenständige, nicht per
    # Template geteilte Kopie derselben Eingabezeile, siehe Kommentare in
    # beiden Dateien) blieb unbemerkt auf dem alten, fehlerhaften Stand.
    # Dieser Test hält beide Dateien strukturell im Takt.
    html = (STATIC_DIR / filename).read_text()
    form_match = re.search(r'<form id="question-form".*?</form>', html, re.S)
    assert form_match, f"#question-form wurde in {filename} nicht gefunden."
    assert 'id="turnstile-container"' not in form_match.group(0), (
        f"#turnstile-container liegt in {filename} wieder innerhalb von #question-form - "
        "das verursacht das 'Mikrofon-Icon springt'-Problem erneut (siehe Backlog 2026-08-09)."
    )
