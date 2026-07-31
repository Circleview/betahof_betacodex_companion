// Backlog (2026-07-31): Eingabezeile verschwand auf Mobile hinter der
// virtuellen Tastatur bzw. verschob sich sichtbar. Ursache: iOS Safari
// verkleinert den LAYOUT-Viewport beim Öffnen der Tastatur oft nicht -
// 100dvh (siehe body:has(#frage-bereich) in style.css) bleibt dadurch auf
// der vollen Bildschirmhöhe stehen, die Tastatur legt sich einfach darüber,
// und alles, was per Flexbox auf "volle Höhe" gesetzt ist (hier: die
// unten bündige Eingabezeile), landet dadurch hinter der Tastatur statt
// darüber. window.visualViewport bildet die TATSÄCHLICH sichtbare Höhe
// dagegen zuverlässig ab, auch wenn sich der Layout-Viewport selbst nicht
// ändert - wird hier live in die CSS-Variable --app-height gespiegelt, die
// style.css statt eines festen 100dvh nutzt (mit 100dvh als Fallback für
// Browser ohne visualViewport-Unterstützung).
//
// Bewusst als klassisches, blockierendes <script> im <head> eingebunden
// (kein type="module", kein defer) - document.documentElement existiert
// schon während des Head-Parsings, --app-height steht dadurch schon vor
// dem ersten Layout/Paint bereit, kein sichtbares Nachjustieren beim Laden.
function updateAppHeight() {
  const height = window.visualViewport ? window.visualViewport.height : window.innerHeight;
  document.documentElement.style.setProperty('--app-height', `${height}px`);
}

updateAppHeight();
if (window.visualViewport) {
  window.visualViewport.addEventListener('resize', updateAppHeight);
  window.visualViewport.addEventListener('scroll', updateAppHeight);
} else {
  window.addEventListener('resize', updateAppHeight);
}
