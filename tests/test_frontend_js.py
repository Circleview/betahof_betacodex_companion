import json
import re
import subprocess
from pathlib import Path

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
