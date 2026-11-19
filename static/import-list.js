// Quellenliste der Quellenseite: Laden, Sortieren, Rendern, Filter, Suche.
// Aus import.js herausgezogen (Idee 313ad93d). Zyklische Imports mit
// import-authors.js/import-terms.js greifen nur innerhalb von Funktionen zu,
// nie beim Laden des Moduls (sonst TDZ-Fehler).
import { t, getLang } from '/i18n.js';
import { renderMarkdown } from '/markdown.js';
import { currentUserEmail } from '/auth.js';
import { displayTitle, findableTitle, citationHref, translatedBadge } from '/source-lang.js';
import {
  EXTERNAL_LINK_ICON,
  MAGIC_ICON,
  UNDO_DURATION_MS,
  urlErrorText,
  jsonHeaders,
  normalizeAuthor,
  buildEditPanel,
  normalizeTerm,
} from '/source-edit.js';
import {
  EDIT_ICON,
  WARNING_ICON,
  expandedSourceIds,
  hasPflegerRole,
  pendingDeletions,
  state,
} from '/import-state.js';
import { allAuthors, loadAuthors, renderAuthorInfoPanel } from '/import-authors.js';
import { loadTermOverview, renderTermOverview } from '/import-terms.js';

const brokenLinksBtn = document.getElementById('typ-broken-links');

export let allSources = [];
// Die zuletzt an renderSourceList() übergebene, NICHT expandierte Quellenliste
// (z.B. allSources oder eine gefilterte Teilmenge) - wird für Re-Renders der
// gleichen Ansicht (Auf-/Zuklappen, nach Bearbeiten, ...) verwendet. Würde man
// stattdessen currentDisplayedSources erneut übergeben, würde sortSources()
// im Autoren-Modus die dort bereits (Quelle, Autor)-expandierten Einträge bei
// jedem Re-Render erneut expandieren (Quelle erscheint dann mehrfach).
export let currentSourceList = [];
let currentDisplayedSources = [];
// Backlog #57: die Quellenliste wird nicht komplett auf einmal ins DOM
// gerendert, sondern nur die ersten SOURCES_PAGE_SIZE Einträge - beim
// Erreichen des Listenendes (IntersectionObserver auf einem Sentinel-Element,
// siehe renderSourceList) wächst visibleSourceCount um eine weitere Seite.
// Die Daten selbst (allSources) sind weiterhin komplett geladen - es geht
// hier nur um die Menge an gleichzeitig existierenden DOM-Knoten.
const SOURCES_PAGE_SIZE = 20;
let visibleSourceCount = SOURCES_PAGE_SIZE;
let sourceListObserver = null;

// Schlagwort-Ansicht (2026-09-24): dieselbe Quelle kann dort unter mehreren
// aufgeklappten Schlagworten stehen - __editRowKey unterscheidet diese Zeilen
// wie __sortAuthor die Autor:innen-Zeilen.
function editRowKey(s) {
  return s.__editRowKey || s.__sortAuthor || null;
}
function isActiveEditRow(s) {
  return state.activeEditId === s.id && state.activeEditAuthorKey === editRowKey(s);
}

let currentSortMode = 'author';

// Wird bei jedem Wechsel auf eine inhaltlich NEUE Liste aufgerufen (neuer
// Filter, Filter aufgehoben) - nicht aber bei einem bloßen Re-Render der
// gleichen Ansicht (Auf-/Zuklappen, Bearbeiten, Neuladen nach einer Änderung),
// damit die Scroll-/Lade-Position dabei nicht unnötig auf die erste Seite
// zurückspringt.
function resetSourcePagination() {
  visibleSourceCount = SOURCES_PAGE_SIZE;
}

// Stellt sicher, dass eine bestimmte Quelle (z.B. per Deep-Link direkt im
// Bearbeiten-Modus geöffnet) unabhängig von ihrer Position in der sortierten
// Liste bereits im sichtbaren, paginierten Bereich liegt.
export function ensureSourceVisible(sourceId) {
  const index = sortSources(currentSourceList).findIndex((s) => s.id === sourceId);
  if (index >= 0) {
    visibleSourceCount = Math.max(visibleSourceCount, index + 1);
  }
}

// Wird von den Popover-Buttons (url/file/jobs) mitverwendet, damit sich der
// Suchbereich schließt, sobald eine andere Aktion in der Icon-Leiste
// gestartet wird - analog dazu, dass diese sich gegenseitig schließen.
export function closeSearchBar() {
  if (!state.searchBarOpen) return;
  state.searchBarOpen = false;
  document.getElementById('search-bar').classList.add('hidden');
  renderSourceList(currentSourceList);
}

// Anbindung der Bearbeiten-Komponente (static/source-edit.js) an die Liste.
const EDIT_PANEL_CALLBACKS = {
  onSaved() {
    state.activeEditId = null;
    state.activeEditAuthorKey = null;
    loadSources();
    loadAuthors();
  },
  onCancel() {
    state.activeEditId = null;
    state.activeEditAuthorKey = null;
    renderSourceList(currentSourceList);
  },
  onDelete: (s) => scheduleDeletion(s),
  onUndoDelete: (id) => cancelDeletion(id),
  onLinkVerified: () => loadSources(),
};

function scheduleDeletion(s) {
  const timeoutId = setTimeout(async () => {
    pendingDeletions.delete(s.id);
    if (state.activeEditId === s.id) {
      // Löschen betrifft die ganze Quelle, unabhängig davon, unter welcher
      // Autor:in-Zeile gerade bearbeitet wurde - deshalb hier bewusst ohne
      // isActiveEditRow()/__sortAuthor-Abgleich.
      state.activeEditId = null;
      state.activeEditAuthorKey = null;
    }
    try {
      await fetch(`/api/sources/${s.id}`, { method: 'DELETE', headers: jsonHeaders() });
    } catch (err) {
      // Fehler beim endgültigen Löschen: Quelle taucht beim nächsten Laden wieder auf.
    }
    loadSources();
    loadAuthors();
  }, UNDO_DURATION_MS);
  pendingDeletions.set(s.id, { timeoutId });
  renderSourceList(currentSourceList);
}

function cancelDeletion(id) {
  const entry = pendingDeletions.get(id);
  if (entry) {
    clearTimeout(entry.timeoutId);
    pendingDeletions.delete(id);
  }
  renderSourceList(currentSourceList);
}

function buildUndoRow(s) {
  const li = document.createElement('li');
  li.className = 'source-row source-row--deleting';

  const topRow = document.createElement('div');
  topRow.className = 'source-row-top';

  const textSpan = document.createElement('span');
  textSpan.textContent = t('common.deletingStatus', { title: s.title });
  topRow.appendChild(textSpan);

  const undoBtn = document.createElement('button');
  undoBtn.type = 'button';
  undoBtn.className = 'link-button';
  undoBtn.textContent = t('common.undo');
  undoBtn.addEventListener('click', () => cancelDeletion(s.id));
  topRow.appendChild(undoBtn);

  li.appendChild(topRow);

  const bar = document.createElement('div');
  bar.className = 'undo-bar';
  const fill = document.createElement('div');
  fill.className = 'undo-bar-fill';
  bar.appendChild(fill);
  li.appendChild(bar);

  requestAnimationFrame(() => {
    fill.style.transitionDuration = `${UNDO_DURATION_MS}ms`;
    fill.style.width = '0%';
  });

  return li;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function highlightTermsInElement(container, keyTerms) {
  if (!keyTerms || keyTerms.length === 0) return;
  // Von der KI vorgeschlagene Schlagworte dürfen Eigennamen enthalten, die
  // zufällig mit einer erfassten Autor:in übereinstimmen - dieser Abgleich
  // war zu fehleranfällig (z.B. bei Namensgleichheit/-teilen), deshalb werden
  // solche Treffer grundsätzlich nicht mehr hervorgehoben, auch nicht als
  // generisches Schlagwort.
  const filteredTerms = keyTerms.filter(
    (term) => !allAuthors.some((a) => a.name.toLowerCase() === term.toLowerCase())
  );
  if (filteredTerms.length === 0) return;
  const pattern = new RegExp(`(${filteredTerms.map(escapeRegExp).join('|')})`, 'gi');
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  let node = walker.nextNode();
  while (node) {
    pattern.lastIndex = 0;
    if (pattern.test(node.textContent)) textNodes.push(node);
    node = walker.nextNode();
  }
  textNodes.forEach((textNode) => {
    pattern.lastIndex = 0;
    const parts = textNode.textContent.split(pattern);
    if (parts.length <= 1) return;
    const frag = document.createDocumentFragment();
    parts.forEach((part) => {
      const isTerm = filteredTerms.some((term) => term.toLowerCase() === part.toLowerCase());
      if (isTerm) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'term-highlight-button';
        const title = t('import.filterByTermTitle', { term: part });
        btn.title = title;
        btn.setAttribute('aria-label', title);
        const strong = document.createElement('strong');
        strong.textContent = part;
        btn.appendChild(strong);
        btn.addEventListener('click', () => filterByTerm(part));
        frag.appendChild(btn);
      } else if (part) {
        frag.appendChild(document.createTextNode(part));
      }
    });
    textNode.parentNode.replaceChild(frag, textNode);
  });
}

function renderSummaryWithTerms(summaryText, keyTerms) {
  const wrapper = document.createElement('div');
  wrapper.className = 'source-summary-text';
  wrapper.innerHTML = renderMarkdown(summaryText);
  highlightTermsInElement(wrapper, keyTerms);
  return wrapper;
}

export function isFilterActive() {
  return !document.getElementById('source-filter-status').classList.contains('hidden');
}

// Heuristik: Nachname = letztes Wort des Namens (keine getrennten Vor-/
// Nachname-Felder im Datenmodell). Für die alphabetische Autor:innen-
// Sortierung soll "Günther Adam" unter "A" einsortiert werden, nicht unter
// "G" - deckt sich mit gängiger bibliografischer Praxis.
function getSurname(name) {
  const parts = name.trim().split(/\s+/);
  return parts[parts.length - 1];
}

// In der Autor:innen-Sortierung steht bei einer Quelle mit mehreren
// Autor:innen immer die Person voran, deren Nachname gerade die aktuelle
// Sektion bestimmt (__sortAuthor) - z.B. taucht "Günther Adam, Christa
// Bernd" unter "A" auf, aber "Christa Bernd, Günther Adam" unter "B".
function authorsForDisplay(s) {
  if (!s.__sortAuthor || !s.authors || s.authors.length <= 1) return s.authors || [];
  const rest = s.authors.filter((name) => name !== s.__sortAuthor);
  return [s.__sortAuthor, ...rest];
}

// Backlog #65: Alphabet-Sprungleiste - nur in der Autor:innen-Sortierung
// sinnvoll (in der Datums-Ansicht/gefiltert gibt es keine alphabetische
// Ordnung nach Nachnamen) und nur für Buchstaben klickbar, zu denen es
// tatsächlich mindestens eine Quelle gibt.
export const JUMP_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');

function updateAlphabetJumpBar(sorted) {
  const bar = document.getElementById('alphabet-jump-bar');
  if (!bar) return;
  if (state.searchBarOpen || currentSortMode !== 'author' || isFilterActive()) {
    bar.classList.add('hidden');
    bar.replaceChildren();
    return;
  }

  const availableLetters = new Set();
  sorted.forEach((s) => {
    const surname = getSurname(s.__sortAuthor || '');
    if (surname) availableLetters.add(surname[0].toUpperCase());
  });

  bar.classList.toggle('hidden', availableLetters.size === 0);
  bar.replaceChildren();
  JUMP_ALPHABET.forEach((letter) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'alphabet-jump-btn';
    btn.textContent = letter;
    if (availableLetters.has(letter)) {
      const label = t('import.jumpToLetterTitle', { letter });
      btn.title = label;
      btn.setAttribute('aria-label', label);
      btn.addEventListener('click', () => jumpToLetter(letter));
    } else {
      btn.disabled = true;
    }
    bar.appendChild(btn);
  });
}

// Springt zur ersten Quelle, deren Autor:in-Nachname mit "letter" beginnt.
// Liegt dieser Eintrag jenseits der aktuell per Infinite Scroll (Backlog
// #57) geladenen Seite, wird die sichtbare Menge erst erweitert (analog
// ensureSourceVisible bei Deep-Links) - sonst würde der Sprung ins Leere
// laufen, weil die Zeile noch gar nicht im DOM existiert.
function jumpToLetter(letter) {
  const sorted = sortSources(currentSourceList);
  const index = sorted.findIndex((s) => getSurname(s.__sortAuthor || '').toUpperCase().startsWith(letter));
  if (index < 0) return;

  if (index >= visibleSourceCount) {
    visibleSourceCount = index + 1;
    renderSourceList(currentSourceList);
  }

  requestAnimationFrame(() => {
    document
      .querySelector(`#source-list [data-row-index="${index}"]`)
      ?.scrollIntoView({ block: 'start', behavior: 'smooth' });
  });
}

export function sortSources(sources) {
  // In einer bereits gefilterten Ansicht (z.B. "nach Autor:in gefiltert")
  // ist die Liste schon auf die relevanten Quellen eingeschränkt - hier NICHT
  // zusätzlich pro Autor:in expandieren, sonst erscheint eine Quelle mit
  // mehreren Autor:innen mehrfach identisch untereinander.
  if (currentSortMode === 'date' || isFilterActive()) {
    const copy = [...sources];
    copy.sort((a, b) => {
      if (!a.date && !b.date) return displayTitle(a).localeCompare(displayTitle(b));
      if (!a.date) return 1;
      if (!b.date) return -1;
      return b.date.localeCompare(a.date);
    });
    return copy;
  }

  // Autor-Modus: jede:r Autor:in bekommt eine eigene Zwischenüberschrift
  // (Nutzerwunsch 2026-08-31, auch bei nur einer Quelle) - eine Quelle mit
  // mehreren Autor:innen bekommt deshalb einen Eintrag PRO Autor:in, damit
  // sie unter jeder Sektion auffindbar ist. Quellen ganz ohne Autor bleiben
  // ein Eintrag.
  const expanded = [];
  sources.forEach((s) => {
    const sourceAuthors = s.authors || [];
    if (!sourceAuthors.length) {
      expanded.push({ ...s, __sortAuthor: null });
      return;
    }
    sourceAuthors.forEach((authorName) => {
      expanded.push({ ...s, __sortAuthor: authorName });
    });
  });

  expanded.sort((a, b) => {
    const authorA = getSurname(a.__sortAuthor || '￿').toLowerCase();
    const authorB = getSurname(b.__sortAuthor || '￿').toLowerCase();
    if (authorA !== authorB) return authorA.localeCompare(authorB);
    if (!a.date && !b.date) return displayTitle(a).localeCompare(displayTitle(b));
    if (!a.date) return 1;
    if (!b.date) return -1;
    if (a.date !== b.date) return b.date.localeCompare(a.date);
    return displayTitle(a).localeCompare(displayTitle(b));
  });
  return expanded;
}

const MONTH_NAMES = {
  de: [
    'Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
    'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember',
  ],
  en: [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
  ],
};

function formatYear(dateStr) {
  if (!dateStr) return t('common.noDate');
  return dateStr.split('-')[0];
}

function monthYearKey(dateStr) {
  if (!dateStr) return '';
  const [year, month] = dateStr.split('-');
  return `${year}-${month}`;
}

function formatMonthYear(dateStr) {
  if (!dateStr) return t('common.noDate');
  const [year, month] = dateStr.split('-');
  const monthNames = MONTH_NAMES[getLang()] || MONTH_NAMES.en;
  const monthIndex = parseInt(month, 10) - 1;
  const monthName = monthNames[monthIndex] || month;
  return `${monthName} ${year}`;
}

function appendOpenLink(container, citationUrl) {
  const link = document.createElement('a');
  link.href = citationUrl;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.className = 'source-open-link';
  const openLabel = t('common.openSource');
  link.title = openLabel;
  link.setAttribute('aria-label', openLabel);
  link.innerHTML = EXTERNAL_LINK_ICON;
  const target = container.querySelector('p:last-of-type') || container;
  target.appendChild(document.createTextNode(' '));
  target.appendChild(link);
}

export function prependAiIcon(container, tooltipKey = 'import.aiSummaryTooltip') {
  const icon = document.createElement('span');
  icon.className = 'source-summary-icon';
  icon.innerHTML = MAGIC_ICON;
  const tooltip = t(tooltipKey);
  icon.title = tooltip;
  icon.setAttribute('aria-label', tooltip);
  const target = container.querySelector('p:first-of-type') || container;
  target.insertBefore(icon, target.firstChild);
  icon.after(document.createTextNode(' '));
}

function buildSourceDetails(s, citationUrl) {
  const container = document.createElement('div');
  container.className = 'source-summary';

  const summaryEl = renderSummaryWithTerms(s.summary, s.key_terms);
  if (s.summary_ai_generated) prependAiIcon(summaryEl);
  container.appendChild(summaryEl);
  if (citationUrl) appendOpenLink(summaryEl, citationUrl);

  return container;
}

function buildTimelineMarker(label) {
  const li = document.createElement('li');
  li.className = 'timeline-marker';
  li.textContent = label;
  return li;
}

function buildAuthorMarker(name) {
  const li = document.createElement('li');
  li.className = 'author-marker';
  li.textContent = name;
  return li;
}

// ToDo: Anzahl der importierten Quellen in der Überschrift - bewusst NICHT
// aus dem sources-Parameter von renderSourceList() abgeleitet, da der dort
// gelegentlich eine gefilterte Teilmenge ist (Autor:innen-/Begriffs-Filter,
// Alphabet-Sprungziele) - stattdessen immer aus der vollständigen
// allSources-Liste, abzüglich Quellen, die gerade im Lösch-Countdown stehen
// (siehe pendingDeletions/scheduleDeletion) und damit für die Nutzer:in
// bereits als gelöscht gelten.
function updateImportedSourcesCount() {
  const countEl = document.getElementById('imported-sources-count');
  if (!countEl) return;
  const count = allSources.filter((s) => !pendingDeletions.has(s.id)).length;
  countEl.textContent = `(${count})`;
}

// Eine Quelle als Listeneintrag(e): normale Zeile (Titel aufklappbar mit
// Kurzbeschreibung, Autor:innen, Aktionen), ggf. gefolgt vom Bearbeiten-
// Formular, bzw. die Rückgängig-Zeile nach dem Löschen. Genutzt von der
// Quellenliste UND der Schlagwort-Ansicht (Nutzerwunsch 2026-09-24: Quellen
// dort "vor Ort" aufklappen/bearbeiten). Alle Interaktionen zeichnen über
// renderSourceList neu - das aktualisiert in der Schlagwort-Ansicht auch
// diese mit (siehe Ende von renderSourceList).
export function buildSourceEntries(s, rowIndex, options = {}) {
  if (pendingDeletions.has(s.id)) {
    return [isActiveEditRow(s) ? buildEditPanel(s, { ...EDIT_PANEL_CALLBACKS, pendingDeletion: true, rowIndex }) : buildUndoRow(s)];
  }

  const li = document.createElement('li');
  li.className = 'source-row';
  if (s.url_reachable === false) {
    li.classList.add('source-row--unreachable');
  }
  li.dataset.sourceId = s.id;
  // Backlog #65: eindeutiges Sprungziel für die Alphabet-Leiste - anders
  // als data-source-id (mehrdeutig, wenn eine Quelle im Autor:innen-Modus
  // mehrfach expandiert erscheint) trifft der Index in der sortierten
  // Liste immer genau DIESE eine Zeile.
  if (typeof rowIndex === 'number') li.dataset.rowIndex = String(rowIndex);

  const header = document.createElement('div');
  header.className = 'source-row-header';

  // Nutzerwunsch (2026-09-23): eine Quelle mit erkanntem defektem Link
  // (url_reachable === false, siehe source-row--unreachable oben) soll
  // nirgendwo mehr verlinkt werden - auch nicht hier in der eigenen
  // Quellenverwaltung.
  const citationUrl = citationHref(s);
  const hasDetails = !!s.summary;
  const isProcessing = !!s.processing_status;
  // Nutzerwunsch (2026-08-03): "error" zaehlt NICHT als aktiv - da laeuft
  // nichts mehr, das ein manueller Edit ueberschreiben koennte (siehe
  // Kommentar am editBtn unten). Nur pending/running sperren Bearbeiten.
  const isActivelyProcessing = s.processing_status === 'pending' || s.processing_status === 'running';

  const textSpan = document.createElement('span');
  if (hasDetails) {
    const titleBtn = document.createElement('button');
    titleBtn.type = 'button';
    titleBtn.className = 'link-button source-title-toggle';
    titleBtn.textContent = displayTitle(s);
    titleBtn.addEventListener('click', () => {
      if (expandedSourceIds.has(s.id)) {
        expandedSourceIds.delete(s.id);
      } else {
        expandedSourceIds.add(s.id);
      }
      renderSourceList(currentSourceList, options);
    });
    textSpan.appendChild(titleBtn);
  } else {
    textSpan.append(displayTitle(s));
  }
  // EN-UI, fremdsprachiger Text: Hinweis "translated" (siehe source-lang.js).
  const translated = translatedBadge(s);
  if (translated) textSpan.append(' ', translated);
  textSpan.append(' – ');
  if (s.authors && s.authors.length) {
    authorsForDisplay(s).forEach((name, index) => {
      if (index > 0) textSpan.append(', ');
      const authorBtn = document.createElement('button');
      authorBtn.type = 'button';
      authorBtn.className = 'link-button';
      authorBtn.textContent = name;
      authorBtn.addEventListener('click', () => filterByAuthor(name));
      textSpan.appendChild(authorBtn);
    });
  } else {
    textSpan.append(t('common.unknownAuthor'));
  }
  textSpan.append(` (${formatYear(s.date)})`);
  if (s.restricted) {
    const badge = document.createElement('span');
    badge.className = 'restricted-badge';
    badge.textContent = t('common.restrictedBadge');
    textSpan.appendChild(document.createTextNode(' '));
    textSpan.appendChild(badge);
  }
  if (isProcessing) {
    const badge = document.createElement('span');
    badge.className = 'restricted-badge';
    badge.textContent = t('import.processingBadge');
    textSpan.appendChild(document.createTextNode(' '));
    textSpan.appendChild(badge);
  }
  if (options.mentionOnlyIds?.has(s.id)) {
    const badge = document.createElement('span');
    badge.className = 'restricted-badge';
    badge.textContent = t('import.mentionOnlyBadge');
    badge.title = t('import.mentionOnlyBadgeTitle', { name: options.mentionOnlyName || '' });
    textSpan.appendChild(document.createTextNode(' '));
    textSpan.appendChild(badge);
  }
  header.appendChild(textSpan);

  const actions = document.createElement('span');
  actions.className = 'source-row-actions';

  // Nutzerwunsch (2026-11-19): Bild-Icon ganz links in der Aktionsleiste
  // (Stift/Öffnen schieben es nach links), sobald die Quelle
  // Bilder hat (auch ausgeblendete); image_count kommt nur für Pfleger:innen.
  if (s.image_count > 0) {
    const icon = document.createElement('span');
    icon.className = 'source-image-count-icon';
    icon.setAttribute('role', 'img');
    icon.title = t(s.image_count === 1 ? 'import.imageCountTitleOne' : 'import.imageCountTitle', { count: s.image_count });
    icon.setAttribute('aria-label', icon.title);
    icon.innerHTML =
      '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"></rect>' +
      '<circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>';
    actions.appendChild(icon);
  }

  if (s.url_reachable === false) {
    const warning = document.createElement(hasPflegerRole() ? 'button' : 'span');
    if (hasPflegerRole()) warning.type = 'button';
    warning.className = 'icon-button warning-icon';
    // Backlog #163: für Pfleger:innen/Admins den konkreten Fehlergrund
    // direkt im Tooltip ergänzen (url_reason_code/url_status_code sind
    // für alle anderen bereits serverseitig auf null gesetzt, siehe
    // app/main.py: _to_source_out).
    const warnLabel = hasPflegerRole()
      ? `${t('common.urlUnreachable')} – ${urlErrorText(s)}`
      : t('common.urlUnreachable');
    warning.title = warnLabel;
    warning.setAttribute('aria-label', warnLabel);
    warning.innerHTML = WARNING_ICON;
    if (hasPflegerRole()) {
      warning.addEventListener('click', () => {
        if (isActiveEditRow(s)) {
          state.activeEditId = null;
          state.activeEditAuthorKey = null;
        } else {
          state.activeEditId = s.id;
          state.activeEditAuthorKey = editRowKey(s);
        }
        renderSourceList(currentSourceList, options);
      });
    }
    actions.appendChild(warning);
  }

  if (citationUrl) {
    const linkBtn = document.createElement('a');
    linkBtn.href = citationUrl;
    linkBtn.target = '_blank';
    linkBtn.rel = 'noopener noreferrer';
    linkBtn.className = 'icon-button';
    const openLabel = t('common.openSource');
    linkBtn.title = openLabel;
    linkBtn.setAttribute('aria-label', openLabel);
    linkBtn.innerHTML = EXTERNAL_LINK_ICON;
    actions.appendChild(linkBtn);
  }

  if (hasPflegerRole()) {
    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'icon-button';
    // Solange die Quelle noch AKTIV verarbeitet wird (pending/running),
    // würde ein manueller Edit vom später eintreffenden Transkript
    // überschrieben - deshalb für GENAU diese eine Quelle deaktiviert,
    // alle anderen bleiben normal bearbeitbar (das ist ja gerade der Zweck
    // der Hintergrund-Verarbeitung). Bei "error" laeuft dagegen nichts
    // mehr - Bearbeiten ist dort die Reparatur (siehe update_source, das
    // den Fehlerzustand bei erfolgreichem Speichern zuruecksetzt).
    editBtn.disabled = isActivelyProcessing;
    const editLabel = isActivelyProcessing ? t('import.editDisabledWhileProcessing') : t('common.editSource');
    editBtn.title = editLabel;
    editBtn.setAttribute('aria-label', editLabel);
    editBtn.innerHTML = EDIT_ICON;
    editBtn.addEventListener('click', async () => {
      // Fix (2026-08-31): das Bearbeiten-Formular zeigt den Volltext (s.text)
      // - der wird seit der zweiphasigen Ladereihenfolge (siehe loadSources/
      // loadFullSourceText) erst NACH der sichtbaren Liste im Hintergrund
      // nachgeladen. Ohne dieses Warten hätte ein sehr schnelles Klicken
      // kurz nach dem Seitenaufruf ein leeres Textfeld gezeigt - und ein
      // Speichern hätte den echten Volltext der Quelle gelöscht.
      if (fullTextReady) await fullTextReady;
      if (isActiveEditRow(s)) {
        state.activeEditId = null;
        state.activeEditAuthorKey = null;
      } else {
        state.activeEditId = s.id;
        state.activeEditAuthorKey = editRowKey(s);
      }
      renderSourceList(currentSourceList, options);
    });
    actions.appendChild(editBtn);
  }

  header.appendChild(actions);
  li.appendChild(header);

  if (hasDetails && expandedSourceIds.has(s.id)) {
    li.appendChild(buildSourceDetails(s, citationUrl));
  }

  if (isActiveEditRow(s)) return [li, buildEditPanel(s, { ...EDIT_PANEL_CALLBACKS, rowIndex })];
  return [li];
}

export function renderSourceList(sources, options = {}) {
  currentSourceList = sources;
  const sorted = sortSources(sources);
  currentDisplayedSources = sorted;
  updateAlphabetJumpBar(sorted);
  updateImportedSourcesCount();
  const list = document.getElementById('source-list');
  // Schlagwort-Ansicht ersetzt die Quellenliste nur ungefiltert - ein
  // Filter (z.B. "nach diesem Schlagwort filtern") oder die Suche zeigt
  // wieder die passenden Quellen.
  const showTerms = currentSortMode === 'term' && !isFilterActive() && !state.searchBarOpen;
  list.classList.toggle('hidden', showTerms);
  document.getElementById('term-overview').classList.toggle('hidden', !showTerms);
  list.innerHTML = '';
  // Versteckte Quellenliste gar nicht erst aufbauen - ein offenes Bearbeiten-
  // Formular stünde sonst doppelt im DOM (gleiche IDs, Labels träfen das
  // versteckte Feld). Alle Neuzeichnen-Wege laufen über diese Funktion, so
  // bleibt die Schlagwort-Ansicht (mit ihren Quellen-Zeilen) aktuell.
  if (showTerms) {
    sourceListObserver?.disconnect();
    renderTermOverview();
    return;
  }
  let lastMonthYear = null;
  let lastAuthorKey = null;
  let gridRow = 0;
  // In der Timeline-Ansicht braucht jede <li> eine EXPLIZITE Grid-Zeile:
  // ohne das packt CSS-Grid-Auto-Placement eine Quellen-Zeile fälschlich
  // in dieselbe Zeile wie das direkt vorangehende Monat-Jahr-Label
  // (Spalte 3 ist dort ja noch frei) - dadurch verschwanden Punkt und
  // Zeitlinie für genau diese Zeilen.
  const appendTimelineRow = (el) => {
    if (currentSortMode === 'date') {
      gridRow += 1;
      el.style.gridRow = String(gridRow);
    }
    list.appendChild(el);
  };

  const visible = sorted.slice(0, visibleSourceCount);
  visible.forEach((s, rowIndex) => {
    if (currentSortMode === 'date' && !pendingDeletions.has(s.id)) {
      const key = monthYearKey(s.date);
      if (key !== lastMonthYear) {
        appendTimelineRow(buildTimelineMarker(formatMonthYear(s.date)));
        lastMonthYear = key;
      }
    }

    if (currentSortMode === 'author' && !pendingDeletions.has(s.id)) {
      const key = s.__sortAuthor ? normalizeAuthor(s.__sortAuthor) : null;
      const isNewAuthor = key && key !== lastAuthorKey;
      if (isNewAuthor) {
        list.appendChild(buildAuthorMarker(s.__sortAuthor));
      }
      lastAuthorKey = key;
    }

    buildSourceEntries(s, rowIndex, options).forEach(appendTimelineRow);
  });

  if (currentSortMode === 'date') {
    // "-1" als Grid-Zeilen-Ende bezieht sich nur auf EXPLIZIT deklarierte
    // Zeilen (grid-template-rows), nicht auf implizit erzeugte - deshalb hier
    // das tatsächliche Zeilenende als Variable setzen, damit die Zeitlinie
    // (::after) wirklich bis zur letzten Zeile durchläuft.
    list.style.setProperty('--timeline-row-end', String(gridRow + 1));
  }

  // Backlog #57: solange noch mehr Einträge als aktuell gerendert vorhanden
  // sind, ein unsichtbares Sentinel-Element ans Listenende hängen - kommt es
  // beim Scrollen in den sichtbaren Bereich, wird die nächste Seite
  // nachgeladen (d.h. neu gerendert, die Daten liegen ja bereits vor).
  sourceListObserver?.disconnect();
  if (sorted.length > visible.length) {
    const sentinel = document.createElement('li');
    sentinel.className = 'source-list-sentinel';
    list.appendChild(sentinel);
    sourceListObserver = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          sourceListObserver.disconnect();
          visibleSourceCount += SOURCES_PAGE_SIZE;
          renderSourceList(currentSourceList, options);
        }
      },
      { rootMargin: '400px' }
    );
    sourceListObserver.observe(sentinel);
  }

  // Fix: die native Browser-Suche (Cmd/Strg+F) fand bisher nur Titel
  // innerhalb der bereits gerenderten ersten Seite(n) - alles, was die
  // Pagination (Backlog #57) noch nicht nachgeladen hatte, existierte
  // schlicht nicht im DOM und lieferte 0 Treffer. Für jede noch nicht
  // gerenderte Quelle hängen wir deshalb einen minimalen, mit
  // hidden="until-found" versteckten Platzhalter an: Chrome/Edge können
  // solche Elemente trotzdem durchsuchen und blenden sie bei einem Treffer
  // automatisch ein (beforematch-Event), bevor sie zur Fundstelle scrollen.
  // Der Platzhalter wird danach (leicht verzögert, um das synchrone
  // Scrollen der Suche nicht zu stören) durch die vollwertige, interaktive
  // Zeile ersetzt.
  sorted.slice(visible.length).forEach((s) => {
    const placeholder = document.createElement('li');
    placeholder.setAttribute('hidden', 'until-found');
    placeholder.textContent = `${findableTitle(s)} ${authorsForDisplay(s).join(' ')}`;
    placeholder.addEventListener(
      'beforematch',
      () => {
        placeholder.removeAttribute('hidden');
        setTimeout(() => {
          const index = sortSources(currentSourceList).findIndex((entry) => entry.id === s.id);
          if (index >= 0) {
            visibleSourceCount = Math.max(visibleSourceCount, index + 1);
          }
          renderSourceList(currentSourceList, options);
        }, 0);
      },
      { once: true }
    );
    list.appendChild(placeholder);
  });
}

// Der Klick auf einen Autor/Begriff kann von weit unten in der Liste
// kommen (z.B. aus dem Autoren-Verzeichnis oder einer Quellenzeile) - die
// gefilterte Ergebnisliste erscheint aber oben bei "Importierte Quellen",
// deshalb dorthin scrollen statt die aktuelle Scroll-Position zu behalten.
function scrollToFilteredResults() {
  document.getElementById('quellen-liste-bereich')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Merkt sich den aktiven Filter, damit loadSources() (z.B. nach dem
// Aktualisieren/Löschen einer Quelle) ihn erneut anwenden kann, statt
// stillschweigend auf die ungefilterte Liste zurückzufallen.
let activeFilter = null;

export async function applyAuthorFilter(name) {
  // Nutzerwunsch (2026-08-24): Der Klick auf einen im Explore-Netzwerk mit
  // einem Schlagwort zusammengeführten Autor:innen-Knoten (siehe app/
  // main.py:_build_knowledge_graph) soll BEIDE Quellenmengen liefern -
  // eigene Texte UND fremde Texte, die die Person nur als Schlagwort
  // erwähnen (z.B. "Jos de Blok" im Text von Elisabeth Sechser). Ohne
  // diesen Abgleich gegen /api/terms würde applyAuthorFilter nur eigene
  // Texte finden, obwohl der Graph-Knoten längst beides zusammenführt.
  const [authorsRes, termsRes] = await Promise.all([
    fetch('/api/authors', { headers: { 'X-Lang': getLang() } }),
    fetch('/api/terms'),
  ]);
  if (authorsRes.status === 429 || termsRes.status === 429) return showTooManyRequests();
  if (!authorsRes.ok || !termsRes.ok) return;
  const authorEntries = await authorsRes.json();
  const termEntries = await termsRes.json();
  const match = authorEntries.find((a) => normalizeAuthor(a.name) === normalizeAuthor(name));
  const displayName = match ? match.name : name;
  const ownIds = match ? match.source_ids : [];
  const termMatch = termEntries.find((te) => normalizeAuthor(te.term) === normalizeAuthor(name));
  const mentionIds = termMatch ? termMatch.source_ids : [];
  const ids = Array.from(new Set([...ownIds, ...mentionIds]));
  const mentionOnlyIds = new Set(mentionIds.filter((id) => !ownIds.includes(id)));

  document.getElementById('source-filter-label').textContent = t(
    mentionOnlyIds.size > 0
      ? 'import.filteredByAuthorAndMentions'
      : ids.length === 1
        ? 'import.filteredByAuthor'
        : 'import.filteredByAuthorPlural'
  );
  document.getElementById('source-filter-name').textContent = displayName;
  // Muss VOR renderSourceList() gesetzt werden - sortSources() liest den
  // Filter-Status, um die Autoren-Expansion in der gefilterten Ansicht zu
  // unterdrücken (siehe isFilterActive()).
  document.getElementById('source-filter-status').classList.remove('hidden');
  renderSourceList(allSources.filter((s) => ids.includes(s.id)), { mentionOnlyIds, mentionOnlyName: displayName });

  state.filteredAuthorEntry = match || null;
  state.authorPanelEditMode = false;
  renderAuthorInfoPanel();
}

export async function filterByAuthor(name) {
  activeFilter = { type: 'author', value: name };
  resetSourcePagination();
  await applyAuthorFilter(name);
  scrollToFilteredResults();
}

async function applyTermFilter(term) {
  const res = await fetch('/api/terms');
  if (res.status === 429) return showTooManyRequests();
  if (!res.ok) return;
  const termEntries = await res.json();
  const match = termEntries.find((t2) => normalizeTerm(t2.term) === normalizeTerm(term));
  const ids = match ? match.source_ids : [];
  ids.forEach((id) => expandedSourceIds.add(id));

  document.getElementById('source-filter-label').textContent = t('import.filteredByTerm');
  document.getElementById('source-filter-name').textContent = match ? match.term : term;
  document.getElementById('source-filter-status').classList.remove('hidden');
  renderSourceList(allSources.filter((s) => ids.includes(s.id)));

  state.filteredAuthorEntry = null;
  state.authorPanelEditMode = false;
  renderAuthorInfoPanel();
}

export async function filterByTerm(term) {
  activeFilter = { type: 'term', value: term };
  resetSourcePagination();
  await applyTermFilter(term);
  scrollToFilteredResults();
}

// Backlog #94: Volltextsuche - anders als bei Autor/Begriff kein Backend-
// Aufruf nötig, allSources ist bereits vollständig (inkl. Volltext) im
// Speicher geladen, daher direkte, sofortige Filterung pro Tastenanschlag.
function normalizeSearch(value) {
  return (value || '').toLowerCase();
}

function sourceMatchesSearch(source, query) {
  const q = normalizeSearch(query);
  if (!q) return true;
  const haystacks = [
    source.title,
    displayTitle(source),
    source.text,
    source.summary,
    (source.authors || []).join(' '),
    (source.key_terms || []).join(' '),
  ];
  return haystacks.some((h) => normalizeSearch(h).includes(q));
}

// Idee 669405f0: Gäste bekommen nie Volltext - ihre Suche läuft serverseitig
// (GET /api/sources/search liefert nur IDs), 300 ms entprellt.
let guestSearchTimer = null;
let guestSearchSeq = 0;

export function showTooManyRequests() {
  document.getElementById('source-filter-label').textContent = t('import.tooManyRequests');
  document.getElementById('source-filter-name').textContent = '';
}

function showSearchFailed() {
  document.getElementById('source-filter-label').textContent = t('import.searchFailed');
  document.getElementById('source-filter-name').textContent = '';
}

function applyGuestSearch(query) {
  clearTimeout(guestSearchTimer);
  const seq = ++guestSearchSeq;
  guestSearchTimer = setTimeout(async () => {
    try {
      const res = await fetch('/api/sources/search?q=' + encodeURIComponent(query), {
        headers: { 'X-Lang': getLang() },
      });
      if (seq !== guestSearchSeq || activeFilter?.value !== query) return;
      if (res.status === 429) return showTooManyRequests();
      if (!res.ok) return showSearchFailed();
      const ids = new Set((await res.json()).ids);
      if (seq !== guestSearchSeq || activeFilter?.value !== query) return;
      renderSourceList(allSources.filter((s) => ids.has(s.id)));
    } catch {
      if (seq === guestSearchSeq) showSearchFailed();
    }
  }, 300);
}

function applySearchFilter(query) {
  document.getElementById('source-filter-label').textContent = t('import.filteredBySearch');
  document.getElementById('source-filter-name').textContent = query;
  document.getElementById('source-filter-status').classList.remove('hidden');
  if (currentUserEmail()) {
    renderSourceList(allSources.filter((s) => sourceMatchesSearch(s, query)));
  } else if (query.length < 2) {
    renderSourceList(allSources);
  } else {
    applyGuestSearch(query);
  }

  state.filteredAuthorEntry = null;
  state.authorPanelEditMode = false;
  renderAuthorInfoPanel();
}

export function searchSources(query) {
  activeFilter = { type: 'search', value: query };
  resetSourcePagination();
  applySearchFilter(query);
}

// Backlog (2026-08-02): Filter auf Quellen mit defektem Link, erreichbar
// über den neuen Button in der Toolbar (Badge zeigt die Anzahl) - kein
// eigener Backend-Aufruf nötig, url_reachable steckt bereits in allSources
// (siehe GET /api/sources).
function applyBrokenLinksFilter() {
  document.getElementById('source-filter-label').textContent = t('import.filteredByBrokenLinks');
  document.getElementById('source-filter-name').textContent = '';
  document.getElementById('source-filter-status').classList.remove('hidden');
  renderSourceList(allSources.filter((s) => s.url_reachable === false));

  state.filteredAuthorEntry = null;
  state.authorPanelEditMode = false;
  renderAuthorInfoPanel();
}

export function filterByBrokenLinks() {
  activeFilter = { type: 'broken-links', value: null };
  resetSourcePagination();
  applyBrokenLinksFilter();
  scrollToFilteredResults();
}

// Zählt bei jedem Laden/Neuladen neu, wie viele Quellen aktuell einen
// defekten Link haben, und spiegelt das im Zähler-Badge am Toolbar-Button.
// Der Button selbst wird bei 0 defekten Links komplett ausgeblendet (nicht
// nur das Badge) - ohne betroffene Quellen gibt es nichts zu filtern.
function updateBrokenLinksButton() {
  const badge = document.getElementById('broken-links-count-badge');
  if (!badge) return;
  const count = allSources.filter((s) => s.url_reachable === false).length;
  badge.textContent = String(count);
  badge.classList.toggle('hidden', count === 0);
  brokenLinksBtn.classList.toggle('hidden', !hasPflegerRole() || count === 0);
}

// scroll=false beim Leeren des Suchfelds während des Tippens - die Ansicht
// soll dabei nicht plötzlich unter der noch fokussierten, oben in der
// Kopfzeile sitzenden Suchbox wegspringen (anders als beim expliziten
// Klick auf "Alle anzeigen", wo ein Sprung an den Listenanfang erwartet wird).
export function clearSourceFilter({ scroll = true } = {}) {
  activeFilter = null;
  resetSourcePagination();
  document.getElementById('source-filter-status').classList.add('hidden');
  document.getElementById('search-input').value = '';
  renderSourceList(allSources);
  state.filteredAuthorEntry = null;
  state.authorPanelEditMode = false;
  renderAuthorInfoPanel();
  if (scroll) scrollToFilteredResults();
}

export function setSortMode(mode) {
  currentSortMode = mode;
  document.getElementById('sort-author').classList.toggle('active', mode === 'author');
  document.getElementById('sort-date').classList.toggle('active', mode === 'date');
  document.getElementById('sort-term').classList.toggle('active', mode === 'term');
  document.getElementById('source-list').classList.toggle('timeline-mode', mode === 'date');
  renderSourceList(currentSourceList);
}

// Nutzerwunsch (2026-08-31): erst die sichtbare Liste laden, den Volltext
// (nur für die client-seitige Volltextsuche, Backlog #94 - sonst nirgends
// gebraucht außer im Bearbeiten-Formular, siehe editBtn unten) danach im
// Hintergrund nachladen - GET /api/sources?include_text=false ist um
// Größenordnungen kleiner als die Vollversion und lässt die Liste sofort
// erscheinen, statt auf mehrere MB Volltext aller Quellen zu warten.
export let fullTextReady = null;

export async function loadSources() {
  const res = await fetch('/api/sources?include_text=false', {
    headers: { 'X-Lang': getLang() },
  });
  if (res.status === 429) {
    showTooManyRequests();
    document.getElementById('source-filter-status').classList.remove('hidden');
    return;
  }
  if (!res.ok) return;
  allSources = await res.json();
  // Ein aktiver Autor:innen-/Begriffs-/Broken-Links-Filter soll ein
  // Neuladen (z.B. nach dem Aktualisieren oder Löschen einer Quelle)
  // überleben, statt stillschweigend auf die ungefilterte Liste
  // zurückzuspringen.
  if (activeFilter?.type === 'author') {
    await applyAuthorFilter(activeFilter.value);
  } else if (activeFilter?.type === 'term') {
    await applyTermFilter(activeFilter.value);
  } else if (activeFilter?.type === 'search') {
    applySearchFilter(activeFilter.value);
  } else if (activeFilter?.type === 'broken-links') {
    applyBrokenLinksFilter();
  } else {
    renderSourceList(allSources);
    state.filteredAuthorEntry = null;
    state.authorPanelEditMode = false;
    renderAuthorInfoPanel();
  }
  updateBrokenLinksButton();
  loadTermOverview();

  if (currentUserEmail()) fullTextReady = loadFullSourceText();
}

async function loadFullSourceText() {
  const res = await fetch('/api/sources', { headers: { 'X-Lang': getLang() } });
  const full = await res.json();
  const textById = new Map(full.map((s) => [s.id, s.text]));
  allSources.forEach((s) => {
    if (textById.has(s.id)) s.text = textById.get(s.id);
  });
  // Eine bereits laufende Volltextsuche sah bis hierhin nur die Titel/
  // Zusammenfassungen/Autor:innen/Schlagworte der schlanken Liste - jetzt mit
  // vollständigen Daten erneut filtern, damit Volltext-Treffer nicht fehlen.
  if (activeFilter?.type === 'search') {
    applySearchFilter(activeFilter.value);
  }
}
