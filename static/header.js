import { initI18n, t } from '/i18n.js';
import { initAuth, hasRole, onAuthChange } from '/auth.js';

// Gemeinsame Navigation (Backlog 2026-07-30): früher auf jeder Seite als
// vier identische <a>-Blöcke von Hand kopiert - ein vergessenes Update an
// einer einzelnen Stelle (z.B. die anfangs fehlende CSS-Regel fürs
// Fragen-Log-Icon) blieb dadurch leicht unbemerkt. Jetzt eine einzige
// Quelle: jede Seite liefert nur noch ein leeres <header id="site-header">
// mit den beiden bereits bestehenden Platzhaltern (#lang-switcher,
// #auth-widget) - dieses Modul baut Markenname + die vier Sprungicons
// drumherum auf. Die beiden Platzhalter werden per appendChild verschoben
// (nicht neu erzeugt) - das funktioniert unabhängig davon, ob i18n.js/
// auth.js zu diesem Zeitpunkt schon hineingerendert haben oder nicht, da
// appendChild einen bestehenden Knoten samt Inhalt an die neue Stelle
// verschiebt, statt ihn zu klonen.

const CONVERSATION_ICON =
  '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>' +
  '</svg>';

const IMPORT_ICON =
  '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16.5a1 1 0 0 1-1 1H6.5A2.5 2.5 0 0 1 4 18V5.5Z"></path>' +
  '<path d="M6.5 3A2.5 2.5 0 0 0 4 5.5V18a2.5 2.5 0 0 0 2.5 2.5H19"></path>' +
  '<line x1="8" y1="7" x2="16" y2="7"></line>' +
  '<line x1="8" y1="11" x2="16" y2="11"></line>' +
  '</svg>';

// Backlog #97 (Nachtrag): eine Sprechblase mit kleinem Uhr-Abzeichen -
// "Sprechblase kombiniert mit einem Log-Icon", bewusst anders als das reine
// Sprechblasen-Icon der Konversation und der reine Uhr-Kreis des
// Änderungs-Logs, damit alle drei auf einen Blick unterscheidbar bleiben.
const QUESTION_LOG_ICON =
  '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" ' +
  'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M4 4h10a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2H8l-3.5 3v-3H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z"></path>' +
  '<circle cx="17.5" cy="16.5" r="6" fill="var(--color-bg)" stroke="none"></circle>' +
  '<circle cx="17.5" cy="16.5" r="5.2"></circle>' +
  '<polyline points="17.5 13.8 17.5 16.5 19.8 17.8"></polyline>' +
  '</svg>';

// Backlog (2026-08-01, Nutzerwunsch): Stift (Bearbeiten/Änderungen) statt
// nur einer reinen Uhr - dieselbe Bauweise wie QUESTION_LOG_ICON oben
// (Hauptform oben links, kleines Uhr-Abzeichen unten rechts mit
// Hintergrund-Ausstanzung), damit die Bedeutung "Log von Änderungen über
// die Zeit" auf einen Blick klar wird statt nur "Zeit" zu zeigen.
const CHANGELOG_ICON =
  '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" ' +
  'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' +
  '<g transform="translate(-1.5,-1.5) scale(0.7)">' +
  '<path d="M12 20h9"></path>' +
  '<path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"></path>' +
  '</g>' +
  '<circle cx="17.5" cy="16.5" r="6" fill="var(--color-bg)" stroke="none"></circle>' +
  '<circle cx="17.5" cy="16.5" r="5.2"></circle>' +
  '<polyline points="17.5 13.8 17.5 16.5 19.8 17.8"></polyline>' +
  '</svg>';

// gated: nur für Quellen-Pfleger:innen/System-Admins sichtbar (siehe
// updateNavVisibility) - Konversation und Quellenverzeichnis bleiben für
// alle Besucher:innen sichtbar.
// badge: Backlog (2026-08-02) - Warn-Badge, falls mindestens eine Quelle
// einen defekten Link hat (siehe updateBrokenLinksBadge unten), damit das
// von JEDER Seite aus auffällt, nicht erst nach dem Öffnen der
// Quellenübersicht.
const NAV_LINKS = [
  { id: 'conversation-link', href: '/', icon: CONVERSATION_ICON, titleKey: 'index.viewConversation', gated: false },
  { id: 'import-link', href: '/import.html', icon: IMPORT_ICON, titleKey: 'index.viewSources', gated: false, badge: true },
  { id: 'question-log-link', href: '/question-log.html', icon: QUESTION_LOG_ICON, titleKey: 'index.viewQuestionLog', gated: true },
  { id: 'changelog-link', href: '/changelog.html', icon: CHANGELOG_ICON, titleKey: 'index.viewChangelog', gated: true },
];

// Gleiches Warndreieck-Motiv wie das bestehende Vorbild für fehlgeschlagene
// Imports (static/import.html, #jobs-icon-warning).
const NAV_WARNING_BADGE_ICON =
  '<svg viewBox="0 0 24 24" width="9" height="9" fill="none" stroke="currentColor" ' +
  'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M12 3.5 2 20h20L12 3.5z"></path>' +
  '<line x1="12" y1="9.5" x2="12" y2="14"></line>' +
  '<circle cx="12" cy="17" r="0.6" fill="currentColor" stroke="none"></circle>' +
  '</svg>';

function buildNavLink({ id, href, icon, gated, badge }) {
  const a = document.createElement('a');
  a.id = id;
  a.href = href;
  if (gated) a.classList.add('hidden');
  a.innerHTML = icon;
  if (badge) {
    const badgeEl = document.createElement('span');
    badgeEl.id = `${id}-badge`;
    badgeEl.className = 'nav-warning-badge hidden';
    badgeEl.innerHTML = NAV_WARNING_BADGE_ICON;
    a.appendChild(badgeEl);
  }
  return a;
}

// Backlog (2026-08-02): Anzahl Quellen mit defektem Link (aus dem
// wöchentlichen Hintergrund-Check, app/main.py) fürs Badge am
// "Quellen"-Menüpunkt holen - nur für Pfleger:innen/Admins relevant, der
// Endpoint ist entsprechend rollen-geschützt (GET /api/sources/broken-
// links-count liefert für alle anderen ohnehin 403).
async function updateBrokenLinksBadge(visible) {
  const badgeEl = document.getElementById('import-link-badge');
  if (!badgeEl) return;
  if (!visible) {
    badgeEl.classList.add('hidden');
    return;
  }
  try {
    const res = await fetch('/api/sources/broken-links-count');
    if (!res.ok) return;
    const data = await res.json();
    badgeEl.classList.toggle('hidden', !(data.count > 0));
  } catch (err) {
    // Netzwerkfehler: Badge bleibt im letzten bekannten Zustand.
  }
}

function applyNavTexts() {
  NAV_LINKS.forEach(({ id, titleKey }) => {
    const el = document.getElementById(id);
    if (!el) return;
    const label = t(titleKey);
    el.title = label;
    el.setAttribute('aria-label', label);
  });
  const brandName = document.querySelector('#brand-link .brand-name');
  if (brandName) brandName.textContent = t('index.brandName');
}

function updateNavVisibility() {
  const visible = hasRole('quellen_pfleger');
  NAV_LINKS.filter((link) => link.gated).forEach(({ id }) => {
    document.getElementById(id)?.classList.toggle('hidden', !visible);
  });
  updateBrokenLinksBadge(visible);
}

function renderHeaderShell() {
  const header = document.getElementById('site-header');
  if (!header) return;

  const langSwitcher = document.getElementById('lang-switcher');
  const authWidget = document.getElementById('auth-widget');

  const h1 = document.createElement('h1');
  const brand = document.createElement('a');
  brand.href = '/';
  brand.id = 'brand-link';
  brand.className = 'brand-link';
  // Fix: Klick auf den Marken-Namen soll immer eine LEERE Konversation
  // öffnen, statt (wie ein normaler Klick auf "/") die zuletzt gespeicherte
  // Konversation wiederherzustellen (siehe CONVERSATION_STORAGE_KEY in
  // question.js - der Schlüsselname muss hier übereinstimmen). War vorher
  // in init-footer.js an das statische #brand-link gebunden - jetzt direkt
  // hier bei der Erzeugung, da das Element erst asynchron entsteht und ein
  // Listener von außen es sonst u.U. verpassen würde.
  brand.addEventListener('click', () => {
    sessionStorage.removeItem('conversationHistory');
  });
  const dot = document.createElement('span');
  dot.className = 'brand-dot';
  dot.setAttribute('aria-hidden', 'true');
  const name = document.createElement('span');
  name.className = 'brand-name';
  brand.append(dot, name);
  h1.appendChild(brand);

  const actions = document.createElement('div');
  actions.className = 'header-actions';
  NAV_LINKS.forEach((link) => actions.appendChild(buildNavLink(link)));
  if (langSwitcher) actions.appendChild(langSwitcher);
  if (authWidget) actions.appendChild(authWidget);

  header.replaceChildren(h1, actions);
}

// Nutzerwunsch (2026-08-23): der Marken-NAME (nicht der Punkt) soll sich
// elegant ausblenden, sobald der (sticky, siehe style.css #site-header)
// Header beim Herunterscrollen wirklich "geklebt" ist - d.h. sein oberer
// Rand hat den Sticky-Versatz (CSS top) erreicht. Jede Aufwärtsbewegung -
// unabhängig davon, wie tief man auf der Seite gescrollt hat - blendet ihn
// sofort wieder ein, bewusst NICHT erst wieder am Seitenanfang (Nutzerwunsch:
// "wie diese modernen, eleganten Transitionen z.B. auf dem iPhone", analog
// zur Safari-Werkzeugleiste auf iOS). rAF-Throttling, damit der scroll-Handler
// nicht öfter als einmal pro Frame läuft.
function initStickyHeaderCollapse() {
  const header = document.getElementById('site-header');
  if (!header) return;
  const STUCK_TOLERANCE_PX = 4;
  let lastScrollY = window.scrollY;
  let ticking = false;

  function update() {
    const currentScrollY = window.scrollY;
    const scrollingDown = currentScrollY > lastScrollY;
    const stickyTop = parseFloat(getComputedStyle(header).top) || 0;
    const isStuck = header.getBoundingClientRect().top <= stickyTop + STUCK_TOLERANCE_PX;
    if (scrollingDown && isStuck) {
      header.classList.add('site-header--compact');
    } else if (!scrollingDown) {
      header.classList.remove('site-header--compact');
    }
    lastScrollY = currentScrollY;
    ticking = false;
  }

  window.addEventListener(
    'scroll',
    () => {
      if (!ticking) {
        ticking = true;
        requestAnimationFrame(update);
      }
    },
    { passive: true },
  );
}

export async function initHeader() {
  await initI18n();
  await initAuth();
  renderHeaderShell();
  applyNavTexts();
  updateNavVisibility();
  initStickyHeaderCollapse();
  document.addEventListener('i18n:changed', applyNavTexts);
  onAuthChange(updateNavVisibility);
}
