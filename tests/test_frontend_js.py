import json
import re
import subprocess
from pathlib import Path

import pytest

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _import_js_source() -> str:
    # Seit 2026-09-25 liegt das Bearbeiten-Formular samt Helfern in
    # static/source-edit.js (von import.js importiert) - die Regex-basierten
    # Funktions-Extraktionen unten durchsuchen beide Dateien gemeinsam.
    # "export " fällt weg, damit per node -e ausgeführte Ausschnitte laufen.
    # Seit Idee 313ad93d ist import.js in import-*.js aufgeteilt (Zustand, Jobs,
    # Begriffe, Liste, Web, Autor:innen) - alle Teile gehören zusammen.
    parts = [STATIC_DIR / "import.js", *sorted(STATIC_DIR.glob("import-*.js")), STATIC_DIR / "source-edit.js"]
    combined = "\n".join(p.read_text() for p in parts)
    return re.sub(r"^export ", "", combined, flags=re.M)


def _question_js_source() -> str:
    # Idee 313ad93d: die Quellen-/Zitat-Darstellung liegt in
    # static/question-sources.js (von question.js importiert) - die
    # Regex-Extraktionen durchsuchen beide Dateien gemeinsam. "export " fällt
    # weg, damit per node -e ausgeführte Ausschnitte laufen.
    parts = [STATIC_DIR / "question.js", STATIC_DIR / "question-sources.js"]
    combined = "\n".join(p.read_text() for p in parts if p.exists())
    return re.sub(r"^export ", "", combined, flags=re.M)


def test_static_modules_only_import_names_that_are_exported():
    # Ein vergessenes `export` wäre erst im Browser ein SyntaxError.
    files = {p.name: p.read_text() for p in STATIC_DIR.glob("*.js")}
    for name, text in files.items():
        for names, target in re.findall(r"import\s*\{([^}]*)\}\s*from\s*'/([^'/]+\.js)'", text):
            assert target in files, f"{name} importiert aus unbekanntem {target}"
            exported = set(
                re.findall(r"^export\s+(?:async\s+)?(?:function\*?|const|let|var|class)\s+(\w+)", files[target], flags=re.M)
            )
            for group in re.findall(r"^export\s*\{([^}]*)\}", files[target], flags=re.M):
                exported |= {x.split(" as ")[-1].strip() for x in group.split(",") if x.strip()}
            for imported in (n.split(" as ")[0].strip() for n in names.split(",") if n.strip()):
                assert imported in exported, f"{name} importiert {imported} aus {target}, dort fehlt der Export"


def test_import_modules_only_import_names_that_are_exported():
    # Idee 313ad93d: import.js ist in import-*.js aufgeteilt - ein vergessenes
    # `export` wäre erst im Browser ein SyntaxError (Modul lädt nicht).
    files = {p.name: p.read_text() for p in STATIC_DIR.glob("import*.js")}
    for name, text in files.items():
        for names, target in re.findall(r"import\s*\{([^}]*)\}\s*from\s*'/(import-[a-z]+\.js)'", text):
            for imported in (n.split(" as ")[0].strip() for n in names.split(",") if n.strip()):
                assert re.search(
                    rf"^export (?:async )?(?:function|const|let) {re.escape(imported)}\b", files[target], re.M
                ), f"{name} importiert {imported} aus {target}, dort fehlt der Export"


def _run_node(script: str):
    """Führt ein Node-Skript aus und parst dessen stdout als JSON - gemeinsame
    Grundlage für alle _run_*-Helfer unten, die jeweils nur den JS-Quelltext
    zusammenbauen."""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def _source_lang_js() -> str:
    """Echtes static/source-lang.js als Node-Skript-Ausschnitt: Imports und
    `export` entfernt, getLang() liest globalThis.__UI_LANG (Standard 'de').
    t() muss das jeweilige Testskript selbst definieren."""
    src = (STATIC_DIR / "source-lang.js").read_text()
    src = re.sub(r"^import .*$", "", src, flags=re.M)
    src = re.sub(r"^export ", "", src, flags=re.M)
    return "function getLang() { return globalThis.__UI_LANG || 'de'; }\n" + src


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
    return _run_node(script)


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
    return _run_node(script)

def _run_find_highlight_range(text, highlight):
    """Führt static/question.js#findHighlightRange per Node real aus - reine
    Funktion ohne DOM-Abhängigkeit, bisher OHNE jede Testabdeckung, obwohl
    sie allein entscheidet, ob überhaupt ein Highlight-<mark> erscheint."""
    js_source = _question_js_source()
    match = re.search(r"function findHighlightRange.*?\n\}", js_source, re.S)
    assert match, "findHighlightRange wurde in question.js nicht gefunden."
    func_source = match.group(0)
    script = f"""
{func_source}
console.log(JSON.stringify(findHighlightRange({json.dumps(text)}, {json.dumps(highlight)})));
"""
    return _run_node(script)


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
    js_source = _question_js_source()
    match = re.search(r"function appendTitleText.*?\n\}", js_source, re.S)
    assert match, "appendTitleText wurde in question.js nicht gefunden."
    func_source = _source_lang_js() + "\n" + match.group(0)
    script = f"""
function t(key) {{ return key; }}
const EXTERNAL_LINK_ICON = '<svg></svg>';
class FakeNode {{
  constructor(type, value) {{
    this.type = type;
    this.value = value;
    this.children = [];
  }}
  appendChild(child) {{ this.children.push(child); return child; }}
  addEventListener() {{}}
  setAttribute() {{}}
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
    return _run_node(script)


def test_append_title_text_links_title_when_url_present():
    children = _run_append_title_text({"title": "Ein Artikel", "url": "https://beispiel.org/artikel"})
    assert len(children) == 2
    assert children[0]["type"] == "element:a"
    assert children[0]["href"] == "https://beispiel.org/artikel"
    assert children[0]["textContent"] == "Ein Artikel"
    assert children[0]["className"] == "citation-title-link"
    assert children[1]["type"] == "element:a"
    assert children[1]["href"] == "https://beispiel.org/artikel"
    assert children[1]["className"] == "external-link"


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


def test_append_title_text_renders_plain_text_when_link_unreachable():
    """Nutzerwunsch (2026-09-23): eine Quelle mit erkanntem defektem Link
    soll auch im Konversationsmodus nicht mehr verlinkt werden, auch wenn
    eine URL vorhanden ist."""
    children = _run_append_title_text(
        {"title": "Ein Artikel", "url": "https://beispiel.org/artikel", "url_reachable": False}
    )
    assert len(children) == 1
    assert children[0]["type"] == "text"
    assert children[0]["value"] == "Ein Artikel"


def _run_append_exclude_web_page_button(*, is_pfleger, source_obj, fetch_ok=True):
    """Führt static/question.js#appendExcludeWebPageButton per Node real aus,
    inkl. simuliertem Klick (ruft den registrierten click-Listener direkt
    auf) - mit minimalen Stubs für hasPflegerRole/fetch/t/getLang (kein
    volles jsdom nötig, siehe _run_append_title_text)."""
    js_source = _question_js_source()
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
    this.dataset = {{}};
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
    return _run_node(script)


def _run_citations_click_sequence(paragraph_text, sources, click_sequence):
    """Wie _run_make_citations_clickable, führt zusätzlich eine feste Klick-
    Sequenz (Liste von Button-Indizes, in Auftrittsreihenfolge im Text) aus
    und gibt die Kartenanzahl nach JEDEM Klick zurück."""
    js_source = _question_js_source()
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
    this.dataset = {{}};
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
  setAttribute() {{}}
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
function t(key) {{ return key; }}
const CLOSE_ICON = '<svg></svg>';

function buildSourceInfo(source, highlight) {{
  const marker = document.createElement('div');
  marker.textContent = 'CARD:' + source.chunk_id + '::' + (highlight || '');
  return marker;
}}

{_source_lang_js()}
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
    return _run_node(script)


def _run_citations_click_all_and_read_markers(paragraph_text, sources):
    """Wie _run_citations_click_sequence, klickt aber JEDEN Button genau
    einmal (in Textreihenfolge) und gibt pro Klick den Marker-Text der
    dabei geöffneten Karte zurück - damit prüfbar ist, dass jedes Vorkommen
    wirklich SEIN EIGENES highlighted_texts[occurrence] bekommt, auch wenn
    zwischendurch andere Zitatnummern auftauchen (z.B. [1]...[2]...[1])."""
    js_source = _question_js_source()
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
    this.dataset = {{}};
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
  setAttribute() {{}}
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
function t(key) {{ return key; }}
const CLOSE_ICON = '<svg></svg>';

function buildSourceInfo(source, highlight) {{
  const marker = document.createElement('div');
  marker.textContent = 'CARD:' + source.chunk_id + '::' + (highlight || '');
  return marker;
}}

{_source_lang_js()}
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
  const marker = card ? card.children[1].textContent : null;
  btn.listeners.click(); // gleich wieder schliessen, damit sich Karten nicht ueberlappen
  return marker;
}});
console.log(JSON.stringify(markers));
"""
    return _run_node(script)


def _run_citations_and_read_button_labels(paragraph_text, sources):
    """Wie die anderen _run_citations_*-Helfer, liest aber den sichtbaren
    Button-Text jedes Zitat-Vorkommens statt Kartenanzahl/Marker."""
    js_source = _question_js_source()
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
    this.dataset = {{}};
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
  setAttribute() {{}}
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
function t(key) {{ return key; }}
const CLOSE_ICON = '<svg></svg>';

function buildSourceInfo(source, highlight) {{
  const marker = document.createElement('div');
  marker.textContent = 'CARD:' + source.chunk_id + '::' + (highlight || '');
  return marker;
}}

{_source_lang_js()}
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
console.log(JSON.stringify(findButtons(container, []).map((b) => b.textContent)));
"""
    return _run_node(script)


def _run_current_tag_segment_bounds(value: str, cursor_pos: int):
    js_source = _import_js_source()
    match = re.search(r"function currentTagSegmentBounds.*?\n\}", js_source, re.S)
    assert match, "currentTagSegmentBounds wurde in import.js nicht gefunden."
    script = f"""
{match.group(0)}
console.log(JSON.stringify(currentTagSegmentBounds({json.dumps(value)}, {cursor_pos})));
"""
    return _run_node(script)


def test_current_tag_segment_bounds_finds_the_segment_under_the_cursor():
    # Nutzerwunsch (2026-09-22, Nachtrag): das Segment fürs Tag-Vorschlagen
    # (static/import.js#attachTagSuggestions) hing bisher fix am LETZTEN
    # Komma - ein Begriff MITTEN in der Liste ließ sich dadurch nicht per
    # Vorschlag ersetzen. Bestimmt das Segment jetzt über die Cursor-Position.
    value = "Agilität, Selbstorganisation, Management"
    # Cursor irgendwo im mittleren Begriff "Selbstorganisation".
    cursor_in_middle = value.index("Selbst") + 3
    # start liegt direkt HINTER dem Komma (inkl. des folgenden Leerzeichens,
    # genau wie beim alten, rein letzten-Segment-basierten Split) - nur die
    # Endpunkte grenzen das Segment ein, Trimmen passiert separat beim
    # eigentlichen Query-Vergleich.
    assert _run_current_tag_segment_bounds(value, cursor_in_middle) == {
        "start": value.index(",") + 1,
        "end": value.index(", Management"),
    }
    # Cursor im ersten Begriff.
    assert _run_current_tag_segment_bounds(value, 3) == {"start": 0, "end": value.index(",")}
    # Cursor im letzten (noch offenen) Begriff, kein Komma danach.
    cursor_at_end = len(value)
    assert _run_current_tag_segment_bounds(value, cursor_at_end) == {
        "start": value.rindex(",") + 1,
        "end": len(value),
    }


def test_citation_labels_are_sequential_even_when_the_same_source_is_cited_twice():
    # Nutzerwunsch (2026-09-22): die ANGEZEIGTE Zitatnummer wiederholte sich
    # bisher ("[1]" erschien zweimal im Text), sobald derselbe Chunk mehrfach
    # zitiert wurde - verwirrend, auch wenn die Karten selbst schon korrekt
    # unabhängig auf-/zuklappbar waren. Jedes Vorkommen bekommt jetzt eine
    # eigene, im Antworttext fortlaufende Nummer.
    sources = [
        {"chunk_id": "chunk-1", "highlighted_texts": ["Zitat A", "Zitat B"]},
        {"chunk_id": "chunk-2", "highlighted_texts": ["Einziges Zitat B"]},
    ]
    labels = _run_citations_and_read_button_labels(
        "Aussage eins [1]. Aussage zwei [2]. Aussage drei [1].", sources
    )
    assert labels == ["[1]", "[2]", "[3]"]


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
    r"\b(?:appendChild|append|insertBefore|prepend|replaceChild|replaceChildren|insertAdjacentElement|appendTimelineRow)\s*\("
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
            rf"(?:appendChild|append|insertBefore|prepend|replaceChild|replaceChildren|insertAdjacentElement|appendTimelineRow)\([^)]*\b{name}\b",
            function_body,
        )
        # Direkte Rückgabe (`return label;`), als Objekt-Property (`return
        # { label, input };`, z.B. buildFieldLabel()) oder als Array-Element
        # (`return [li, panel];`, z.B. buildSourceEntries()).
        returned = (
            re.search(rf"\breturn\s+{name}\b", function_body)
            or re.search(rf"\breturn\s*\{{[^}}]*\b{name}\b[^}}]*\}}", function_body)
            or re.search(rf"\breturn\s*\[[^\]]*\b{name}\b", function_body)
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
    js_source = _import_js_source()
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
    js_source = _question_js_source()
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
    js_source = _import_js_source()
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
    js_source = _question_js_source()

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
    js_source = _import_js_source()
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
    return _run_node(script)


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
    js_source = _import_js_source()

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
    output = _run_node(script)
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
    calls = _run_node(script)
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
    played_order = _run_node(script)
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
    priorities = _run_node(script)
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
    output = _run_node(script)
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
    output = _run_node(script)
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
    return _run_node(script)


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
    return _run_node(script)


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
    return _run_node(script)


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
    return _run_node(script)


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


def test_sticky_header_ignores_zero_delta_scroll_tick_while_collapsed():
    """Fix (2026-09-23, gemeldetes Flackern in der Konversationsansicht bei
    641-899px Breite): ein Scroll-Event OHNE tatsächliche Bewegung
    (scrollY unverändert - z.B. ein Tick mit Delta 0 am Ende einer
    Trackpad-Momentum-Geste) wurde bisher fälschlich wie "nach oben
    gescrollt" behandelt (nur !scrollingDown statt echtem scrollingUp
    geprüft) und startete den Wiedereinblende-Timer, obwohl der Header
    weiterhin geklebt/ausgeblendet bleiben sollte."""
    results = _run_sticky_header_collapse_with_fake_timer(
        [
            ("scroll", 300, 8),  # nach unten, geklebt -> ausgeblendet
            ("scroll", 300, 8),  # Tick OHNE Bewegung -> darf NICHT wie "nach oben" zählen
            ("fire_timer",),  # kein Timer sollte je geplant worden sein - bleibt ausgeblendet
        ]
    )
    assert results == [True, True, True]


def _run_source_suggestion_row_click(action: str, *, fetch_ok: bool = True) -> dict:
    """Führt static/import.js#renderSourceSuggestionRow per Node aus und
    simuliert einen Klick auf "Annehmen" oder "Ablehnen" - mit minimalen
    Stubs für fetch/t/jsonHeaders (kein volles jsdom nötig, siehe
    _run_append_title_text). openUrlPopoverWithUrl (separate Funktion,
    siehe import.js) wird durch einen Spy ersetzt, der nur festhält, ob und
    mit welcher URL er aufgerufen wurde - hier geht es um die Annehmen/
    Ablehnen-Logik selbst, nicht um den Popover-Mechanismus (der bereits
    über extractAndFillFromUrl/den bestehenden #popover-load-Test-Pfad
    abgedeckt ist)."""
    js_source = _import_js_source()
    match = re.search(r"function renderSourceSuggestionRow.*?\n\}", js_source, re.S)
    assert match, "renderSourceSuggestionRow wurde in import.js nicht gefunden."
    func_source = match.group(0)
    script = f"""
function t(key) {{ return key; }}
function jsonHeaders() {{ return {{}}; }}
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
    this.dataset = {{}};
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
    return _run_node(script)


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
    fehlgeschlagenen Jobs - mit minimalen Stubs für fetch/t/jsonHeaders/
    fetchImportJobs/loadSources (kein volles jsdom nötig, siehe
    _run_append_title_text)."""
    js_source = _import_js_source()
    match = re.search(r"function renderJobsListInto.*?\n\}", js_source, re.S)
    assert match, "renderJobsListInto wurde in import.js nicht gefunden."
    func_source = match.group(0)
    script = f"""
function t(key) {{ return key; }}
function jsonHeaders() {{ return {{}}; }}
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
    this.dataset = {{}};
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
    return _run_node(script)


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
    js_source = _import_js_source()
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
    return _run_node(script)


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
    js_source = _import_js_source()
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
    return _run_node(script)


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
    js_source = _import_js_source()
    match = re.search(r"const PHOTO_HOST_LABELS.*?function photoCreditDomain.*?\n\}", js_source, re.S)
    assert match, "PHOTO_HOST_LABELS/photoCreditDomain wurden in import.js nicht gefunden."
    hostname_match = re.search(r"function extractHostname.*?\n\}", js_source, re.S)
    assert hostname_match, "extractHostname wurde nicht gefunden."
    script = f"""
{hostname_match.group(0)}
{match.group(0)}
console.log(JSON.stringify({call_expr}));
"""
    return _run_node(script)


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
    js_source = _import_js_source()
    parts = []
    for pattern in patterns:
        match = re.search(pattern, js_source, re.S)
        assert match, f"Muster {pattern!r} wurde in import.js nicht gefunden."
        parts.append(match.group(0))
    script = "\n".join(parts) + f"\nconsole.log(JSON.stringify({call_expr}));\n"
    return _run_node(script)


# Nutzerwunsch (2026-08-26): kein manuelles Plattform-Feld mehr im Social-
# Links-Formular - resolveSocialPlatform() ermittelt die Plattform beim
# Speichern automatisch aus der URL (siehe buildSocialLinksField).
_RESOLVE_SOCIAL_PLATFORM_PATTERNS = [
    r"const SOCIAL_PLATFORM_HOSTS.*?\n\];",
    r"function detectSocialPlatform.*?\n\}",
    r"function extractHostname.*?\n\}",
    r"function resolveSocialPlatform.*?\n\}",
]


def _run_sort_sources(sources: list[dict]) -> list[dict]:
    """Führt static/import.js#sortSources() im Autor:innen-Modus per Node aus
    (Nutzerwunsch 2026-08-31: jede:r Autor:in bekommt jetzt eine eigene
    Zwischenüberschrift, auch bei nur einer Quelle - eine Quelle mit
    mehreren Autor:innen muss deshalb unter JEDER ihrer Autor:innen als
    eigener Eintrag erscheinen, nicht nur bei Autor:innen mit >1 Quelle)."""
    js_source = _import_js_source()
    match = re.search(r"function sortSources.*?\n\}", js_source, re.S)
    assert match, "sortSources wurde in import.js nicht gefunden."
    func_source = match.group(0)
    script = f"""
function normalizeAuthor(name) {{ return name.trim().split(/\\s+/).join(' ').toLowerCase(); }}
function getSurname(name) {{ const parts = name.trim().split(/\\s+/); return parts[parts.length - 1]; }}
const currentSortMode = 'author';
function isFilterActive() {{ return false; }}
function t(k) {{ return k; }}
{_source_lang_js()}

{func_source}

console.log(JSON.stringify(sortSources({json.dumps(sources)}).map((s) => ({{ id: s.id, __sortAuthor: s.__sortAuthor }}))));
"""
    return _run_node(script)


def test_sort_sources_expands_single_source_author_for_own_heading():
    result = _run_sort_sources([{"id": "1", "title": "T", "date": "2020", "authors": ["Einzel Autor"]}])
    assert result == [{"id": "1", "__sortAuthor": "Einzel Autor"}]


def test_sort_sources_expands_every_author_of_a_multi_author_source_even_without_other_sources():
    result = _run_sort_sources(
        [{"id": "1", "title": "T", "date": "2020", "authors": ["Anna Adler", "Bruno Berg"]}]
    )
    assert {r["__sortAuthor"] for r in result} == {"Anna Adler", "Bruno Berg"}
    assert len(result) == 2


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
    js_source = _import_js_source()
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
const termMergeBtn = new FakeNode(0);
const sortDateBtn = new FakeNode(0);

global.document = {{
  querySelector: (sel) => {{
    if (sel === '.section-heading-row') return row;
    if (sel === '.section-heading-actions') return actions;
    if (sel === '.sort-toolbar') return sortToolbar;
    return null;
  }},
  getElementById: (id) => ({{ 'typ-term-merge': termMergeBtn, 'sort-date': sortDateBtn }})[id] || null,
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
    return _run_node(script)


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


def _run_source_toolbar_overflow_last_resort(client_width: int) -> dict:
    """Wie _run_source_toolbar_overflow, aber mit einer Icon-Gruppe, deren
    gemessene Breite auf das Ausblenden von #typ-term-merge reagiert (40px
    Anteil), damit sich die LETZTE Stufe der gestaffelten Platz-Einsparung
    (Nutzerwunsch 2026-09-23: Ähnliche-Schlagworte-Icon statt der Suche)
    isoliert testen lässt. Liefert den Zustand aller drei Stufen nach einem
    einzelnen Schritt."""
    js_source = _import_js_source()
    match = re.search(r"function initSourceToolbarOverflow.*?\n\}", js_source, re.S)
    assert match, "initSourceToolbarOverflow wurde in import.js nicht gefunden."
    func_source = match.group(0)
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
  getBoundingClientRect() {{
    const shrink =
      (this === iconGroup && termMergeBtn._classes.has('hidden') ? 40 : 0) +
      (this === sortToolbar && sortDateBtn._classes.has('hidden') ? 31 : 0);
    return {{ width: this._width - shrink }};
  }}
}}

const iconGroup = new FakeNode(200);
const sortToolbar = new FakeNode(93);
const searchToolbar = new FakeNode(53);
const actions = new FakeNode(0);
actions.children = [iconGroup, sortToolbar, searchToolbar];
actions.clientWidth = {client_width};
const row = new FakeNode(0);
const termMergeBtn = new FakeNode(0);
const sortDateBtn = new FakeNode(0);

global.document = {{
  querySelector: (sel) => {{
    if (sel === '.section-heading-row') return row;
    if (sel === '.section-heading-actions') return actions;
    if (sel === '.sort-toolbar') return sortToolbar;
    return null;
  }},
  getElementById: (id) => ({{ 'typ-term-merge': termMergeBtn, 'sort-date': sortDateBtn }})[id] || null,
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
resizeCallback();
console.log(JSON.stringify({{
  sortHidden: sortToolbar._classes.has('sort-toolbar--hidden-for-space'),
  sortDateHidden: sortDateBtn._classes.has('hidden'),
  termMergeHidden: termMergeBtn._classes.has('hidden'),
}}));
"""
    return _run_node(script)


def test_source_toolbar_hides_whole_sort_toolbar_only_as_last_resort():
    """Nutzerwunsch (2026-09-23): die Suche soll auf kleinen Screens NIE
    verschwinden, und die Sortierung nach Autor:in/Schlagwort soll mobil
    möglichst sichtbar bleiben - erst fallen Datums-Button und "Ähnliche
    Schlagworte" (#typ-term-merge) weg, die ganze Sortier-Leiste zuletzt."""
    result = _run_source_toolbar_overflow_last_resort(250)
    assert result == {"sortHidden": True, "sortDateHidden": True, "termMergeHidden": True}


def test_source_toolbar_hides_date_button_before_term_merge():
    result = _run_source_toolbar_overflow_last_resort(360)
    assert result == {"sortHidden": False, "sortDateHidden": True, "termMergeHidden": False}


def test_source_toolbar_hides_term_merge_before_author_and_term_sort():
    result = _run_source_toolbar_overflow_last_resort(320)
    assert result == {"sortHidden": False, "sortDateHidden": True, "termMergeHidden": True}


def test_source_toolbar_keeps_everything_when_it_fits():
    result = _run_source_toolbar_overflow_last_resort(400)
    assert result == {"sortHidden": False, "sortDateHidden": False, "termMergeHidden": False}


def _run_remove_source_suggestion_row(*, reserve_ids: list[str], visible_ids: list[str] = None) -> dict:
    """Führt static/import.js#removeSourceSuggestionRow per Node aus -
    prüft sowohl den SOFORTIGEN Zustand (Fade-Out-Klasse, Entfernung aus
    sourceSuggestionsVisible) als auch den Zustand NACH Ablauf von
    SOURCE_SUGGESTION_LEAVE_MS (tatsächliche DOM-Entfernung, Nachrücken aus
    sourceSuggestionsReserve samt Fade-In-Klasse). renderSourceSuggestionRow
    wird durch einen Spy ersetzt - hier geht es nur um die Nachrück-
    Choreographie selbst, nicht um den Zeilenaufbau (separat abgedeckt).
    Entfernt wird immer die Zeile mit id 'a'."""
    js_source = _import_js_source()
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
    return _run_node(script)


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
    return _run_node(script)


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


# --- explore.js: Autor:innen-Fotos werden gestaffelt geladen (2026-09-01) ---


def test_photo_images_do_not_set_href_synchronously_at_creation():
    """Regression (realer Mobil-Absturz beim Navigieren/Klicken im
    Netzwerk): das <image>-Element darf href nicht direkt in derselben
    D3-Attribut-Kette wie x/y/width/height/clip-path setzen - genau das
    dekodierte bisher ALLE (potenziell hochauflösenden, extern frei
    eingetragenen) Autor:innen-Fotos gleichzeitig, `loading="lazy"` wird auf
    SVG-<image> von praktisch keinem Browser beachtet. href muss stattdessen
    separat, zeitversetzt (siehe PHOTO_LOAD_BATCH_SIZE/-_DELAY_MS) gesetzt
    werden - dieser Test hält das strukturell fest, da renderGraph() selbst
    (D3/SVG-lastig) nicht sinnvoll isoliert in Node ausführbar ist."""
    js_source = (STATIC_DIR / "explore.js").read_text()
    match = re.search(
        r"const photoImages = node\s*\n.*?\.attr\('decoding', 'async'\);", js_source, re.S
    )
    assert match, "Die photoImages-Attribut-Kette wurde in explore.js nicht gefunden."
    creation_chain = match.group(0)
    assert "href" not in creation_chain, (
        "href wird wieder direkt beim Erzeugen des <image>-Elements gesetzt - das "
        "dekodiert alle Fotos gleichzeitig und kann auf Mobilgeräten zum Tab-Absturz führen."
    )


def test_photos_load_in_delayed_batches_only_for_visible_nodes():
    js_source = (STATIC_DIR / "explore.js").read_text()
    match = re.search(r"function loadVisiblePhotos\(\) \{.*?\n  \}\n", js_source, re.S)
    assert match, "loadVisiblePhotos wurde in explore.js nicht gefunden."
    batch_source = match.group(0)
    assert "setTimeout" in batch_source
    assert "PHOTO_LOAD_BATCH_SIZE" in batch_source
    assert "nodesInViewport" in batch_source
    assert "_photoQueued" in batch_source
    assert "setAttribute('href', d.photo_url)" in batch_source


def test_photo_timers_are_cleared_on_rerender():
    js_source = (STATIC_DIR / "explore.js").read_text()
    match = re.search(r"function renderGraph\(data\) \{.*?svg\.selectAll\('\*'\)\.remove\(\);", js_source, re.S)
    assert match, "renderGraph-Anfang wurde nicht gefunden."
    assert "stopPhotoLoading()" in match.group(0)
    stop = re.search(r"function stopPhotoLoading\(\) \{.*?\n\}", js_source, re.S)
    assert stop and "photoTimers.forEach(clearTimeout)" in stop.group(0)


def _explore_tier_fn(name: str, call_expr: str):
    return _run_explore_js_function(rf"function {name}\(.*?\n\}}", call_expr)


@pytest.mark.parametrize(
    "k,expected",
    [(0.2, "far"), (0.59, "far"), (0.6, "mid"), (0.99, "mid"), (1.0, "near"), (1.79, "near"), (1.8, "close"), (4, "close")],
)
def test_zoom_level_for_thresholds(k, expected):
    assert _explore_tier_fn("zoomLevelFor", f"zoomLevelFor({k})") == expected


_EDGE_SAMPLE = """[
  { source: 'a', target: 'b', weight: 5 },
  { source: 'a', target: 'c', weight: 5 },
  { source: 'b', target: 'c', weight: 1 },
  { source: 'c', target: 'd', weight: 3 },
  { source: 'd', target: 'e', weight: 2 },
  { source: 'e', target: 'a', weight: 1 }
]"""


def test_edge_tiers_empty():
    assert _explore_tier_fn("edgeTiers", "edgeTiers([], 800)") == []


def test_edge_tiers_every_node_has_a_tier_1_edge_and_ties_pick_first():
    result = _explore_tier_fn("edgeTiers", f"edgeTiers({_EDGE_SAMPLE}, 0)")
    # a: stärkste Kante 0 (Gleichstand mit 1, erste gewinnt); b: Kante 0; c: Kante 1 (5);
    # d: Kante 3 (3); e: Kante 4 (2).
    assert result == [1, 1, 3, 1, 1, 3]


def test_edge_tiers_tier_1_is_at_most_node_count():
    result = _explore_tier_fn("edgeTiers", f"edgeTiers({_EDGE_SAMPLE}, 0)")
    assert result.count(1) <= 5


def test_edge_tiers_fills_tier_2_up_to_limit():
    result = _explore_tier_fn("edgeTiers", f"edgeTiers({_EDGE_SAMPLE}, 5)")
    assert result.count(1) + result.count(2) == 5
    # Verbleibende Kante mit dem niedrigsten Gewicht (Index 2 oder 5): erste in Reihenfolge fällt in Stufe 2.
    assert result == [1, 1, 2, 1, 1, 3]


def test_edge_tiers_limit_larger_than_edge_count_leaves_no_tier_3():
    result = _explore_tier_fn("edgeTiers", f"edgeTiers({_EDGE_SAMPLE}, 800)")
    assert 3 not in result


def test_edge_tiers_does_not_mutate_input():
    result = _run_explore_js_function(
        r"function edgeTiers\(.*?\n\}",
        f"(() => {{ const e = {_EDGE_SAMPLE}; const before = JSON.stringify(e); edgeTiers(e, 5); return JSON.stringify(e) === before; }})()",
    )
    assert result is True


def test_rank_tiers_empty():
    assert _explore_tier_fn("rankTiers", "rankTiers([], [60])") == []


def test_rank_tiers_fewer_values_than_limit_all_tier_1():
    assert _explore_tier_fn("rankTiers", "rankTiers([1, 5, 3], [60])") == [1, 1, 1]


def test_rank_tiers_exactly_limit_in_tier_1_and_stable_ties():
    weights = [3, 3, 3, 1, 9]
    result = _explore_tier_fn("rankTiers", f"rankTiers({weights}, [2])")
    # Rang: 9 (Index 4), dann 3er in Reihenfolge (Index 0, 1, 2), dann 1 (Index 3).
    assert result == [1, 2, 2, 2, 1]
    assert result.count(1) == 2


def test_rank_tiers_does_not_mutate_input():
    result = _run_explore_js_function(
        r"function rankTiers\(.*?\n\}",
        "(() => { const w = [3, 1, 2]; rankTiers(w, [1]); return JSON.stringify(w); })()",
    )
    assert result == "[3,1,2]"


def _prominent(nodes_expr: str, per_type: int):
    return sorted(_explore_tier_fn("prominentNodeIds", f"Array.from(prominentNodeIds({nodes_expr}, {per_type}))"))


def test_prominent_node_ids_per_type_limit():
    nodes = (
        "[...Array.from({length: 12}, (_, i) => ({ id: 'a' + i, type: 'author', weight: i })),"
        " ...Array.from({length: 12}, (_, i) => ({ id: 't' + i, type: 'term', weight: i + 100 }))]"
    )
    result = _prominent(nodes, 3)
    assert result == sorted(["a11", "a10", "a9", "t11", "t10", "t9"])


def test_prominent_node_ids_fewer_nodes_than_limit_returns_all():
    nodes = "[{ id: 'a', type: 'author', weight: 1 }, { id: 't', type: 'term', weight: 1 }]"
    assert _prominent(nodes, 8) == ["a", "t"]


def test_prominent_node_ids_only_authors():
    nodes = "[{ id: 'a1', type: 'author', weight: 1 }, { id: 'a2', type: 'author', weight: 2 }, { id: 'a3', type: 'author', weight: 3 }]"
    assert _prominent(nodes, 2) == ["a2", "a3"]


def test_prominent_node_ids_ties_are_stable():
    nodes = "[{ id: 'x', type: 'term', weight: 2 }, { id: 'y', type: 'term', weight: 2 }, { id: 'z', type: 'term', weight: 2 }]"
    assert _prominent(nodes, 2) == ["x", "y"]


def test_prominent_node_ids_empty_and_no_mutation():
    assert _prominent("[]", 8) == []
    result = _run_explore_js_function(
        r"function prominentNodeIds\(.*?\n\}",
        "(() => { const n = [{ id: 'a', type: 'term', weight: 1 }, { id: 'b', type: 'term', weight: 5 }]; prominentNodeIds(n, 1); return n.map((x) => x.id).join(); })()",
    )
    assert result == "a,b"


def _in_viewport(nodes_expr: str, t_expr: str, margin: int = 100):
    return _explore_tier_fn("nodesInViewport", f"nodesInViewport({nodes_expr}, {t_expr}, 1000, 600, {margin}).map((d) => d.id)")


def test_nodes_in_viewport_center_inside():
    assert _in_viewport("[{ id: 'c', x: 500, y: 300 }]", "{ x: 0, y: 0, k: 1 }") == ["c"]


def test_nodes_in_viewport_margin_and_far_away():
    nodes = "[{ id: 'edge', x: -50, y: 300 }, { id: 'far', x: -500, y: 300 }, { id: 'below', x: 500, y: 650 }]"
    assert _in_viewport(nodes, "{ x: 0, y: 0, k: 1 }") == ["edge", "below"]


def test_nodes_in_viewport_scaled_and_translated():
    # k=2, Verschiebung -800: Knoten x=450 -> 100 (drin), x=100 -> -600 (draußen), x=900 -> 1000 (drin).
    nodes = "[{ id: 'in', x: 450, y: 150 }, { id: 'out', x: 100, y: 150 }, { id: 'in2', x: 900, y: 150 }]"
    assert _in_viewport(nodes, "{ x: -800, y: 0, k: 2 }") == ["in", "in2"]


def test_nodes_in_viewport_undefined_position_is_excluded():
    assert _in_viewport("[{ id: 'u' }, { id: 'v', x: 10 }]", "{ x: 0, y: 0, k: 1 }") == []


@pytest.mark.parametrize(
    "level,focus,dimmed,prominent,expected",
    [
        ("far", False, False, True, True),
        ("far", False, False, False, False),
        ("far", True, False, False, True),
        ("far", True, True, False, False),
        ("far", True, True, True, True),
        ("mid", True, False, True, False),
        ("near", True, False, False, False),
    ],
)
def test_far_label_is_scaled_for_prominent_and_focused_nodes(level, focus, dimmed, prominent, expected):
    call = f"isFarScaledLabel('{level}', {str(focus).lower()}, {str(dimmed).lower()}, {str(prominent).lower()})"
    assert _explore_tier_fn("isFarScaledLabel", call) is expected


def test_open_icon_transform_follows_label_scale():
    # Anforderung: Bei k = 0.5 ist die Schrift doppelt so groß (11.2/k), das Icon sitzt
    # (halbe Breite + 6)/k rechts vom Mittelpunkt und wird mit 1/k skaliert.
    result = _explore_tier_fn("openIconTransform", "openIconTransform(10, 20, 0.5)")
    nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", result)]
    assert nums == pytest.approx([52, 10 + (12 - 11.2 * 0.35 - 4.5) / 0.5, 2])
    normal = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", _explore_tier_fn("openIconTransform", "openIconTransform(10, 20, 1)"))]
    assert normal == pytest.approx([26, 10 + 12 - 11.2 * 0.35 - 4.5, 1])


@pytest.mark.parametrize(
    "r,level,k,expected",
    [
        (6, "far", 0.2, 100),  # 20 px am Bildschirm = 20/k Graph-Einheiten
        (6, "far", 0.5, 40),
        (45, "far", 0.5, 53),  # r + 8 größer als 20/k
        (6, "mid", 0.8, 14),
        (6, "near", 1.3, 14),
        (6, "close", 3, 14),
    ],
)
def test_hit_radius_gives_20px_tap_target_at_far(r, level, k, expected):
    assert _explore_tier_fn("hitRadiusFor", f"hitRadiusFor({r}, '{level}', {k})") == pytest.approx(expected)


def _explore_source() -> str:
    return (STATIC_DIR / "explore.js").read_text()


def test_stop_photo_loading_interrupts_transitions_and_clears_all_timers():
    js = _explore_source()
    stop = re.search(r"function stopPhotoLoading\(\) \{.*?\n\}", js, re.S).group(0)
    assert stop.index("svg.interrupt()") < stop.index("photoTimers.forEach(clearTimeout)")
    assert "clearTimeout(photoDebounce)" in stop
    assert "clearTimeout(searchZoomTimer)" in stop
    assert re.search(r"^let searchZoomTimer", js, re.M), "searchZoomTimer muss Modul-Variable sein."


def test_explore_rerenders_on_real_size_change_only_debounced():
    """Nur Breitenwechsel baut neu: am Handy ändert die Adressleiste beim
    Scrollen nur die Höhe - ein Neuaufbau würde Zoom und Auswahl verwerfen."""
    js = _explore_source()
    assert "addEventListener('resize'" in js
    assert "orientationchange" in js
    handler = re.search(r"function onWrapResize\(\) \{.*?\n\}", js, re.S)
    assert handler, "onWrapResize fehlt."
    body = handler.group(0)
    assert "clientWidth" in body
    assert "clientHeight" not in body, "Höhenänderung (mobile Adressleiste) darf nicht neu bauen."
    assert "200" in js[js.index("function onWrapResize") - 400 : js.index("function onWrapResize") + len(body)]


def test_within_far_only_scaling_is_updated_not_reset_and_filtered():
    js = _explore_source()
    apply_level = re.search(r"function applyLevel\(level\) \{.*?\n  \}\n", js, re.S).group(0)
    assert "setNodeScale(scaledNodes" in apply_level
    assert "rescaleLabels()" not in apply_level


def test_counter_scaled_labels_get_scaled_halo():
    js = _explore_source()
    scale = re.search(r"function setNodeScale\(sel, k\) \{.*?\n  \}\n", js, re.S).group(0)
    assert "stroke-width" in scale and "3 / k" in scale and "null" in scale


def test_explore_source_guards():
    js = _explore_source()
    # stopPhotoLoading im Leer-Zweig
    empty = js[js.index("if (!filtered.nodes.length)") :]
    assert "stopPhotoLoading()" in empty[: empty.index("return;")]
    # _photoQueued-Reset vor dem Aufbau der Linien/Knoten
    assert js.index("d._photoQueued = false") < js.index(".selectAll('line')")
    # clearSelection() am Anfang des Such-Handlers
    handler = js[js.index("currentSearchHandler = () =>") :]
    assert handler.index("clearSelection()") < handler.index("normalizeSearch(d.label)")
    # Fokus-Regeln nach den Stufen-Regeln
    css = (STATIC_DIR / "style.css").read_text()
    assert css.index(".explore-graph--focus .explore-node:not") > css.index(".explore-graph--mid .explore-node image")
    assert css.index(".explore-graph--focus .explore-edge:not") > css.index(".explore-graph--near .explore-edge--tier-3")


def test_focus_dimmed_nodes_ignore_clicks_and_focused_nodes_are_raised():
    # Im Browser bestätigt (k=0.3, echte Daten): ohne das lagen 79 von 99 Open-Icons unter fremden Trefferkreisen.
    css = (STATIC_DIR / "style.css").read_text()
    assert re.search(r"\.explore-graph--focus \.explore-node--dimmed \{\s*pointer-events: none;", css)
    assert ".raise()" in _explore_source()


def _cull(boxes_expr: str):
    return sorted(_explore_tier_fn("cullOverlappingLabels", f"Array.from(cullOverlappingLabels({boxes_expr}))"))


def test_cull_overlapping_labels_empty_and_disjoint():
    assert _cull("[]") == []
    boxes = "[{id:'a',x:0,y:0,w:50,h:14},{id:'b',x:100,y:0,w:50,h:14},{id:'c',x:0,y:40,w:50,h:14}]"
    assert _cull(boxes) == ["a", "b", "c"]


def test_cull_overlapping_labels_first_box_wins():
    boxes = "[{id:'a',x:0,y:0,w:50,h:14},{id:'b',x:30,y:5,w:50,h:14},{id:'c',x:60,y:5,w:50,h:14}]"
    # b schneidet a (fällt weg); c schneidet nur b, das nicht behalten wurde -> bleibt.
    assert _cull(boxes) == ["a", "c"]


def test_cull_overlapping_labels_keeps_a_gap_of_2px():
    # b beginnt 1 px nach dem Ende von a: weniger als 2 px Abstand -> weg; c mit 3 px Abstand bleibt.
    assert _cull("[{id:'a',x:0,y:0,w:50,h:14},{id:'b',x:51,y:0,w:50,h:14}]") == ["a"]
    assert _cull("[{id:'a',x:0,y:0,w:50,h:14},{id:'c',x:53,y:0,w:50,h:14}]") == ["a", "c"]


def test_cull_overlapping_labels_does_not_mutate_input():
    result = _run_explore_js_function(
        r"function cullOverlappingLabels\(.*?\n\}",
        "(() => { const b = [{id:'a',x:0,y:0,w:50,h:14},{id:'b',x:10,y:0,w:50,h:14}]; const before = JSON.stringify(b); cullOverlappingLabels(b); return JSON.stringify(b) === before; })()",
    )
    assert result is True


def test_culled_label_rule_hides_label_and_icon_after_focus_rules():
    css = (STATIC_DIR / "style.css").read_text()
    rule = re.search(r"#explore-graph \.explore-node--label-culled \.explore-node-label,\s*#explore-graph \.explore-node--label-culled \.explore-node-open-icon \{\s*display: none;", css)
    assert rule, "Regel für ausgeblendete Namen fehlt."
    assert rule.start() > css.index(".explore-graph--focus .explore-edge:not")


def test_explore_legend_zoom_hint_is_translated_and_appended():
    js_source = (STATIC_DIR / "explore.js").read_text()
    assert "explore.legendZoomHint" in js_source
    for lang in ("de", "en"):
        assert json.loads((STATIC_DIR / "i18n" / f"{lang}.json").read_text())["explore.legendZoomHint"]


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
    js_source = _import_js_source()
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
    this.dataset = {{}};
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
    return _run_node(script)


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
    func = match.group(0).replace("export function", "function")
    script = (
        f"function t(k) {{ return k; }}\n{_source_lang_js()}\n{func}\n"
        f"console.log(JSON.stringify(creativeSourceLabel({json.dumps(source)})));"
    )
    return _run_node(script)


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
    return _run_node(script)


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
    return _run_node(script)


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
    return _run_node(script)


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
    return _run_node(script)


def test_render_markdown_escapes_html():
    html = _run_render_markdown("<script>alert('x')</script> & Co")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp; Co" in html


def test_render_markdown_bold_and_italic():
    html = _run_render_markdown("**fett** und *kursiv*")
    assert html == "<p><strong>fett</strong> und <em>kursiv</em></p>"


def test_render_markdown_heading_is_not_nested_when_also_bold():
    # Regression (2026-09-11): schreibt das Modell eine Überschrift
    # zusätzlich fett ("## **Titel**"), darf daraus kein verschachteltes
    # <strong> ohne .md-heading-Klasse entstehen - genau das machte die
    # Überschrift in question.js (makeTermsClickable) versehentlich zu einem
    # klickbaren, rot eingefärbten Schlagwort-Link (.term-followup).
    html = _run_render_markdown("## **Wichtiger Titel**\n\nText danach.")
    assert html == '<p><strong class="md-heading">Wichtiger Titel</strong></p><p>Text danach.</p>'


def test_render_markdown_plain_heading_unaffected():
    html = _run_render_markdown("### Einfache Überschrift\n\nText danach.")
    assert html == '<p><strong class="md-heading">Einfache Überschrift</strong></p><p>Text danach.</p>'


def _run_make_terms_clickable(paragraphs):
    """Führt static/question.js#makeTermsClickable per Node aus, mit einem
    minimalen FakeNode-DOM (kein volles jsdom nötig, siehe
    _run_append_title_text) - querySelectorAll ist fest auf den einen in der
    Funktion genutzten Selektor 'strong:not(.md-heading)' zugeschnitten.
    `paragraphs` ist eine Liste von Absätzen, jeder Absatz eine Liste von
    Kindknoten: {"type": "text", "value": "..."} / {"type": "br"} /
    {"type": "strong", "text": "...", "heading": bool}."""
    js_source = _question_js_source()
    match = re.search(r"function makeTermsClickable.*?\n\}", js_source, re.S)
    assert match, "makeTermsClickable wurde in question.js nicht gefunden."
    func_source = match.group(0)
    script = f"""
const Node = {{ TEXT_NODE: 3 }};
function t(key) {{ return key; }}
const questionInput = {{ value: '' }};
const questionForm = {{ requestSubmit() {{}} }};

class FakeNode {{
  constructor(nodeType, tagOrText, {{ className }} = {{}}) {{
    this.nodeType = nodeType;
    this.children = [];
    this.parentNode = null;
    if (nodeType === Node.TEXT_NODE) {{
      this.nodeName = '#text';
      this._text = tagOrText;
    }} else {{
      this.nodeName = tagOrText.toUpperCase();
      this.classList = new Set(className ? [className] : []);
      this.classList.add = Set.prototype.add.bind(this.classList);
    }}
  }}
  appendChild(child) {{
    child.parentNode = this;
    this.children.push(child);
    return child;
  }}
  get previousSibling() {{
    const i = this.parentNode.children.indexOf(this);
    return i > 0 ? this.parentNode.children[i - 1] : null;
  }}
  get nextSibling() {{
    const i = this.parentNode.children.indexOf(this);
    return i < this.parentNode.children.length - 1 ? this.parentNode.children[i + 1] : null;
  }}
  get textContent() {{
    if (this.nodeType === Node.TEXT_NODE) return this._text;
    return this.children.map((c) => c.textContent).join('');
  }}
  querySelectorAll(selector) {{
    if (selector !== 'strong:not(.md-heading)') throw new Error('unerwarteter Selektor: ' + selector);
    const found = [];
    const walk = (node) => {{
      for (const child of node.children) {{
        if (child.nodeType !== Node.TEXT_NODE) {{
          if (child.nodeName === 'STRONG' && !child.classList.has('md-heading')) found.push(child);
          walk(child);
        }}
      }}
    }};
    walk(this);
    return found;
  }}
  addEventListener() {{}}
}}

const container = new FakeNode(1, 'div');
for (const paragraph of {json.dumps(paragraphs)}) {{
  const p = new FakeNode(1, 'p');
  container.appendChild(p);
  for (const node of paragraph) {{
    if (node.type === 'text') p.appendChild(new FakeNode(Node.TEXT_NODE, node.value));
    else if (node.type === 'br') p.appendChild(new FakeNode(1, 'br'));
    else if (node.type === 'strong') {{
      const strong = new FakeNode(1, 'strong', node.heading ? {{ className: 'md-heading' }} : {{}});
      strong.appendChild(new FakeNode(Node.TEXT_NODE, node.text));
      p.appendChild(strong);
    }}
  }}
}}

{func_source}

makeTermsClickable(container);
const result = container.querySelectorAll('strong:not(.md-heading)').map((el) => ({{
  text: el.textContent,
  clickable: el.classList.has('term-followup'),
}}));
console.log(JSON.stringify(result));
"""
    return _run_node(script)


def test_make_terms_clickable_keeps_inline_term_clickable():
    result = _run_make_terms_clickable(
        [[{"type": "text", "value": "Beta-Unternehmen zeichnen sich durch "},
          {"type": "strong", "text": "überdurchschnittliche Rentabilität"},
          {"type": "text", "value": " aus."}]]
    )
    assert result == [{"text": "überdurchschnittliche Rentabilität", "clickable": True}]


def test_make_terms_clickable_excludes_standalone_paragraph_heading():
    # Regression (2026-09-11): "**Die ersten drei Prinzipien**" als einziger
    # Inhalt eines eigenen Absatzes - eine informelle Zwischenüberschrift
    # ohne "#"-Syntax, keine klickbare Schlagwort-Folgefrage.
    result = _run_make_terms_clickable([[{"type": "strong", "text": "Die ersten drei Prinzipien"}]])
    assert result == [{"text": "Die ersten drei Prinzipien", "clickable": False}]


def test_make_terms_clickable_excludes_heading_line_followed_by_br_in_same_paragraph():
    # Regression (2026-09-11): "**§1 Titel**<br>Fließtext" - Überschrift und
    # Folgetext im selben Absatz (nur per Zeilenumbruch getrennt statt
    # eigenem Absatz), trotzdem keine klickbare Folgefrage für die Zeile.
    result = _run_make_terms_clickable(
        [[{"type": "strong", "text": "§1 Teamautonomie"},
          {"type": "br"},
          {"type": "text", "value": "Dieses Prinzip verkörpert die klare Einsicht."}]]
    )
    assert result == [{"text": "§1 Teamautonomie", "clickable": False}]


def test_make_terms_clickable_keeps_term_at_paragraph_start_when_prose_continues_inline():
    # Ein Fachbegriff als erstes Wort eines fließenden Satzes (kein
    # Zeilenumbruch danach) ist kein Überschriften-Muster und bleibt klickbar.
    result = _run_make_terms_clickable(
        [[{"type": "strong", "text": "Teamautonomie"},
          {"type": "text", "value": " ist ein zentrales Prinzip."}]]
    )
    assert result == [{"text": "Teamautonomie", "clickable": True}]


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


# --- i18n.js: detectLang liest ?lang= (2026-09-01) ---


def _run_detect_lang(*, search: str, stored_lang: str | None, nav_language: str, pathname: str = "/") -> dict:
    """Führt i18n.js#detectLang per Node aus. Gibt sowohl den ermittelten
    Sprachcode als auch den Zustand von localStorage/der (simulierten)
    Adresszeile danach zurück, damit sich sowohl die Übernahme des
    ?lang=-Parameters als auch dessen Entfernung aus der URL (bei Erhalt
    anderer, gleichzeitig vorhandener Parameter) prüfen lässt. pathname
    simuliert, auf welcher Seite detectLang() läuft (Standard '/' = nicht
    embed.html, siehe test_detect_lang_defaults_to_english_on_embed_page)."""
    js_source = (STATIC_DIR / "i18n.js").read_text()
    match = re.search(r"function detectLang\(\).*?\n\}", js_source, re.S)
    assert match, "detectLang wurde in i18n.js nicht gefunden."
    func_source = match.group(0)
    store = {"lang": stored_lang} if stored_lang is not None else {}
    script = f"""
const store = {json.dumps(store)};
global.localStorage = {{
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => {{ store[k] = v; }},
}};
let currentPath = {json.dumps(pathname + search)};
global.window = {{ location: {{ search: {json.dumps(search)}, pathname: {json.dumps(pathname)} }} }};
global.history = {{
  replaceState: (state, title, url) => {{ currentPath = url; }},
}};
global.navigator = {{ language: {json.dumps(nav_language)} }};
const SUPPORTED_LANGS = ['de', 'en'];
const DEFAULT_LANG = 'en';

{func_source}

console.log(JSON.stringify({{ lang: detectLang(), storedLang: store.lang, path: currentPath }}));
"""
    return _run_node(script)


def test_detect_lang_prefers_url_param_over_stored_and_navigator_language():
    result = _run_detect_lang(search="?lang=en", stored_lang="de", nav_language="de-DE")
    assert result["lang"] == "en"


def test_detect_lang_persists_url_param_to_local_storage():
    result = _run_detect_lang(search="?lang=en", stored_lang="de", nav_language="de-DE")
    assert result["storedLang"] == "en"


def test_detect_lang_removes_lang_param_but_keeps_other_params():
    # Analog zum Bug bei consumeConversationHandoffToken (siehe
    # conversation-handoff.js): darf nur den eigenen Parameter entfernen,
    # ein gleichzeitig vorhandenes ?handoff=<token> muss erhalten bleiben.
    result = _run_detect_lang(search="?handoff=abc123&lang=en", stored_lang=None, nav_language="de-DE")
    assert result["path"] == "/?handoff=abc123"


def test_detect_lang_ignores_unsupported_url_param():
    result = _run_detect_lang(search="?lang=fr", stored_lang="de", nav_language="de-DE")
    assert result["lang"] == "de"


def test_detect_lang_falls_back_to_stored_value_without_url_param():
    result = _run_detect_lang(search="", stored_lang="en", nav_language="de-DE")
    assert result["lang"] == "en"


def test_detect_lang_defaults_to_english_regardless_of_navigator_language():
    """Nutzerwunsch (Livegang-Vorbereitung, 2026-09-10): IMMER mit Englisch
    starten, unabhängig von der Browser-Spracheinstellung - der zuvor nur
    für embed.html geltende Sonderfall ist jetzt der allgemeine Standard.
    Der Sprachumschalter bleibt bedienbar (siehe Test unten)."""
    result = _run_detect_lang(search="", stored_lang=None, nav_language="de-DE")
    assert result["lang"] == "en"


def test_detect_lang_default_applies_to_embed_page_too():
    # Kein Unterschied mehr zwischen embed.html und anderen Seiten - siehe
    # Kommentar in i18n.js#detectLang.
    result = _run_detect_lang(search="", stored_lang=None, nav_language="de-DE", pathname="/embed.html")
    assert result["lang"] == "en"


def test_detect_lang_still_honors_stored_german_choice():
    result = _run_detect_lang(search="", stored_lang="de", nav_language="de-DE")
    assert result["lang"] == "de"


def _run_detect_text_language(text: str) -> str | None:
    """Führt i18n.js#detectTextLanguage per Node aus (Stoppwort-Heuristik für
    die automatische Sprachumschaltung, Livegang-Vorbereitung 2026-09-10)."""
    js_source = (STATIC_DIR / "i18n.js").read_text()
    match = re.search(
        r"const DE_MARKER_WORDS.*?\nexport function detectTextLanguage\(text\).*?\n\}", js_source, re.S
    )
    assert match, "detectTextLanguage (inkl. Wortlisten) wurde in i18n.js nicht gefunden."
    func_source = match.group(0).replace("export function", "function")
    script = f"""
{func_source}
console.log(JSON.stringify(detectTextLanguage({json.dumps(text)})));
"""
    return _run_node(script)


def test_detect_text_language_recognizes_german_question():
    assert _run_detect_text_language("Was ist ein List Owner?") == "de"


def test_detect_text_language_recognizes_english_question():
    assert _run_detect_text_language("What is a List Owner?") == "en"


def test_detect_text_language_umlaut_alone_is_a_strong_german_signal():
    # Umlaute/ß kommen im Englischen nicht vor - schon ein kurzer Satz mit
    # einem einzigen Umlaut soll sicher als Deutsch erkannt werden.
    assert _run_detect_text_language("Wer führt Teams?") == "de"


def test_detect_text_language_returns_null_for_pure_domain_jargon():
    # "List Owner" ist in beiden Sprachen derselbe (Lehnwort-)Fachbegriff -
    # ohne Funktionswörter darf NICHT geraten werden (siehe Kommentar in
    # i18n.js: lieber nichts erkennen als riskant falsch umschalten).
    assert _run_detect_text_language("List Owner") is None


def test_detect_text_language_returns_null_for_empty_text():
    assert _run_detect_text_language("") is None


def test_detect_text_language_ignores_case():
    assert _run_detect_text_language("WAS IST DAS?") == "de"


def test_detect_text_language_recognizes_english_imperative_instruction():
    # Regressionstest (live im Browser gefunden, 2026-09-10): eine Kreativ-
    # Modus-Anweisung ist ein Imperativ, keine Frage - enthielt zunächst
    # keines der (nur fragenorientierten) Marker-Wörter und wurde fälschlich
    # nicht erkannt.
    assert _run_detect_text_language("Write a short blog post about decentralized decision making") == "en"


def test_detect_text_language_recognizes_german_imperative_instruction():
    assert _run_detect_text_language("Schreibe einen kurzen Artikel über dezentrale Entscheidungsfindung") == "de"


def test_detect_text_language_ignores_long_quoted_foreign_language_excerpt():
    # Regressionstest, realer Bug 2026-09-14: eine kurze deutsche Antwort mit
    # einem langen woertlichen englischen Zitat (Quellenmaterial im
    # Original) wurde faelschlich als Englisch erkannt, obwohl Frage UND
    # umgebender Antworttext durchgehend Deutsch waren - die Zitatwoerter
    # duerfen nicht in die Spracherkennung der Antwort einfliessen.
    text = (
        'Ackoff argumentiert, dass Manager typischerweise die einzelnen Teile '
        'einer Organisation verbessern, anstatt die Interaktionen zwischen '
        'ihnen zu gestalten. Er sagt dazu: "Most managers currently manage '
        "the actions of their organizations' parts taken separately. This is "
        "based on the false assumption that improving the performance of the "
        "parts separately necessarily improves the performance of the whole, "
        'the corporation. That is a false premise."'
    )
    assert _run_detect_text_language(text) == "de"


# --- question.js: embedExpandButton gibt aktuelle Sprache mit (2026-09-01) ---


def test_embed_expand_button_appends_current_lang_without_conversation_history():
    js_source = _question_js_source()
    match = re.search(
        r"if \(embedExpandButton\) \{.*?\n\}", js_source, re.S
    )
    assert match, "embedExpandButton-Click-Handler wurde in question.js nicht gefunden."
    handler_source = match.group(0)
    assert "window.open(`/?${langParam}`" in handler_source
    assert "getLang()" in handler_source


def test_embed_expand_button_appends_current_lang_alongside_handoff_token():
    js_source = _question_js_source()
    match = re.search(
        r"if \(embedExpandButton\) \{.*?\n\}", js_source, re.S
    )
    assert match
    handler_source = match.group(0)
    assert "handoff=${encodeURIComponent(token)}&${langParam}" in handler_source


# --- question.js: ?q= öffnet die Konversation mit genau dieser Frage (2026-09-01) ---


def _run_consume_ask_param(*, search: str) -> dict:
    js_source = _question_js_source()
    match = re.search(r"function consumeAskParam\(\).*?\n\}", js_source, re.S)
    assert match, "consumeAskParam wurde in question.js nicht gefunden."
    func_source = match.group(0)
    script = f"""
let currentPath = null;
global.window = {{ location: {{ search: {json.dumps(search)}, pathname: '/' }} }};
global.history = {{
  replaceState: (state, title, url) => {{ currentPath = url; }},
}};

{func_source}

console.log(JSON.stringify({{ ask: consumeAskParam(), path: currentPath }}));
"""
    return _run_node(script)


def test_consume_ask_param_returns_decoded_question():
    result = _run_consume_ask_param(search="?q=Was%20ist%20der%20BetaCodex%3F")
    assert result["ask"] == "Was ist der BetaCodex?"


def test_consume_ask_param_removes_only_its_own_param():
    result = _run_consume_ask_param(search="?lang=en&q=Frage")
    assert result["path"] == "/?lang=en"


def test_consume_ask_param_returns_null_when_absent():
    result = _run_consume_ask_param(search="?lang=en")
    assert result["ask"] is None


def test_ask_param_auto_submit_is_wired_up():
    js_source = _question_js_source()
    match = re.search(
        r"const askParam = consumeAskParam\(\);.*?questionForm\.requestSubmit\(\);\n\}",
        js_source,
        re.S,
    )
    assert match, "Die ?q=-Vorbefüllung/Auto-Submit wurde in question.js nicht gefunden."
    block = match.group(0)
    assert "consumeAskParam()" in block
    assert "questionInput.value = askParam" in block


def test_ask_param_auto_submit_runs_after_submit_listener_is_registered():
    # Regression (2026-09-01, real gemeldet): der Auto-Submit-Block stand
    # vorher VOR questionForm.addEventListener('submit', ...) im Datei-
    # Quelltext - requestSubmit() löste das "submit"-Event zu diesem
    # Zeitpunkt bereits synchron aus, aber noch OHNE registrierten Handler
    # (der e.preventDefault() aufruft). Ohne Handler griff die native
    # Browser-Formular-Absendung (echter GET-Reload derselben Seite, da
    # #question-form kein eigenes action/method hat) - das erklärt das
    # gemeldete Bild-Flackern, die verschwindende Frage und die nie
    # ankommende Antwort. Der Auto-Submit-Aufruf muss deshalb TEXTUELL NACH
    # der addEventListener('submit', ...)-Registrierung stehen.
    js_source = _question_js_source()
    listener_index = js_source.index("questionForm.addEventListener('submit'")
    auto_submit_index = js_source.index("const askParam = consumeAskParam();")
    assert auto_submit_index > listener_index, (
        "Der ?q=-Auto-Submit-Aufruf steht vor der questionForm-submit-Listener-Registrierung - "
        "requestSubmit() würde dann ohne registrierten Handler nativ absenden (echter Seiten-Reload)."
    )


def test_ask_param_auto_submit_waits_for_turnstile_before_submitting():
    # Regression (2026-09-01, real gemeldet): ohne dieses Warten feuerte
    # requestSubmit() oft, bevor das extern/asynchron nachladende
    # Turnstile-Widget bereit war - der Server lehnte den dadurch leeren
    # Captcha-Token ab, die Nutzer:innen-Frage erschien zwar, aber es kam
    # nur eine Fehlermeldung statt einer echten Antwort.
    js_source = _question_js_source()
    match = re.search(
        r"const askParam = consumeAskParam\(\);.*?questionForm\.requestSubmit\(\);\n\}",
        js_source,
        re.S,
    )
    assert match, "Der ?q=-Auto-Submit-Block wurde in question.js nicht gefunden."
    block = match.group(0)
    assert "turnstileReadyPromise" in block
    # Muss VOR requestSubmit() stehen, nicht danach.
    assert block.index("turnstileReadyPromise") < block.index("questionForm.requestSubmit()")


def test_turnstile_ready_promise_is_capped_with_a_timeout():
    js_source = _question_js_source()
    assert "Promise.race([turnstileReadyPromise" in js_source


# --- question.js: Sidebar dedupliziert Quellen statt Chunks (2026-09-01) ---


def test_attach_answer_sources_deduplicates_sidebar_by_source_id_not_chunk_id():
    # Regression (real gemeldet): zwei verschiedene [n]-Vorkommen, die auf
    # unterschiedliche Chunks DERSELBEN Quelle verweisen, ließen dieselbe
    # Quelle zweimal (identisch aussehend, gleicher Titel/gleiche
    # KI-Zusammenfassung) in der Sidebar auftauchen, weil bisher nach
    # chunk_id statt nach source_id dedupliziert wurde.
    js_source = _question_js_source()
    match = re.search(r"function attachAnswerSources\(bubble, sources\) \{.*?\n\}", js_source, re.S)
    assert match, "attachAnswerSources wurde in question.js nicht gefunden."
    func_source = match.group(0)
    assert "conversationCitedSources.set(s.source_id, s)" in func_source
    assert "conversationCitedSources.set(s.chunk_id, s)" not in func_source


def test_build_sources_list_keys_details_by_source_id():
    js_source = _question_js_source()
    match = re.search(r"function buildSourcesList\(sources\) \{.*?\n\}", js_source, re.S)
    assert match, "buildSourcesList wurde in question.js nicht gefunden."
    func_source = match.group(0)
    assert "details.dataset.sourceId = s.source_id" in func_source


def test_render_sidebar_sources_preserves_open_state_by_source_id():
    js_source = _question_js_source()
    match = re.search(r"function renderSidebarSources\(\) \{.*?\n\}", js_source, re.S)
    assert match, "renderSidebarSources wurde in question.js nicht gefunden."
    func_source = match.group(0)
    assert "dataset.sourceId" in func_source
    assert "dataset.chunkId" not in func_source


# --- question.js: Daumen-hoch/-runter je Antwort (2026-09-01) ---


def test_attach_feedback_buttons_sends_question_answer_and_value():
    js_source = (STATIC_DIR / "answer-feedback.js").read_text()
    match = re.search(r"export function buildAnswerFeedback\(.*?\n\}\n", js_source, re.S)
    assert match, "buildAnswerFeedback wurde in answer-feedback.js nicht gefunden."
    func_source = match.group(0)
    assert "/api/answer-feedback" in func_source
    assert "JSON.stringify({ question, answer, feedback: value, mode })" not in func_source
    assert "feedback: value, mode" in func_source
    assert "buildButton('good', THUMBS_UP_ICON)" in func_source
    assert "buildButton('bad', THUMBS_DOWN_ICON)" in func_source
    assert "index.feedbackGoodTitle" in js_source and "creative.feedbackGoodTitle" in js_source


def test_attach_feedback_buttons_shows_permanent_checkmark_on_success():
    # Nutzerwunsch (2026-09-01, Nachtrag): der Haken bleibt nach
    # erfolgreichem Absenden dauerhaft stehen, kein Zurücksetzen auf das
    # ursprüngliche Daumen-Icon.
    js_source = (STATIC_DIR / "answer-feedback.js").read_text()
    match = re.search(r"export function buildAnswerFeedback\(.*?\n\}\n", js_source, re.S)
    assert match
    func_source = match.group(0)
    assert "btn.innerHTML = FEEDBACK_SENT_ICON" in js_source
    assert "feedback-btn--sent" in func_source
    assert "originalIcon" not in func_source
    assert "setTimeout" not in func_source


def test_attach_feedback_buttons_locks_both_buttons_after_success():
    js_source = (STATIC_DIR / "answer-feedback.js").read_text()
    match = re.search(r"export function buildAnswerFeedback\(.*?\n\}\n", js_source, re.S)
    assert match
    func_source = match.group(0)
    assert "function lockButtons()" in func_source
    assert "b.disabled = true" in func_source
    assert "feedback-btn--locked" in func_source
    assert "lockButtons();" in func_source


def test_attach_feedback_buttons_unlocks_both_buttons_after_failure():
    js_source = (STATIC_DIR / "answer-feedback.js").read_text()
    match = re.search(r"export function buildAnswerFeedback\(.*?\n\}\n", js_source, re.S)
    assert match
    func_source = match.group(0)
    assert "function unlockButtons()" in func_source
    assert "unlockButtons();" in func_source
    assert "success = res.ok" in func_source


def test_attach_speak_button_wires_up_feedback_buttons():
    js_source = _question_js_source()
    match = re.search(r"function attachSpeakButton\(bubble, question, answer\) \{.*?\n\}\n", js_source, re.S)
    assert match, "attachSpeakButton wurde in question.js nicht gefunden."
    assert "attachFeedbackButtons(bubble, question, answer)" in match.group(0)


# --- question-log.js: neue Ereignistypen, Filter, Frage als Link (2026-09-01) ---


def test_question_log_builds_ask_deep_link_opening_in_new_tab():
    js_source = (STATIC_DIR / "question-log.js").read_text()
    match = re.search(r"function buildQuestionLink\(text, mode\) \{.*?\n\}", js_source, re.S)
    assert match, "buildQuestionLink wurde in question-log.js nicht gefunden."
    func_source = match.group(0)
    assert "/?q=${encodeURIComponent(text)}" in func_source
    assert "a.target = '_blank'" in func_source
    assert "a.rel = 'noopener'" in func_source


def test_question_log_event_type_labels_cover_all_three_types():
    js_source = (STATIC_DIR / "question-log.js").read_text()
    match = re.search(r"const EVENT_TYPE_LABEL_KEYS = \{.*?\n\};", js_source, re.S)
    assert match, "EVENT_TYPE_LABEL_KEYS wurde in question-log.js nicht gefunden."
    labels = match.group(0)
    assert "first_question:" in labels
    assert "no_answer:" in labels
    assert "feedback:" in labels


def test_question_log_filter_toggles_active_class_and_reapplies_filter():
    js_source = (STATIC_DIR / "question-log.js").read_text()
    match = re.search(r"filterButtons\.forEach\(\(btn\) => \{.*?\n\}\);", js_source, re.S)
    assert match, "Die Filter-Button-Verdrahtung wurde in question-log.js nicht gefunden."
    block = match.group(0)
    assert "activeEventTypes.delete(eventType)" in block
    assert "activeEventTypes.add(eventType)" in block
    assert "applyFilter()" in block


def test_question_log_answer_is_wrapped_in_collapsible_details():
    # Nutzerwunsch (2026-09-01): die volle Antwort steht standardmäßig
    # eingeklappt, damit das Log auf einen Blick überschaubar bleibt - ein
    # Klick auf "Antwort anzeigen" öffnet sie.
    js_source = (STATIC_DIR / "question-log.js").read_text()
    match = re.search(r"if \(entry\.has_answer\) \{.*?\n  \}", js_source, re.S)
    assert match, "Der Antwort-Block in buildEntryElement wurde nicht gefunden."
    block = match.group(0)
    assert "document.createElement('details')" in block
    assert "document.createElement('summary')" in block
    assert "t('questionLog.showAnswer')" in block


def test_question_log_render_preserves_open_answer_details_across_filter():
    js_source = (STATIC_DIR / "question-log.js").read_text()
    match = re.search(r"function render\(\) \{.*?\n\}", js_source, re.S)
    assert match, "render() wurde in question-log.js nicht gefunden."
    block = match.group(0)
    assert "querySelectorAll('details[open]')" in block
    assert "openTimestamps.has(d.dataset.timestamp)" in block


# --- import.js: "Als geprüft markieren"-Button bei defektem Link (2026-09-01) ---


def test_url_health_status_block_includes_verify_link_button():
    js_source = (STATIC_DIR / "source-edit.js").read_text()
    match = re.search(r"if \(s\.url_reachable === false\) \{.*?\n  \}", js_source, re.S)
    assert match, "Der url-health-status-Block wurde in import.js nicht gefunden."
    block = match.group(0)
    assert "verify-link-button" in block
    assert "verifySourceLink(s.id, healthStatus, verifyBtn, options.onLinkVerified)" in block


def test_verify_source_link_posts_to_verify_link_endpoint_and_reloads():
    js_source = _import_js_source()
    match = re.search(r"async function verifySourceLink\(sourceId, statusEl, button, onVerified\) \{.*?\n\}", js_source, re.S)
    assert match, "verifySourceLink wurde in source-edit.js nicht gefunden."
    func_source = match.group(0)
    assert "/api/sources/${sourceId}/verify-link" in func_source
    assert "onVerified?.();" in func_source
    # Die Quellenliste lädt danach neu (Callback aus import.js).
    assert "onLinkVerified: () => loadSources()" in js_source


# --- import.js: Scroll-Fokus beim Annehmen eines Quellenvorschlags (2026-09-01) ---


def test_open_url_popover_with_url_scrolls_the_popover_into_view():
    # Regression (real gemeldet): im Akkordeon-Modus (Mobile) landet das
    # Formular normal im Dokumentfluss statt als schwebendes Overlay -
    # ohne aktives Scrollen blieb es außerhalb des sichtbaren Bereichs,
    # wenn die Nutzer:in beim Annehmen eines Quellenvorschlags tief in der
    # Liste gescrollt war.
    js_source = _import_js_source()
    match = re.search(r"function openUrlPopoverWithUrl\(url\) \{.*?\n\}", js_source, re.S)
    assert match, "openUrlPopoverWithUrl wurde in import.js nicht gefunden."
    func_source = match.group(0)
    assert "urlPopover.scrollIntoView(" in func_source


# --- import.js: Seitentitel für Nutzer:innen ohne Pfleger:innen-Rolle (2026-09-02) ---


def test_update_source_management_visibility_sets_read_only_heading_without_pfleger_role():
    js_source = _import_js_source()
    match = re.search(r"function updateSourceManagementVisibility\(\) \{.*?\n\}", js_source, re.S)
    assert match, "updateSourceManagementVisibility wurde in import.js nicht gefunden."
    func_source = match.group(0)
    assert "t('import.title')" in func_source
    assert "t('import.titleReadOnly')" in func_source
    assert "hasPflegerRole()" in func_source
    assert "import-page-heading" in func_source


def test_i18n_changed_reapplies_source_management_visibility():
    # Regression: applyStaticTranslations() (i18n.js) setzt [data-i18n]-
    # Elemente bei jedem Sprachwechsel auf ihren Standardtext zurück - ohne
    # erneuten Aufruf hier würde die rollenabhängige Überschrift nach einem
    # Sprachwechsel wieder "Quellen verwalten" zeigen, selbst ohne
    # Pfleger:innen-Rolle.
    js_source = _import_js_source()
    match = re.search(r"document\.addEventListener\('i18n:changed', \(\) => \{.*?\n\}\);", js_source, re.S)
    assert match, "Der i18n:changed-Listener wurde in import.js nicht gefunden."
    assert "updateSourceManagementVisibility();" in match.group(0)


def test_import_page_heading_element_exists_in_html():
    html = (STATIC_DIR / "import.html").read_text()
    assert 'id="import-page-heading"' in html


# --- footer.js: responsives Embed-iframe (Livegang-Vorbereitung, 2026-09-10) ---


def _run_build_embed_snippet(width):
    """Führt footer.js#buildEmbedSnippet per Node aus."""
    js_source = (STATIC_DIR / "footer.js").read_text()
    match = re.search(r"function buildEmbedSnippet\(width\) \{.*?\n\}", js_source, re.S)
    assert match, "buildEmbedSnippet wurde in footer.js nicht gefunden."
    func_source = match.group(0)
    script = f"""
global.window = {{ location: {{ origin: 'https://companion.betahof.com' }} }};
global.document = {{ currentScript: null }};

{func_source}

console.log(JSON.stringify(buildEmbedSnippet({json.dumps(width)})));
"""
    return _run_node(script)


def test_build_embed_snippet_iframe_width_fills_container_up_to_max_width():
    snippet = _run_build_embed_snippet(480)
    assert "width:100%" in snippet
    assert "max-width:480px" in snippet


def test_build_embed_snippet_falls_back_to_default_width_for_invalid_input():
    snippet = _run_build_embed_snippet(None)
    assert "max-width:480px" in snippet


def test_build_embed_snippet_rounds_and_uses_custom_width():
    snippet = _run_build_embed_snippet(320.7)
    assert "max-width:321px" in snippet


def test_embed_html_reports_height_to_parent_on_resize():
    """Führt static/embed-resize.js per Node aus. Seit v0.93.1 externe Datei:
    das frühere Inline-Skript (ponytail-Review 2026-09-10) blockierte die CSP
    (kein 'unsafe-inline'), es lief im Browser nie."""
    script_body = (STATIC_DIR / "embed-resize.js").read_text()
    script = f"""
global.document = {{ documentElement: {{ scrollHeight: 321 }} }};
const posted = [];
global.window = {{}};
global.window.parent = {{ postMessage: (data, origin) => posted.push({{ data, origin }}) }};
global.ResizeObserver = class {{
  constructor(cb) {{ this.cb = cb; }}
  observe() {{ this.cb(); }}
}};

{script_body}

console.log(JSON.stringify(posted));
"""
    posted = _run_node(script)
    assert len(posted) == 1
    assert posted[0]["data"]["type"] == "betacodex-chat-embed-resize"
    assert posted[0]["data"]["height"] == 321
    assert posted[0]["origin"] == "*"


def test_embed_html_skips_reporting_when_not_embedded():
    script_body = (STATIC_DIR / "embed-resize.js").read_text()
    script = f"""
global.document = {{ documentElement: {{ scrollHeight: 321 }} }};
const posted = [];
global.window = {{}};
global.window.parent = global.window;
global.ResizeObserver = class {{
  constructor(cb) {{ this.cb = cb; }}
  observe() {{ this.cb(); }}
}};

{script_body}

console.log(JSON.stringify(posted));
"""
    posted = _run_node(script)
    assert posted == []


def test_build_embed_snippet_includes_resize_listener_matching_embed_html():
    snippet = _run_build_embed_snippet(480)
    embed_js = (STATIC_DIR / "embed-resize.js").read_text()
    assert "betacodex-chat-embed-resize" in snippet
    # Derselbe Nachrichtentyp muss auf beiden Seiten (Embed + Snippet)
    # übereinstimmen, sonst bleibt die Höhenanpassung wirkungslos.
    assert "betacodex-chat-embed-resize" in embed_js
    assert "e.source!==f.contentWindow" in snippet.replace(" ", "")


# --- legal-page-lang-nav.js: Sprachumschalter navigiert auf Rechtstext-Seiten (2026-09-10) ---


def _run_legal_page_lang_nav(*, pathname: str, clicked_lang: str):
    """Simuliert einen Klick auf den DE/EN-Button im Sprachumschalter auf
    einer der vier Rechtstext-Seiten und gibt zurück, wohin (falls
    überhaupt) navigiert wurde."""
    js_source = (STATIC_DIR / "legal-page-lang-nav.js").read_text()
    script = f"""
global.window = {{ location: {{ pathname: {json.dumps(pathname)}, href: '' }} }};
const listeners = [];
const switcher = {{
  addEventListener: (type, handler, useCapture) => listeners.push({{ type, handler, useCapture }}),
}};
global.document = {{ getElementById: (id) => (id === 'lang-switcher' ? switcher : null) }};

{js_source}

const btn = {{ textContent: {json.dumps(clicked_lang.upper())}, closest: () => btn }};
let defaultPrevented = false;
let stopped = false;
const event = {{
  target: btn,
  preventDefault: () => {{ defaultPrevented = true; }},
  stopImmediatePropagation: () => {{ stopped = true; }},
}};
listeners[0].handler(event);
console.log(JSON.stringify({{
  navigatedTo: global.window.location.href,
  defaultPrevented,
  stopped,
  registeredCapture: listeners[0].useCapture,
}}));
"""
    return _run_node(script)


def test_legal_page_lang_nav_navigates_to_counterpart_page():
    result = _run_legal_page_lang_nav(pathname="/datenschutz.html", clicked_lang="en")
    assert result["navigatedTo"] == "/privacy.html"
    assert result["defaultPrevented"] is True
    assert result["stopped"] is True


def test_legal_page_lang_nav_does_not_navigate_for_current_language():
    result = _run_legal_page_lang_nav(pathname="/datenschutz.html", clicked_lang="de")
    assert result["navigatedTo"] == ""


def test_legal_page_lang_nav_listener_uses_capture_phase():
    # Muss VOR dem eigenen setLang()-Klick-Handler des Buttons laufen (siehe
    # i18n.js: renderLangSwitcher) - nur die Capture-Phase garantiert das.
    result = _run_legal_page_lang_nav(pathname="/impressum.html", clicked_lang="en")
    assert result["registeredCapture"] is True
    assert result["navigatedTo"] == "/legal-notice.html"


def test_legal_page_lang_nav_covers_all_four_legal_pages():
    cases = [
        ("/datenschutz.html", "en", "/privacy.html"),
        ("/privacy.html", "de", "/datenschutz.html"),
        ("/impressum.html", "en", "/legal-notice.html"),
        ("/legal-notice.html", "de", "/impressum.html"),
    ]
    for pathname, clicked_lang, expected in cases:
        result = _run_legal_page_lang_nav(pathname=pathname, clicked_lang=clicked_lang)
        assert result["navigatedTo"] == expected, pathname


def test_format_countdown_renders_minutes_and_padded_seconds():
    """static/footer.js#formatCountdown - Feedback-Cooldown-Anzeige (m:ss,
    aufgerundet, nie negativ)."""
    js_source = (STATIC_DIR / "footer.js").read_text()
    match = re.search(r"function formatCountdown.*?\n\}", js_source, re.S)
    assert match, "formatCountdown wurde in footer.js nicht gefunden."
    script = f"""
{match.group(0)}
console.log(JSON.stringify([60000, 59001, 5000, 1, 0, -50].map(formatCountdown)));
"""
    assert _run_node(script) == ["1:00", "1:00", "0:05", "0:01", "0:00", "0:00"]


def test_creative_page_has_new_text_and_copy_buttons_with_bilingual_titles():
    """Kreativ-Modus: 'Neu anfangen'-Button neben der Überschrift und
    'Text kopieren'-Button links neben der Vorschau - Tooltips in DE+EN."""
    html = (STATIC_DIR / "creative.html").read_text()
    assert 'id="creative-new-btn"' in html and 'id="creative-copy-btn"' in html
    assert html.index("creative-copy-btn") < html.index("creative-preview-toggle")
    for lang, new_title, copy_title in (
        ("de", "Neuen Kreativ-Text erarbeiten", "Text kopieren"),
        ("en", "Work on a new creative text", "Copy text"),
    ):
        strings = json.loads((STATIC_DIR / "i18n" / f"{lang}.json").read_text())
        assert strings["creative.newTextTitle"] == new_title
        assert strings["creative.copyTitle"] == copy_title
        assert "creative.newTextConfirmButton" in strings


def test_flash_edit_affordances_flashes_toggle_and_section_buttons_once():
    """static/creative.js#flashEditAffordances: 'Bearbeiten' und jeder
    Abschnitts-Stift bekommen .attention-flash, die Klasse verschwindet nach
    animationend wieder (einmaliges Aufblinken)."""
    js_source = (STATIC_DIR / "creative.js").read_text()
    match = re.search(r"function flashEditAffordances.*?\n\}", js_source, re.S)
    assert match, "flashEditAffordances wurde in creative.js nicht gefunden."
    script = f"""
function makeBtn() {{
  const classes = new Set(); let onEnd = null;
  return {{
    classList: {{ add: (c) => classes.add(c), remove: (c) => classes.delete(c), has: (c) => classes.has(c) }},
    addEventListener: (_, fn) => {{ onEnd = fn; }},
    end: () => onEnd(),
  }};
}}
const previewToggleBtn = makeBtn();
const currentSectionEls = [{{ reviseBtn: makeBtn() }}, {{ reviseBtn: makeBtn() }}];
{match.group(0)}
flashEditAffordances();
const all = [previewToggleBtn, ...currentSectionEls.map((e) => e.reviseBtn)];
const during = all.map((b) => b.classList.has('attention-flash'));
all.forEach((b) => b.end());
const after = all.map((b) => b.classList.has('attention-flash'));
console.log(JSON.stringify({{ during, after }}));
"""
    assert _run_node(script) == {"during": [True, True, True], "after": [False, False, False]}


def test_creative_mode_uses_shared_feedback_component_below_text_box_and_logs_creative_mode():
    """Kreativ-Modus: Daumen-Feedback nutzt dieselbe Komponente wie die
    Konversation (answer-feedback.js), sitzt unter Textfeld UND Vorschau und
    meldet mode 'creative' ans Fragen-Log."""
    html = (STATIC_DIR / "creative.html").read_text()
    assert html.index('id="creative-document-preview"') < html.index('id="creative-feedback"')
    assert html.index('id="creative-feedback"') < html.index('for="creative-instruction"')
    js = (STATIC_DIR / "creative.js").read_text()
    assert "import { buildAnswerFeedback } from '/answer-feedback.js'" in js
    assert "mode: 'creative'" in js
    assert "buildAnswerFeedback" in _question_js_source()


def test_question_log_links_creative_entries_to_creative_mode_with_badge():
    js_source = (STATIC_DIR / "question-log.js").read_text()
    match = re.search(r"function buildQuestionLink\(text, mode\) \{.*?\n\}", js_source, re.S)
    assert match
    assert "/creative.html?instruction=${encodeURIComponent(text)}" in match.group(0)
    assert "entry.mode === 'creative'" in js_source
    for lang in ("de", "en"):
        strings = json.loads((STATIC_DIR / "i18n" / f"{lang}.json").read_text())
        for key in ("creative.feedbackGoodTitle", "creative.feedbackBadTitle", "questionLog.eventType.creative", "questionLog.openCreativeTitle"):
            assert key in strings


# --- question-log.js: Lazy Loading (Antworten beim Aufklappen, Seiten per Sentinel) ---


def test_question_log_loads_lean_list_and_fetches_answer_only_when_opened():
    js_source = (STATIC_DIR / "question-log.js").read_text()
    assert "/api/question-log?include_answers=false" in js_source
    match = re.search(r"async function loadAnswer\(entry, answerEl\) \{.*?\n\}", js_source, re.S)
    assert match, "loadAnswer wurde in question-log.js nicht gefunden."
    block = match.group(0)
    assert "answerCache.has(entry.id)" in block  # schon geladen: kein zweiter Request
    assert "/api/question-log/${entry.id}" in block
    assert "if (details.open) loadAnswer(entry, answer)" in js_source


def test_question_log_filter_runs_over_all_entries_and_paging_only_limits_rendering():
    js_source = (STATIC_DIR / "question-log.js").read_text()
    apply_filter = re.search(r"function applyFilter\(.*?\n\}", js_source, re.S).group(0)
    assert "buildBlocks(allEntries," in apply_filter  # Filter über den kompletten Bestand (Blöcke)
    assert "visibleCount = LOG_PAGE_SIZE" in apply_filter  # neuer Filter -> wieder ab Seite 1
    render = re.search(r"function render\(\) \{.*?\n\}", js_source, re.S).group(0)
    assert "pageBlocks(filteredBlocks, visibleCount)" in render  # Paging zählt Blöcke
    assert "new IntersectionObserver" in render
    assert "visibleCount += LOG_PAGE_SIZE" in render
    # Löschen darf den Scroll-Stand (bereits geladene Seiten) nicht zurücksetzen.
    assert js_source.count("applyFilter({ resetPaging: false })") == 3


def _run_term_overview(entries, sources, lang):
    """Führt static/import.js#buildOverviewTerms und #termLetter per Node
    aus (Schlagwort-Übersicht, Nutzerwunsch 2026-09-23) - beide Funktionen
    werden isoliert aus dem Quelltext extrahiert."""
    js_source = _import_js_source()
    build = re.search(r"function buildOverviewTerms.*?\n\}", js_source, re.S)
    letter = re.search(r"function termLetter.*?\n\}", js_source, re.S)
    assert build and letter, "buildOverviewTerms/termLetter wurden in import.js nicht gefunden."
    script = f"""
const JUMP_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');
{build.group(0)}
{letter.group(0)}
const result = buildOverviewTerms({json.dumps(entries)}, {json.dumps(sources)}, {json.dumps(lang)});
console.log(JSON.stringify(result.map((e) => ({{
  term: e.term, ids: e.sources.map((s) => s.id), letter: termLetter(e.term),
}}))));
"""
    return _run_node(script)


def test_term_overview_filters_by_lang_hides_unknown_sources_and_sorts():
    entries = [
        {"term": "Zeit", "source_ids": ["a"], "langs": ["de"]},
        {"term": "Ärger", "source_ids": ["a", "gone"], "langs": ["de"]},
        {"term": "time", "source_ids": ["a"], "langs": ["en"]},
        {"term": "Nur gelöscht", "source_ids": ["gone"], "langs": ["de"]},
        {"term": "3-Ebenen", "source_ids": ["b"], "langs": ["de", "en"]},
        {"term": "beta", "source_ids": ["a", "b"], "langs": ["de"]},
    ]
    sources = [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}]
    result = _run_term_overview(entries, sources, "de")
    assert [e["term"] for e in result] == ["3-Ebenen", "Ärger", "beta", "Zeit"]
    assert result[1]["ids"] == ["a"]
    assert [e["letter"] for e in result] == ["", "A", "B", "Z"]


def test_format_countdown_shows_minutes_and_zero_padded_seconds():
    js_source = (STATIC_DIR / "creative.js").read_text()
    match = re.search(r"export function formatCountdown.*?\n\}", js_source, re.S)
    assert match, "formatCountdown wurde in creative.js nicht gefunden."
    func = match.group(0).replace("export function", "function")
    result = _run_node(f"{func}\nconsole.log(JSON.stringify([599, 61, 9, 1].map(formatCountdown)));")
    assert result == ["9:59", "1:01", "0:09", "0:01"]


def test_conversation_edit_dialog_loads_single_source_with_full_text():
    """Nutzerwunsch (2026-09-25): der Stift in der Konversation öffnet das
    Bearbeiten-Formular (source-edit.js) direkt vor Ort. Es muss die Quelle
    einzeln MIT Volltext laden - sonst würde Speichern einen leeren Text über
    den echten schreiben (siehe fullTextReady-Test oben)."""
    js_source = _question_js_source()
    link_match = re.search(r"function appendEditSourceLink.*?\n\}", js_source, re.S)
    assert link_match and "openSourceEditDialog(sourceId)" in link_match.group(0)
    dialog_match = re.search(r"async function openSourceEditDialog.*?\n\}", js_source, re.S)
    assert dialog_match, "openSourceEditDialog wurde in question.js nicht gefunden."
    body = dialog_match.group(0)
    assert "import('/source-edit.js')" in body
    assert "fetchSource(sourceId)" in body
    fetch_match = re.search(r"async function fetchSource.*?\n\}", js_source, re.S)
    assert fetch_match and "fetch(`/api/sources/${encodeURIComponent(sourceId)}`" in fetch_match.group(0)
    assert "module.buildEditPanel(source" in body
    # Speichern/Löschen übertragen sich auf die Konversation (Titel, Status).
    assert "updateCitedSource(sourceId, {" in body
    assert "updateCitedSource(sourceId, { deleted: true })" in body
    # Rückgängig wie in der Quellenübersicht; Schließen bestätigt das Löschen.
    assert "setTimeout(deleteNow, module.UNDO_DURATION_MS)" in body
    assert "if (pendingDeletion) deleteNow();" in body
    exports = (STATIC_DIR / "source-edit.js").read_text()
    assert "export function buildEditPanel(" in exports
    assert "export function setKnownAuthors(" in exports


def test_icon_buttons_visible_in_conversation_edit_dialog():
    """Regression (2026-09-25, v0.77.0): .icon-button ist auf Desktop per
    opacity:0 versteckt und erscheint nur beim Zeilen-Hover in der
    Quellenliste - im Bearbeiten-Dialog der Konversation war der Mülleimer
    dadurch unsichtbar."""
    css = (STATIC_DIR / "style.css").read_text()
    match = re.search(r"\.source-edit-dialog \.icon-button \{\s*opacity: 1;", css)
    assert match, "Icons im Bearbeiten-Dialog müssen immer sichtbar sein."


def test_view_source_link_opens_reader_dialog_instead_of_new_tab():
    """Nutzerwunsch (2026-09-25): das Auge ("Quelle ansehen") öffnet eine
    Lese-Ansicht in der Konversation - ein neuer Tab auf die eigene Domain
    landete bei installierter App im App-Fenster."""
    js_source = _question_js_source()
    link_match = re.search(r"function appendViewSourceLink.*?\n\}", js_source, re.S)
    assert link_match and "openSourceViewDialog(sourceId)" in link_match.group(0)
    assert "e.preventDefault()" in link_match.group(0)
    reader_match = re.search(r"function buildSourceReader.*?\n\}", js_source, re.S)
    assert reader_match, "buildSourceReader wurde nicht gefunden."
    reader = reader_match.group(0)
    # Geschützte Quellen: Server liefert den Text leer, der Dialog erklärt das.
    assert "common.readerRestrictedNote" in reader
    assert "renderMarkdown(s.text)" in reader
    # Volltext nur ohne Web-Quelle (2026-09-26) - sonst führt der Link zum Original.
    assert reader.index("if (s.url || s.listen_url) return article;") < reader.index("renderMarkdown(s.text)")


def test_404_page_uses_shared_site_header():
    """Nutzer-Meldung (2026-09-25): auf der 404-Seite fehlte die
    Navigationsleiste - sie muss denselben Header wie alle Seiten nutzen."""
    html = (STATIC_DIR / "404.html").read_text()
    assert '<header id="site-header">' in html
    assert '<script type="module" src="/init-header.js"></script>' in html


def test_creative_cooldown_shows_on_buttons_and_greys_out_inputs():
    """Nutzerwunsch (2026-09-25): Countdown auch im Absenden-Button, und
    Anweisungsfeld + Mikrofon gesperrt, solange nichts abgeschickt werden kann."""
    js_source = (STATIC_DIR / "creative.js").read_text()
    match = re.search(r"function applyCooldown\(\) \{.*?\n\}", js_source, re.S)
    assert match, "applyCooldown wurde nicht gefunden."
    body = match.group(0)
    assert "instructionField.disabled = disabled" in body
    assert "creativeMicButton.disabled = disabled" in body
    assert "els.micBtn.disabled = disabled" in body
    assert "creative.cooldownButtonTitle" in body
    # "i"-Icon neben dem Countdown, nur während des Cooldowns sichtbar.
    assert "info.classList.toggle('hidden', !blocked)" in body
    assert "creative.cooldownInfo" in body
    css = (STATIC_DIR / "style.css").read_text()
    assert "#creative-instruction:disabled" in css


def test_creative_format_buttons_keep_scroll_position():
    """Nutzerwunsch (2026-09-25): Formatieren springt nicht mehr ans Textende."""
    js_source = (STATIC_DIR / "creative.js").read_text()
    match = re.search(r"btn\.addEventListener\('click', \(\) => \{\s*rememberForUndo\(\);.*?\n  \}\);", js_source, re.S)
    assert match
    body = match.group(0)
    assert "documentField.focus({ preventScroll: true })" in body
    assert "documentField.scrollTop = scrollTop" in body


def test_reader_shows_ai_icons_and_sticky_close_button():
    """Nutzerwunsch (2026-09-26): KI-Icon an Zusammenfassung/Schlagworten,
    solange nicht von Hand überarbeitet; "x" bleibt beim Scrollen sichtbar."""
    js_source = _question_js_source()
    reader = re.search(r"function buildSourceReader.*?\n\}", js_source, re.S).group(0)
    assert "if (s.summary_ai_generated !== false) p.prepend(aiIcon('import.aiSummaryTooltip'), ' ');" in reader
    assert "if (s.key_terms_ai_generated !== false) p.prepend(aiIcon('common.aiKeyTermsTooltip'), ' ');" in reader
    css = (STATIC_DIR / "style.css").read_text()
    block = re.search(r"\.source-edit-dialog \.jobs-bar-close \{[^}]*\}", css).group(0)
    assert "position: sticky" in block and "background: var(--color-bg)" in block


def test_user_management_moved_from_popover_to_own_page():
    """2026-09-26: Nutzerverwaltung als eigene Seite (users.html) - das
    Login-Popover verlinkt nur noch dorthin."""
    auth_js = (STATIC_DIR / "auth.js").read_text()
    assert "buildAdminSection" not in auth_js
    assert "usersLink.href = '/users.html'" in auth_js
    users_js = (STATIC_DIR / "users.js").read_text()
    assert "/resend-invite" in users_js
    assert "method: 'DELETE'" in users_js
    assert "JSON.stringify({ email: email.value.trim(), roles," in users_js
    html = (STATIC_DIR / "users.html").read_text()
    assert '<script type="module" src="/users.js"></script>' in html
    assert '<header id="site-header">' in html


def test_costs_moved_from_mcp_page_to_own_page():
    """2026-09-26: Kostenübersicht als eigene Seite - System-Admins alle
    Kosten, alle anderen Angemeldeten nur die eigenen."""
    mcp_html = (STATIC_DIR / "mcp.html").read_text()
    assert 'id="mcp-summary"' not in mcp_html and 'id="mcp-month"' not in mcp_html
    assert "/api/mcp/usage" not in (STATIC_DIR / "mcp.js").read_text()
    costs_js = (STATIC_DIR / "costs.js").read_text()
    assert "const base = all ? '/api/costs' : '/api/costs/mine';" in costs_js
    assert "buildSummaryTable(summary, { showAccounts: all })" in costs_js
    assert "costsLink.href = '/costs.html'" in (STATIC_DIR / "auth.js").read_text()


def test_costs_page_has_monthly_bar_chart_linked_to_month_filter():
    """Nutzerwunsch (2026-09-26): Monatsverlauf als Balkengrafik; die
    Monatstabelle mit Filter bleibt, Klick auf einen Balken wählt den Monat."""
    js = (STATIC_DIR / "costs.js").read_text()
    assert "fetch(`${base}/history`" in js
    assert "monthInput.value = entry.month;" in js
    html = (STATIC_DIR / "costs.html").read_text()
    assert 'id="costs-chart"' in html and 'id="costs-month"' in html and 'id="costs-summary"' in html


def test_cost_chart_stacks_by_usage_type_and_shows_providers():
    """Nutzerwunsch (2026-09-26): Balken nach Nutzungsart gestapelt (4 Gruppen,
    Legende), Anbieter im Tooltip. Jeder Kanal gehört zu genau einer Gruppe."""
    js = (STATIC_DIR / "costs.js").read_text()
    for key in ("conversation", "creative", "tts", "background"):
        assert f"key: '{key}'" in js
    for channel in ("'ask'", "'ui'", "'mcp'", "'tts'", "'summary'", "'ocr'", "'stt'", "'discovery'"):
        assert js.count(channel) >= 1
    assert "costs.provider." in js
    assert "renderLegend();" in js


# --- Fragen-Log mobil optimieren (Idee e1cd2bc6) ---


def _question_log_css_block_mobile() -> str:
    css = (STATIC_DIR / "style.css").read_text()
    base = css.index("#question-log-list .question-log-entry {")
    start = css.index("@media (max-width: 480px) {", base)
    end = css.index("\n}\n", start)
    assert "#question-log-list" in css[start:end], "Mobil-Block fürs Fragen-Log fehlt nach den Basisregeln."
    return css[start:end]


def test_question_log_mobile_block_uses_two_column_timeline_and_scrolling_filter():
    block = _question_log_css_block_mobile()
    assert "grid-template-columns: 1.25rem minmax(0, 1fr)" in block
    assert re.search(r"\.question-log-header-row \{[^}]*position: static", block)
    assert re.search(r"\.question-log-filter \{[^}]*overflow-x: auto", block)
    assert re.search(r"\.question-log-filter-btn \{[^}]*min-height: 44px", block)
    assert re.search(r"\.question-log-day-marker \{[^}]*grid-column: 1 / -1", block)
    assert re.search(r"::after \{[^}]*grid-column: 1;", block)
    # Letzte Pille scrollt aus dem Verlauf; Fokusrahmen wird nicht abgeschnitten.
    filt = re.search(r"\.question-log-filter \{[^}]*\}", block).group(0)
    assert "padding-inline-end" in filt and "padding-block" in filt


def test_question_log_text_wraps_long_words_and_clamps():
    css = (STATIC_DIR / "style.css").read_text()
    assert re.search(r"\.question-log-text \{[^}]*overflow-wrap: anywhere", css)
    assert re.search(r"\.question-log-answer \{[^}]*overflow-wrap: anywhere", css)
    clamp = re.search(r"\.question-log-text--clamped \{[^}]*\}", css)
    assert clamp and "-webkit-line-clamp: 4" in clamp.group(0)


def test_question_log_filter_buttons_start_with_aria_pressed_true():
    html = (STATIC_DIR / "question-log.html").read_text()
    buttons = re.findall(r"<button[^>]*question-log-filter-btn[^>]*>", html)
    assert len(buttons) == 6  # inkl. Folgefrage (Idee 56580b6e)
    assert all('aria-pressed="true"' in b for b in buttons)


def test_question_log_show_more_less_texts_in_both_languages():
    for lang in ("de", "en"):
        data = json.loads((STATIC_DIR / "i18n" / f"{lang}.json").read_text())
        assert data["questionLog.showMore"] and data["questionLog.showLess"]


def _run_question_log_text(text: str, expanded_ids: list, overflow: bool, click: bool):
    """Führt appendQuestionText aus question-log.js per Node mit Mini-DOM aus."""
    js_source = (STATIC_DIR / "question-log.js").read_text()
    consts = re.search(r"const CLAMP_MIN_CHARS = \d+;", js_source)
    assert consts, "CLAMP_MIN_CHARS fehlt."
    set_decl = re.search(r"const expandedIds = new Set\(\);", js_source)
    assert set_decl, "expandedIds fehlt."
    funcs = [
        re.search(rf"function {name}\(.*?\n\}}", js_source, re.S)
        for name in ("buildMoreButton", "appendQuestionText", "runClampChecks")
    ]
    assert all(funcs), "buildMoreButton/appendQuestionText/runClampChecks fehlen."
    assert re.search(r"let clampChecks = \[\];", js_source), "clampChecks fehlt."
    script = f"""
class El {{
  constructor(tag) {{ this.tag = tag; this.children = []; this.attrs = {{}}; this.cls = new Set(); this.l = {{}};
    this.textContent = ''; this.isConnected = true; this.scrollHeight = {100 if overflow else 40}; this.clientHeight = 40; }}
  set className(v) {{ this.cls = new Set(v.split(' ').filter(Boolean)); }}
  get className() {{ return [...this.cls].join(' '); }}
  get classList() {{ const s = this.cls; return {{ add: (c) => s.add(c), remove: (c) => s.delete(c), contains: (c) => s.has(c),
    toggle: (c, f) => {{ if (f === undefined) f = !s.has(c); f ? s.add(c) : s.delete(c); return f; }} }}; }}
  appendChild(c) {{ this.children.push(c); c.parent = this; return c; }}
  after(c) {{ const i = this.parent.children.indexOf(this); this.parent.children.splice(i + 1, 0, c); c.parent = this.parent; }}
  setAttribute(k, v) {{ this.attrs[k] = String(v); }}
  getAttribute(k) {{ return this.attrs[k]; }}
  addEventListener(e, f) {{ this.l[e] = f; }}
  click() {{ this.l.click(); }}
}}
global.document = {{ createElement: (t) => new El(t) }};
global.requestAnimationFrame = (f) => f();
const t = (k) => k;
function buildQuestionLink(text) {{ const a = new El('a'); a.textContent = text; return a; }}
{consts.group(0)}
{set_decl.group(0)}
{funcs[0].group(0)}
{funcs[1].group(0)}
let clampChecks = [];
{funcs[2].group(0)}
for (const id of {json.dumps(expanded_ids)}) expandedIds.add(id);
const li = new El('li');
appendQuestionText(li, {{ id: 'a', text: {json.dumps(text)}, mode: 'chat' }});
runClampChecks();
let p = li.children[0];
let btn = li.children[1];
if ({json.dumps(click)} && btn) btn.click();
console.log(JSON.stringify({{
  clamped: p.cls.has('question-log-text--clamped'),
  hasBtn: !!btn,
  expanded: btn ? btn.attrs['aria-expanded'] : null,
  label: btn ? btn.textContent : null,
  stored: expandedIds.has('a'),
  btnClamped: btn ? btn.cls.has('question-log-more-btn') : null,
  controls: btn ? btn.attrs['aria-controls'] === p.id && !!p.id : null,
}}));
"""
    return _run_node(script)


LONG = "Wie funktioniert die dezentrale Führung im Beta-Kodex genau? " * 5


def test_question_log_long_overflowing_text_is_clamped_with_more_button():
    r = _run_question_log_text(LONG, [], overflow=True, click=False)
    assert r == {"clamped": True, "hasBtn": True, "expanded": "false", "label": "questionLog.showMore", "stored": False, "btnClamped": True, "controls": True}


def test_question_log_more_button_expands_and_collapses():
    r = _run_question_log_text(LONG, [], overflow=True, click=True)
    assert r["clamped"] is False and r["expanded"] == "true" and r["label"] == "questionLog.showLess" and r["stored"] is True


def test_question_log_long_text_that_fits_gets_no_button():
    r = _run_question_log_text(LONG, [], overflow=False, click=False)
    assert r["hasBtn"] is False and r["clamped"] is False


def test_question_log_clamp_check_is_batched_and_delete_clears_expanded():
    js = (STATIC_DIR / "question-log.js").read_text()
    assert "requestAnimationFrame" not in re.search(r"function appendQuestionText.*?\n\}", js, re.S).group(0)
    assert js.count("requestAnimationFrame(runClampChecks)") == 1
    assert "expandedIds.delete(entry.id)" in re.search(r"async function deleteEntry.*?\n\}", js, re.S).group(0)


def test_question_log_short_text_never_clamped_or_button():
    r = _run_question_log_text("Kurze Frage?", [], overflow=True, click=False)
    assert r["clamped"] is False and r["hasBtn"] is False


def test_question_log_expanded_state_survives_rerender():
    r = _run_question_log_text(LONG, ["a"], overflow=True, click=False)
    assert r["clamped"] is False and r["hasBtn"] is True and r["expanded"] == "true"


# --- Änderungslog mobil optimieren (gleiches Muster wie Fragen-Log) ---


def _changelog_css_block_mobile() -> str:
    css = (STATIC_DIR / "style.css").read_text()
    base = css.index("#changelog-list .changelog-entry {")
    start = css.index("@media (max-width: 480px) {", base)
    end = css.index("\n}\n", start)
    assert "#changelog-list" in css[start:end], "Mobil-Block fürs Änderungslog fehlt nach den Basisregeln."
    return css[start:end]


def test_changelog_mobile_block_uses_two_column_timeline():
    block = _changelog_css_block_mobile()
    assert re.search(r"#changelog-list\.timeline-mode \{[^}]*grid-template-columns: 1\.25rem minmax\(0, 1fr\)", block)
    assert re.search(r"#changelog-list\.timeline-mode::after \{[^}]*grid-column: 1;", block)
    assert re.search(r"\.changelog-day-marker \{[^}]*grid-column: 1 / -1", block)
    assert re.search(r"#changelog-list \.changelog-entry \{[^}]*grid-column: 2", block)


def test_changelog_mobile_revert_buttons_are_touch_targets_and_wrap():
    block = _changelog_css_block_mobile()
    assert re.search(r"\.changelog-revert-row \{[^}]*flex-wrap: wrap", block)
    assert re.search(r"\.changelog-revert-row \.link-button \{[^}]*min-height: 44px", block)


def test_changelog_long_labels_and_values_wrap_on_all_viewports():
    css = (STATIC_DIR / "style.css").read_text()
    assert re.search(r"\.changelog-target-label \{[^}]*overflow-wrap: anywhere", css)
    assert re.search(r"\.changelog-field-list li \{[^}]*overflow-wrap: anywhere", css)
    # 1fr ohne minmax(0, …) lässt lange Inhalte die Spalte sprengen (Desktop).
    assert re.search(r"#changelog-list\.timeline-mode \{[^}]*grid-template-columns: max-content 1\.25rem minmax\(0, 1fr\)", css)


def test_changelog_mobile_time_sits_on_top_like_question_log():
    block = _changelog_css_block_mobile()
    assert re.search(r"\.changelog-time \{[^}]*order: -1[^}]*flex-basis: 100%", block)


def _run_rescroll_after_keyboard(*, with_viewport: bool, resize: bool, timeout: bool) -> dict:
    """Führt question.js#rescrollAfterKeyboard per Node mit Stubs aus."""
    js_source = _question_js_source()
    match = re.search(r"function rescrollAfterKeyboard.*?\n\}", js_source, re.S)
    assert match, "rescrollAfterKeyboard wurde nicht gefunden."
    script = f"""
{match.group(0)}
let scrolls = 0, resizeFn = null, timerFn = null, timerMs = null;
const viewport = {json.dumps(with_viewport)} ? {{
  addEventListener: (type, fn) => {{ if (type === 'resize') resizeFn = fn; }},
  removeEventListener: () => {{ resizeFn = null; }},
}} : undefined;
rescrollAfterKeyboard(viewport, (fn, ms) => {{ timerFn = fn; timerMs = ms; }}, () => {{ scrolls++; }});
if ({json.dumps(resize)} && resizeFn) resizeFn();
if ({json.dumps(timeout)} && timerFn) timerFn();
console.log(JSON.stringify({{ scrolls, timerMs }}));
"""
    return _run_node(script)


def test_rescroll_after_keyboard_scrolls_exactly_once():
    """Idee b5bd431b: Nach-Scroll nach dem Schließen der Tastatur - genau
    einmal, egal ob resize, Timeout oder beides; ohne visualViewport kein Fehler."""
    assert _run_rescroll_after_keyboard(with_viewport=True, resize=True, timeout=False)["scrolls"] == 1
    assert _run_rescroll_after_keyboard(with_viewport=True, resize=False, timeout=True)["scrolls"] == 1
    assert _run_rescroll_after_keyboard(with_viewport=False, resize=False, timeout=True)["scrolls"] == 1
    both = _run_rescroll_after_keyboard(with_viewport=True, resize=True, timeout=True)
    assert both["scrolls"] == 1
    assert both["timerMs"] == 400
    # Vor Resize/Timeout kein Scroll.
    assert _run_rescroll_after_keyboard(with_viewport=True, resize=False, timeout=False)["scrolls"] == 0


def test_touch_submit_blurs_input_before_scroll_and_desktop_keeps_focus():
    """Idee b5bd431b: Touch-Geräte (pointer: coarse, auch iPad/iPhone quer)
    verlassen das Feld vor dem Scroll; focus() nur ohne Touch."""
    js_source = _question_js_source()
    handler = re.search(r"questionForm\.addEventListener\('submit'.*?questionInput\.focus\(\);\s*\}", js_source, re.S)
    assert handler, "Submit-Handler wurde nicht gefunden."
    body = handler.group(0)
    assert "matchMedia('(pointer: coarse)')" in body
    assert "max-width: 640px" not in body
    assert body.index("questionInput.blur()") < body.index("scrollQuestionIntoView(userMessage)")
    assert "rescrollAfterKeyboard(" in body
    assert body.count("questionInput.blur()") == 1
    assert body.count("questionInput.focus()") == 1


# --- EPUB-Upload / Kapitelüberschrift im Auszug (Idee 8d1b69dd) --------------

def _run_split_leading_heading(text):
    js_source = _question_js_source()
    match = re.search(r"function splitLeadingHeading.*?\n\}", js_source, re.S)
    assert match, "splitLeadingHeading wurde in question.js nicht gefunden."
    script = f"""
{match.group(0)}
console.log(JSON.stringify(splitLeadingHeading({json.dumps(text)})));
"""
    return _run_node(script)


def test_split_leading_heading_extracts_markdown_heading():
    assert _run_split_leading_heading("## Kapitel Zwei\nDer Rumpf.") == {"heading": "Kapitel Zwei", "body": "Der Rumpf."}


def test_split_leading_heading_leaves_text_without_heading():
    text = "Kein Titel hier.\n# nicht am Anfang"
    assert _run_split_leading_heading(text) == {"heading": "", "body": text}


def test_split_leading_heading_ignores_hash_without_space_and_level_four():
    assert _run_split_leading_heading("#Tag und mehr")["heading"] == ""
    assert _run_split_leading_heading("#### Zu tief\nText")["heading"] == ""


def test_import_js_routes_epub_files_to_epub_endpoint():
    source = _import_js_source()
    assert "/api/extract-epub-upload" in source
    assert "epub" in (STATIC_DIR / "import.html").read_text().lower()


@pytest.mark.parametrize("lang", ["de", "en"])
def test_import_file_labels_mention_epub(lang):
    strings = json.loads((STATIC_DIR / "i18n" / f"{lang}.json").read_text())
    assert "EPUB" in strings["import.fileFieldLabel"]
    assert "EPUB" in strings["import.typeFileTitle"]


def test_prepare_excerpt_strips_heading_from_highlight_too():
    # Backend-split_sentences hängt die Überschrift an den ersten Satz.
    js_source = _question_js_source()
    funcs = [re.search(rf"function {n}.*?\n\}}", js_source, re.S) for n in ("splitLeadingHeading", "findHighlightRange", "prepareExcerpt")]
    assert all(funcs), "prepareExcerpt/splitLeadingHeading/findHighlightRange fehlen in question.js"
    text = "## Kapitel\nErster Satz. Zweiter Satz."
    highlight = "## Kapitel\nErster Satz."
    script = (
        "\n".join(f.group(0) for f in funcs)
        + f"\nconst r = prepareExcerpt({json.dumps(text)}, {json.dumps(highlight)});"
        + "\nconsole.log(JSON.stringify({heading: r.heading, range: findHighlightRange(r.body, r.highlight), body: r.body}));"
    )
    out = _run_node(script)
    assert out["heading"] == "Kapitel"
    assert out["range"] == [0, len("Erster Satz.")]


# --- conversation_id im Chat-Client (Idee 56580b6e) ---


def test_feedback_sends_conversation_id_only_when_given():
    js = (STATIC_DIR / "answer-feedback.js").read_text()
    assert "conversationId = null" in js
    assert "payload.conversation_id = conversationId" in js
    assert "if (conversationId)" in js


def test_handoff_carries_conversation_id():
    js = (STATIC_DIR / "conversation-handoff.js").read_text()
    assert "export const CONVERSATION_ID_STORAGE_KEY" in js
    assert "createConversationHandoffToken(history, conversationId = null)" in js
    assert "conversation_id: conversationId" in js
    assert "conversationId: data.conversation_id || null" in js


def test_question_js_sends_conversation_id():
    js = _question_js_source()
    assert "crypto.randomUUID()" in js
    assert "let conversationId" in js
    assert "conversation_id: conversationId" in js
    assert "conversationId })" in js  # buildAnswerFeedback
    assert "createConversationHandoffToken(conversationHistory, conversationId)" in js
    assert "handoff.conversationId" in js


def test_import_js_stores_handoff_conversation_id():
    js = _import_js_source()
    assert "CONVERSATION_ID_STORAGE_KEY" in js
    assert "handoff.conversationId" in js


def test_question_js_first_message_counts_sent_not_answered_questions():
    # Live-Befund v0.87.0: eine zweite Frage, abgeschickt während die erste
    # noch streamt (conversationHistory erst nach "done" gefüllt), ging als
    # is_first_message=true raus - zwei "erste Fragen" im selben Chat-Block.
    # Maßgeblich ist, ob in dieser Konversation schon eine Frage gesendet wurde.
    js = _question_js_source()
    assert "const isFirstMessage = conversationHistory.length === 0 && !questionSentInConversation" in js
    assert "is_first_message: isFirstMessage" in js
    assert "questionSentInConversation = true" in js


# ---------------------------------------------------------------------------
# Idee ff895248: Bildleiste aus Quellen-Bildern (static/question.js)
# ---------------------------------------------------------------------------

_FAKE_DOM_JS = """
class FakeNode {
  constructor(nodeType, tag) {
    this.nodeType = nodeType;
    this.tag = tag || null;
    this.children = [];
    this.parentNode = null;
    this.className = '';
    this._text = '';
    this.listeners = {};
    this.dataset = {};
    this.style = {};
    this.attrs = {};
  }
  get textContent() {
    return this._text + this.children.map((c) => c.textContent).join('');
  }
  set textContent(v) { this._text = v; this.children = []; }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  removeChildNode(child) {
    const i = this.children.indexOf(child);
    if (i !== -1) this.children.splice(i, 1);
  }
  remove() { if (this.parentNode) this.parentNode.removeChildNode(this); this.parentNode = null; }
  closest(tag) {
    let n = this;
    while (n) { if (n.tag === tag) return n; n = n.parentNode; }
    return null;
  }
  insertAdjacentElement(where, el) {
    if (!this.parentNode) return;
    const siblings = this.parentNode.children;
    const i = siblings.indexOf(this);
    el.parentNode = this.parentNode;
    siblings.splice(where === 'afterend' ? i + 1 : i, 0, el);
  }
  replaceChild(newNode, oldNode) {
    const i = this.children.indexOf(oldNode);
    if (i === -1) return;
    const replacement = newNode.nodeType === 'fragment' ? newNode.children : [newNode];
    replacement.forEach((c) => { c.parentNode = this; });
    this.children.splice(i, 1, ...replacement);
  }
  get localName() { return this.tag; }
  get nextSibling() {
    const sib = this.parentNode ? this.parentNode.children : [];
    return sib[sib.indexOf(this) + 1] || null;
  }
  get previousSibling() {
    const sib = this.parentNode ? this.parentNode.children : [];
    return sib[sib.indexOf(this) - 1] || null;
  }
  get classList() {
    const node = this;
    const names = () => node.className.split(' ').filter(Boolean);
    return {
      add: (n) => { if (!names().includes(n)) node.className = [...names(), n].join(' '); },
      remove: (n) => { node.className = names().filter((x) => x !== n).join(' '); },
      contains: (n) => names().includes(n),
    };
  }
  addEventListener(evt, fn) { this.listeners[evt] = fn; }
  setAttribute(k, v) { this.attrs[k] = String(v); this[k] = String(v); }
  querySelectorAll(sel) {
    const cls = sel.split('.').pop();
    const acc = [];
    (function walk(n) {
      n.children.forEach((c) => {
        if (c.nodeType !== 'text' && (' ' + c.className + ' ').includes(' ' + cls + ' ')) acc.push(c);
        walk(c);
      });
    })(this);
    return acc;
  }
}
const document = {
  createElement: (tag) => new FakeNode('element', tag),
  createTextNode: (text) => { const n = new FakeNode('text'); n._text = text; return n; },
  createDocumentFragment: () => new FakeNode('fragment'),
  createTreeWalker: (root) => {
    const stack = [];
    (function collect(node) {
      node.children.forEach((child) => {
        if (child.nodeType === 'text') stack.push(child);
        else collect(child);
      });
    })(root);
    let i = 0;
    return { nextNode: () => (i < stack.length ? stack[i++] : null) };
  },
};
const NodeFilter = { SHOW_TEXT: 4 };
function t(key, vars = {}) {
  let s = ({ 'index.sourceImagePage': 'S. {n}' })[key] || key;
  for (const [k, v] of Object.entries(vars)) s = s.replaceAll('{' + k + '}', v);
  return s;
}
const CLOSE_ICON = '<svg></svg>';
const EXTERNAL_LINK_ICON = '<svg></svg>';
"""


def _question_js_funcs(*names: str) -> str:
    js_source = _question_js_source()
    parts = []
    for name in names:
        match = re.search(rf"function {name}\b.*?\n\}}", js_source, re.S)
        assert match, f"{name} wurde in question.js nicht gefunden."
        parts.append(match.group(0))
    return "\n\n".join(parts)


def _question_js_consts(*names: str) -> str:
    js_source = _question_js_source()
    out = []
    for name in names:
        match = re.search(rf"^const {name} = .*;$", js_source, re.M)
        assert match, f"{name} wurde in question.js nicht gefunden."
        out.append(match.group(0))
    return "\n".join(out)


def _run_question_js(body: str, *funcs: str):
    consts = _question_js_consts("INLINE_MARKER_RE", "MIN_INLINE_IMAGE_PX") if "placeInlineImage" in funcs else ""
    script = f"{_FAKE_DOM_JS}\n{_source_lang_js()}\n{consts}\n{_question_js_funcs(*funcs)}\n{body}"
    return _run_node(script)


_STRIP_SUMMARY_JS = """
function findAll(node, pred, acc = []) {
  node.children.forEach((c) => { if (pred(c)) acc.push(c); findAll(c, pred, acc); });
  return acc;
}
function summarize(strip) {
  if (!strip) return null;
  return {
    cls: strip.className,
    figures: findAll(strip, (n) => n.tag === 'figure').map((f) => ({
      img: findAll(f, (n) => n.tag === 'img').map((i) => ({
        src: i.src, alt: i.alt, loading: i.loading, referrerPolicy: i.referrerPolicy,
      }))[0],
      caption: findAll(f, (n) => n.tag === 'figcaption').map((c) => c.textContent)[0],
      links: findAll(f, (n) => n.tag === 'a').map((a) => ({
        href: a.href, target: a.target, rel: a.rel,
      })),
    })),
  };
}
"""

_STRIP_FUNCS = ("safeImageSrc", "buildImageFigure", "buildImageStrip")


def _src(i):
    return f"https://img.example/{i}.jpg"


def _source(i, images, **extra):
    return {
        "source_id": f"s{i}", "chunk_id": f"c{i}", "title": f"Titel {i}",
        "url": f"https://example.org/{i}", "images": images, **extra,
    }


def _run_strip(sources):
    return _run_question_js(
        f"{_STRIP_SUMMARY_JS}\nconsole.log(JSON.stringify(summarize(buildImageStrip({json.dumps(sources)}))));",
        *_STRIP_FUNCS,
    )


def test_image_strip_shows_title_and_page_in_caption_and_safe_attributes():
    sources = [_source(1, [{"src": _src(1), "alt": "Grafik", "page": 7}])]
    strip = _run_strip(sources)
    assert len(strip["figures"]) == 1
    fig = strip["figures"][0]
    assert fig["caption"] == "Titel 1 · S. 7"
    assert fig["img"] == {"src": _src(1), "alt": "Grafik", "loading": "lazy", "referrerPolicy": "no-referrer"}
    assert fig["links"] == [
        {"href": "https://example.org/1", "target": "_blank", "rel": "noopener noreferrer"}
    ]


def test_image_strip_caption_has_no_page_for_web_images_and_links_are_not_pdf_anchored():
    strip = _run_strip([_source(1, [{"src": _src(1), "alt": "", "page": None}])])
    assert strip["figures"][0]["caption"] == "Titel 1"


def test_image_strip_links_pdf_url_with_page_anchor():
    src = _source(1, [{"src": "/api/sources/abc/images/" + "a" * 32 + ".webp", "alt": "x", "page": 3}],
                  url="https://example.org/doc.pdf")
    strip = _run_strip([src])
    assert strip["figures"][0]["links"][0]["href"] == "https://example.org/doc.pdf#page=3"
    assert strip["figures"][0]["img"]["src"] == "/api/sources/abc/images/" + "a" * 32 + ".webp"


def test_image_strip_has_no_link_without_usable_url():
    for extra in ({"url": None}, {"url": "javascript:alert(1)"}, {"url_reachable": False}):
        strip = _run_strip([_source(1, [{"src": _src(1), "alt": "a", "page": None}], **extra)])
        assert strip["figures"][0]["links"] == [], extra
        assert strip["figures"][0]["caption"] == "Titel 1", extra


def test_image_strip_caps_at_six_and_dedupes_by_src():
    images = [{"src": _src(i % 8), "alt": "", "page": None} for i in range(12)]  # 8 verschiedene
    strip = _run_strip([_source(1, images)])
    assert [f["img"]["src"] for f in strip["figures"]] == [_src(i) for i in range(6)]


def test_image_strip_is_absent_without_images():
    for images in ([], None):
        assert _run_strip([_source(1, images)]) is None
    assert _run_strip([{"source_id": "s", "chunk_id": "c", "title": "T"}]) is None  # Feld fehlt (alte Daten)
    assert _run_strip([]) is None


def test_image_strip_drops_unsafe_image_sources():
    bad = ["http://img.example/a.jpg", "javascript:alert(1)", "data:image/png;base64,AAAA",
           "//evil.example/a.jpg", "/api/sources/../x.webp", "/other/path.webp", ""]
    images = [{"src": s, "alt": "", "page": None} for s in bad]
    assert _run_strip([_source(1, images)]) is None


def test_image_strip_alt_with_script_markup_stays_plain_text():
    alt = "<script>alert(1)</script>"
    strip = _run_strip([_source(1, [{"src": _src(1), "alt": alt, "page": None}], title=alt)])
    fig = strip["figures"][0]
    assert fig["img"]["alt"] == alt  # nur als Attribut/Text, nie als HTML
    assert fig["caption"] == alt


def test_image_strip_error_removes_image_and_empties_strip():
    script = f"""
{_STRIP_SUMMARY_JS}
const host = new FakeNode('element', 'div');
const strip = buildImageStrip({json.dumps([_source(1, [
    {"src": _src(1), "alt": "", "page": None}, {"src": _src(2), "alt": "", "page": None}])])});
host.appendChild(strip);
const imgs = findAll(strip, (n) => n.tag === 'img');
imgs[0].listeners.error();
const afterFirst = findAll(strip, (n) => n.tag === 'figure').length;
const stripStillThere = host.children.length;
imgs[1].listeners.error();
console.log(JSON.stringify({{afterFirst, stripStillThere, hostChildren: host.children.length}}));
"""
    assert _run_question_js(script, *_STRIP_FUNCS) == {"afterFirst": 1, "stripStillThere": 1, "hostChildren": 0}


def test_cited_sources_use_real_source_index_not_display_number():
    # Antwort zitiert [2] und [4]; die Buttons zeigen fortlaufend [1] und [2].
    sources = [_source(i, [{"src": _src(i), "alt": "", "page": None}]) for i in range(1, 6)]
    script = f"""
{_STRIP_SUMMARY_JS}
const container = new FakeNode('element', 'div');
const p = document.createElement('p');
container.appendChild(p);
p.appendChild(document.createTextNode('Erst [2] dann [4].'));
const sources = {json.dumps(sources)};
makeCitationsClickable(container, sources);
const cited = extractCitedSources(container, sources);
const strip = buildImageStrip(cited);
console.log(JSON.stringify({{
  cited: cited.map((s) => s.source_id),
  imgs: summarize(strip).figures.map((f) => f.img.src),
}}));
"""
    result = _run_question_js(script, "makeCitationsClickable", "extractCitedSources", *_STRIP_FUNCS)
    assert result == {"cited": ["s2", "s4"], "imgs": [_src(2), _src(4)]}


def test_cited_sources_ignore_duplicate_citations():
    sources = [_source(i, []) for i in range(1, 4)]
    script = f"""
const container = new FakeNode('element', 'div');
const p = document.createElement('p');
container.appendChild(p);
p.appendChild(document.createTextNode('A [3] B [3] C [1] D [9]'));
const sources = {json.dumps(sources)};
makeCitationsClickable(container, sources);
console.log(JSON.stringify(extractCitedSources(container, sources).map((s) => s.source_id)));
"""
    assert _run_question_js(script, "makeCitationsClickable", "extractCitedSources") == ["s3", "s1"]


def test_safe_http_url_accepts_only_http_and_https():
    script = """
console.log(JSON.stringify(['https://a.example/x', 'http://a.example/', 'javascript:alert(1)',
  'data:text/html,x', '/relativ', '', null, undefined].map(safeHttpUrl)));
"""
    assert _run_question_js(script) == [
        "https://a.example/x", "http://a.example/", None, None, None, None, None, None
    ]


def test_append_title_text_does_not_link_javascript_url():
    result = _run_append_title_text({"title": "T", "url": "javascript:alert(1)"})
    assert all(not c["href"] for c in result)
    assert result[0]["value"] == "T"


def test_question_js_uses_safe_http_url_for_every_citation_url():
    js = _question_js_source()
    raw = re.findall(r"=\s*s\.url_reachable === false \? null : s\.listen_url \|\| s\.url;", js)
    assert raw == [], "Quellen-URLs müssen durch safeHttpUrl() laufen."


def _run_refresh(body: str):
    return _run_question_js(
        f"{_STRIP_SUMMARY_JS}\n"
        "function bubbleWith(text) { const b = new FakeNode('element', 'div'); const p = document.createElement('p');"
        " b.appendChild(p); p.appendChild(document.createTextNode(text)); return b; }\n"
        "function strips(b) { return b.querySelectorAll('.source-image-strip'); }\n" + body,
        "makeCitationsClickable", "extractCitedSources", *_STRIP_FUNCS, "refreshImageStrip", "applyDoneImages",
    )


def test_done_event_images_replace_early_images_in_single_strip():
    # sources-Event: Bild am Chunk 1; done-Event: Bild am (zitierten) Chunk 2 derselben Quelle.
    early = [_source(1, [{"src": _src(1), "alt": "", "page": None}]), _source(2, [])]
    done = [_source(1, []), _source(2, [{"src": _src(2), "alt": "", "page": None}])]
    result = _run_refresh(f"""
const early = {json.dumps(early)}; const done = {json.dumps(done)};
const b = bubbleWith('A [1] B [2]');
makeCitationsClickable(b, early);
refreshImageStrip(b, extractCitedSources(b, early));
const before = strips(b).map((s) => summarize(s).figures.map((f) => f.img.src));
applyDoneImages(b, early, done);
applyDoneImages(b, early, done);
console.log(JSON.stringify({{before, after: strips(b).map((s) => summarize(s).figures.map((f) => f.img.src)),
  stored: early.map((s) => s.images.length)}}));
""")
    assert result == {"before": [[_src(1)]], "after": [[_src(2)]], "stored": [0, 1]}


def test_done_event_without_images_removes_strip():
    early = [_source(1, [{"src": _src(1), "alt": "", "page": None}])]
    done = [_source(1, [])]
    result = _run_refresh(f"""
const early = {json.dumps(early)}; const done = {json.dumps(done)};
const b = bubbleWith('A [1]');
makeCitationsClickable(b, early);
refreshImageStrip(b, extractCitedSources(b, early));
applyDoneImages(b, early, done);
console.log(JSON.stringify(strips(b).length));
""")
    assert result == 0


def test_refresh_image_strip_never_creates_two_strips():
    early = [_source(1, [{"src": _src(1), "alt": "", "page": None}])]
    result = _run_refresh(f"""
const early = {json.dumps(early)};
const b = bubbleWith('A [1]');
makeCitationsClickable(b, early);
for (let i = 0; i < 3; i += 1) refreshImageStrip(b, extractCitedSources(b, early));
console.log(JSON.stringify(strips(b).length));
""")
    assert result == 1


def test_ask_error_shows_speaking_message_and_retry_button():
    """Nutzerwunsch (2026-10-25): statt "Error: Failed to fetch" eine
    verständliche Meldung (DE/EN) und ein Button, der dieselbe Frage erneut
    stellt."""
    script = """
const results = [new TypeError('Failed to fetch'), new Error('Zu viele Anfragen'), new Error('')].map((err) => {
  const bubble = document.createElement('div');
  let retried = 0;
  renderAskError(bubble, err, () => { retried += 1; });
  const btn = bubble.querySelectorAll('.retry-button')[0];
  btn.listeners.click();
  return { text: bubble.children[0].textContent, button: btn.textContent, type: btn.type, retried };
});
console.log(JSON.stringify(results));
"""
    assert _run_question_js(script, "askErrorText", "renderAskError") == [
        {"text": "index.askErrorNetwork", "button": "index.retry", "type": "button", "retried": 1},
        {"text": "Zu viele Anfragen", "button": "index.retry", "type": "button", "retried": 1},
        {"text": "index.askFailed", "button": "index.retry", "type": "button", "retried": 1},
    ]


# --- Idee 2070893d: Gesprächsgedächtnis 50 Turns / 200.000 Bytes ---


def _run_node_stdin(script: str):
    # Große Eingaben passen nicht in die Argumentliste (node -e) - Skript per stdin.
    result = subprocess.run(["node", "-"], input=script, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def _run_build_ask_history(turns):
    js = _question_js_source()
    consts = "\n".join(re.findall(r"^const ASK_HISTORY_[A-Z_]+ = [^;]+;$", js, flags=re.M))
    func = re.search(r"^function buildAskHistory\(.*?^}\n", js, flags=re.M | re.S).group(0)
    script = f"{consts}\n{func}\nconsole.log(JSON.stringify(buildAskHistory({json.dumps(turns)})));"
    return _run_node_stdin(script)


def _js_turns(n, size=10):
    return [{"question": f"F{i:03d}" + "q" * size, "answer": f"A{i:03d}" + "a" * size} for i in range(n)]


def _js_sized(n, per_turn_bytes):
    half = per_turn_bytes // 2
    return [
        {"question": f"F{i:03d}".ljust(half, "q"), "answer": f"A{i:03d}".ljust(per_turn_bytes - half, "a")}
        for i in range(n)
    ]


def test_build_ask_history_sends_all_turns_up_to_fifty():
    assert _run_build_ask_history(_js_turns(12)) == _js_turns(12)
    assert _run_build_ask_history(_js_turns(50)) == _js_turns(50)


def test_build_ask_history_block_cut_is_stable_for_51_to_60_and_jumps_at_61():
    firsts = {_run_build_ask_history(_js_turns(n))[0]["question"] for n in range(51, 61)}
    assert len(firsts) == 1
    assert _run_build_ask_history(_js_turns(51)) == _js_turns(51)[10:]
    assert _run_build_ask_history(_js_turns(61)) == _js_turns(61)[20:]


def test_build_ask_history_budget_in_utf8_bytes_with_block_cut():
    turns = _js_sized(50, 4000)  # genau 200.000 Bytes -> alle bleiben
    assert _run_build_ask_history(turns) == turns
    turns[-1]["answer"] += "x"
    assert _run_build_ask_history(turns) == turns[10:]
    umlauts = [{"question": "ä" * 2000, "answer": "ä" * 2000} for _ in range(26)]  # 208.000 Bytes, 104.000 Zeichen
    assert _run_build_ask_history(umlauts) == umlauts[10:]


def test_build_ask_history_truncates_fields_and_drops_blank_turns():
    turns = [{"question": " ", "answer": "A"}, {"question": "q" * 8100, "answer": "a" * 8100}]
    result = _run_build_ask_history(turns)
    assert result == [{"question": "q" * 8000, "answer": "a" * 8000}]


def test_build_ask_history_block_jump_stops_at_last_turn():
    turns = [{"question": "ä" * 8000, "answer": "ä" * 8000}] * 7  # 7 x 32.000 = 224.000 Bytes
    assert len(_run_build_ask_history(turns)) == 1  # Block (10) springt höchstens bis zum letzten Turn


def test_question_js_uses_build_ask_history_in_request_body():
    js = _question_js_source()
    assert "history: buildAskHistory(conversationHistory)," in js
    assert "top_k: 5," in js


def _run_handoff(history, fetch_ok=True):
    js = re.sub(r"^export ", "", (STATIC_DIR / "conversation-handoff.js").read_text(), flags=re.M)
    script = f"""
{js}
let posted = null;
global.fetch = async (url, opts) => {{ posted = JSON.parse(opts.body); return {{ ok: true, json: async () => ({{ token: 't' }}) }}; }};
(async () => {{
  const token = await createConversationHandoffToken({json.dumps(history)}, 'cid');
  console.log(JSON.stringify({{ token, posted }}));
}})();
"""
    return _run_node_stdin(script)


def test_handoff_frontend_trims_oldest_turns_to_max_turns():
    turn = {"question": "F", "answer": "A", "sources": []}
    history = [dict(turn, question=f"F{i}") for i in range(130)]
    result = _run_handoff(history)
    assert result["token"] == "t"
    assert [t["question"] for t in result["posted"]["history"]] == [f"F{i}" for i in range(30, 130)]
    assert result["posted"]["conversation_id"] == "cid"


def test_handoff_frontend_trims_to_below_800kb_with_realistic_sources():
    source = {
        "chunk_id": "c", "source_id": "s", "title": "T", "authors": ["A"], "date": "2021-01-01", "url": "u",
        "listen_url": None, "position": 1, "text": "t" * 3000, "summary": "s" * 300, "summary_ai_generated": True,
        "highlighted_texts": ["h" * 200], "is_web_fallback": False, "allowlist_entry_id": None,
    }
    history = [{"question": f"F{i}", "answer": "A" * 3500, "sources": [source] * 5} for i in range(100)]
    result = _run_handoff(history)
    sent = result["posted"]["history"]
    assert 0 < len(sent) < 100
    assert sent[-1]["question"] == "F99"  # neueste bleiben, älteste fallen weg
    assert len(json.dumps(result["posted"], separators=(",", ":")).encode()) < 800_000
    # eine weitere ältere Runde hätte das Limit gesprengt (Kürzung nicht übertrieben)
    one_more = [history[100 - len(sent) - 1]] + sent
    assert len(json.dumps({"history": one_more, "conversation_id": "cid"}, separators=(",", ":")).encode()) >= 800_000


def test_handoff_frontend_limits_match_backend():
    from app import main as main_module

    js = (STATIC_DIR / "conversation-handoff.js").read_text()
    turns = int(re.search(r"const CONVERSATION_HANDOFF_MAX_TURNS = ([\d_]+);", js).group(1).replace("_", ""))
    max_bytes = int(re.search(r"const CONVERSATION_HANDOFF_MAX_BYTES = ([\d_]+);", js).group(1).replace("_", ""))
    assert turns == main_module.CONVERSATION_HANDOFF_MAX_TURNS
    assert max_bytes == 800_000 < main_module.CONVERSATION_HANDOFF_MAX_BYTES


@pytest.mark.parametrize("name", ["index.html", "embed.html"])
def test_question_textarea_has_maxlength_8000(name):
    html = (STATIC_DIR / name).read_text()
    tag = re.search(r'<textarea id="question"[^>]*>', html).group(0)
    assert 'maxlength="8000"' in tag


def test_question_js_truncates_question_and_handles_list_detail():
    js = _question_js_source()
    # Sprachdiktat setzt value per Code (maxlength greift nicht)
    assert re.search(r"const question = questionInput\.value\.trim\(\)\.slice\(0, ASK_QUESTION_MAX_CHARS\);", js)
    assert re.search(r"const ASK_QUESTION_MAX_CHARS = 8000;", js)
    # 422 liefert detail als Liste -> allgemeine Fehlermeldung statt [object Object]
    assert "typeof err.detail === 'string' ? err.detail : t('index.askFailed')" in js
    assert "throw new Error(err.detail || t('index.askError'))" not in js


# ---------------------------------------------------------------------------
# Idee 134c868a: Quellen-Sprache (static/source-lang.js) - englischer Titel,
# Google-Translate-Link, Ausblenden nicht übersetzbarer Quellen in der EN-UI
# ---------------------------------------------------------------------------

_DE_URL = "https://beispiel.org/artikel?x=1&y=2"
_TRANSLATE = "https://translate.google.com/translate?sl=de&tl=en&u="


def _lang_src(**kw):
    base = {"source_id": "s1", "chunk_id": "c1", "title": "Originaltitel", "url": _DE_URL,
            "text_lang": "de", "title_en": "English title"}
    base.update(kw)
    return base


def _run_lang(lang: str, expr: str):
    """Wertet einen JS-Ausdruck gegen das echte source-lang.js aus (UI-Sprache `lang`)."""
    body = f"globalThis.__UI_LANG = {json.dumps(lang)};\nconsole.log(JSON.stringify({expr}));"
    return _run_question_js(body)


def test_source_lang_display_title_uses_english_title_for_foreign_text_in_en_ui():
    assert _run_lang("en", f"displayTitle({json.dumps(_lang_src())})") == "English title"


@pytest.mark.parametrize(
    "lang, src",
    [
        ("de", _lang_src()),  # DE-UI: Original
        ("en", _lang_src(text_lang="en")),  # englische Quelle
        ("en", _lang_src(title_en=None)),  # kein englischer Titel
        ("en", _lang_src(text_lang=None)),  # nicht klassifiziert
        ("en", _lang_src(text_lang="de&u=evil")),  # ungültiger Code
        ("en", {"title": "Originaltitel", "url": None, "is_web_fallback": True}),  # Web-Fallback
    ],
)
def test_source_lang_display_title_keeps_original(lang, src):
    assert _run_lang(lang, f"displayTitle({json.dumps(src)})") == "Originaltitel"


def test_source_lang_display_title_follows_runtime_language_switch():
    body = f"""
const s = {json.dumps(_lang_src())};
const out = [];
globalThis.__UI_LANG = 'de'; out.push(displayTitle(s));
globalThis.__UI_LANG = 'en'; out.push(displayTitle(s));
globalThis.__UI_LANG = 'de'; out.push(displayTitle(s));
console.log(JSON.stringify(out));
"""
    assert _run_question_js(body) == ["Originaltitel", "English title", "Originaltitel"]


def test_source_lang_citation_href_translates_with_encoded_url():
    href = _run_lang("en", f"citationHref({json.dumps(_lang_src())})")
    assert href == _TRANSLATE + "https%3A%2F%2Fbeispiel.org%2Fartikel%3Fx%3D1%26y%3D2"


def test_source_lang_citation_href_translates_even_without_english_title():
    href = _run_lang("en", f"citationHref({json.dumps(_lang_src(title_en=None))})")
    assert href.startswith(_TRANSLATE)


def test_source_lang_citation_href_uses_source_language_code():
    href = _run_lang("en", f"citationHref({json.dumps(_lang_src(text_lang='fr'))})")
    assert href.startswith("https://translate.google.com/translate?sl=fr&tl=en&u=")


@pytest.mark.parametrize(
    "lang, src, expected",
    [
        ("de", _lang_src(), _DE_URL),  # DE-UI: Original-URL
        ("en", _lang_src(text_lang="en"), _DE_URL),
        ("en", _lang_src(text_lang=None), _DE_URL),
        ("en", _lang_src(text_lang="de&u=evil"), _DE_URL),
        ("en", _lang_src(url="https://beispiel.org/a.pdf"), "https://beispiel.org/a.pdf"),
        ("en", _lang_src(url="https://beispiel.org/a.PDF?download=1"), "https://beispiel.org/a.PDF?download=1"),
        ("en", _lang_src(url="https://beispiel.org/a.mp3"), "https://beispiel.org/a.mp3"),
        ("en", _lang_src(url="https://beispiel.org/a.mp4"), "https://beispiel.org/a.mp4"),
        ("en", _lang_src(url="https://www.youtube.com/watch?v=abc"), "https://www.youtube.com/watch?v=abc"),
        ("en", _lang_src(url="https://youtu.be/abc"), "https://youtu.be/abc"),
        ("en", _lang_src(url="https://www.linkedin.com/posts/x"), "https://www.linkedin.com/posts/x"),
        ("en", _lang_src(url="https://feed.podigee.io/x"), "https://feed.podigee.io/x"),
        ("en", _lang_src(restricted=True), _DE_URL),
        ("en", _lang_src(listen_url="https://beispiel.org/audio"), "https://beispiel.org/audio"),
        ("en", _lang_src(url_reachable=False), None),
        ("en", _lang_src(url="javascript:alert(1)"), None),
        ("en", _lang_src(url=None), None),
    ],
)
def test_source_lang_citation_href_no_translate_link(lang, src, expected):
    href = _run_lang(lang, f"citationHref({json.dumps(src)})")
    assert href == expected


@pytest.mark.parametrize(
    "lang, src, hidden",
    [
        ("en", _lang_src(url="https://beispiel.org/a.pdf"), True),  # de-PDF
        ("en", _lang_src(url="https://beispiel.org/a.mp3"), True),
        ("en", _lang_src(url="https://www.youtube.com/watch?v=abc"), True),
        ("en", _lang_src(restricted=True), True),
        ("en", _lang_src(listen_url="https://beispiel.org/audio"), True),
        ("en", _lang_src(url_reachable=False), True),
        ("en", _lang_src(url=None), True),
        ("en", _lang_src(), False),  # de-HTML: sichtbar mit Translate-Link
        ("en", _lang_src(text_lang="en", url="https://beispiel.org/a.pdf"), False),  # en-PDF
        ("en", _lang_src(text_lang=None, url="https://beispiel.org/a.pdf"), False),  # unklassifiziert
        ("en", _lang_src(text_lang="de&u=evil", url="https://beispiel.org/a.pdf"), False),
        ("de", _lang_src(url="https://beispiel.org/a.pdf"), False),  # DE-UI
        ("en", {"title": "W", "url": "https://w.example/x", "is_web_fallback": True}, False),
    ],
)
def test_source_lang_is_hidden_for_lang(lang, src, hidden):
    assert _run_lang(lang, f"isHiddenForLang({json.dumps(src)})") is hidden


def test_source_lang_translated_badge_only_for_foreign_text_in_en_ui():
    def badge(lang, src):
        return _run_lang(
            lang,
            f"(() => {{ const b = translatedBadge({json.dumps(src)}); "
            "return b && {cls: b.className, text: b.textContent, title: b.title}; })()",
        )

    shown = badge("en", _lang_src())
    assert shown == {
        "cls": "source-translated-badge",
        "text": "common.translatedBadge",
        "title": "common.translatedBadgeTooltip",
    }
    assert badge("de", _lang_src()) is None
    assert badge("en", _lang_src(text_lang="en")) is None
    assert badge("en", _lang_src(text_lang=None)) is None


def test_source_lang_translated_link_has_machine_translation_label():
    label = lambda s, lang="en": _run_lang(lang, f"citationLinkLabel({json.dumps(s)})")  # noqa: E731
    assert label(_lang_src()) == "common.machineTranslatedLink"
    assert label(_lang_src(), "de") == "common.openSource"
    assert label(_lang_src(url="https://beispiel.org/a.pdf")) == "common.openSource"


def _marker_texts(text, sources, lang="en"):
    body = f"""
globalThis.__UI_LANG = {json.dumps(lang)};
const container = new FakeNode('element', 'div');
const p = document.createElement('p');
container.appendChild(p);
p.appendChild(document.createTextNode({json.dumps(text)}));
const sources = {json.dumps(sources)};
makeCitationsClickable(container, sources);
function walk(n, acc) {{
  if (n.tag === 'button') acc.buttons.push(n.textContent);
  else if (n.nodeType === 'text') acc.text.push(n.textContent);
  n.children.forEach((c) => walk(c, acc));
  return acc;
}}
const acc = walk(container, {{ buttons: [], text: [] }});
console.log(JSON.stringify({{
  buttons: acc.buttons,
  text: acc.text.join(''),
  cited: extractCitedSources(container, sources).map((s) => s.source_id),
}}));
"""
    return _run_question_js(body, "makeCitationsClickable", "extractCitedSources")


_HIDDEN = _lang_src(source_id="hid", chunk_id="ch", url="https://beispiel.org/a.pdf")
_VISIBLE = _lang_src(source_id="vis", chunk_id="cv")
_ENGLISH = _lang_src(source_id="eng", chunk_id="ce", text_lang="en", title_en=None, url="https://beispiel.org/e.pdf")


def test_hidden_source_marker_removed_in_en_ui():
    r = _marker_texts("Das stimmt [1]. Und das auch.", [_HIDDEN])
    assert r["buttons"] == []
    assert r["text"] == "Das stimmt. Und das auch."
    assert r["cited"] == []


def test_hidden_source_marker_kept_in_de_ui():
    r = _marker_texts("Das stimmt [1].", [_HIDDEN], lang="de")
    assert r["buttons"] == ["[1]"]
    assert r["cited"] == ["hid"]


def test_hidden_source_marker_removed_numbers_stay_gapless():
    r = _marker_texts("A [1] B [2] C [3] D [2]", [_VISIBLE, _HIDDEN, _ENGLISH])
    assert r["buttons"] == ["[1]", "[2]"]  # [2] (versteckt) entfällt, [3] wird zu [2]
    assert r["text"] == "A  B C  D"  # " [2]" samt Leerraum entfernt
    assert r["cited"] == ["vis", "eng"]


def test_hidden_source_multi_markers_leave_no_remainder():
    r = _marker_texts("Satz [1][2] und Satz [2][1].", [_HIDDEN, _VISIBLE])
    assert r["buttons"] == ["[1]", "[2]"]
    assert r["text"] == "Satz  und Satz ."
    r = _marker_texts("Nur versteckt [1][1].", [_HIDDEN])
    assert r["buttons"] == [] and r["text"] == "Nur versteckt."


def test_hidden_source_comma_marker_group_handled():
    r = _marker_texts("Beleg [1, 2] hier", [_HIDDEN, _VISIBLE])
    assert r["buttons"] == ["[1]"] and r["text"] == "Beleg  hier"
    r = _marker_texts("Beleg [1, 2] hier", [_HIDDEN, _HIDDEN])
    assert r["buttons"] == [] and r["text"] == "Beleg hier"


def test_hidden_source_all_hidden_keeps_answer_text_and_no_cited_sources():
    r = _marker_texts("Antwort [1] mit [2] Belegen.", [_HIDDEN, _HIDDEN])
    assert r["text"] == "Antwort mit Belegen."
    assert r["buttons"] == [] and r["cited"] == []


def test_visible_translatable_source_stays_citable_in_en_ui():
    r = _marker_texts("Beleg [1].", [_VISIBLE])
    assert r["buttons"] == ["[1]"] and r["cited"] == ["vis"]
    assert _marker_texts("Beleg [1].", [_ENGLISH])["buttons"] == ["[1]"]
    unclassified = _lang_src(source_id="u", text_lang=None, url="https://beispiel.org/a.pdf")
    assert _marker_texts("Beleg [1].", [unclassified])["buttons"] == ["[1]"]


def test_hidden_source_dropped_from_image_strip_via_cited_sources():
    sources = [
        {**_HIDDEN, "images": [{"src": _src(1), "alt": "", "page": None}]},
        {**_VISIBLE, "images": [{"src": _src(2), "alt": "", "page": None}]},
    ]
    script = f"""
{_STRIP_SUMMARY_JS}
globalThis.__UI_LANG = 'en';
const container = new FakeNode('element', 'div');
const p = document.createElement('p');
container.appendChild(p);
p.appendChild(document.createTextNode('A [1] B [2]'));
const sources = {json.dumps(sources)};
makeCitationsClickable(container, sources);
const strip = buildImageStrip(extractCitedSources(container, sources));
console.log(JSON.stringify(summarize(strip).figures.map((f) => [f.img.src, f.caption, f.links[0].href])));
"""
    result = _run_question_js(script, "makeCitationsClickable", "extractCitedSources", *_STRIP_FUNCS)
    assert result == [[_src(2), "English title", _TRANSLATE + "https%3A%2F%2Fbeispiel.org%2Fartikel%3Fx%3D1%26y%3D2"]]


def test_creative_source_label_uses_english_title_for_foreign_text_in_en_ui():
    js_source = (STATIC_DIR / "creative.js").read_text()
    match = re.search(r"export function creativeSourceLabel.*?\n\}", js_source, re.S)
    assert match
    func = match.group(0).replace("export function", "function")
    script = (
        "function t(k) { return k; }\n"
        + _source_lang_js()
        + "\n"
        + func
        + f"\nconst s = {json.dumps(_lang_src(authors=['A. Autor']))};\n"
        "globalThis.__UI_LANG = 'en'; const en = creativeSourceLabel(s);\n"
        "globalThis.__UI_LANG = 'de'; const de = creativeSourceLabel(s);\n"
        "console.log(JSON.stringify([en, de]));"
    )
    assert _run_node(script) == ["English title — A. Autor", "Originaltitel — A. Autor"]


def test_creative_js_imports_source_lang_module_instead_of_question_js():
    js = (STATIC_DIR / "creative.js").read_text()
    assert "from '/source-lang.js'" in js
    assert "question.js" not in js.split("\n\n")[0]
    assert "isHiddenForLang" in js


def test_question_js_filters_hidden_sources_and_rerenders_on_language_change():
    js = _question_js_source()
    assert "from '/source-lang.js'" in js
    # Sprachwechsel baut Antworten neu auf (ausgeblendete erscheinen bei DE wieder).
    assert "rerenderConversation" in js.split("document.addEventListener('i18n:changed'")[1]


def test_import_js_source_list_uses_display_title_and_badge():
    js = _import_js_source()
    assert "displayTitle" in js and "translatedBadge" in js


# ---------------------------------------------------------------------------
# Idee 134c868a (H4/H6): Formularfelder Textsprache / englischer Titel
# ---------------------------------------------------------------------------


def _run_edit_lang(expr: str):
    return _run_import_js_functions(
        [
            r"function languageSelectCodes.*?\n\}",
            r"function isTitleEnVisible.*?\n\}",
            r"function aiLangFlags.*?\n\}",
            r"function changedLangFields.*?\n\}",
        ],
        expr,
    )


def test_language_select_offers_de_en_and_keeps_other_existing_code():
    assert _run_edit_lang("languageSelectCodes(null)") == ["de", "en"]
    assert _run_edit_lang("languageSelectCodes('fr')") == ["de", "en", "fr"]
    assert _run_edit_lang("languageSelectCodes('de')") == ["de", "en"]
    assert _run_edit_lang("languageSelectCodes('xx&u=1')") == ["de", "en"]


def test_english_title_field_hidden_for_english_or_unknown_text_language():
    assert _run_edit_lang("[isTitleEnVisible('de'), isTitleEnVisible('fr')]") == [True, True]
    assert _run_edit_lang("[isTitleEnVisible('en'), isTitleEnVisible(''), isTitleEnVisible(null)]") == [
        False, False, False,
    ]


def test_ai_icon_only_while_value_present_and_not_hand_edited():
    flags = lambda s: _run_edit_lang(f"aiLangFlags({json.dumps(s)})")  # noqa: E731
    assert flags({"text_lang": "de", "title_en": "T", "text_lang_ai_generated": True,
                  "title_en_ai_generated": True}) == {"textLang": True, "titleEn": True}
    # Felder fehlen (alte Daten) -> wie Zusammenfassung: Standard KI
    assert flags({"text_lang": "de", "title_en": "T"}) == {"textLang": True, "titleEn": True}
    assert flags({"text_lang": "de", "title_en": "T", "text_lang_ai_generated": False,
                  "title_en_ai_generated": False}) == {"textLang": False, "titleEn": False}
    # kein Wert -> kein Icon
    assert flags({"text_lang": None, "title_en": None}) == {"textLang": False, "titleEn": False}


def test_only_changed_language_fields_are_sent_on_save():
    changed = lambda s, lang, title: _run_edit_lang(  # noqa: E731
        f"changedLangFields({json.dumps(s)}, {json.dumps(lang)}, {json.dumps(title)})"
    )
    src = {"text_lang": "de", "title_en": "Old"}
    assert changed(src, "de", "Old") == {}
    assert changed(src, "de", "New") == {"title_en": "New"}
    assert changed(src, "fr", "Old") == {"text_lang": "fr"}
    assert changed({"text_lang": None, "title_en": None}, "", "") == {}
    # Titel bei englischer Sprache unsichtbar: nicht senden
    assert changed(src, "en", "Old changed") == {"text_lang": "en"}


def test_edit_form_wires_language_fields_to_detect_endpoint_and_put():
    js = (STATIC_DIR / "source-edit.js").read_text()
    assert "/detect-language" in js
    assert "changedLangFields(" in js.split("method: 'PUT'")[1]
    assert "addMagicButton(textLangSelect" in js and "addMagicButton(titleEnInput" in js


# ---------------------------------------------------------------------------
# Idee 134c868a: Nachbesserungen aus dem Fehler-Check
# ---------------------------------------------------------------------------


def test_on_saved_updates_language_fields_of_cited_source():
    js = _question_js_source()
    block = js.split("onSaved: (updated) => {")[1].split("dialog.close();")[0]
    for key in ("text_lang", "title_en", "restricted", "text_lang_ai_generated", "title_en_ai_generated"):
        assert f"{key}: updated.{key}" in block, key


def test_detected_language_becomes_new_baseline_so_put_does_not_send_it():
    # Der Endpunkt speichert den KI-Vorschlag selbst (KI-Status bleibt):
    # der PUT darf ihn nicht als Handänderung schicken.
    src = {"text_lang": None, "title_en": None}
    detected = {"text_lang": "de", "title_en": "Neuer Titel"}
    changed = _run_import_js_functions(
        [
            r"function applyDetectedLang.*?\n\}",
            r"function isTitleEnVisible.*?\n\}",
            r"function changedLangFields.*?\n\}",
        ],
        f"changedLangFields(applyDetectedLang({json.dumps(src)}, {json.dumps(detected)}), 'de', 'Neuer Titel')",
    )
    assert changed == {}
    edited = _run_import_js_functions(
        [
            r"function applyDetectedLang.*?\n\}",
            r"function isTitleEnVisible.*?\n\}",
            r"function changedLangFields.*?\n\}",
        ],
        f"changedLangFields(applyDetectedLang({json.dumps(src)}, {json.dumps(detected)}), 'de', 'Von Hand')",
    )
    assert edited == {"title_en": "Von Hand"}


def test_edit_form_keeps_ai_icon_after_magic_wand():
    js = (STATIC_DIR / "source-edit.js").read_text()
    body = js.split("const triggerDetectLanguage")[1].split("langMagicButtons.push(addMagicButton")[0]
    assert "applyDetectedLang(" in body
    assert "icon.classList.add('hidden')" not in body


def test_import_search_and_sort_use_display_title_in_en_ui():
    src = _lang_src(id="1", title="Zebra", title_en="Apple")
    other = _lang_src(id="2", title="Mango", title_en="Mango en", source_id="2")
    sort_js = re.search(r"function sortSources.*?\n\}", _import_js_source(), re.S).group(0)
    search_js = re.search(r"function sourceMatchesSearch.*?\n\}", _import_js_source(), re.S).group(0)
    norm_js = re.search(r"function normalizeSearch.*?\n\}", _import_js_source(), re.S).group(0)
    script = f"""
function t(k) {{ return k; }}
function getSurname(n) {{ return n; }}
const currentSortMode = 'date';
function isFilterActive() {{ return false; }}
{_source_lang_js()}
{norm_js}
{search_js}
{sort_js}
const list = {json.dumps([src, other])};
globalThis.__UI_LANG = 'en';
const en = sortSources(list).map((s) => s.id);
const hit = sourceMatchesSearch(list[0], 'apple');
globalThis.__UI_LANG = 'de';
const de = sortSources(list).map((s) => s.id);
const missDe = sourceMatchesSearch(list[0], 'apple');
console.log(JSON.stringify({{ en, de, hit, missDe }}));
"""
    assert _run_node(script) == {"en": ["1", "2"], "de": ["2", "1"], "hit": True, "missDe": False}


def test_translated_badge_tooltip_mentions_link_only_with_translate_link():
    def tip(src):
        return _run_lang("en", f"translatedBadge({json.dumps(src)}).title")

    assert tip(_lang_src()) == "common.translatedBadgeTooltip"
    assert tip(_lang_src(url="https://beispiel.org/a.pdf")) == "common.translatedTitleTooltip"
    assert tip(_lang_src(restricted=True)) == "common.translatedTitleTooltip"


@pytest.mark.parametrize(
    "text, sources, expected",
    [
        ("Aussage (siehe [1]) hier.", [_HIDDEN], "Aussage hier."),
        ("Aussage (vgl. [1][2]) hier.", [_HIDDEN, _HIDDEN], "Aussage hier."),
        ("Ein foo() bleibt [1].", [_HIDDEN], "Ein foo() bleibt."),
        ("Alt () bleibt auch.", [_HIDDEN], "Alt () bleibt auch."),
    ],
)
def test_hidden_marker_parenthesis_cleanup_only_around_marker(text, sources, expected):
    assert _marker_texts(text, sources)["text"] == expected


def test_hidden_marker_parenthesis_keeps_visible_marker():
    r = _marker_texts("Aussage (siehe [1][2]) hier.", [_HIDDEN, _VISIBLE])
    assert r["buttons"] == ["[1]"]
    assert r["text"] == "Aussage (siehe ) hier."  # Button [1] steht zwischen den Textteilen


def test_language_change_rerender_keeps_bubble_controls_and_running_answer_sources():
    js = _question_js_source()
    body = js.split("function rerenderConversation()")[1].split("\n}\n")[0]
    assert "replaceChildren" not in body.split("renderSidebarSources")[0].replace("conversationCitedSources", "")
    assert "renderAnswerBubble(" not in body  # Bubble nicht komplett neu bauen
    assert "conversationCitedSources.clear()" not in body  # laufende Antwort behält Quellen


# Idee 134c868a (Live-Test v0.91.0): die hidden="until-found"-Platzhalter der
# Quellenliste machen Cmd/Strg+F über noch nicht gerenderte Quellen möglich.
# In der EN-UI muss dort der sichtbare englische Titel stehen (sonst findet
# die Browser-Suche ihn nicht), der Originaltitel bleibt zusätzlich findbar.
@pytest.mark.parametrize(
    "lang, src, expected",
    [
        ("en", _lang_src(), "English title Originaltitel"),
        ("de", _lang_src(), "Originaltitel"),
        ("en", _lang_src(text_lang="en"), "Originaltitel"),
    ],
)
def test_source_lang_findable_title_contains_visible_and_original_title(lang, src, expected):
    assert _run_lang(lang, f"findableTitle({json.dumps(src)})") == expected


def test_import_js_until_found_placeholder_uses_findable_title():
    js_source = _import_js_source()
    assert "placeholder.textContent = `${findableTitle(s)} " in js_source


def test_render_markdown_rejects_protocol_relative_link_target():
    html = _run_render_markdown("[x](//fremd.example/pfad)")
    assert "<a " not in html
    assert '<a href="/creative.html?instruction=a">k</a>' in _run_render_markdown("[k](/creative.html?instruction=a)")


def test_dev_vergleich_js_guards():
    js = (Path(__file__).resolve().parent.parent / "app" / "dev_vergleich" / "vergleich.js").read_text()
    html = (Path(__file__).resolve().parent.parent / "app" / "dev_vergleich" / "vergleich.html").read_text()
    assert "sonnetEl.disabled" in js  # Kästchen nach Runde 1 gesperrt, Reset gibt frei
    assert "slice(0, 8000)" in js  # Antwort im Verlauf wie static/question.js
    assert "'X-Lang'" in js and 'id="vg-lang"' in html
    assert "max_tokens" in js and "stop_reason" in js
    assert "quotes_expected" in js


# Nutzerwunsch (2026-11-15, Idee af02ecb1): Der Modellname ist kein
# Fachbegriff zum Vertiefen. Das Modell setzt ihn trotz Prompt-Regel fett,
# deshalb entfernt renderMarkdown die Hervorhebung.
@pytest.mark.parametrize("name", ["Beta-Kodex", "BetaCodex", "beta-kodex", "Betacodex"])
def test_render_markdown_never_bolds_beta_kodex(name):
    html = _run_render_markdown(f"Der **{name}** kennt **Teamautonomie**.")
    assert html == f"<p>Der {name} kennt <strong>Teamautonomie</strong>.</p>"


def test_render_markdown_keeps_bold_compound_with_beta_kodex():
    html = _run_render_markdown("**Beta-Kodex-Gesetze** gelten.")
    assert html == "<p><strong>Beta-Kodex-Gesetze</strong> gelten.</p>"



# ---------------------------------------------------------------------------
# Idee fe44f080: Inline-Bild per Marker [bild:n.m] (static/question.js)
# ---------------------------------------------------------------------------

_INLINE_FUNCS = (
    "safeImageSrc", "buildImageFigure", "buildImageStrip", "buildImagePlaceholder", "inlineMarkerNodes",
    "removeInlineMarkers", "placeInlineImage", "makeCitationsClickable", "extractCitedSources", "refreshImageStrip",
)

_INLINE_HELPERS_JS = """
function para(...parts) {
  const p = document.createElement('p');
  parts.forEach((part) => p.appendChild(part === 'BR' ? document.createElement('br') : document.createTextNode(part)));
  return p;
}
function bubbleOf(...paras) {
  const b = document.createElement('div');
  paras.forEach((p) => b.appendChild(p));
  return b;
}
function describe(node) {
  return node.children.map((c) => c.nodeType === 'text' ? 'T:' + c.textContent
    : c.tag === 'br' ? 'BR'
    : c.tag === 'p' ? 'P:' + c.children.map((x) => x.nodeType === 'text' ? x.textContent : x.tag).join('|')
    : c.tag + '.' + c.className);
}
function all(node, pred, acc = []) {
  node.children.forEach((c) => { if (pred(c)) acc.push(c); all(c, pred, acc); });
  return acc;
}
"""


def _run_inline(body: str, lang="de"):
    return _run_question_js(
        f"globalThis.__UI_LANG = {json.dumps(lang)};\n{_INLINE_HELPERS_JS}\n{body}", *_INLINE_FUNCS
    )


def _img_source(i=1, n_images=1, **extra):
    return _source(i, [{"src": _src(k), "alt": f"Alt {k}", "page": None} for k in range(1, n_images + 1)], **extra)


def test_inline_valid_marker_places_one_figure_after_its_paragraph():
    result = _run_inline(f"""
const sources = {json.dumps([_img_source(1), _img_source(2, 2)])};
const b = bubbleOf(para('Erster Absatz [2].'), para('[bild:2.2]'), para('Dritter.'));
placeInlineImage(b, sources);
const fig = all(b, (n) => n.tag === 'figure')[0];
console.log(JSON.stringify({{
  order: describe(b),
  src: all(fig, (n) => n.tag === 'img')[0].src,
  alt: all(fig, (n) => n.tag === 'img')[0].alt,
  caption: all(fig, (n) => n.tag === 'figcaption')[0].textContent,
  href: all(fig, (n) => n.tag === 'a')[0].href,
  dataSrc: fig.dataset.src,
  text: b.textContent,
}}));
""")
    assert result["order"] == ["P:Erster Absatz [2].", "figure.inline-source-image is-loading", "P:Dritter."]
    assert result["src"] == _src(2) and result["alt"] == "Alt 2" and result["dataSrc"] == _src(2)
    assert result["caption"] == "Titel 2" and result["href"] == "https://example.org/2"
    assert "[bild:" not in result["text"]


def test_inline_figure_links_pdf_page():
    src = _source(1, [{"src": _src(1), "alt": "", "page": 4}], url="https://example.org/buch.pdf")
    result = _run_inline(f"""
const b = bubbleOf(para('A [1].'), para('[bild:1.1]'));
placeInlineImage(b, {json.dumps([src])});
const fig = all(b, (n) => n.tag === 'figure')[0];
console.log(JSON.stringify({{href: all(fig, (n) => n.tag === 'a')[0].href, caption: all(fig, (n) => n.tag === 'figcaption')[0].textContent}}));
""")
    assert result == {"href": "https://example.org/buch.pdf#page=4", "caption": "Titel 1 · S. 4"}


def test_inline_marker_in_bullet_list_paragraph_puts_figure_behind_paragraph_without_stray_br():
    result = _run_inline(f"""
const b = bubbleOf(para('\\u2022 Eins [1]', 'BR', '[bild:1.1]', 'BR', '\\u2022 Zwei'));
placeInlineImage(b, {json.dumps([_img_source(1)])});
console.log(JSON.stringify(describe(b)));
""")
    assert result == ["P:• Eins [1]|br|• Zwei", "figure.inline-source-image is-loading"]


def test_inline_marker_as_last_line_removes_preceding_br():
    result = _run_inline(f"""
const b = bubbleOf(para('Text [1].', 'BR', '[bild:1.1]'));
placeInlineImage(b, {json.dumps([_img_source(1)])});
console.log(JSON.stringify(describe(b)));
""")
    assert result == ["P:Text [1].", "figure.inline-source-image is-loading"]


@pytest.mark.parametrize(
    "marker, source",
    [
        ("[bild:9.1]", _img_source(1)),  # unbekannte Quelle
        ("[bild:1.5]", _img_source(1)),  # unbekanntes Bild
        ("[bild:1.1]", _source(1, [{"src": "javascript:alert(1)", "alt": "", "page": None}])),  # unsichere src
        ("[bild:1.1]", _source(1, [])),  # Quelle ohne Bilder
    ],
)
def test_inline_unknown_marker_or_unsafe_src_gives_no_figure_and_no_visible_marker(marker, source):
    result = _run_inline(f"""
const b = bubbleOf(para('A [1].'), para({json.dumps(marker)}), para('B.'));
placeInlineImage(b, {json.dumps([source])});
console.log(JSON.stringify({{order: describe(b), figures: all(b, (n) => n.tag === 'figure').length}}));
""")
    assert result == {"order": ["P:A [1].", "P:B."], "figures": 0}


def test_inline_hidden_source_gives_no_figure():
    source = _img_source(1, text_lang="de")  # EN-UI, fremdsprachig, ohne Übersetzungslink
    source["url"] = None
    result = _run_inline(
        f"""
const b = bubbleOf(para('A [1].'), para('[bild:1.1]'));
placeInlineImage(b, {json.dumps([source])});
console.log(JSON.stringify({{order: describe(b), figures: all(b, (n) => n.tag === 'figure').length}}));
""",
        lang="en",
    )
    assert result == {"order": ["P:A [1]."], "figures": 0}


def test_inline_only_first_marker_is_placed_all_others_removed():
    result = _run_inline(f"""
const b = bubbleOf(para('A [1].'), para('[bild:1.2]'), para('B [1] [bild:1.1] weiter.'));
placeInlineImage(b, {json.dumps([_img_source(1, 2)])});
const imgs = all(b, (n) => n.tag === 'img').map((i) => i.src);
console.log(JSON.stringify({{imgs, text: b.textContent}}));
""")
    assert result["imgs"] == [_src(2)]
    assert "[bild:" not in result["text"] and "B [1]  weiter." in result["text"]


def test_inline_alt_and_title_with_markup_stay_plain_text():
    alt = '"><img src=x onerror=alert(1)>'
    source = _source(1, [{"src": _src(1), "alt": alt, "page": None}], title="<b>T</b>")
    result = _run_inline(f"""
const b = bubbleOf(para('A [1].'), para('[bild:1.1]'));
placeInlineImage(b, {json.dumps([source])});
const fig = all(b, (n) => n.tag === 'figure')[0];
const img = all(fig, (n) => n.tag === 'img')[0];
console.log(JSON.stringify({{alt: img.alt, rp: img.referrerPolicy, caption: all(fig, (n) => n.tag === 'figcaption')[0].textContent,
  imgs: all(b, (n) => n.tag === 'img').length}}));
""")
    assert result == {"alt": alt, "rp": "no-referrer", "caption": "<b>T</b>", "imgs": 1}


def test_inline_placeholder_replaces_marker_then_figure_replaces_placeholder_at_same_place():
    result = _run_inline(f"""
const sources = {json.dumps([_img_source(1)])};
const live = bubbleOf(para('A [1].'), para('[bild:1.1]'), para('B.'));
placeInlineImage(live, null);
const ph = all(live, (n) => n.className.includes('inline-source-image'))[0];
const placeholder = {{order: describe(live), aria: ph.attrs['aria-hidden'], tag: ph.tag, text: live.textContent}};
const done = bubbleOf(para('A [1].'), para('[bild:1.1]'), para('B.'));
done.appendChild(ph);  // Platzhalter vom Live-Stand noch im DOM
placeInlineImage(done, sources);
console.log(JSON.stringify({{placeholder, done: describe(done), inline: all(done, (n) => n.className.includes('inline-source-image')).length}}));
""")
    assert result["placeholder"] == {
        "order": ["P:A [1].", "div.inline-source-image is-loading", "P:B."], "aria": "true", "tag": "div", "text": "A [1].B.",
    }
    assert result["done"] == ["P:A [1].", "figure.inline-source-image is-loading", "P:B."]
    assert result["inline"] == 1


def test_inline_figure_loses_loading_state_on_load_and_is_removed_on_error():
    result = _run_inline(f"""
const sources = {json.dumps([_img_source(1)])};
const mk = () => {{ const b = bubbleOf(para('A [1].'), para('[bild:1.1]')); placeInlineImage(b, sources); return b; }};
const ok = mk();
const okFig = all(ok, (n) => n.tag === 'figure')[0];
const before = okFig.className;
all(okFig, (n) => n.tag === 'img')[0].listeners.load();
const bad = mk();
all(bad, (n) => n.tag === 'img')[0].listeners.error();
console.log(JSON.stringify({{before, after: okFig.className, badLeft: all(bad, (n) => n.className.includes('inline-source-image')).length}}));
""")
    assert result == {"before": "inline-source-image is-loading", "after": "inline-source-image", "badLeft": 0}


def test_inline_without_marker_leaves_bubble_untouched():
    result = _run_inline(f"""
const b = bubbleOf(para('A [1].'));
placeInlineImage(b, {json.dumps([_img_source(1)])});
console.log(JSON.stringify(describe(b)));
""")
    assert result == ["P:A [1]."]


def test_strip_leaves_out_inline_image_and_refresh_reads_it_from_the_bubble():
    sources = [_img_source(1, 3)]
    result = _run_inline(f"""
const sources = {json.dumps(sources)};
const b = bubbleOf(para('A [1].'), para('[bild:1.2]'));
placeInlineImage(b, sources);
makeCitationsClickable(b, sources);
refreshImageStrip(b, extractCitedSources(b, sources));
refreshImageStrip(b, extractCitedSources(b, sources));
const strips = b.querySelectorAll('.source-image-strip');
console.log(JSON.stringify({{strips: strips.length, imgs: all(strips[0], (n) => n.tag === 'img').map((i) => i.src)}}));
""")
    assert result == {"strips": 1, "imgs": [_src(1), _src(3)]}


def test_inline_figure_survives_citation_rendering_and_strip_refresh():
    sources = [_img_source(1)]
    result = _run_inline(f"""
const sources = {json.dumps(sources)};
const b = bubbleOf(para('A [1].'), para('[bild:1.1]'));
placeInlineImage(b, sources);
makeCitationsClickable(b, sources);
refreshImageStrip(b, extractCitedSources(b, sources));
console.log(JSON.stringify({{figs: all(b, (n) => n.tag === 'figure').length, strips: b.querySelectorAll('.source-image-strip').length}}));
""")
    assert result == {"figs": 1, "strips": 0}  # einziges Bild steht inline, die Leiste entfällt


@pytest.mark.parametrize("text", ["A [1].\n\n[bild:1.1]\n\nB.", "A [bild:12.3] B"])
def test_speech_strips_image_marker(text):
    assert "bild" not in _run_strip_markdown_for_speech(text)


def test_question_js_wires_inline_image_into_live_view_copy_and_done():
    js = _question_js_source()
    assert "placeInlineImage(assistantBubble, null)" in js  # Skeleton im Live-Stream
    assert re.search(r"placeInlineImage\(bubble, sources\);\s*makeCitationsClickable\(bubble, sources\)", js)
    assert "\\[bild:\\d{1,2}\\.\\d{1,2}\\]" in js.split("function buildCopyAnswerButton")[1].split("startSpeaking")[0]
    done = js.split("function applyDoneImages")[1].split("\n}\n")[0]
    assert "placeInlineImage" not in done


def test_inline_image_css_has_skeleton_shimmer_reduced_motion_and_mobile_rules():
    css = (STATIC_DIR / "style.css").read_text()
    assert ".inline-source-image.is-loading" in css and "aspect-ratio: 16 / 9" in css
    assert "@keyframes inline-image-shimmer" in css
    reduced = css.split("@media (prefers-reduced-motion: reduce)")
    assert any(".inline-source-image" in part.split("}\n}")[0] and "animation: none" in part.split("}\n}")[0] for part in reduced[1:])


def test_inline_marker_with_three_digits_is_not_a_marker():
    result = _run_inline(f"""
const b = bubbleOf(para('A [1].'), para('[bild:123.1]'));
placeInlineImage(b, {json.dumps([_img_source(1)])});
console.log(JSON.stringify(all(b, (n) => n.tag === 'figure').length));
""")
    assert result == 0


# Fix v0.94.1: Ein Inline-Bild unter der Mindestbreite (z. B. 300-px-
# Vorschau) wirkt unscharf. Es verlässt den Text und erscheint in der Leiste.
def _two_image_source():
    return _source(1, [{"src": _src(1), "alt": "", "page": None}, {"src": _src(2), "alt": "", "page": None}])


def _inline_after_load(width):
    return _run_inline(f"""
const sources = {json.dumps([_two_image_source()])};
const b = bubbleOf(para('A [1].'), para('[bild:1.1]'));
placeInlineImage(b, sources);
makeCitationsClickable(b, sources);
refreshImageStrip(b, extractCitedSources(b, sources), sources);
const img = all(b, (n) => n.tag === 'img' && n.parentNode && all(b, (x) => x.className && x.className.includes('inline-source-image'))[0]
  && all(all(b, (x) => x.className && x.className.includes('inline-source-image'))[0], (y) => y === n).length)[0];
img.naturalWidth = {width};
img.listeners.load();
const strip = all(b, (n) => n.className === 'source-image-strip')[0];
console.log(JSON.stringify({{
  inline: all(b, (n) => n.className && n.className.includes('inline-source-image')).length,
  strip: strip ? all(strip, (n) => n.tag === 'img').map((i) => i.src) : [],
}}));
""")


def test_inline_image_below_min_width_moves_to_strip():
    assert _inline_after_load(300) == {"inline": 0, "strip": [_src(1), _src(2)]}


def test_inline_image_wide_enough_stays_inline():
    assert _inline_after_load(1200) == {"inline": 1, "strip": [_src(2)]}


# Fix v0.94.1: Die Leiste zeigt nach den zitierten Quellen auch Bilder der
# übrigen gefundenen Quellen (das Inline-Bild darf ja auch von dort kommen).
def test_strip_shows_cited_sources_first_then_other_found_sources():
    sources = [
        _source(1, [{"src": _src(1), "alt": "", "page": None}]),
        _source(2, [{"src": _src(2), "alt": "", "page": None}]),
        _source(3, [{"src": _src(3), "alt": "", "page": None}]),
    ]
    result = _run_inline(f"""
const sources = {json.dumps(sources)};
const b = bubbleOf(para('A [3].'));
makeCitationsClickable(b, sources);
refreshImageStrip(b, extractCitedSources(b, sources), sources);
const strip = all(b, (n) => n.className === 'source-image-strip')[0];
console.log(JSON.stringify(all(strip, (n) => n.tag === 'img').map((i) => i.src)));
""")
    assert result == [_src(3), _src(1), _src(2)]


def test_strip_leaves_out_uncited_sources_hidden_for_ui_language():
    sources = [
        {**_HIDDEN, "images": [{"src": _src(1), "alt": "", "page": None}]},
        {**_VISIBLE, "images": [{"src": _src(2), "alt": "", "page": None}]},
    ]
    result = _run_inline(f"""
const sources = {json.dumps(sources)};
const b = bubbleOf(para('A [2].'));
makeCitationsClickable(b, sources);
refreshImageStrip(b, extractCitedSources(b, sources), sources);
const strip = all(b, (n) => n.className === 'source-image-strip')[0];
console.log(JSON.stringify(all(strip, (n) => n.tag === 'img').map((i) => i.src)));
""", lang="en")
    assert result == [_src(2)]


# --- KI-Hinweis nach Art. 50 KI-Verordnung (Idee 36bb9a6e) ---


@pytest.mark.parametrize(
    "filename,form_pattern,textarea_id,notice_id,key",
    [
        ("index.html", r'<form id="question-form".*?</form>', "question", "ai-notice", "index.aiNotice"),
        ("embed.html", r'<form id="question-form".*?</form>', "question", "ai-notice", "index.aiNotice"),
        ("creative.html", r'<div class="creative-submit-row">.*?</div>', "creative-instruction", "creative-ai-notice", "creative.aiNotice"),
    ],
)
def test_ai_notice_below_input_and_linked_for_screen_readers(filename, form_pattern, textarea_id, notice_id, key):
    html = (STATIC_DIR / filename).read_text()
    notice = re.search(rf'<p id="{notice_id}" class="ai-notice" data-i18n="{re.escape(key)}"></p>', html)
    assert notice, f"KI-Hinweis fehlt in {filename}."
    container = re.search(form_pattern, html, re.S)
    assert container and notice.start() > container.end(), f"KI-Hinweis muss in {filename} nach dem Eingabebereich stehen, nicht darin."
    textarea = re.search(rf'<textarea\s+id="{textarea_id}"[^>]*>', html, re.S)
    assert textarea and f'aria-describedby="{notice_id}"' in textarea.group(0)
    for lang in ("de", "en"):
        messages = json.loads((STATIC_DIR / "i18n" / f"{lang}.json").read_text())
        assert messages.get(key, "").strip(), f"{key} fehlt in {lang}.json"


@pytest.mark.parametrize("filename", ["datenschutz.html", "privacy.html"])
def test_privacy_policy_names_ai_act(filename):
    assert "2024/1689" in (STATIC_DIR / filename).read_text()
