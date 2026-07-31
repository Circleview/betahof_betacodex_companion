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
