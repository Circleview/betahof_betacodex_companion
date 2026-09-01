import { initI18n, t, getLang } from '/i18n.js';
import { initAuth } from '/auth.js';

// Backlog #97, erweitert 2026-09-01: zeigt GET /api/question-log
// chronologisch (neueste zuerst), nach Kalendertag gruppiert - gleiches
// Zeitstrahl-Grid wie changelog.html/js (siehe #changelog-list.timeline-mode
// in style.css), hier aber ohne Icons/Diffs/Rückgängig-Funktion, da es
// dafür keine Entsprechung gibt.
//
// Nutzerwunsch (2026-09-01): drei Ereignistypen statt nur der ersten Frage
// jeder Konversation - "no_answer" (der Companion konnte laut eigener
// Systemanweisung nicht/nur teilweise antworten) und "feedback"
// (Daumen-hoch/-runter, siehe question.js: attachFeedbackButtons) bringen
// zusätzlich Frage UND Antwort mit. Die Frage ist bei allen drei Typen ein
// Link, der den Konversationsmodus in einem neuen Tab MIT genau dieser
// Frage öffnet (siehe question.js: consumeAskParam) - so lässt sich der
// gemeldete Fall nachvollziehen und eine Quellenverbesserung direkt gegen
// dieselbe Frage testen, ohne sie erneut abzutippen.

await initI18n();
await initAuth();

const listEl = document.getElementById('question-log-list');
const statusEl = document.getElementById('question-log-status');
const filterButtons = Array.from(document.querySelectorAll('.question-log-filter-btn'));

let allEntries = [];
const activeEventTypes = new Set(filterButtons.map((btn) => btn.dataset.eventType));

function isSameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function dayKey(date) {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

function formatDayLabel(date) {
  const today = new Date();
  if (isSameDay(date, today)) return t('questionLog.today');
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  if (isSameDay(date, yesterday)) return t('questionLog.yesterday');
  return date.toLocaleDateString(getLang() === 'de' ? 'de-DE' : 'en-US', {
    weekday: 'long',
    day: '2-digit',
    month: 'long',
    year: 'numeric',
  });
}

function formatTime(date) {
  return date.toLocaleTimeString(getLang() === 'de' ? 'de-DE' : 'en-US', { hour: '2-digit', minute: '2-digit' });
}

function buildDayMarker(label) {
  const li = document.createElement('li');
  li.className = 'question-log-day-marker';
  li.textContent = label;
  return li;
}

const EVENT_TYPE_LABEL_KEYS = {
  first_question: 'questionLog.eventType.firstQuestion',
  no_answer: 'questionLog.eventType.noAnswer',
  feedback: 'questionLog.eventType.feedback',
};

// Öffnet den Konversationsmodus in einem neuen Tab mit genau dieser Frage
// (siehe question.js: consumeAskParam - liest ?q=, füllt das Eingabefeld
// und stellt die Frage automatisch, kein zusätzlicher Klick nötig).
function buildQuestionLink(text) {
  const a = document.createElement('a');
  a.className = 'question-log-question-link';
  a.href = `/?q=${encodeURIComponent(text)}`;
  a.target = '_blank';
  a.rel = 'noopener';
  a.textContent = text;
  a.title = t('questionLog.openConversationTitle');
  a.setAttribute('aria-label', t('questionLog.openConversationTitle'));
  return a;
}

function buildFeedbackBadge(feedback) {
  const span = document.createElement('span');
  span.className = `question-log-feedback-badge question-log-feedback-badge--${feedback}`;
  span.textContent = feedback === 'good' ? t('questionLog.feedbackGood') : t('questionLog.feedbackBad');
  return span;
}

function buildEntryElement(entry) {
  const li = document.createElement('li');
  li.className = `question-log-entry question-log-entry--${entry.event_type}`;

  const time = document.createElement('span');
  time.className = 'question-log-time';
  time.textContent = formatTime(new Date(entry.timestamp));
  li.appendChild(time);

  const badge = document.createElement('span');
  badge.className = 'question-log-type-badge';
  badge.textContent = t(EVENT_TYPE_LABEL_KEYS[entry.event_type] || EVENT_TYPE_LABEL_KEYS.first_question);
  li.appendChild(badge);

  if (entry.event_type === 'feedback' && entry.feedback) {
    li.appendChild(buildFeedbackBadge(entry.feedback));
  }

  const text = document.createElement('p');
  text.className = 'question-log-text';
  text.appendChild(buildQuestionLink(entry.text));
  li.appendChild(text);

  if (entry.answer) {
    // Nutzerwunsch (2026-09-01): die volle Antwort steht standardmäßig
    // eingeklappt, damit das Log auf einen Blick überschaubar bleibt (nur
    // Frage + Badges) - ein Klick auf "Antwort anzeigen" öffnet sie, um die
    // Antwortqualität über die Zeit nachvollziehen zu können (z.B. ob eine
    // Quellenverbesserung eine vorher schlecht bewertete Antwort verbessert
    // hat). data-timestamp dient nur als stabiler Schlüssel, um einen
    // bereits geöffneten Zustand über ein erneutes render() (z.B. beim
    // Filtern) hinweg zu erhalten - analog zu question.js:
    // renderSidebarSources.
    const details = document.createElement('details');
    details.className = 'question-log-answer-details';
    details.dataset.timestamp = entry.timestamp;
    const summary = document.createElement('summary');
    summary.textContent = t('questionLog.showAnswer');
    details.appendChild(summary);
    const answer = document.createElement('p');
    answer.className = 'question-log-answer';
    answer.textContent = entry.answer;
    details.appendChild(answer);
    li.appendChild(details);
  }

  return li;
}

function render(entries) {
  // Bleibt über ein erneutes render() hinweg erhalten (z.B. beim Filtern) -
  // siehe Kommentar bei buildEntryElement/details.dataset.timestamp.
  const openTimestamps = new Set(
    Array.from(listEl.querySelectorAll('details[open]')).map((d) => d.dataset.timestamp)
  );
  listEl.replaceChildren();
  if (!entries.length) {
    statusEl.textContent = t('questionLog.empty');
    statusEl.classList.remove('hidden');
    return;
  }
  statusEl.classList.add('hidden');

  let gridRow = 0;
  let lastDayKey = null;
  entries.forEach((entry) => {
    const date = new Date(entry.timestamp);
    const key = dayKey(date);
    if (key !== lastDayKey) {
      lastDayKey = key;
      gridRow += 1;
      const marker = buildDayMarker(formatDayLabel(date));
      marker.style.gridRow = String(gridRow);
      listEl.appendChild(marker);
    }
    gridRow += 1;
    const el = buildEntryElement(entry);
    el.style.gridRow = String(gridRow);
    listEl.appendChild(el);
  });
  listEl.querySelectorAll('details').forEach((d) => {
    if (openTimestamps.has(d.dataset.timestamp)) d.open = true;
  });
  listEl.style.setProperty('--timeline-row-end', String(gridRow + 1));
}

function applyFilter() {
  render(allEntries.filter((entry) => activeEventTypes.has(entry.event_type)));
}

filterButtons.forEach((btn) => {
  btn.addEventListener('click', () => {
    const eventType = btn.dataset.eventType;
    if (activeEventTypes.has(eventType)) {
      activeEventTypes.delete(eventType);
      btn.classList.remove('active');
    } else {
      activeEventTypes.add(eventType);
      btn.classList.add('active');
    }
    btn.setAttribute('aria-pressed', String(activeEventTypes.has(eventType)));
    applyFilter();
  });
});

async function loadQuestionLog() {
  statusEl.textContent = t('questionLog.loading');
  statusEl.classList.remove('hidden');
  try {
    const res = await fetch('/api/question-log', { headers: { 'X-Lang': getLang() } });
    if (res.status === 403) {
      listEl.replaceChildren();
      statusEl.textContent = t('questionLog.noAccess');
      statusEl.classList.remove('hidden');
      return;
    }
    if (!res.ok) throw new Error();
    allEntries = await res.json();
    applyFilter();
  } catch (err) {
    statusEl.textContent = t('questionLog.loadFailed');
    statusEl.classList.remove('hidden');
  }
}

loadQuestionLog();
