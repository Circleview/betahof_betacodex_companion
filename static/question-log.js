import { initI18n, t, getLang } from '/i18n.js';
import { initAuth } from '/auth.js';
import { buildBlocks, pageBlocks, shortId } from '/question-log-blocks.js';

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
//
// Idee 56580b6e: jede Frage eines Chats wird geloggt (event_type "follow_up"
// ab der zweiten). Die Liste zeigt deshalb Blöcke je conversation_id - die
// reine Gruppierung steht in question-log-blocks.js (testbar ohne DOM).

await initI18n();
await initAuth();

const listEl = document.getElementById('question-log-list');
const statusEl = document.getElementById('question-log-status');
const chatBarEl = document.getElementById('question-log-chat-bar');
const filterButtons = Array.from(document.querySelectorAll('.question-log-filter-btn'));

// Wie die Quellenliste (import.js: SOURCES_PAGE_SIZE): ALLE Einträge liegen als
// schlanke Liste (ohne Antworttexte) vor - Filter wirken deshalb immer auf den
// kompletten Bestand -, gerendert werden aber nur die ersten LOG_PAGE_SIZE
// des gefilterten Ergebnisses (Paging zählt BLÖCKE, kein Chat wird zerschnitten); beim Erreichen des Listenendes (Sentinel +
// IntersectionObserver) kommt die nächste Seite dazu. Die Antwort eines
// Eintrags wird erst beim Aufklappen einzeln nachgeladen und dann gemerkt.
const LOG_PAGE_SIZE = 30;
let allEntries = [];
let filteredBlocks = [];
// Chat-Filter (Klick auf den Chip) und zweistufiges "Ganzes Gespräch löschen".
let activeConversationId = null;
let deleteConversationPending = false;
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
// Lange Fragetexte werden auf 4 Zeilen gekürzt; aufgeklappte IDs bleiben über
// render() (Filter, Löschen-Klick, Nachladen) hinweg erhalten.
const CLAMP_MIN_CHARS = 140;
const expandedIds = new Set();
let clampChecks = [];

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
  follow_up: 'questionLog.eventType.followUp',
  no_answer: 'questionLog.eventType.noAnswer',
  feedback: 'questionLog.eventType.feedback',
  // 2026-09-24: jede Anfrage im Kreativ-Modus (Oberfläche) bzw. über MCP
  // (app/mcp_server.py) - beides anonym.
  creative: 'questionLog.eventType.creative',
  mcp: 'questionLog.eventType.mcp',
};

// Öffnet den Konversationsmodus in einem neuen Tab mit genau dieser Frage
// (siehe question.js: consumeAskParam - liest ?q=, füllt das Eingabefeld
// und stellt die Frage automatisch, kein zusätzlicher Klick nötig). Bei
// Einträgen aus dem Kreativ-Modus (mode 'creative', text = Anweisung) statt
// dessen den Kreativ-Modus mit vorausgefüllter Anweisung (?instruction=).
function buildQuestionLink(text, mode) {
  const creative = mode === 'creative' || mode === 'mcp';
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

function buildMoreButton(entry, textEl) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'link-button question-log-more-btn';
  btn.setAttribute('aria-controls', textEl.id);
  const sync = () => {
    const open = expandedIds.has(entry.id);
    btn.setAttribute('aria-expanded', String(open));
    btn.textContent = t(open ? 'questionLog.showLess' : 'questionLog.showMore');
    textEl.classList.toggle('question-log-text--clamped', !open);
  };
  sync();
  btn.addEventListener('click', () => {
    if (expandedIds.has(entry.id)) expandedIds.delete(entry.id);
    else expandedIds.add(entry.id);
    sync();
  });
  return btn;
}

// Fragetext (Link) + ggf. "Mehr"-Knopf. Der Knopf erscheint nur, wenn der
// gekürzte Text wirklich überläuft (gebündelte Messung, siehe runClampChecks).
function appendQuestionText(li, entry) {
  const text = document.createElement('p');
  text.className = 'question-log-text';
  text.appendChild(buildQuestionLink(entry.text, entry.mode));
  li.appendChild(text);
  if (entry.text.length <= CLAMP_MIN_CHARS) return;
  text.id = `question-log-text-${entry.id}`;
  if (expandedIds.has(entry.id)) {
    li.appendChild(buildMoreButton(entry, text));
    return;
  }
  text.classList.add('question-log-text--clamped');
  clampChecks.push({ text, entry });
}

// Erst alle Höhen lesen, dann schreiben (kein Layout-Thrashing). Ohne
// Überlauf fällt die Kürzung weg, damit kein abgeschnittener Text ohne Knopf bleibt.
function runClampChecks() {
  const checks = clampChecks.filter(({ text }) => text.isConnected);
  clampChecks = [];
  const overflowing = checks.map(({ text }) => text.scrollHeight > text.clientHeight);
  checks.forEach(({ text, entry }, i) => {
    if (overflowing[i]) text.after(buildMoreButton(entry, text));
    else text.classList.remove('question-log-text--clamped');
  });
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

// Chip "Chat 3f2a · k/n": Button (textContent, kein innerHTML), schaltet den
// Chat-Filter für diesen Chat ein/aus.
function buildChatChip(cid, k, n) {
  const chip = document.createElement('button');
  chip.type = 'button';
  chip.className = 'question-log-chat-chip';
  const label = t('questionLog.chatChip', { id: shortId(cid), k, n });
  chip.textContent = label;
  chip.setAttribute('aria-label', t('questionLog.chatChipAria', { id: shortId(cid), k, n }));
  chip.setAttribute('aria-pressed', String(activeConversationId === cid));
  chip.addEventListener('click', () => {
    activeConversationId = activeConversationId === cid ? null : cid;
    deleteConversationPending = false;
    applyFilter();
  });
  return chip;
}

function buildEntryElement(entry, k, n, blockStart) {
  let li = document.createElement('li');
  // Fix (2026-09-14, gemeldeter Bug): eine Frage, auf die mehrere
  // Kriterien gleichzeitig zutreffen (z.B. "erste Frage" UND "keine
  // Antwort gefunden"), ist jetzt EIN Eintrag mit mehreren event_types
  // statt zwei separaten, identisch aussehenden Einträgen - bekommt hier
  // entsprechend mehrere Badges/Modifier-Klassen statt nur einer.
  li.className = ['question-log-entry', ...entry.event_types.map((et) => `question-log-entry--${et}`)].join(' ');

  // Inhalt in .question-log-entry-body: trägt den Blockbalken (border-left in
  // --conversation-color) - nie der li selbst, sonst läge er auf Zeitleiste/Punkt.
  const body = document.createElement('div');
  body.className = 'question-log-entry-body';
  const mainLi = li;
  li = body;

  const time = document.createElement('span');
  time.className = 'question-log-time';
  const entryDate = new Date(entry.timestamp);
  // Folgefrage an einem späteren Tag als der Blockstart: Datum mit anzeigen,
  // sonst liest sie sich wie am Starttag (Tagesmarker) gestellt.
  const dateHint = blockStart && !isSameDay(entryDate, new Date(blockStart))
    ? `${entryDate.toLocaleDateString(getLang() === 'de' ? 'de-DE' : 'en-US', { day: '2-digit', month: '2-digit' })} `
    : '';
  time.textContent = dateHint + formatTime(entryDate);
  li.appendChild(time);
  if (entry.conversation_id) li.appendChild(buildChatChip(entry.conversation_id, k, n));

  const badgeKeys = entry.event_types.map((et) => EVENT_TYPE_LABEL_KEYS[et] || EVENT_TYPE_LABEL_KEYS.first_question);
  if (entry.mode === 'creative' && !entry.event_types.includes('creative')) {
    badgeKeys.push('questionLog.eventType.creative');
  }
  if (entry.section) badgeKeys.push('questionLog.eventType.section');
  badgeKeys.forEach((key) => {
    const badge = document.createElement('span');
    badge.className = 'question-log-type-badge';
    badge.textContent = t(key);
    li.appendChild(badge);
  });

  if (entry.event_types.includes('feedback') && entry.feedback) {
    li.appendChild(buildFeedbackBadge(entry.feedback));
  }

  appendQuestionText(li, entry);

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

  mainLi.appendChild(body);
  return mainLi;
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
    expandedIds.delete(entry.id);
    allEntries = allEntries.filter((e) => e.id !== entry.id);
    answerCache.delete(entry.id);
    applyFilter({ resetPaging: false });
  } catch (err) {
    statusEl.textContent = t('questionLog.deleteFailed');
    statusEl.classList.remove('hidden');
  }
}

// Leiste über der Liste: nur bei aktivem Chat-Filter sichtbar, mit
// "Ganzes Gespräch löschen" (zweistufig wie deleteConfirmPendingIds).
function renderChatBar() {
  chatBarEl.replaceChildren();
  chatBarEl.classList.toggle('hidden', !activeConversationId);
  if (!activeConversationId) return;
  const label = document.createElement('span');
  label.className = 'question-log-chat-bar-label';
  label.textContent = t('questionLog.chatFilterActive', { id: shortId(activeConversationId) });
  const del = document.createElement('button');
  del.type = 'button';
  del.className = 'link-button question-log-delete-button question-log-delete-conversation';
  del.textContent = t(deleteConversationPending ? 'questionLog.deleteConversationConfirm' : 'questionLog.deleteConversation');
  del.addEventListener('click', deleteConversation);
  chatBarEl.append(label, del);
}

// Löscht alle Einträge des aktiven Chats (DELETE /api/question-log/conversation/{cid}).
async function deleteConversation() {
  if (!deleteConversationPending) {
    deleteConversationPending = true;
    renderChatBar();
    return;
  }
  const cid = activeConversationId;
  try {
    const res = await fetch(`/api/question-log/conversation/${encodeURIComponent(cid)}`, {
      method: 'DELETE',
      headers: { 'X-Lang': getLang() },
    });
    if (!res.ok) throw new Error();
    allEntries = allEntries.filter((e) => e.conversation_id !== cid);
    activeConversationId = null;
    deleteConversationPending = false;
    applyFilter({ resetPaging: false });
  } catch (err) {
    deleteConversationPending = false;
    renderChatBar();
    statusEl.textContent = t('questionLog.deleteConversationFailed');
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
  renderChatBar();
  if (!filteredBlocks.length) {
    statusEl.textContent = t('questionLog.empty');
    statusEl.classList.remove('hidden');
    return;
  }
  statusEl.classList.add('hidden');

  let gridRow = 0;
  let lastDayKey = null;
  pageBlocks(filteredBlocks, visibleCount).forEach((block, blockIndex) => {
    // Tagesmarker richtet sich nach dem Blockstart: eine Folgefrage am
    // nächsten Tag bleibt im Block unter dem Starttag.
    const date = new Date(block.start);
    const key = dayKey(date);
    let first = null;
    if (key !== lastDayKey) {
      lastDayKey = key;
      gridRow += 1;
      first = buildDayMarker(formatDayLabel(date));
      first.style.gridRow = String(gridRow);
      listEl.appendChild(first);
    }
    block.items.forEach(({ entry, k, n }, i) => {
      gridRow += 1;
      const el = buildEntryElement(entry, k, n, block.start);
      el.style.gridRow = String(gridRow);
      if (block.color) el.style.setProperty('--conversation-color', block.color);
      el.classList.toggle('question-log-entry--in-chat', Boolean(block.color));
      if (i === 0) first = first || el;
      listEl.appendChild(el);
    });
    // Abstand zwischen Blöcken (nicht vor dem ersten).
    if (blockIndex > 0) first.classList.add('question-log-block-start');
  });
  listEl.querySelectorAll('details').forEach((d) => {
    if (openTimestamps.has(d.dataset.timestamp)) d.open = true;
  });
  listEl.style.setProperty('--timeline-row-end', String(gridRow + 1));
  requestAnimationFrame(runClampChecks);

  // Noch nicht gerenderte Blöcke übrig: unsichtbares Sentinel ans Ende, das
  // beim Scrollen die nächste Seite nachlädt (Daten liegen ja schon vor).
  if (filteredBlocks.length > visibleCount) {
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
  filteredBlocks = buildBlocks(allEntries, activeEventTypes, activeConversationId);
  // Passt kein Eintrag des gewählten Chats mehr (Typ-Filter, Löschen): Chat-Filter zurück.
  if (activeConversationId && !filteredBlocks.length) {
    activeConversationId = null;
    deleteConversationPending = false;
    filteredBlocks = buildBlocks(allEntries, activeEventTypes, null);
  }
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
