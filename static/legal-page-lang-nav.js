// Nutzerwunsch (Livegang-Vorbereitung, 2026-09-10): auf den Rechtstext-
// Seiten (Datenschutz/Impressum, je DE+EN) ist der Inhalt fest in einer
// Sprache geschrieben (echter Fließtext, kein data-i18n) - der
// Sprachumschalter im Header (siehe i18n.js: renderLangSwitcher) würde
// dort sonst nur Tooltips umstellen, während der sichtbare Rechtstext
// unverändert bliebe. Fängt den Klick auf #lang-switcher in der
// Capture-Phase ab (läuft VOR dem eigenen setLang()-Klick-Handler des
// Buttons, siehe stopImmediatePropagation) und navigiert stattdessen zur
// jeweils anderen Sprachfassung derselben Seite. #lang-switcher existiert
// bereits als leeres <span> im statischen HTML - keine Wartezeit auf
// initI18n() nötig, Event-Delegation greift auch für erst später
// hineingerenderte Buttons.
const LEGAL_PAGE_COUNTERPART = {
  '/datenschutz.html': { de: null, en: '/privacy.html' },
  '/privacy.html': { de: '/datenschutz.html', en: null },
  '/impressum.html': { de: null, en: '/legal-notice.html' },
  '/legal-notice.html': { de: '/impressum.html', en: null },
};

const counterpart = LEGAL_PAGE_COUNTERPART[window.location.pathname];
if (counterpart) {
  document.getElementById('lang-switcher')?.addEventListener(
    'click',
    (e) => {
      const btn = e.target.closest('.lang-button');
      if (!btn) return;
      e.stopImmediatePropagation();
      e.preventDefault();
      const target = counterpart[btn.textContent.trim().toLowerCase()];
      if (target) window.location.href = target;
    },
    true
  );
}
