import { getLang, t } from '/i18n.js';

// Gemeinsame Quellen-Sprachlogik für question.js (Chat) und creative.js
// (Kreativmodus) - bewusst eigenes Modul: question.js hat Top-Level-Code und
// darf nicht von creative.js importiert werden. Wirkt nur in der EN-UI und
// nur bei Quellen mit erkannter, nicht-englischer Textsprache (text_lang);
// ohne text_lang (noch nicht klassifiziert, Web-Fallback) bleibt alles wie
// bisher.

// Nur http(s)-URLs werden verlinkt (verhindert javascript:-Links aus
// manipulierten Quellendaten, z.B. über den anonymen Handoff).
export function safeHttpUrl(value) {
  if (!value) return null;
  try {
    const u = new URL(value);
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : null;
  } catch {
    return null;
  }
}

const LANG_CODE = /^[a-z]{2,3}$/;
// Google Translate übersetzt nur HTML-Seiten, keine Dateien/Streams/Login-Seiten.
const UNTRANSLATABLE_PATH = /\.(pdf|mp3|m4a|wav|ogg|oga|opus|aac|flac|mp4|m4v|mov|webm|avi|mkv)$/i;
const UNTRANSLATABLE_HOSTS = ['youtube.com', 'youtu.be', 'linkedin.com'];

function isForeignText(s) {
  return getLang() === 'en' && LANG_CODE.test(s.text_lang || '') && s.text_lang !== 'en';
}

// Ziel für die Maschinenübersetzung oder null, wenn die Quelle nicht
// übersetzbar ist (geschützt, Audio-Link, kein http(s), defekter Link, Datei/Video/Login-Seite).
function translateHref(s) {
  if (s.restricted || s.listen_url || s.url_reachable === false) return null;
  const url = safeHttpUrl(s.url);
  if (!url) return null;
  const { hostname, pathname } = new URL(url);
  if (UNTRANSLATABLE_PATH.test(pathname)) return null;
  if (hostname.includes('podigee')) return null;
  if (UNTRANSLATABLE_HOSTS.some((h) => hostname === h || hostname.endsWith(`.${h}`))) return null;
  return `https://translate.google.com/translate?sl=${encodeURIComponent(s.text_lang)}&tl=en&u=${encodeURIComponent(url)}`;
}

export function displayTitle(s) {
  return isForeignText(s) && s.title_en ? s.title_en : s.title;
}

// Link-Ziel einer Quelle: Maschinenübersetzung (nur EN-UI, fremdsprachig,
// übersetzbar), sonst wie bisher listen_url vor url (defekter Link: keiner).
export function citationHref(s) {
  if (isForeignText(s)) {
    const translated = translateHref(s);
    if (translated) return translated;
  }
  return safeHttpUrl(s.url_reachable === false ? null : s.listen_url || s.url);
}

export function citationLinkLabel(s) {
  return isForeignText(s) && translateHref(s) ? t('common.machineTranslatedLink') : t('common.openSource');
}

// EN-UI + fremdsprachig + nicht übersetzbar: Quelle wird nicht angezeigt
// (nur Anzeige, das Backend nutzt sie weiter für die Antwort).
export function isHiddenForLang(s) {
  return isForeignText(s) && !translateHref(s);
}

// Kleines Label "translated" neben übersetzten Titeln (nur EN-UI).
export function translatedBadge(s) {
  if (!isForeignText(s)) return null;
  const badge = document.createElement('span');
  badge.className = 'source-translated-badge';
  badge.textContent = t('common.translatedBadge');
  badge.title = t('common.translatedBadgeTooltip');
  return badge;
}
