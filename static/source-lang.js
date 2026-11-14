import { getLang, t } from '/i18n.js';

// STUB (rot-Phase): heutiges Verhalten, noch ohne Sprachlogik.
export function safeHttpUrl(value) {
  if (!value) return null;
  try {
    const u = new URL(value);
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : null;
  } catch {
    return null;
  }
}
export function displayTitle(s) {
  return s.title;
}
export function citationHref(s) {
  return safeHttpUrl(s.url_reachable === false ? null : s.listen_url || s.url);
}
export function isHiddenForLang() {
  return false;
}
export function translatedBadge() {
  return null;
}
