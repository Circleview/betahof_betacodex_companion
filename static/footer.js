import { t, getLang, initI18n } from '/i18n.js';
import { createTurnstileWidget } from '/turnstile.js';

let currentVersion = '';

function buildLink(href, text, className) {
  const a = document.createElement('a');
  a.href = href;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.textContent = text;
  if (className) a.className = className;
  return a;
}

// Spam-/Bot-Schutz fürs Feedback-Popover (Backlog #85) - nutzt dieselbe
// Turnstile-Anbindung wie das Frage-Formular (siehe question.js/turnstile.js).
// Wird erst beim ERSTEN Öffnen des Popovers gerendert (nicht schon beim
// Seitenaufbau) - ein noch verstecktes Popover hätte einen Container mit
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

function buildFeedbackWidget() {
  const wrapper = document.createElement('span');
  wrapper.className = 'footer-feedback';

  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'link-button';
  trigger.textContent = t('footer.feedback');
  wrapper.appendChild(trigger);

  const popover = document.createElement('div');
  popover.className = 'popover feedback-popover hidden';
  const arrow = document.createElement('div');
  arrow.className = 'popover-arrow';
  popover.appendChild(arrow);

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
      const res = await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Lang': getLang() },
        body: JSON.stringify({
          message: messageInput.value,
          email: emailInput.value,
          turnstile_token: feedbackTurnstileWidget.getToken(),
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

  popover.appendChild(form);
  wrapper.appendChild(popover);

  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    const wasHidden = popover.classList.contains('hidden');
    popover.classList.toggle('hidden');
    if (wasHidden) renderFeedbackTurnstileWidget();
  });

  return wrapper;
}

document.addEventListener('click', (e) => {
  const container = document.querySelector('.footer-feedback');
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
  // hielte die (jetzt neue) Popover-Instanz das Widget fälschlich für
  // "schon gerendert".
  feedbackTurnstileWidget.destroy();
  feedbackTurnstileWidget = { getToken: () => '', reset: () => {}, destroy: () => {} };
  feedbackTurnstileRendered = false;

  const taglineSpan = document.createElement('span');
  taglineSpan.className = 'footer-tagline';
  taglineSpan.textContent = t('index.tagline');

  // GitHub-Link und Versionsnummer sind zu einem Link zusammengefasst -
  // sichtbarer Text ist die Version, das Ziel ist dasselbe Repo wie beim
  // vorherigen separaten "GitHub"-Link. Bleibt (anders als der frühere
  // .footer-github-link) auch auf schmalen Bildschirmen sichtbar, da die
  // Versionsnummer nicht verzichtbar ist.
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

  footer.replaceChildren(
    taglineSpan,
    buildFeedbackWidget(),
    buildLink('https://betacodex.org', 'betacodex.org'),
    versionLink,
    buildLink('https://www.betahof.de/beratung/', 'Beta Hof'),
    buildLink('https://www.betahof.de/impressum/', t('footer.impressum')),
    privacyPolicyLink,
  );
}

export async function initFooter() {
  const footer = document.getElementById('site-footer');
  if (!footer) return;

  await initI18n();

  try {
    const res = await fetch('/api/version');
    const data = await res.json();
    currentVersion = data.version;
  } catch (err) {
    currentVersion = '';
  }

  renderFooter();
  document.addEventListener('i18n:changed', renderFooter);
}
