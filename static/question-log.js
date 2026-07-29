import { initI18n, t, getLang } from '/i18n.js';
import { initAuth } from '/auth.js';

// Backlog #97: anonymisiertes Log der ersten Frage jeder Konversation.
// Zeigt GET /api/question-log chronologisch (neueste zuerst), nach
// Kalendertag gruppiert - gleiches Zeitstrahl-Grid wie changelog.html/js
// (siehe #changelog-list.timeline-mode in style.css), hier aber ohne
// Icons/Diffs/Rückgängig-Funktion, da es dafür keine Entsprechung gibt.

await initI18n();
await initAuth();

const listEl = document.getElementById('question-log-list');
const statusEl = document.getElementById('question-log-status');

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

function buildEntryElement(entry) {
  const li = document.createElement('li');
  li.className = 'question-log-entry';

  const time = document.createElement('span');
  time.className = 'question-log-time';
  time.textContent = formatTime(new Date(entry.timestamp));
  li.appendChild(time);

  const text = document.createElement('p');
  text.className = 'question-log-text';
  text.textContent = entry.text;
  li.appendChild(text);

  return li;
}

function render(entries) {
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
  listEl.style.setProperty('--timeline-row-end', String(gridRow + 1));
}

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
    const entries = await res.json();
    render(entries);
  } catch (err) {
    statusEl.textContent = t('questionLog.loadFailed');
    statusEl.classList.remove('hidden');
  }
}

loadQuestionLog();
