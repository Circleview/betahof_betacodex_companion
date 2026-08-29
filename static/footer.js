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
  feedbackTurnstileRendered = true;
  createTurnstileWidget('feedback-turnstile-container').then((widget) => {
    feedbackTurnstileWidget = widget;
  });
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
    panel.className = 'footer-feedback-panel hidden';
    footer.parentNode.insertBefore(panel, footer);
  }
  return panel;
}

function buildFeedbackForm() {
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
      form.replaceChildren();
      const confirmation = document.createElement('p');
      confirmation.textContent = data.detail;
      form.appendChild(confirmation);
    } catch (err) {
      status.textContent = t('common.errorPrefix') + err.message;
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = t('footer.feedbackSubmit');
    }
  });

  return form;
}

function buildFeedbackPanelCloseButton(panel) {
  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'footer-feedback-panel-close';
  const label = t('import.closeButtonTitle');
  closeBtn.title = label;
  closeBtn.setAttribute('aria-label', label);
  closeBtn.innerHTML = CLOSE_ICON;
  closeBtn.addEventListener('click', () => panel.classList.add('hidden'));
  return closeBtn;
}

function buildFeedbackTrigger() {
  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'footer-feedback-trigger link-button';
  trigger.textContent = t('footer.feedback');
  trigger.addEventListener('click', () => {
    const panel = ensureFeedbackPanel();
    if (!panel) return;
    const wasHidden = panel.classList.contains('hidden');
    panel.classList.toggle('hidden');
    if (wasHidden) renderFeedbackTurnstileWidget();
  });
  return trigger;
}

// Backlog #75: Popover fürs Embed-Snippet - Trigger-Button öffnet ein
// Popover, Klick außerhalb schließt es (bleibt bewusst bei diesem Muster,
// anders als der Feedback-Bereich - hier gibt es keine nach oben
// überstehenden Inhalte, das Clipping-Risiko besteht also nicht). Nur die
// Breite ist konfigurierbar (Höhe bleibt fix), da
// ausschließlich die Breite vom Nutzer als anpassbar gewünscht wurde - eine
// schmale Standardbreite unter der 900px-Schwelle, ab der die Quellen-
// Sidebar im Embed erscheint (siehe static/style.css), passt für die
// meisten Einbettungs-Szenarien (z.B. eine Seitenspalte).
function buildEmbedSnippet(width) {
  const safeWidth = Number.isFinite(width) && width > 0 ? Math.round(width) : 480;
  return (
    `<iframe src="${window.location.origin}/embed.html" width="${safeWidth}" height="600" ` +
    'style="border:0" loading="lazy" title="BetaCodex Companion"></iframe>'
  );
}

function buildEmbedWidget() {
  const wrapper = document.createElement('span');
  wrapper.className = 'footer-embed';

  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'link-button';
  trigger.textContent = t('footer.embed');
  wrapper.appendChild(trigger);

  const popover = document.createElement('div');
  popover.className = 'popover embed-popover hidden';
  const arrow = document.createElement('div');
  arrow.className = 'popover-arrow';
  popover.appendChild(arrow);

  const heading = document.createElement('p');
  heading.className = 'embed-popover-heading';
  heading.textContent = t('footer.embedHeading');
  popover.appendChild(heading);

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
  popover.appendChild(widthLabel);

  const snippetArea = document.createElement('textarea');
  snippetArea.readOnly = true;
  snippetArea.className = 'embed-snippet';
  snippetArea.value = buildEmbedSnippet(480);
  popover.appendChild(snippetArea);

  widthInput.addEventListener('input', () => {
    snippetArea.value = buildEmbedSnippet(parseInt(widthInput.value, 10));
  });

  const copyBtn = document.createElement('button');
  copyBtn.type = 'button';
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
  popover.appendChild(copyBtn);

  wrapper.appendChild(popover);

  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    popover.classList.toggle('hidden');
  });

  return wrapper;
}

// Nur noch fürs Embed-Popover relevant - der Feedback-Bereich schließt sich
// (wie die Volltextsuche in import.js) nicht mehr automatisch bei Klick
// außerhalb, sondern nur über den eigenen Auslöser-Button.
document.addEventListener('click', (e) => {
  const container = document.querySelector('.footer-embed');
  if (container && !container.contains(e.target)) {
    container.querySelector('.popover')?.classList.add('hidden');
  }
});

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
  feedbackTurnstileWidget.destroy();
  feedbackTurnstileWidget = { getToken: () => '', reset: () => {}, destroy: () => {} };
  feedbackTurnstileRendered = false;
  const feedbackPanel = ensureFeedbackPanel();
  if (feedbackPanel) {
    feedbackPanel.replaceChildren(buildFeedbackPanelCloseButton(feedbackPanel), buildFeedbackForm());
    feedbackPanel.classList.add('hidden');
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

  // Backlog #115: eigene, lokale Seite (nicht extern wie das Impressum) -
  // beschreibt die Datenverarbeitung DIESER Anwendung, nicht die von
  // Beta Hof allgemein. Zwei fest sprachige HTML-Dateien statt i18n-Keys,
  // da eine Datenschutzerklärung als zusammenhängendes, korrektes Dokument
  // gelesen werden muss statt aus einzeln übersetzten Fragmenten zu bestehen.
  const privacyPolicyLink = buildLink(
    getLang() === 'en' ? '/privacy.html' : '/datenschutz.html',
    t('footer.privacyPolicy')
  );

  // Nutzerwunsch (2026-08-30): Reihenfolge Feedback -> betacodex.org ->
  // Einbetten (nur falls aktiv) -> Version, Rest unverändert. Der separate
  // "Beta Hof"-Beratungslink wurde auf Nutzerwunsch ganz entfernt (Impressum
  // verlinkt zwar weiterhin auf betahof.de, ist aber ein eigener, klar
  // beschrifteter Rechtstext-Link, kein "Beta Hof"-Verweis).
  const children = [taglineSpan, buildFeedbackTrigger(), buildLink('https://betacodex.org', 'betacodex.org')];
  if (embedEnabled) children.push(buildEmbedWidget());
  children.push(versionLink, buildLink('https://www.betahof.de/impressum/', t('footer.impressum')), privacyPolicyLink);
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
