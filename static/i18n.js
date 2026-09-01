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
    btn.addEventListener('click', async () => {
      if (lang === currentLang) return;
      localStorage.setItem('lang', lang);
      currentLang = lang;
      dict = await loadDict(currentLang);
      applyStaticTranslations();
      renderLangSwitcher();
      document.dispatchEvent(new CustomEvent('i18n:changed'));
    });
    el.appendChild(btn);
  });
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
