import { t, getLang, initI18n } from '/i18n.js';
import { createTurnstileWidget } from '/turnstile.js';

let currentVersion = '';
// Backlog #75: Feature-Schalter serverseitig (EMBED_ENABLED-Env), damit der
// Footer-Link auch während der Early-Access-Testphase komplett unsichtbar
// bleibt - siehe app/main.py get_version().
let embedEnabled = false;

function buildLink(href, text, className) {
  const a = document.createElement('a');
  a.href = href;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.textContent = text;
  if (className) a.className = className;
  return a;
}

// Spam-/Bot-Schutz fürs Feedback-Formular (Backlog #85) - nutzt dieselbe
// Turnstile-Anbindung wie das Frage-Formular (siehe question.js/turnstile.js).
// Wird erst beim ERSTEN Öffnen des Panels gerendert (nicht schon beim
// Seitenaufbau) - ein noch verstecktes Panel hätte einen Container mit
// Breite/Höhe 0, in den Cloudflare das Widget nicht zuverlässig rendert.
let feedbackTurnstileWidget = { getToken: () => '', reset: () => {}, destroy: () => {} };
let feedbackTurnstileRendered = false;

function renderFeedbackTurnstileWidget() {
  if (feedbackTurnstileRendered) return;
  // Während des Cooldowns steht kein Formular (und damit kein Container) im DOM.
  if (!document.getElementById('feedback-turnstile-container')) return;
  feedbackTurnstileRendered = true;
  createTurnstileWidget('feedback-turnstile-container').then((widget) => {
    feedbackTurnstileWidget = widget;
  });
}

function resetFeedbackTurnstile() {
  feedbackTurnstileWidget.destroy();
  feedbackTurnstileWidget = { getToken: () => '', reset: () => {}, destroy: () => {} };
  feedbackTurnstileRendered = false;
}

// Nach einem erfolgreichen Absenden darf erst nach dieser Wartezeit erneut
// Feedback gesendet werden (Serverseitig gilt zusätzlich das Rate-Limit von
// /api/feedback). Als Zeitstempel statt Zähler gespeichert, damit ein
// Sprachwechsel (baut den Footer neu auf) den Cooldown nicht zurücksetzt.
const FEEDBACK_COOLDOWN_MS = 60 * 1000;
let feedbackCooldownUntil = 0;
let feedbackCooldownTimer = null;

function formatCountdown(ms) {
  const totalSeconds = Math.max(0, Math.ceil(ms / 1000));
  const seconds = String(totalSeconds % 60).padStart(2, '0');
  return `${Math.floor(totalSeconds / 60)}:${seconds}`;
}

const CLOSE_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<line x1="18" y1="6" x2="6" y2="18"></line>' +
  '<line x1="6" y1="6" x2="18" y2="18"></line>' +
  '</svg>';

function buildFeedbackField(labelKey, type) {
  const label = document.createElement('label');
  const span = document.createElement('span');
  span.textContent = t(labelKey);
  label.appendChild(span);
  const input = document.createElement(type === 'textarea' ? 'textarea' : 'input');
  if (type === 'textarea') {
    input.rows = 4;
    input.required = true;
  } else {
    input.type = type;
  }
  label.appendChild(input);
  return { label, input };
}

// Fix: statt eines Popovers (position:absolute - anfällig für Clipping durch
// overflow auf Vorfahren-Elementen, siehe die Diskussion beim Footer-
// Zeilenumbruch, und auf Mobile schwer sauber auszurichten) klappt der
// Feedback-Bereich jetzt wie die Volltextsuche in import.js (#search-bar)
// in normalem Fluss auf - hier als eigenständiger Block OBERHALB der
// Trennlinie des Footers, da <footer id="site-footer"> selbst die
// Trennlinie als border-top trägt und ein Kind-Element davon zwangsläufig
// darunter läge.
function ensureFeedbackPanel() {
  let panel = document.getElementById('footer-feedback-panel');
  if (!panel) {
    const footer = document.getElementById('site-footer');
    if (!footer) return null;
    panel = document.createElement('div');
    panel.id = 'footer-feedback-panel';
    panel.className = 'footer-panel hidden';
    footer.parentNode.insertBefore(panel, footer);
  }
  return panel;
}

function ensureEmbedPanel() {
  let panel = document.getElementById('footer-embed-panel');
  if (!panel) {
    const footer = document.getElementById('site-footer');
    if (!footer) return null;
    panel = document.createElement('div');
    panel.id = 'footer-embed-panel';
    panel.className = 'footer-panel footer-embed-panel hidden';
    footer.parentNode.insertBefore(panel, footer);
  }
  return panel;
}

// Feedback- und Einbetten-Bereich: nie beide offen. Beide stehen im DOM vor
// der Footer-Zeile und wachsen dadurch nach oben; beim Öffnen wird die
// Footer-Zeile mit ins Bild gescrollt, damit die Links an ihrer Stelle
// bleiben und der ganze Bereich sichtbar ist.
const FOOTER_PANEL_IDS = ['footer-feedback-panel', 'footer-embed-panel'];
const footerPanelTriggers = {};

function closeFooterPanels(exceptId) {
  FOOTER_PANEL_IDS.forEach((id) => {
    if (id !== exceptId) document.getElementById(id)?.classList.add('hidden');
  });
}

function openFooterPanel(panel, focusTarget) {
  closeFooterPanels(panel.id);
  panel.classList.remove('hidden');
  document.getElementById('site-footer')?.scrollIntoView({ block: 'end', behavior: 'instant' });
  panel.scrollIntoView({ block: 'nearest', behavior: 'instant' });
  focusTarget?.focus({ preventScroll: true });
}

function closeFooterPanel(panel) {
  panel.classList.add('hidden');
  const trigger = footerPanelTriggers[panel.id];
  if (trigger) trigger.focus();
}

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  const open = FOOTER_PANEL_IDS.map((id) => document.getElementById(id)).find(
    (panel) => panel && !panel.classList.contains('hidden')
  );
  if (open) closeFooterPanel(open);
});

// Wrapper, dessen Inhalt zwischen Formular und Cooldown-Ansicht wechselt.
function buildFeedbackSection() {
  const box = document.createElement('div');
  renderFeedbackSection(box, '');
  return box;
}

function renderFeedbackSection(box, confirmationText) {
  clearInterval(feedbackCooldownTimer);
  if (Date.now() >= feedbackCooldownUntil) {
    box.replaceChildren(buildFeedbackForm(box));
    return;
  }
  const children = [];
  if (confirmationText) {
    const confirmation = document.createElement('p');
    confirmation.textContent = confirmationText;
    children.push(confirmation);
  }
  const timer = document.createElement('p');
  timer.className = 'feedback-cooldown';
  children.push(timer);
  box.replaceChildren(...children);
  const tick = () => {
    const remaining = feedbackCooldownUntil - Date.now();
    if (remaining <= 0) {
      clearInterval(feedbackCooldownTimer);
      // Das alte Formular (samt Turnstile-Container) ist längst entfernt.
      resetFeedbackTurnstile();
      renderFeedbackSection(box, '');
      const panel = document.getElementById('footer-feedback-panel');
      if (panel && !panel.classList.contains('hidden')) renderFeedbackTurnstileWidget();
      return;
    }
    timer.textContent = t('footer.feedbackCooldown', { time: formatCountdown(remaining) });
  };
  tick();
  feedbackCooldownTimer = setInterval(tick, 1000);
}

function buildFeedbackForm(box) {
  const form = document.createElement('form');

  const { label: messageLabel, input: messageInput } = buildFeedbackField(
    'footer.feedbackMessageLabel',
    'textarea'
  );
  form.appendChild(messageLabel);

  const { label: emailLabel, input: emailInput } = buildFeedbackField(
    'footer.feedbackEmailLabel',
    'email'
  );
  form.appendChild(emailLabel);

  const turnstileContainer = document.createElement('div');
  turnstileContainer.id = 'feedback-turnstile-container';
  turnstileContainer.className = 'turnstile-container';
  form.appendChild(turnstileContainer);

  const submitBtn = document.createElement('button');
  submitBtn.type = 'submit';
  submitBtn.textContent = t('footer.feedbackSubmit');
  form.appendChild(submitBtn);

  const status = document.createElement('p');
  status.className = 'feedback-status';
  form.appendChild(status);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    submitBtn.disabled = true;
    submitBtn.textContent = t('footer.feedbackSending');
    status.textContent = '';
    try {
      const turnstileToken = await feedbackTurnstileWidget.getToken();
      const res = await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Lang': getLang() },
        body: JSON.stringify({
          message: messageInput.value,
          email: emailInput.value,
          turnstile_token: turnstileToken,
        }),
      });
      // Turnstile-Tokens sind Einweg-Token - nach jedem Versuch (egal ob
      // erfolgreich oder nicht) zurücksetzen, damit ein erneuter Versuch ein
      // frisches Token bekommt.
      feedbackTurnstileWidget.reset();
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || t('footer.feedbackFailed'));
      feedbackCooldownUntil = Date.now() + FEEDBACK_COOLDOWN_MS;
      renderFeedbackSection(box, data.detail);
      return;
    } catch (err) {
      status.textContent = t('common.errorPrefix') + err.message;
    }
    submitBtn.disabled = false;
    submitBtn.textContent = t('footer.feedbackSubmit');
  });

  return form;
}

function buildFooterPanelCloseButton(panel) {
  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'footer-panel-close';
  const label = t('import.closeButtonTitle');
  closeBtn.title = label;
  closeBtn.setAttribute('aria-label', label);
  closeBtn.innerHTML = CLOSE_ICON;
  closeBtn.addEventListener('click', () => closeFooterPanel(panel));
  return closeBtn;
}

function buildFeedbackTrigger() {
  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'footer-trigger link-button';
  footerPanelTriggers['footer-feedback-panel'] = trigger;
  trigger.textContent = t('footer.feedback');
  trigger.addEventListener('click', () => {
    const panel = ensureFeedbackPanel();
    if (!panel) return;
    if (!panel.classList.contains('hidden')) {
      closeFooterPanel(panel);
      return;
    }
    openFooterPanel(panel, panel.querySelector('textarea, input'));
    renderFeedbackTurnstileWidget();
  });
  return trigger;
}

// Backlog #75: Embed-Snippet im Footer-Bereich (#footer-embed-panel, wie das
// Feedback). Der
// Breiten-Eingabewert wirkt jetzt als max-width statt als feste Breite -
// eine schmale Standardbreite unter der 900px-Schwelle, ab der die Quellen-
// Sidebar im Embed erscheint (siehe static/style.css), passt für die
// meisten Einbettungs-Szenarien (z.B. eine Seitenspalte).
//
// Nutzerwunsch (Livegang-Vorbereitung, 2026-09-10): iframe passt sich
// dynamisch/relativ zur Einbettungsumgebung an - Breite füllt per CSS
// (width: 100%) den verfügbaren Platz bis zur oben genannten max-width,
// die Höhe kann die einbettende Seite nicht selbst kennen (wächst mit
// jeder neuen Chat-Nachricht) und wird deshalb per postMessage vom Embed
// gemeldet (siehe static/embed-resize.js) - das kleine Inline-Skript hier
// hört genau darauf und setzt die Höhe entsprechend. document.currentScript.
// previousElementSibling statt einer festen ID, damit mehrere Einbettungen
// derselben Seite (z.B. zum Breiten-Vergleich) einander nicht in die Quere
// kommen. Mobil-Erkennung im Embed selbst (siehe question.js: matchMedia)
// bleibt unberührt - sie wertet ohnehin die tatsächliche iframe-Breite aus,
// die durch width: 100% jetzt sogar echter auf schmalen Bildschirmen
// schrumpft statt immer eine feste Pixelzahl zu sein.
function buildEmbedSnippet(width) {
  const safeWidth = Number.isFinite(width) && width > 0 ? Math.round(width) : 480;
  return (
    `<iframe src="${window.location.origin}/embed.html" ` +
    `style="border:0;display:block;width:100%;max-width:${safeWidth}px;height:600px" ` +
    'loading="lazy" title="BetaCodex Chat"></iframe>\n' +
    '<script>(function(){' +
    'var f=document.currentScript.previousElementSibling;' +
    "window.addEventListener('message',function(e){" +
    "if(e.source!==f.contentWindow||!e.data||e.data.type!=='betacodex-chat-embed-resize')return;" +
    'f.style.height=e.data.height+"px";' +
    '});' +
    '})()</script>'
  );
}

function buildEmbedTrigger() {
  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'footer-trigger footer-embed-trigger link-button';
  trigger.textContent = t('footer.embed');
  footerPanelTriggers['footer-embed-panel'] = trigger;
  trigger.addEventListener('click', () => {
    const panel = ensureEmbedPanel();
    if (!panel) return;
    if (!panel.classList.contains('hidden')) {
      closeFooterPanel(panel);
      return;
    }
    openFooterPanel(panel, panel.querySelector('input'));
  });
  return trigger;
}

function buildEmbedSection() {
  const box = document.createElement('div');

  const heading = document.createElement('p');
  heading.className = 'footer-embed-panel-heading';
  heading.textContent = t('footer.embedHeading');
  box.appendChild(heading);

  const widthLabel = document.createElement('label');
  const widthLabelSpan = document.createElement('span');
  widthLabelSpan.textContent = t('footer.embedWidthLabel');
  widthLabel.appendChild(widthLabelSpan);
  const widthInput = document.createElement('input');
  widthInput.type = 'number';
  widthInput.min = '280';
  widthInput.step = '10';
  widthInput.value = '480';
  widthLabel.appendChild(widthInput);
  box.appendChild(widthLabel);

  const snippetArea = document.createElement('textarea');
  snippetArea.readOnly = true;
  snippetArea.className = 'footer-embed-snippet';
  snippetArea.setAttribute('aria-label', t('footer.embedSnippetLabel'));
  snippetArea.value = buildEmbedSnippet(480);
  box.appendChild(snippetArea);

  widthInput.addEventListener('input', () => {
    snippetArea.value = buildEmbedSnippet(parseInt(widthInput.value, 10));
  });

  const copyBtn = document.createElement('button');
  copyBtn.type = 'button';
  copyBtn.className = 'footer-embed-copy';
  copyBtn.textContent = t('footer.embedCopyButton');
  copyBtn.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(snippetArea.value);
      copyBtn.textContent = t('footer.embedCopied');
    } catch (err) {
      snippetArea.select();
    } finally {
      setTimeout(() => {
        copyBtn.textContent = t('footer.embedCopyButton');
      }, 2000);
    }
  });
  box.appendChild(copyBtn);
  return box;
}

// Der Footer sieht auf jeder Seite identisch aus - der Hinweistext steht
// deshalb immer fest im Footer, unabhängig von Bildschirmbreite oder Seite.
function renderFooter() {
  const footer = document.getElementById('site-footer');
  if (!footer) return;

  // Der Footer wird bei jedem Sprachwechsel komplett neu aufgebaut - ein
  // eventuell bereits gerendertes Feedback-Turnstile-Widget hängt dann an
  // einem inzwischen entfernten DOM-Knoten und muss verworfen werden, sonst
  // hielte das (jetzt neue) Panel das Widget fälschlich für "schon
  // gerendert". Das Panel klappt dabei bewusst wieder zu (analog dazu, wie
  // sich auch #search-bar bei jedem renderSourceList()-Aufruf nicht selbst
  // merkt, ob es offen war).
  resetFeedbackTurnstile();
  const feedbackPanel = ensureFeedbackPanel();
  if (feedbackPanel) {
    feedbackPanel.replaceChildren(buildFooterPanelCloseButton(feedbackPanel), buildFeedbackSection());
    feedbackPanel.classList.add('hidden');
  }

  // Einbetten-Bereich nur bei aktivem EMBED_ENABLED; sonst ein evtl. altes
  // Panel entfernen (Footer wird bei jedem Sprachwechsel neu aufgebaut).
  if (embedEnabled) {
    const embedPanel = ensureEmbedPanel();
    if (embedPanel) {
      embedPanel.replaceChildren(buildFooterPanelCloseButton(embedPanel), buildEmbedSection());
      embedPanel.classList.add('hidden');
    }
  } else {
    document.getElementById('footer-embed-panel')?.remove();
  }

  const taglineSpan = document.createElement('span');
  taglineSpan.className = 'footer-tagline';
  taglineSpan.textContent = t('index.tagline');

  // GitHub-Link und Versionsnummer sind zu einem Link zusammengefasst -
  // sichtbarer Text ist die Version, das Ziel ist dasselbe Repo wie beim
  // vorherigen separaten "GitHub"-Link. Bleibt (anders als .footer-embed)
  // auch auf schmalen Bildschirmen sichtbar - explizit vom Nutzer bestätigt,
  // die Versionsnummer soll immer sichtbar bleiben.
  const versionLink = buildLink(
    'https://github.com/Circleview/betahof_betacodex_companion',
    currentVersion,
    'footer-version'
  );
  versionLink.id = 'footer-version';
  versionLink.title = t('footer.github');

  // Backlog #115: eigene, lokale Seite (nicht extern wie zuvor das
  // Impressum) - beschreibt die Datenverarbeitung DIESER Anwendung, nicht
  // die von Beta Hof allgemein. Zwei fest sprachige HTML-Dateien statt
  // i18n-Keys, da eine Datenschutzerklärung als zusammenhängendes,
  // korrektes Dokument gelesen werden muss statt aus einzeln übersetzten
  // Fragmenten zu bestehen.
  const privacyPolicyLink = buildLink(
    getLang() === 'en' ? '/privacy.html' : '/datenschutz.html',
    t('footer.privacyPolicy')
  );

  // Nutzerwunsch (Livegang-Vorbereitung, 2026-09-10): eigene, lokale
  // Impressum-Seite statt externem Link auf betahof.de/impressum/ - Daten
  // von dort übernommen (siehe static/impressum.html/legal-notice.html),
  // gleiches Zwei-Datei-Prinzip wie bei der Datenschutzerklärung oben.
  const impressumLink = buildLink(
    getLang() === 'en' ? '/legal-notice.html' : '/impressum.html',
    t('footer.impressum')
  );

  // Nutzerwunsch (2026-08-30): Reihenfolge Feedback -> betacodex.org ->
  // Einbetten (nur falls aktiv) -> Version, Rest unverändert.
  const children = [taglineSpan, buildFeedbackTrigger(), buildLink('https://betacodex.org', 'betacodex.org')];
  if (embedEnabled) children.push(buildEmbedTrigger());
  children.push(versionLink, impressumLink, privacyPolicyLink);
  footer.replaceChildren(...children);
}

export async function initFooter() {
  const footer = document.getElementById('site-footer');
  if (!footer) return;

  await initI18n();

  try {
    const res = await fetch('/api/version');
    const data = await res.json();
    currentVersion = data.version;
    embedEnabled = !!data.embed_enabled;
  } catch (err) {
    currentVersion = '';
    embedEnabled = false;
  }

  renderFooter();
  document.addEventListener('i18n:changed', renderFooter);
}
