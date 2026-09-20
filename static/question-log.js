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

// Wie die Quellenliste (import.js: SOURCES_PAGE_SIZE): ALLE Einträge liegen als
// schlanke Liste (ohne Antworttexte) vor - Filter wirken deshalb immer auf den
// kompletten Bestand -, gerendert werden aber nur die ersten LOG_PAGE_SIZE
// des gefilterten Ergebnisses; beim Erreichen des Listenendes (Sentinel +
// IntersectionObserver) kommt die nächste Seite dazu. Die Antwort eines
// Eintrags wird erst beim Aufklappen einzeln nachgeladen und dann gemerkt.
const LOG_PAGE_SIZE = 30;
let allEntries = [];
let filteredEntries = [];
let visibleCount = LOG_PAGE_SIZE;
let logObserver = null;
const answerCache = new Map();
const activeEventTypes = new Set(filterButtons.map((btn) => btn.dataset.eventType));
// Nutzerwunsch (Livegang-Vorbereitung, 2026-09-10): Löschfunktion für
// einzelne Einträge (jeden event_type) - zweistufige Bestätigung direkt am
// Button statt eines nativen confirm()-Dialogs, gleiches Muster wie das
// Abbrechen eines Imports in import.js. Modul-weites Set statt lokalem
// Zustand pro Element, damit es ein erneutes render() (z.B. durch einen
// Filter-Klick) übersteht.
const deleteConfirmPendingIds = new Set();

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
// und stellt die Frage automatisch, kein zusätzlicher Klick nötig). Bei
// Einträgen aus dem Kreativ-Modus (mode 'creative', text = Anweisung) statt
// dessen den Kreativ-Modus mit vorausgefüllter Anweisung (?instruction=).
function buildQuestionLink(text, mode) {
  const creative = mode === 'creative';
  const titleKey = creative ? 'questionLog.openCreativeTitle' : 'questionLog.openConversationTitle';
  const a = document.createElement('a');
  a.className = 'question-log-question-link';
  a.href = creative
    ? `/creative.html?instruction=${encodeURIComponent(text)}`
    : `/?q=${encodeURIComponent(text)}`;
  a.target = '_blank';
  a.rel = 'noopener';
  a.textContent = text;
  a.title = t(titleKey);
  a.setAttribute('aria-label', t(titleKey));
  return a;
}

function buildFeedbackBadge(feedback) {
  const span = document.createElement('span');
  span.className = `question-log-feedback-badge question-log-feedback-badge--${feedback}`;
  span.textContent = feedback === 'good' ? t('questionLog.feedbackGood') : t('questionLog.feedbackBad');
  return span;
}

async function loadAnswer(entry, answerEl) {
  if (answerCache.has(entry.id)) {
    answerEl.textContent = answerCache.get(entry.id);
    return;
  }
  answerEl.textContent = t('questionLog.loading');
  try {
    const res = await fetch(`/api/question-log/${entry.id}`, { headers: { 'X-Lang': getLang() } });
    if (!res.ok) throw new Error();
    const full = await res.json();
    answerCache.set(entry.id, full.answer || '');
    answerEl.textContent = answerCache.get(entry.id);
  } catch (err) {
    answerEl.textContent = t('questionLog.loadFailed');
  }
}

function buildEntryElement(entry) {
  const li = document.createElement('li');
  // Fix (2026-09-14, gemeldeter Bug): eine Frage, auf die mehrere
  // Kriterien gleichzeitig zutreffen (z.B. "erste Frage" UND "keine
  // Antwort gefunden"), ist jetzt EIN Eintrag mit mehreren event_types
  // statt zwei separaten, identisch aussehenden Einträgen - bekommt hier
  // entsprechend mehrere Badges/Modifier-Klassen statt nur einer.
  li.className = ['question-log-entry', ...entry.event_types.map((et) => `question-log-entry--${et}`)].join(' ');

  const time = document.createElement('span');
  time.className = 'question-log-time';
  time.textContent = formatTime(new Date(entry.timestamp));
  li.appendChild(time);

  const badgeKeys = entry.event_types.map((et) => EVENT_TYPE_LABEL_KEYS[et] || EVENT_TYPE_LABEL_KEYS.first_question);
  if (entry.mode === 'creative') badgeKeys.push('questionLog.eventType.creative');
  badgeKeys.forEach((key) => {
    const badge = document.createElement('span');
    badge.className = 'question-log-type-badge';
    badge.textContent = t(key);
    li.appendChild(badge);
  });

  if (entry.event_types.includes('feedback') && entry.feedback) {
    li.appendChild(buildFeedbackBadge(entry.feedback));
  }

  const text = document.createElement('p');
  text.className = 'question-log-text';
  text.appendChild(buildQuestionLink(entry.text, entry.mode));
  li.appendChild(text);

  if (entry.has_answer) {
    // Nutzerwunsch (2026-09-01): die volle Antwort steht standardmäßig
    // eingeklappt, damit das Log auf einen Blick überschaubar bleibt (nur
    // Frage + Badges) - ein Klick auf "Antwort anzeigen" öffnet sie, um die
    // Antwortqualität über die Zeit nachvollziehen zu können (z.B. ob eine
    // Quellenverbesserung eine vorher schlecht bewertete Antwort verbessert
    // hat). data-timestamp dient nur als stabiler Schlüssel, um einen
    // bereits geöffneten Zustand über ein erneutes render() (z.B. beim
    // Filtern) hinweg zu erhalten - analog zu question.js:
    // renderSidebarSources. Der Antworttext selbst kommt erst beim
    // Aufklappen (siehe loadAnswer).
    const details = document.createElement('details');
    details.className = 'question-log-answer-details';
    details.dataset.timestamp = entry.timestamp;
    const summary = document.createElement('summary');
    summary.textContent = t('questionLog.showAnswer');
    details.appendChild(summary);
    const answer = document.createElement('p');
    answer.className = 'question-log-answer';
    answer.textContent = answerCache.get(entry.id) || '';
    details.appendChild(answer);
    details.addEventListener('toggle', () => {
      if (details.open) loadAnswer(entry, answer);
    });
    li.appendChild(details);
  }

  const deleteBtn = document.createElement('button');
  deleteBtn.type = 'button';
  deleteBtn.className = 'link-button question-log-delete-button';
  deleteBtn.textContent = deleteConfirmPendingIds.has(entry.id)
    ? t('questionLog.deleteConfirmButton')
    : t('questionLog.deleteButton');
  deleteBtn.addEventListener('click', () => deleteEntry(entry));
  li.appendChild(deleteBtn);

  return li;
}

// Nutzerwunsch (Livegang-Vorbereitung, 2026-09-10): löscht einen einzelnen
// Fragen-Log-Eintrag unwiderruflich (jeden event_type). Zweistufige
// Bestätigung direkt am Button statt eines nativen confirm()-Dialogs,
// siehe deleteConfirmPendingIds oben.
async function deleteEntry(entry) {
  if (!deleteConfirmPendingIds.has(entry.id)) {
    deleteConfirmPendingIds.add(entry.id);
    applyFilter({ resetPaging: false });
    return;
  }
  try {
    const res = await fetch(`/api/question-log/${entry.id}`, {
      method: 'DELETE',
      headers: { 'X-Lang': getLang() },
    });
    if (!res.ok) throw new Error();
    deleteConfirmPendingIds.delete(entry.id);
    allEntries = allEntries.filter((e) => e.id !== entry.id);
    answerCache.delete(entry.id);
    applyFilter({ resetPaging: false });
  } catch (err) {
    statusEl.textContent = t('questionLog.deleteFailed');
    statusEl.classList.remove('hidden');
  }
}

function render() {
  // Bleibt über ein erneutes render() hinweg erhalten (z.B. beim Filtern) -
  // siehe Kommentar bei buildEntryElement/details.dataset.timestamp.
  const openTimestamps = new Set(
    Array.from(listEl.querySelectorAll('details[open]')).map((d) => d.dataset.timestamp)
  );
  logObserver?.disconnect();
  listEl.replaceChildren();
  if (!filteredEntries.length) {
    statusEl.textContent = t('questionLog.empty');
    statusEl.classList.remove('hidden');
    return;
  }
  statusEl.classList.add('hidden');

  let gridRow = 0;
  let lastDayKey = null;
  filteredEntries.slice(0, visibleCount).forEach((entry) => {
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

  // Noch nicht gerenderte Einträge übrig: unsichtbares Sentinel ans Ende, das
  // beim Scrollen die nächste Seite nachlädt (Daten liegen ja schon vor).
  if (filteredEntries.length > visibleCount) {
    const sentinel = document.createElement('li');
    sentinel.className = 'question-log-sentinel';
    sentinel.style.gridRow = String(gridRow + 1);
    listEl.appendChild(sentinel);
    logObserver = new IntersectionObserver(
      (observed) => {
        if (observed.some((o) => o.isIntersecting)) {
          logObserver.disconnect();
          visibleCount += LOG_PAGE_SIZE;
          render();
        }
      },
      { rootMargin: '400px' }
    );
    logObserver.observe(sentinel);
  }
}

function applyFilter({ resetPaging = true } = {}) {
  // "oder"-Semantik (Nutzerwunsch 2026-09-14): eine Frage mit mehreren
  // event_types taucht auf, sobald MINDESTENS eines davon aktiv gefiltert
  // ist - auch wenn ein anderes ihrer Labels gerade ausgeblendet ist. Der
  // Filter läuft über ALLE Einträge, nicht nur über die gerade gerenderten.
  filteredEntries = allEntries.filter((entry) => entry.event_types.some((et) => activeEventTypes.has(et)));
  if (resetPaging) visibleCount = LOG_PAGE_SIZE;
  render();
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
    const res = await fetch('/api/question-log?include_answers=false', { headers: { 'X-Lang': getLang() } });
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
