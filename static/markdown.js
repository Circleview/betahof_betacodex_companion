// Bewusst ohne DOM-Umweg (document.createElement) implementiert - dadurch
// bleibt renderMarkdown vollständig DOM-frei und über das Node-Testmuster
// testbar (siehe tests/test_frontend_js.py), statt nur manuell im Browser
// verifizierbar zu sein.
function escapeHtml(value) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function renderMarkdown(text) {
  let html = escapeHtml(text);
  // Nutzerwunsch (2026-08-28): der Konversationsmodus verweist bei
  // Generierungsanfragen per Markdown-Link auf den Kreativ-Modus (siehe
  // llm.CREATIVE_LINK_PLACEHOLDER/app/main.py) - bislang unterstützte
  // renderMarkdown keine Links. Nur http(s)- und interne (mit "/"
  // beginnende) Ziele erlaubt, gegen zufällige/eingeschleuste andere
  // Protokoll-Handler (z.B. javascript:) in KI-generiertem Freitext.
  html = html.replace(/\[([^[\]]+)\]\(((?:https?:\/\/|\/)[^\s()]+)\)/g, '<a href="$2">$1</a>');
  // Nutzerwunsch (2026-09-11): Überschriften dürfen nicht als klickbarer,
  // rot eingefärbter Schlagwort-Link (siehe question.js: makeTermsClickable,
  // .term-followup) enden. Schreibt das Modell eine Überschrift zusätzlich
  // fett ("## **Titel**"), erzeugte die alte Reihenfolge (erst **fett**,
  // dann Überschrift) ein VERSCHACHTELTES <strong> ohne .md-heading-Klasse
  // um den Titeltext - genau das matchte makeTermsClickable. Überschriften
  // laufen deshalb jetzt VOR der Fett-/Kursiv-Ersetzung, mit **/* im
  // erfassten Titeltext entfernt statt in verschachteltes Markup verwandelt.
  const stripEmphasisMarkers = (line) =>
    line.replace(/\*\*(.+?)\*\*/g, '$1').replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '$1');
  html = html.replace(/^### (.+)$/gm, (_, t) => `<strong class="md-heading">${stripEmphasisMarkers(t)}</strong>`);
  html = html.replace(/^## (.+)$/gm, (_, t) => `<strong class="md-heading">${stripEmphasisMarkers(t)}</strong>`);
  html = html.replace(/^# (.+)$/gm, (_, t) => `<strong class="md-heading">${stripEmphasisMarkers(t)}</strong>`);
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>');
  html = html.replace(/^[-*] (.+)$/gm, '&bull;&nbsp;$1');
  html = html.replace(/\n{2,}/g, '</p><p>');
  html = html.replace(/\n/g, '<br>');
  return `<p>${html}</p>`;
}
