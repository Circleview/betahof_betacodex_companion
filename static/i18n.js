const SUPPORTED_LANGS = ['de', 'en'];
const DEFAULT_LANG = 'en';

// Nutzerwunsch (2026-09-01): wechselt man aus dem Embed-Snippet über das
// "Vollständig öffnen"-Icon in den vollständigen Companion (siehe
// question.js: embedExpandButton), soll die dort im Embed gewählte Sprache
// mitgenommen werden, statt dass der neue Tab (eigener, ggf. durch
// Storage-Partitionierung sogar komplett getrennter localStorage/eigene
// navigator.language-basierte Erkennung) erneut selbst rät. Ein ?lang=-
// Parameter hat deshalb Vorrang vor dem gespeicherten/erratenen Stand -
// wird dabei übernommen (persistiert + Query-Parameter entfernt, Muster wie
// conversation-handoff.js:consumeConversationHandoffToken - andere,
// gleichzeitig vorhandene Parameter wie ?handoff= bleiben unangetastet).
function detectLang() {
  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get('lang');
  if (fromUrl && SUPPORTED_LANGS.includes(fromUrl)) {
    localStorage.setItem('lang', fromUrl);
    params.delete('lang');
    const query = params.toString();
    history.replaceState(null, '', window.location.pathname + (query ? `?${query}` : ''));
    return fromUrl;
  }
  const stored = localStorage.getItem('lang');
  if (stored && SUPPORTED_LANGS.includes(stored)) {
    return stored;
  }
  // Nutzerwunsch (Livegang-Vorbereitung, 2026-09-10): das Embed-Widget soll
  // IMMER mit Englisch starten (der Sprachumschalter bleibt bedienbar,
  // siehe renderLangSwitcher) - anders als der übrige Companion NICHT
  // anhand von navigator.language raten, da das Widget auf Drittseiten
  // eingebettet läuft, deren Besucher:innen sprachlich nicht zwangsläufig
  // zur Browser-Spracheinstellung passen.
  if (window.location.pathname === '/embed.html') {
    return DEFAULT_LANG;
  }
  const nav = (navigator.language || navigator.userLanguage || DEFAULT_LANG).toLowerCase();
  return nav.startsWith('de') ? 'de' : DEFAULT_LANG;
}

let currentLang = detectLang();
let dict = {};

async function loadDict(lang) {
  const res = await fetch(`/i18n/${lang}.json`);
  return res.json();
}

export function t(key, vars = {}) {
  let str = dict[key] || key;
  for (const [k, v] of Object.entries(vars)) {
    str = str.replaceAll(`{${k}}`, v);
  }
  return str;
}

export function getLang() {
  return currentLang;
}

function applyStaticTranslations() {
  document.documentElement.lang = currentLang;
  document.querySelectorAll('[data-i18n]').forEach((el) => {
    el.textContent = t(el.getAttribute('data-i18n'));
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
    el.setAttribute('placeholder', t(el.getAttribute('data-i18n-placeholder')));
  });
  document.querySelectorAll('[data-i18n-title]').forEach((el) => {
    const value = t(el.getAttribute('data-i18n-title'));
    el.setAttribute('title', value);
    el.setAttribute('aria-label', value);
  });
}

// Gemeinsame Umschalt-Logik für den Sprachumschalter (Klick) UND die
// automatische Umschaltung anhand der Eingabesprache (siehe
// detectTextLanguage weiter unten, genutzt von question.js/creative.js) -
// beide sollen exakt denselben Zustand aktualisieren (Storage, Wörterbuch,
// sichtbare Übersetzungen, Umschalter-Hervorhebung, i18n:changed-Event).
export async function setLang(lang) {
  if (!SUPPORTED_LANGS.includes(lang) || lang === currentLang) return;
  localStorage.setItem('lang', lang);
  currentLang = lang;
  dict = await loadDict(currentLang);
  applyStaticTranslations();
  renderLangSwitcher();
  document.dispatchEvent(new CustomEvent('i18n:changed'));
}

function renderLangSwitcher() {
  const el = document.getElementById('lang-switcher');
  if (!el) return;
  el.innerHTML = '';
  SUPPORTED_LANGS.forEach((lang, i) => {
    if (i > 0) el.append(' · ');
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'lang-button' + (lang === currentLang ? ' active' : '');
    btn.textContent = lang.toUpperCase();
    btn.addEventListener('click', () => setLang(lang));
    el.appendChild(btn);
  });
}

// Nutzerwunsch (Livegang-Vorbereitung, 2026-09-10): schreibt jemand im
// Konversations- oder Kreativ-Modus in der jeweils anderen Sprache, soll die
// ganze Seite automatisch dorthin umschalten (siehe setLang oben), so als
// hätte die Person den Umschalter selbst benutzt. Rein clientseitige
// Stoppwort-Heuristik statt eines LLM-Aufrufs (kostenlos, sofort verfügbar,
// kein zusätzlicher Server-Roundtrip) - zählt eindeutig sprachtypische
// Funktionswörter (bewusst NUR Wörter, die es nur in einer der beiden
// Sprachen gibt, z.B. nicht "in", das in beiden identisch ist) plus
// deutsche Sonderzeichen (ä/ö/ü/ß, in Englisch nie vorkommend, zählen
// doppelt). Gibt bei einem klaren Mehrheits-Signal die erkannte Sprache
// zurück, sonst null (z.B. bei sehr kurzen/mehrdeutigen Eingaben oder
// reinen Fachbegriffen wie "List Owner") - dann bleibt die aktuelle Sprache
// unangetastet, statt riskant zu raten.
// Fix (2026-09-10, live im Browser gefunden): die ursprüngliche Liste deckte
// nur Fragen ab (wie/was/how/what...) - eine Kreativ-Modus-Anweisung wie
// "Write a short blog post about X" enthält KEINES dieser Wörter (Imperativ,
// keine Frage) und wurde dadurch fälschlich als unentschieden (null)
// gewertet, obwohl sie eindeutig Englisch ist. Ergänzt um unzweideutige
// Imperativ-/Anweisungs-Wörter (schreibe/erstelle/write/create...) sowie
// häufige Artikel/Präpositionen, die es nur in einer der beiden Sprachen so
// gibt (z.B. "a"/"about" nur Englisch, "über"/"zum" nur Deutsch - NICHT "an",
// das es in beiden Sprachen mit unterschiedlicher Bedeutung gibt).
const DE_MARKER_WORDS = new Set([
  'der', 'die', 'das', 'und', 'ist', 'nicht', 'wie', 'was', 'wer', 'warum',
  'wieso', 'weshalb', 'kann', 'kannst', 'könnte', 'welche', 'welcher',
  'welches', 'für', 'mit', 'sich', 'auf', 'sind', 'hat', 'haben', 'wird',
  'werden', 'oder', 'aber', 'wenn', 'wo', 'wann', 'du', 'ich', 'wir', 'ihr',
  'eine', 'einen', 'einem', 'eines', 'dass', 'sollte', 'muss', 'müssen',
  'bitte', 'auch', 'noch', 'schon', 'sehr', 'zwischen', 'über', 'zum', 'zur',
  'im', 'am', 'beim', 'vom', 'kurz', 'kurzen', 'kurze', 'artikel',
  'schreibe', 'erstelle', 'erkläre', 'erzähl', 'mach', 'ergänze', 'füge',
]);
const EN_MARKER_WORDS = new Set([
  'the', 'is', 'and', 'not', 'how', 'what', 'who', 'why', 'can', 'which',
  'for', 'with', 'does', 'do', 'are', 'has', 'have', 'will', 'but', 'if',
  'where', 'when', 'this', 'that', 'you', 'we', 'they', 'should', 'must',
  'could', 'would', 'please', 'also', 'still', 'already', 'very', 'between',
  'a', 'about', 'to', 'of', 'write', 'create', 'make', 'short', 'explain',
  'tell', 'add',
]);
const DE_ONLY_CHARS = /[äöüß]/i;

export function detectTextLanguage(text) {
  const words = (text.toLowerCase().match(/[a-zäöüß]+/g) || []);
  let deScore = DE_ONLY_CHARS.test(text) ? 2 : 0;
  let enScore = 0;
  for (const word of words) {
    if (DE_MARKER_WORDS.has(word)) deScore += 1;
    else if (EN_MARKER_WORDS.has(word)) enScore += 1;
  }
  if (deScore === enScore) return null;
  return deScore > enScore ? 'de' : 'en';
}

let initPromise = null;

// Mehrere unabhängige <script type="module">-Tags (z.B. question.js/import.js
// UND footer.js) rufen initI18n() jeweils selbst auf, um sich nicht auf eine
// bestimmte Ausführungsreihenfolge der Module verlassen zu müssen - ohne
// Memoisierung würde das Wörterbuch mehrfach unnötig neu geladen.
export function initI18n() {
  if (!initPromise) {
    initPromise = (async () => {
      dict = await loadDict(currentLang);
      applyStaticTranslations();
      renderLangSwitcher();
      return dict;
    })();
  }
  return initPromise;
}
