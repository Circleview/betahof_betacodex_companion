import { t } from '/i18n.js';

// Gemeinsame Daumen-hoch/-runter-Komponente für den Konversationsmodus
// (question.js) und den Kreativ-Modus (creative.js) - vorher lag sie nur in
// question.js.

const THUMBS_UP_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3z"></path>' +
  '<path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"></path>' +
  '</svg>';

const THUMBS_DOWN_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3z"></path>' +
  '<path d="M17 2h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"></path>' +
  '</svg>';

const FEEDBACK_SENT_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">' +
  '<polyline points="20 6 9 17 4 12"></polyline>' +
  '</svg>';

const TITLE_KEYS = {
  conversation: { good: 'index.feedbackGoodTitle', bad: 'index.feedbackBadTitle' },
  creative: { good: 'creative.feedbackGoodTitle', bad: 'creative.feedbackBadTitle' },
};

// Nutzerwunsch (2026-09-01): Daumen-hoch/-runter pro Antwort - schreibt ein
// Feedback-Ereignis ins Fragen-Log (siehe app/main.py:
// submit_answer_feedback), damit sich gute/schlechte Antworten später
// gezielt nachschlagen lassen. Im Kreativ-Modus (mode 'creative') ist
// question die Anweisung und answer der erzeugte Text. Bewusst ohne
// Anmeldung/Captcha erreichbar (siehe AnswerFeedbackIn). Nach erfolgreichem
// Absenden bleibt der grüne Haken dauerhaft stehen und BEIDE Buttons werden
// dauerhaft deaktiviert/ausgegraut - ein zweites Feedback zu derselben
// Antwort ist nicht vorgesehen. Schlägt der Request fehl (z.B.
// Netzwerkfehler), bleiben beide Buttons stattdessen normal nutzbar, damit
// ein erneuter Versuch möglich ist. sent ('good'/'bad') stellt einen bereits
// abgesendeten Zustand wieder her (Kreativ-Modus nach Reload), onSent(value)
// meldet ein erfolgreiches Absenden nach außen.
export function buildAnswerFeedback({ question, answer, mode = 'conversation', sent = null, onSent = () => {} }) {
  const wrap = document.createElement('span');
  wrap.className = 'answer-feedback';
  const buttons = [];

  function lockButtons() {
    buttons.forEach((b) => {
      b.disabled = true;
      b.classList.add('feedback-btn--locked');
    });
  }

  function unlockButtons() {
    buttons.forEach((b) => {
      b.disabled = false;
    });
  }

  function markSent(btn) {
    btn.innerHTML = FEEDBACK_SENT_ICON;
    btn.classList.add('feedback-btn--sent');
  }

  function buildButton(value, icon) {
    const titleKey = TITLE_KEYS[mode][value];
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `feedback-btn feedback-btn--${value}`;
    btn.innerHTML = icon;
    btn.title = t(titleKey);
    btn.setAttribute('aria-label', t(titleKey));
    btn.addEventListener('click', async () => {
      if (btn.disabled) return;
      lockButtons();
      let success = false;
      try {
        const res = await fetch('/api/answer-feedback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question, answer, feedback: value, mode }),
        });
        success = res.ok;
      } catch (err) {
        success = false;
      }
      if (success) {
        markSent(btn);
        onSent(value);
      } else {
        unlockButtons();
      }
    });
    buttons.push(btn);
    return btn;
  }

  wrap.appendChild(buildButton('good', THUMBS_UP_ICON));
  wrap.appendChild(buildButton('bad', THUMBS_DOWN_ICON));
  if (sent) {
    lockButtons();
    markSent(buttons.find((b) => b.classList.contains(`feedback-btn--${sent}`)));
  }
  return wrap;
}
