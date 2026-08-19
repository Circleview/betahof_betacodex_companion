// Gemeinsame Cloudflare-Turnstile-Anbindung für alle Spam-/Bot-Schutz-Stellen
// (Frage-Formular in question.js, Feedback-Popover in footer.js). Der
// Site-Key kommt bewusst NICHT fest einkompiliert, sondern zur Laufzeit vom
// Backend (/api/turnstile-config, gespeist aus der Server-seitigen
// TURNSTILE_SITE_KEY-Umgebungsvariable) - so können Dev/Stabil/Produktion
// unterschiedliche, zu ihrem jeweiligen Hostnamen passende Keys nutzen. Ein
// für die Produktionsdomain registrierter Site-Key akzeptiert z.B. kein
// localhost: die Cloudflare-Challenge bliebe dort für immer "pending", ohne
// sichtbaren Fehler und ohne je ein gültiges Token zu liefern (siehe
// .env.example für Cloudflares öffentliche Test-Keys, die für genau diesen
// Fall gedacht sind). Bleibt der Key leer, liefert createTurnstileWidget()
// ein No-op-Widget - der Backend-Check ist dann ebenfalls deaktiviert (siehe
// app/captcha.py), die App bleibt also auch ohne Turnstile-Setup voll nutzbar.
//
// Das JS-SDK wird pro Seite nur EINMAL eingebunden (<script ...
// ?onload=onTurnstileLoad>, siehe index.html/import.html) und ruft beim
// Laden dieses Modul auf - alle Aufrufer:innen von createTurnstileWidget()
// warten auf dasselbe Bereitschafts-Signal, unabhängig davon, wie viele
// Formulare auf der jeweiligen Seite ein eigenes Widget brauchen.

let turnstileSiteKey = '';
const siteKeyPromise = fetch('/api/turnstile-config')
  .then((res) => res.json())
  .then((data) => {
    turnstileSiteKey = data.site_key || '';
  })
  .catch(() => {
    turnstileSiteKey = '';
  });

let resolveApiReady;
const apiReadyPromise = new Promise((resolve) => {
  resolveApiReady = resolve;
});
window.onTurnstileLoad = () => resolveApiReady();
// Falls das SDK bereits vor diesem Modul geladen wurde (z.B. aus dem
// Browser-Cache), hat Cloudflare den Callback dann schon verpasst -
// window.turnstile ist in dem Fall aber schon vorhanden.
if (window.turnstile) resolveApiReady();

// containerId muss beim Aufruf bereits im DOM existieren, aber nicht
// zwingend sichtbar sein - Cloudflare rendert zuverlässig auch in einen
// aktuell unsichtbaren Container. Trotzdem sollte das für lange verzögerte
// Formulare (z.B. ein erst bei Bedarf aufklappendes Popover) erst beim
// tatsächlichen Öffnen aufgerufen werden statt schon beim Seitenaufbau.
export async function createTurnstileWidget(containerId) {
  await Promise.all([siteKeyPromise, apiReadyPromise]);
  const container = document.getElementById(containerId);
  if (!turnstileSiteKey || !container || !window.turnstile) {
    return { getToken: () => '', reset: () => {}, destroy: () => {} };
  }

  // 'interaction-only': das Widget bleibt für die meisten Besucher:innen
  // unsichtbar und erscheint nur, wenn Cloudflare tatsächlich eine
  // Bestätigung braucht (Standard "always" würde die kleine Box dauerhaft
  // im Formular anzeigen, auch wenn sie im Hintergrund automatisch besteht).
  const widgetId = window.turnstile.render(container, {
    sitekey: turnstileSiteKey,
    appearance: 'interaction-only',
    // Cloudflare lässt das gelöste Widget im DOM stehen (der Container ist
    // dann nicht mehr :empty), es würde also ohne diesen Callback sichtbar
    // bleiben, obwohl die Bestätigung bereits abgeschlossen ist.
    callback: () => container.classList.add('turnstile-verified'),
    // Fix (2026-08-19, gemeldeter "Springen"-Bug): der Container wird schon
    // beim Rendern nicht mehr :empty (Cloudflare fügt sein iFrame ein) - für
    // die allermeisten Besucher:innen bleibt dieses iFrame aber unsichtbar
    // und 0px hoch, da fast nie eine echte Interaktion nötig ist. Trotzdem
    // griff bisher sofort die CSS-Regel für den sichtbaren Zustand (u.a.
    // margin-top), wodurch die Eingabezeile kurz nach oben/unten sprang -
    // in der zentrierten Startansicht sogar doppelt, weil die Box dabei
    // vertikal zentriert bleibt. Diese beiden von Cloudflare extra für genau
    // diesen Fall vorgesehenen Callbacks feuern NUR, wenn wirklich eine
    // sichtbare Challenge ansteht - erst dann bekommt der Container per CSS
    // Platz zugewiesen (siehe .turnstile-interactive in style.css).
    'before-interactive-callback': () => container.classList.add('turnstile-interactive'),
    'after-interactive-callback': () => container.classList.remove('turnstile-interactive'),
    // Ohne diesen Callback bleibt ein falsch konfigurierter/nicht für dieses
    // Hostname freigegebener Site-Key komplett stumm (siehe Kommentar oben) -
    // damit landet der Grund wenigstens sichtbar in der Konsole statt in
    // einem für Nutzer:innen undurchsichtigen "Sicherheitsprüfung
    // fehlgeschlagen".
    'error-callback': () => {
      console.error(
        '[Turnstile] Widget-Fehler - Site-Key evtl. nicht für dieses Hostname freigegeben.'
      );
    },
  });

  return {
    getToken: () => window.turnstile.getResponse(widgetId) || '',
    reset: () => {
      window.turnstile.reset(widgetId);
      // Nach dem Reset entscheidet Cloudflare neu, ob eine Interaktion nötig
      // ist - die Klasse muss weg, sonst bliebe das Widget auch bei einer
      // künftig tatsächlich nötigen Bestätigung dauerhaft ausgeblendet.
      container.classList.remove('turnstile-verified');
    },
    // Wird gebraucht, wenn der Container selbst neu aufgebaut wird (z.B.
    // Footer bei einem Sprachwechsel) - ohne das bliebe das alte Widget an
    // einem inzwischen aus dem DOM entfernten Knoten hängen.
    destroy: () => {
      window.turnstile.remove(widgetId);
    },
  };
}
