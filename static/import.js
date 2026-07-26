import { initI18n, t, getLang } from '/i18n.js';
import { renderMarkdown } from '/markdown.js';
import { initAuth, hasRole, onAuthChange } from '/auth.js';

const importBereich = document.getElementById('import-bereich');
const urlPopover = document.getElementById('url-popover');
const filePopover = document.getElementById('file-popover');
const quelltypBereich = document.getElementById('quelltyp-bereich');
const reindexBereich = document.getElementById('reindex-bereich');

const EDIT_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M12 20h9"></path>' +
  '<path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"></path>' +
  "</svg>";

const EXTERNAL_LINK_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>' +
  '<polyline points="15 3 21 3 21 9"></polyline>' +
  '<line x1="10" y1="14" x2="21" y2="3"></line>' +
  "</svg>";

const TRASH_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<polyline points="3 6 5 6 21 6"></polyline>' +
  '<path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>' +
  '<path d="M10 11v6"></path><path d="M14 11v6"></path>' +
  '<path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path>' +
  "</svg>";

const MAGIC_ICON =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor" stroke="none">' +
  '<path d="M12 2l1.8 5.2L19 9l-5.2 1.8L12 16l-1.8-5.2L5 9l5.2-1.8L12 2z"></path>' +
  '<path d="M19 13l.9 2.1L22 16l-2.1.9L19 19l-.9-2.1L16 16l2.1-.9L19 13z"></path>' +
  "</svg>";

const WARNING_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M14 4l1.5-1.5a3.54 3.54 0 1 1 5 5L19 9"></path>' +
  '<path d="M10 15l-1.5 1.5a3.54 3.54 0 1 1-5-5L5 10"></path>' +
  '<line x1="3" y1="3" x2="21" y2="21"></line>' +
  "</svg>";

const PLUS_ICON =
  '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<line x1="12" y1="5" x2="12" y2="19"></line>' +
  '<line x1="5" y1="12" x2="19" y2="12"></line>' +
  "</svg>";

const REMOVE_ICON =
  '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<line x1="5" y1="12" x2="19" y2="12"></line>' +
  "</svg>";


const UNDO_DURATION_MS = 30000;

function wrapSelection(textarea, marker) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const before = textarea.value.slice(0, start);
  const selected = textarea.value.slice(start, end) || t('import.markupPlaceholder');
  const after = textarea.value.slice(end);
  textarea.value = `${before}${marker}${selected}${marker}${after}`;
  textarea.focus();
  textarea.selectionStart = start + marker.length;
  textarea.selectionEnd = start + marker.length + selected.length;
}

function insertHeading(textarea) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const before = textarea.value.slice(0, start);
  const selected = textarea.value.slice(start, end) || t('import.markupPlaceholder');
  const after = textarea.value.slice(end);
  const lineStart = before.lastIndexOf('\n') + 1;
  textarea.value = `${before.slice(0, lineStart)}## ${before.slice(lineStart)}${selected}${after}`;
  textarea.focus();
}

function buildMarkupToolbar(textarea) {
  const toolbar = document.createElement('div');
  toolbar.className = 'markup-toolbar';

  const buttons = [
    { text: 'B', className: 'markup-bold', titleKey: 'import.markupBold', action: () => wrapSelection(textarea, '**') },
    { text: 'I', className: 'markup-italic', titleKey: 'import.markupItalic', action: () => wrapSelection(textarea, '*') },
    { text: 'H', className: 'markup-heading', titleKey: 'import.markupHeading', action: () => insertHeading(textarea) },
  ];

  buttons.forEach((cfg) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `markup-button ${cfg.className}`;
    btn.textContent = cfg.text;
    btn.title = t(cfg.titleKey);
    btn.addEventListener('click', cfg.action);
    toolbar.appendChild(btn);
  });

  return toolbar;
}

let allSources = [];
// Die zuletzt an renderSourceList() übergebene, NICHT expandierte Quellenliste
// (z.B. allSources oder eine gefilterte Teilmenge) - wird für Re-Renders der
// gleichen Ansicht (Auf-/Zuklappen, nach Bearbeiten, ...) verwendet. Würde man
// stattdessen currentDisplayedSources erneut übergeben, würde sortSources()
// im Autoren-Modus die dort bereits (Quelle, Autor)-expandierten Einträge bei
// jedem Re-Render erneut expandieren (Quelle erscheint dann mehrfach).
let currentSourceList = [];
let currentDisplayedSources = [];
let activeEditId = null;
let pendingUploadId = null;
let currentSortMode = 'author';
const pendingDeletions = new Map();
const unreachableSourceIds = new Set();
const expandedSourceIds = new Set();

let allAuthors = [];
// Das aktuell nach Filter angezeigte Autor:innen-Profil (nur gesetzt, wenn
// per Namen gefiltert wird) - steuert die zweigeteilte Ansicht neben der
// gefilterten Quellenliste (buildAuthorInfoView/buildAuthorEditPanel).
let filteredAuthorEntry = null;
let authorPanelEditMode = false;

function hasPflegerRole() {
  return hasRole('quellen_pfleger');
}

function devUserHeaders() {
  // Name beibehalten (viele Call-Sites), sendet aber keinen Header mehr -
  // die Identität kommt jetzt automatisch über das Session-Cookie mit.
  return {
    'Content-Type': 'application/json',
    'X-Lang': getLang(),
  };
}

function updateSourceManagementVisibility() {
  quelltypBereich.classList.toggle('hidden', !hasPflegerRole());
  reindexBereich.classList.toggle('hidden', !hasPflegerRole());
  if (!hasPflegerRole()) {
    importBereich.classList.add('hidden');
    urlPopover.classList.add('hidden');
    filePopover.classList.add('hidden');
  }
}

function showForm() {
  importBereich.classList.remove('hidden');
  urlPopover.classList.add('hidden');
  filePopover.classList.add('hidden');
  // Sonst stand nach einem erfolgreichen Import und direktem Anlegen der
  // nächsten Quelle noch die alte Erfolgsmeldung unter dem Formular.
  document.getElementById('import-status').textContent = '';
}

function fillForm({
  title = '',
  authors = [],
  date = '',
  url = '',
  text = '',
  restricted = false,
}) {
  document.getElementById('title').value = title;
  renderCreateAuthorDateRow(authors, date);
  document.getElementById('url').value = url;
  document.getElementById('text').value = text;
  document.getElementById('restricted').checked = restricted;
}

document.getElementById('typ-text').addEventListener('click', () => {
  pendingUploadId = null;
  fillForm({});
  showForm();
});

document.getElementById('typ-url').addEventListener('click', () => {
  importBereich.classList.add('hidden');
  filePopover.classList.add('hidden');
  urlPopover.classList.toggle('hidden');
  document.getElementById('popover-status').textContent = '';
  if (!urlPopover.classList.contains('hidden')) {
    document.getElementById('popover-url').focus();
  }
});

document.getElementById('typ-file').addEventListener('click', () => {
  importBereich.classList.add('hidden');
  urlPopover.classList.add('hidden');
  filePopover.classList.toggle('hidden');
  document.getElementById('upload-status').textContent = '';
});

document.getElementById('popover-load').addEventListener('click', async () => {
  const url = document.getElementById('popover-url').value.trim();
  const status = document.getElementById('popover-status');
  if (!url) {
    status.textContent = t('import.pleaseEnterUrl');
    return;
  }
  const existing = findExistingSourceByUrl(url);
  if (existing) {
    status.textContent = t('import.urlAlreadyExists', { title: existing.title });
    return;
  }
  status.textContent = t('import.loadingExtracting');
  try {
    const res = await fetch('/api/extract-url', {
      method: 'POST',
      headers: devUserHeaders(),
      body: JSON.stringify({ url }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('import.extractionFailedGeneric'));
    }
    const data = await res.json();
    pendingUploadId = null;
    if (!data.extracted) {
      status.textContent = t('import.extractionEmpty');
      fillForm({ url });
      showForm();
      return;
    }
    fillForm({ title: data.title, authors: data.authors, date: data.date, url, text: data.text });
    showForm();
  } catch (err) {
    status.textContent = t('common.errorPrefix') + err.message;
  }
});

document.getElementById('popover-upload').addEventListener('click', async () => {
  const fileInput = document.getElementById('popover-file');
  const status = document.getElementById('upload-status');
  const file = fileInput.files[0];
  if (!file) {
    status.textContent = t('import.pleaseChooseFile');
    return;
  }
  status.textContent = t('import.uploadingExtracting');
  try {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch('/api/extract-pdf-upload', {
      method: 'POST',
      headers: { 'X-Lang': getLang() },
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('import.uploadFailedGeneric'));
    }
    const data = await res.json();
    pendingUploadId = data.upload_id;
    if (!data.extracted) {
      status.textContent = t('import.extractionEmpty');
      fillForm({});
      showForm();
      return;
    }
    fillForm({ title: data.title, authors: data.authors, date: data.date, text: data.text });
    showForm();
  } catch (err) {
    status.textContent = t('common.errorPrefix') + err.message;
  }
});

function normalizeAuthor(name) {
  return name.trim().split(/\s+/).join(' ').toLowerCase();
}

// Analog zu app/extraction.py:_extract_video_id() - dieselbe Quelle kann
// unter mehreren URL-Formen eingefügt werden (youtu.be/ID vs.
// youtube.com/watch?v=ID, zusätzliche Parameter wie "&t=42s"), die der
// generische String-Vergleich unten sonst als unterschiedlich ansieht.
function extractYoutubeVideoId(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  const host = parsed.hostname.toLowerCase();
  if (host.includes('youtu.be')) {
    return parsed.pathname.replace(/^\/+/, '').split('/')[0] || null;
  }
  if (host.includes('youtube.com')) {
    if (parsed.pathname === '/watch') {
      return parsed.searchParams.get('v');
    }
    if (parsed.pathname.startsWith('/shorts/')) {
      return parsed.pathname.split('/shorts/')[1].split('/')[0] || null;
    }
  }
  return null;
}

function normalizeUrlForComparison(url) {
  const videoId = extractYoutubeVideoId(url);
  if (videoId) return `youtube:${videoId.toLowerCase()}`;
  return url.trim().replace(/\/+$/, '').toLowerCase();
}

function findExistingSourceByUrl(url) {
  const normalized = normalizeUrlForComparison(url);
  if (!normalized) return null;
  return allSources.find((s) => s.url && normalizeUrlForComparison(s.url) === normalized) || null;
}

function buildFieldLabelWithId(labelKey, id, value, type) {
  const label = document.createElement('label');
  label.textContent = t(labelKey);
  const input = document.createElement(type === 'textarea' ? 'textarea' : 'input');
  if (type !== 'textarea') input.type = type;
  else input.rows = 10;
  input.id = id;
  input.value = value || '';
  label.appendChild(input);
  return { label, input };
}

// Wird sowohl im Bearbeiten- als auch im Neu-anlegen-Formular verwendet
// (siehe unten im Skript), damit Autor(en)/Datum an genau einer Stelle
// gepflegt werden und in beiden Masken automatisch gleich aussehen.
// Eine Quelle kann mehrere Autor:innen haben - das erste Feld steht mit dem
// Datum in einer Zeile, über das "+"-Icon lassen sich beliebig viele weitere
// Autoren-Zeilen darunter ergänzen (jede mit eigenem "+"), ab der zweiten
// Zeile zusätzlich mit einem "-"-Icon zum Entfernen.
function buildAuthorFields(authorId, authorValues, dateId, dateValue) {
  const values = authorValues && authorValues.length ? authorValues : [''];

  function buildAuthorInput(value) {
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'author-input';
    input.setAttribute('list', 'author-suggestions');
    input.setAttribute('autocomplete', 'off');
    input.value = value || '';
    return input;
  }

  function buildAddButton(insertNewRow) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-button add-author-btn';
    btn.innerHTML = PLUS_ICON;
    const label = t('import.addAuthor');
    btn.title = label;
    btn.setAttribute('aria-label', label);
    btn.addEventListener('click', () => insertNewRow(buildExtraRow('')));
    return btn;
  }

  function buildRemoveButton(row) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-button remove-author-btn';
    btn.innerHTML = REMOVE_ICON;
    const label = t('import.removeAuthor');
    btn.title = label;
    btn.setAttribute('aria-label', label);
    btn.addEventListener('click', () => row.remove());
    return btn;
  }

  function buildExtraRow(value) {
    const row = document.createElement('div');
    row.className = 'author-extra-row';
    row.appendChild(buildAuthorInput(value));
    row.appendChild(buildAddButton((newRow) => row.insertAdjacentElement('afterend', newRow)));
    row.appendChild(buildRemoveButton(row));
    return row;
  }

  const extraRowsContainer = document.createElement('div');
  extraRowsContainer.className = 'author-extra-rows';
  values.slice(1).forEach((value) => {
    extraRowsContainer.appendChild(buildExtraRow(value));
  });

  const firstInput = buildAuthorInput(values[0]);
  firstInput.id = authorId;
  const authorInputGroup = document.createElement('span');
  authorInputGroup.className = 'author-input-group';
  authorInputGroup.appendChild(firstInput);
  authorInputGroup.appendChild(buildAddButton((newRow) => extraRowsContainer.prepend(newRow)));

  const authorLabel = document.createElement('label');
  authorLabel.textContent = t('import.fieldAuthor');
  authorLabel.appendChild(authorInputGroup);

  const dateField = buildFieldLabelWithId('import.fieldDate', dateId, dateValue, 'date');

  const row = document.createElement('div');
  row.className = 'field-row';
  row.appendChild(authorLabel);
  row.appendChild(dateField.label);

  const wrapper = document.createElement('div');
  wrapper.className = 'author-fields';
  wrapper.appendChild(row);
  wrapper.appendChild(extraRowsContainer);

  function getAuthorValues() {
    return [...wrapper.querySelectorAll('.author-input')]
      .map((input) => input.value.trim())
      .filter((value) => value);
  }

  return { wrapper, dateInput: dateField.input, getAuthorValues };
}

function buildEditPanel(s, options = {}) {
  const pendingDeletion = !!options.pendingDeletion;

  const li = document.createElement('li');
  li.className = 'source-edit-panel';
  if (pendingDeletion) {
    li.classList.add('source-edit-panel--pending-deletion');
  }

  const form = document.createElement('form');
  const status = document.createElement('p');
  status.className = 'edit-status';

  function buildFieldLabel(labelKey, idSuffix, value, type) {
    const label = document.createElement('label');
    label.textContent = t(labelKey);
    const input = document.createElement(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') input.type = type;
    else input.rows = 10;
    input.id = `edit-${idSuffix}-${s.id}`;
    input.value = value || '';
    label.appendChild(input);
    // Explizit setzen statt auf die implizite "erstes labelfähiges Kind"-Regel
    // zu vertrauen - sonst wird ein später in dieses Label eingefügter Button
    // (z.B. das Öffnen-Icon vor dem URL-Feld) zum Klick-Ziel des gesamten
    // Labels, und ein Klick irgendwo in der Zeile löst den Button aus statt
    // nur einen Klick direkt auf das Icon.
    label.htmlFor = input.id;
    return { label, input };
  }

  function field(labelKey, idSuffix, value, type) {
    const { label, input } = buildFieldLabel(labelKey, idSuffix, value, type);
    form.appendChild(label);
    return input;
  }

  const titleInput = field('import.fieldTitle', 'title', s.title, 'text');
  titleInput.required = true;

  const {
    wrapper: authorFieldsWrapper,
    dateInput,
    getAuthorValues,
  } = buildAuthorFields(`edit-author-${s.id}`, s.authors, `edit-date-${s.id}`, s.date);
  form.appendChild(authorFieldsWrapper);

  const urlField = buildFieldLabel('import.fieldUrl', 'url', s.url, 'url');
  const urlInput = urlField.input;
  const openUrlBtn = document.createElement('button');
  openUrlBtn.type = 'button';
  openUrlBtn.className = 'icon-button label-inline-icon';
  const openUrlLabel = t('common.openSource');
  openUrlBtn.title = openUrlLabel;
  openUrlBtn.setAttribute('aria-label', openUrlLabel);
  openUrlBtn.innerHTML = EXTERNAL_LINK_ICON;
  openUrlBtn.addEventListener('click', () => {
    const value = urlInput.value.trim();
    if (value) window.open(value, '_blank', 'noopener,noreferrer');
  });
  urlField.label.insertBefore(openUrlBtn, urlInput);
  form.appendChild(urlField.label);

  const listenUrlField = buildFieldLabel('import.fieldListenUrl', 'listen-url', s.listen_url, 'url');
  const listenUrlInput = listenUrlField.input;
  if (s.has_audio) {
    form.appendChild(listenUrlField.label);
  }

  const textInput = field('import.fieldText', 'text', s.text, 'textarea');
  if (s.restricted) {
    textInput.placeholder = t('import.restrictedTextPlaceholder');
  } else {
    textInput.required = true;
  }

  const toolbarRow = document.createElement('div');
  toolbarRow.className = 'markup-toolbar-row';
  toolbarRow.appendChild(buildMarkupToolbar(textInput));

  if (s.has_pdf) {
    const pdfBtn = document.createElement('button');
    pdfBtn.type = 'button';
    pdfBtn.className = 'link-button';
    pdfBtn.textContent = t('import.openPdf');
    pdfBtn.addEventListener('click', async () => {
      // Fenster MUSS synchron innerhalb des Klick-Handlers geöffnet werden -
      // ruft man window.open() erst nach einem await (fetch/blob), fehlt der
      // Bezug zur User-Geste und der Browser blockiert das Popup lautlos.
      const pdfWindow = window.open('', '_blank');
      try {
        const res = await fetch(`/api/sources/${s.id}/pdf`, { headers: devUserHeaders() });
        if (!res.ok) throw new Error(t('import.openPdfFailed'));
        const blob = await res.blob();
        if (pdfWindow) {
          pdfWindow.location = URL.createObjectURL(blob);
        } else {
          window.open(URL.createObjectURL(blob), '_blank');
        }
      } catch (err) {
        if (pdfWindow) pdfWindow.close();
        status.textContent = t('common.errorPrefix') + err.message;
      }
    });
    toolbarRow.appendChild(pdfBtn);
  }

  textInput.parentNode.insertBefore(toolbarRow, textInput);

  const restrictedLabel = document.createElement('label');
  restrictedLabel.className = 'checkbox-label';
  const restrictedInput = document.createElement('input');
  restrictedInput.type = 'checkbox';
  restrictedInput.checked = !!s.restricted;
  const restrictedText = document.createElement('span');
  restrictedText.textContent = t('import.restrictedLabel');
  restrictedLabel.appendChild(restrictedInput);
  restrictedLabel.appendChild(restrictedText);
  form.appendChild(restrictedLabel);

  const summaryInput = field('import.fieldSummary', 'summary', s.summary, 'textarea');
  summaryInput.rows = 4;
  const keyTermsInput = field(
    'import.fieldKeyTerms',
    'key-terms',
    (s.key_terms || []).join(', '),
    'text'
  );

  if (!pendingDeletion) {
    const magicButtons = [];
    const triggerGenerate = () =>
      generateSummaryFields(s.id, summaryInput, keyTermsInput, status, magicButtons);
    magicButtons.push(addMagicButton(summaryInput, triggerGenerate));
    magicButtons.push(addMagicButton(keyTermsInput, triggerGenerate));
  }

  if (pendingDeletion) {
    [
      titleInput,
      ...authorFieldsWrapper.querySelectorAll('.author-input'),
      dateInput,
      urlInput,
      listenUrlInput,
      textInput,
      restrictedInput,
      summaryInput,
      keyTermsInput,
    ].forEach((input) => {
      input.disabled = true;
    });
  }

  const actionsRow = document.createElement('div');
  actionsRow.className = 'edit-panel-actions';

  if (pendingDeletion) {
    const noticeRow = document.createElement('div');
    noticeRow.className = 'source-row-top';

    const noticeText = document.createElement('span');
    noticeText.textContent = t('common.deletingStatus', { title: s.title });
    noticeRow.appendChild(noticeText);

    const undoBtn = document.createElement('button');
    undoBtn.type = 'button';
    undoBtn.className = 'link-button';
    undoBtn.textContent = t('common.undo');
    undoBtn.addEventListener('click', () => cancelDeletion(s.id));
    noticeRow.appendChild(undoBtn);

    form.appendChild(noticeRow);

    const bar = document.createElement('div');
    bar.className = 'undo-bar';
    const fill = document.createElement('div');
    fill.className = 'undo-bar-fill';
    bar.appendChild(fill);
    form.appendChild(bar);

    requestAnimationFrame(() => {
      fill.style.transitionDuration = `${UNDO_DURATION_MS}ms`;
      fill.style.width = '0%';
    });
  } else {
    const primaryActions = document.createElement('div');

    const submitBtn = document.createElement('button');
    submitBtn.type = 'submit';
    submitBtn.textContent = t('import.updateButton');
    primaryActions.appendChild(submitBtn);

    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'link-button';
    cancelBtn.textContent = t('common.cancel');
    cancelBtn.addEventListener('click', () => {
      activeEditId = null;
      renderSourceList(currentSourceList);
    });
    primaryActions.appendChild(cancelBtn);

    actionsRow.appendChild(primaryActions);

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'icon-button delete-button';
    const deleteLabel = t('common.deleteSource');
    deleteBtn.title = deleteLabel;
    deleteBtn.setAttribute('aria-label', deleteLabel);
    deleteBtn.innerHTML = TRASH_ICON;
    deleteBtn.addEventListener('click', () => scheduleDeletion(s));
    actionsRow.appendChild(deleteBtn);
  }

  form.appendChild(actionsRow);
  form.appendChild(status);

  if (!pendingDeletion) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      status.textContent = t('import.updating');
      try {
        const res = await fetch(`/api/sources/${s.id}`, {
          method: 'PUT',
          headers: devUserHeaders(),
          body: JSON.stringify({
            title: titleInput.value,
            authors: getAuthorValues(),
            date: dateInput.value || null,
            url: urlInput.value || null,
            listen_url: listenUrlInput.value || null,
            text: textInput.value,
            restricted: restrictedInput.checked,
            summary: summaryInput.value,
            key_terms: keyTermsInput.value
              .split(',')
              .map((term) => term.trim())
              .filter((term) => term),
          }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || t('import.updateFailed'));
        }
        activeEditId = null;
        loadSources();
        loadAuthors();
      } catch (err) {
        status.textContent = t('common.errorPrefix') + err.message;
      }
    });
  }

  li.appendChild(form);
  return li;
}

function addMagicButton(input, onClick, titleKey = 'import.generateSummaryTitle') {
  const wrapper = document.createElement('div');
  wrapper.className = 'field-with-magic';
  input.parentNode.insertBefore(wrapper, input);
  wrapper.appendChild(input);

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'magic-button';
  const title = t(titleKey);
  btn.title = title;
  btn.setAttribute('aria-label', title);
  btn.innerHTML = MAGIC_ICON;
  btn.addEventListener('click', onClick);
  wrapper.appendChild(btn);
  return btn;
}

async function generateSummaryFields(sourceId, summaryInput, keyTermsInput, statusEl, buttons) {
  buttons.forEach((b) => {
    b.disabled = true;
  });
  statusEl.textContent = t('import.generatingSummary');
  try {
    const res = await fetch(`/api/sources/${sourceId}/generate-summary`, {
      method: 'POST',
      headers: devUserHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('import.generateSummaryFailed'));
    }
    const data = await res.json();
    if (!summaryInput.value.trim()) summaryInput.value = data.summary;
    if (!keyTermsInput.value.trim()) keyTermsInput.value = data.key_terms.join(', ');
    statusEl.textContent = '';
  } catch (err) {
    statusEl.textContent = t('common.errorPrefix') + err.message;
  } finally {
    buttons.forEach((b) => {
      b.disabled = false;
    });
  }
}

function scheduleDeletion(s) {
  const timeoutId = setTimeout(async () => {
    pendingDeletions.delete(s.id);
    if (activeEditId === s.id) {
      activeEditId = null;
    }
    try {
      await fetch(`/api/sources/${s.id}`, { method: 'DELETE', headers: devUserHeaders() });
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
  const pattern = new RegExp(`(${keyTerms.map(escapeRegExp).join('|')})`, 'gi');
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
      const isTerm = keyTerms.some((term) => term.toLowerCase() === part.toLowerCase());
      if (isTerm) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'term-link';
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

function isFilterActive() {
  return !document.getElementById('source-filter-status').classList.contains('hidden');
}

function sortSources(sources) {
  // In einer bereits gefilterten Ansicht (z.B. "nach Autor:in gefiltert")
  // ist die Liste schon auf die relevanten Quellen eingeschränkt - hier NICHT
  // zusätzlich pro Autor:in expandieren, sonst erscheint eine Quelle mit
  // mehreren Autor:innen mehrfach identisch untereinander.
  if (currentSortMode === 'date' || isFilterActive()) {
    const copy = [...sources];
    copy.sort((a, b) => {
      if (!a.date && !b.date) return a.title.localeCompare(b.title);
      if (!a.date) return 1;
      if (!b.date) return -1;
      return b.date.localeCompare(a.date);
    });
    return copy;
  }

  // Autor-Modus: eine Quelle mit mehreren Autor:innen bekommt einen Eintrag
  // PRO Autor (__sortAuthor), damit sie unter jedem ihrer Autor:innen als
  // eigene Sektion erscheint. Quellen ganz ohne Autor bleiben ein Eintrag.
  const expanded = [];
  sources.forEach((s) => {
    if (s.authors && s.authors.length) {
      s.authors.forEach((authorName) => {
        expanded.push({ ...s, __sortAuthor: authorName });
      });
    } else {
      expanded.push({ ...s, __sortAuthor: null });
    }
  });

  expanded.sort((a, b) => {
    const authorA = (a.__sortAuthor || '￿').toLowerCase();
    const authorB = (b.__sortAuthor || '￿').toLowerCase();
    if (authorA !== authorB) return authorA.localeCompare(authorB);
    if (!a.date && !b.date) return a.title.localeCompare(b.title);
    if (!a.date) return 1;
    if (!b.date) return -1;
    if (a.date !== b.date) return b.date.localeCompare(a.date);
    return a.title.localeCompare(b.title);
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

function prependAiIcon(container, tooltipKey = 'import.aiSummaryTooltip') {
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
  prependAiIcon(summaryEl);
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

function renderSourceList(sources, options = {}) {
  currentSourceList = sources;
  const sorted = sortSources(sources);
  currentDisplayedSources = sorted;
  const list = document.getElementById('source-list');
  list.innerHTML = '';
  let lastMonthYear = null;
  let lastAuthorKey = null;
  const authorCounts = new Map();
  if (currentSortMode === 'author') {
    sorted.forEach((s) => {
      if (!s.__sortAuthor) return;
      const key = normalizeAuthor(s.__sortAuthor);
      authorCounts.set(key, (authorCounts.get(key) || 0) + 1);
    });
  }
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

  sorted.forEach((s) => {
    if (currentSortMode === 'date' && !pendingDeletions.has(s.id)) {
      const key = monthYearKey(s.date);
      if (key !== lastMonthYear) {
        appendTimelineRow(buildTimelineMarker(formatMonthYear(s.date)));
        lastMonthYear = key;
      }
    }

    let extraGapAfterAuthorGroup = false;
    if (currentSortMode === 'author' && !pendingDeletions.has(s.id)) {
      const key = s.__sortAuthor ? normalizeAuthor(s.__sortAuthor) : null;
      const isNewAuthor = key && key !== lastAuthorKey;
      if (isNewAuthor && (authorCounts.get(key) || 0) > 1) {
        list.appendChild(buildAuthorMarker(s.__sortAuthor));
      } else if (
        isNewAuthor &&
        lastAuthorKey &&
        (authorCounts.get(lastAuthorKey) || 0) > 1
      ) {
        // Dieser Autor hat nur eine Quelle (keine eigene Zwischenüberschrift),
        // steht aber direkt nach einem Autor MIT Zwischenüberschrift - ohne
        // zusätzlichen Abstand sähe es so aus, als gehöre die Quelle noch
        // zum vorherigen Autor.
        extraGapAfterAuthorGroup = true;
      }
      lastAuthorKey = key;
    }

    if (pendingDeletions.has(s.id)) {
      if (activeEditId === s.id) {
        appendTimelineRow(buildEditPanel(s, { pendingDeletion: true }));
      } else {
        appendTimelineRow(buildUndoRow(s));
      }
      return;
    }

    const li = document.createElement('li');
    li.className = 'source-row';
    if (unreachableSourceIds.has(s.id)) {
      li.classList.add('source-row--unreachable');
    }
    if (extraGapAfterAuthorGroup) {
      li.classList.add('source-row--after-author-group');
    }
    li.dataset.sourceId = s.id;

    const header = document.createElement('div');
    header.className = 'source-row-header';

    const citationUrl = s.listen_url || s.url;
    const hasDetails = !!s.summary;

    const textSpan = document.createElement('span');
    if (hasDetails) {
      const titleBtn = document.createElement('button');
      titleBtn.type = 'button';
      titleBtn.className = 'link-button source-title-toggle';
      titleBtn.textContent = s.title;
      titleBtn.addEventListener('click', () => {
        if (expandedSourceIds.has(s.id)) {
          expandedSourceIds.delete(s.id);
        } else {
          expandedSourceIds.add(s.id);
        }
        renderSourceList(currentSourceList, options);
      });
      textSpan.appendChild(titleBtn);
      textSpan.append(' – ');
    } else {
      textSpan.append(`${s.title} – `);
    }
    if (s.authors && s.authors.length) {
      s.authors.forEach((name, index) => {
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
    header.appendChild(textSpan);

    const actions = document.createElement('span');
    actions.className = 'source-row-actions';

    if (unreachableSourceIds.has(s.id)) {
      const warning = document.createElement(hasPflegerRole() ? 'button' : 'span');
      if (hasPflegerRole()) warning.type = 'button';
      warning.className = 'icon-button warning-icon';
      const warnLabel = t('common.urlUnreachable');
      warning.title = warnLabel;
      warning.setAttribute('aria-label', warnLabel);
      warning.innerHTML = WARNING_ICON;
      if (hasPflegerRole()) {
        warning.addEventListener('click', () => {
          activeEditId = activeEditId === s.id ? null : s.id;
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
      const editLabel = t('common.editSource');
      editBtn.title = editLabel;
      editBtn.setAttribute('aria-label', editLabel);
      editBtn.innerHTML = EDIT_ICON;
      editBtn.addEventListener('click', () => {
        activeEditId = activeEditId === s.id ? null : s.id;
        renderSourceList(currentSourceList, options);
      });
      actions.appendChild(editBtn);
    }

    header.appendChild(actions);
    li.appendChild(header);

    if (hasDetails && expandedSourceIds.has(s.id)) {
      li.appendChild(buildSourceDetails(s, citationUrl));
    }

    appendTimelineRow(li);

    if (activeEditId === s.id) {
      appendTimelineRow(buildEditPanel(s));
    }
  });

  if (currentSortMode === 'date') {
    // "-1" als Grid-Zeilen-Ende bezieht sich nur auf EXPLIZIT deklarierte
    // Zeilen (grid-template-rows), nicht auf implizit erzeugte - deshalb hier
    // das tatsächliche Zeilenende als Variable setzen, damit die Zeitlinie
    // (::after) wirklich bis zur letzten Zeile durchläuft.
    list.style.setProperty('--timeline-row-end', String(gridRow + 1));
  }
}

async function checkUrlHealth(sources) {
  if (!hasPflegerRole()) return;
  sources.forEach(async (s) => {
    if (!s.url) {
      // URL wurde entfernt (z.B. beim Bearbeiten) - eine evtl. alte
      // Unreachable-Markierung ist dann nicht mehr gültig.
      if (unreachableSourceIds.delete(s.id)) {
        renderSourceList(currentSourceList);
      }
      return;
    }
    try {
      const res = await fetch(`/api/sources/${s.id}/check-url`, { headers: devUserHeaders() });
      if (!res.ok) return;
      const data = await res.json();
      const isUnreachable = data.has_url && data.reachable === false;
      const wasUnreachable = unreachableSourceIds.has(s.id);
      // Sowohl neu erkannte als auch (nach einer URL-Reparatur) nicht mehr
      // bestehende Unreachable-Zustände müssen sofort sichtbar werden -
      // vorher wurde eine Markierung nie wieder entfernt.
      if (isUnreachable && !wasUnreachable) {
        unreachableSourceIds.add(s.id);
        renderSourceList(currentSourceList);
      } else if (!isUnreachable && wasUnreachable) {
        unreachableSourceIds.delete(s.id);
        renderSourceList(currentSourceList);
      }
    } catch (err) {
      // Netzwerkfehler beim Erreichbarkeits-Check ignorieren.
    }
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

async function applyAuthorFilter(name) {
  const res = await fetch('/api/authors');
  const authorEntries = await res.json();
  const match = authorEntries.find((a) => normalizeAuthor(a.name) === normalizeAuthor(name));
  const ids = match ? match.source_ids : [];

  document.getElementById('source-filter-label').textContent = t(
    ids.length === 1 ? 'import.filteredByAuthor' : 'import.filteredByAuthorPlural'
  );
  document.getElementById('source-filter-name').textContent = match ? match.name : name;
  // Muss VOR renderSourceList() gesetzt werden - sortSources() liest den
  // Filter-Status, um die Autoren-Expansion in der gefilterten Ansicht zu
  // unterdrücken (siehe isFilterActive()).
  document.getElementById('source-filter-status').classList.remove('hidden');
  renderSourceList(allSources.filter((s) => ids.includes(s.id)));

  filteredAuthorEntry = match || null;
  authorPanelEditMode = false;
  renderAuthorInfoPanel();
}

async function filterByAuthor(name) {
  activeFilter = { type: 'author', value: name };
  await applyAuthorFilter(name);
  scrollToFilteredResults();
}

function normalizeTerm(term) {
  return term.trim().toLowerCase();
}

async function applyTermFilter(term) {
  const res = await fetch('/api/terms');
  const termEntries = await res.json();
  const match = termEntries.find((t2) => normalizeTerm(t2.term) === normalizeTerm(term));
  const ids = match ? match.source_ids : [];
  ids.forEach((id) => expandedSourceIds.add(id));

  document.getElementById('source-filter-label').textContent = t('import.filteredByTerm');
  document.getElementById('source-filter-name').textContent = match ? match.term : term;
  document.getElementById('source-filter-status').classList.remove('hidden');
  renderSourceList(allSources.filter((s) => ids.includes(s.id)));

  filteredAuthorEntry = null;
  authorPanelEditMode = false;
  renderAuthorInfoPanel();
}

async function filterByTerm(term) {
  activeFilter = { type: 'term', value: term };
  await applyTermFilter(term);
  scrollToFilteredResults();
}

document.getElementById('source-filter-clear').addEventListener('click', () => {
  activeFilter = null;
  document.getElementById('source-filter-status').classList.add('hidden');
  renderSourceList(allSources);
  filteredAuthorEntry = null;
  authorPanelEditMode = false;
  renderAuthorInfoPanel();
});

document.getElementById('sort-author').addEventListener('click', () => setSortMode('author'));
document.getElementById('sort-date').addEventListener('click', () => setSortMode('date'));

document.getElementById('reindex-sources-btn').addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  const status = document.getElementById('reindex-status');
  btn.disabled = true;
  status.textContent = t('import.reindexing');
  status.classList.remove('hidden');
  try {
    const res = await fetch('/api/admin/reindex-sources', { method: 'POST', headers: { 'X-Lang': getLang() } });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('import.reindexFailed'));
    }
    const data = await res.json();
    status.textContent = data.detail;
  } catch (err) {
    status.textContent = t('common.errorPrefix') + err.message;
  } finally {
    btn.disabled = false;
  }
});

function setSortMode(mode) {
  currentSortMode = mode;
  document.getElementById('sort-author').classList.toggle('active', mode === 'author');
  document.getElementById('sort-date').classList.toggle('active', mode === 'date');
  document.getElementById('source-list').classList.toggle('timeline-mode', mode === 'date');
  renderSourceList(currentSourceList);
}

async function loadSources({ skipUrlHealthCheck = false } = {}) {
  const res = await fetch('/api/sources', {
    headers: { 'X-Lang': getLang() },
  });
  allSources = await res.json();
  // Ein aktiver Autor:innen-/Begriffs-Filter soll ein Neuladen (z.B. nach
  // dem Aktualisieren oder Löschen einer Quelle) überleben, statt
  // stillschweigend auf die ungefilterte Liste zurückzuspringen.
  if (activeFilter?.type === 'author') {
    await applyAuthorFilter(activeFilter.value);
  } else if (activeFilter?.type === 'term') {
    await applyTermFilter(activeFilter.value);
  } else {
    renderSourceList(allSources);
    filteredAuthorEntry = null;
    authorPanelEditMode = false;
    renderAuthorInfoPanel();
  }
  // skipUrlHealthCheck: beim allerersten Laden (siehe unten) sollen die
  // Deep-Links (?edit=/?author=) zuerst ihre eigene, für die Nutzer:in
  // sichtbare Anfrage stellen können, bevor der Browser seine begrenzten
  // gleichzeitigen Verbindungen mit einem Check pro Quelle flutet - sonst
  // reiht sich deren Anfrage hinten an und die gefilterte Ansicht wirkt
  // spürbar langsam.
  if (!skipUrlHealthCheck) {
    checkUrlHealth(allSources);
  }
}

async function loadAuthors() {
  const res = await fetch('/api/authors');
  allAuthors = await res.json();
  renderAuthorList();

  const datalist = document.getElementById('author-suggestions');
  datalist.innerHTML = '';
  allAuthors.forEach((a) => {
    const option = document.createElement('option');
    option.value = a.name;
    datalist.appendChild(option);
  });
}

function renderAuthorList() {
  const list = document.getElementById('author-list');
  list.replaceChildren(...allAuthors.map(buildAuthorListItem));
}

function buildAuthorLink(url, label) {
  const link = document.createElement('a');
  link.href = url;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.className = 'author-link';
  const icon = document.createElement('span');
  icon.className = 'author-link-icon';
  icon.innerHTML = EXTERNAL_LINK_ICON;
  link.appendChild(icon);
  link.append(label);
  return link;
}

function buildAuthorBioSection(a) {
  const container = document.createElement('div');
  container.className = 'author-bio-section';

  if (a.bio) {
    const bioP = document.createElement('p');
    bioP.className = 'author-bio-text';
    bioP.textContent = a.bio;
    container.appendChild(bioP);
    if (a.bio_ai_generated) prependAiIcon(container, 'import.aiBioTooltip');
  }

  const linksRow = document.createElement('div');
  linksRow.className = 'author-links-row';
  if (a.website) linksRow.appendChild(buildAuthorLink(a.website, t('import.fieldWebsite')));
  (a.social_links || []).forEach((link) => {
    if (link.url) linksRow.appendChild(buildAuthorLink(link.url, link.platform || link.url));
  });
  if (linksRow.children.length) container.appendChild(linksRow);

  if (!a.bio && !linksRow.children.length && !a.photo_url) {
    const emptyP = document.createElement('p');
    emptyP.className = 'author-bio-text author-bio-text--empty';
    emptyP.textContent = t('import.authorProfileEmpty');
    container.appendChild(emptyP);
  }

  return container;
}

function buildSocialLinksField(initialLinks) {
  const wrapper = document.createElement('div');
  wrapper.className = 'social-links-field';

  const rows = document.createElement('div');
  rows.className = 'social-link-rows';
  wrapper.appendChild(rows);

  // Ohne Zeilen gibt es nichts zu entfernen - dann steht ein einzelner
  // "+"-Button für sich, um die erste Zeile anzulegen (analog zum
  // Mehrfach-Autoren-Feld bei Quellen, das dieselben Icons verwendet).
  const standaloneAddBtn = document.createElement('button');
  standaloneAddBtn.type = 'button';
  standaloneAddBtn.className = 'icon-button add-author-btn';
  standaloneAddBtn.innerHTML = PLUS_ICON;
  const addLabel = t('import.addSocialLink');
  standaloneAddBtn.title = addLabel;
  standaloneAddBtn.setAttribute('aria-label', addLabel);
  standaloneAddBtn.addEventListener('click', () => rows.appendChild(buildRow(null)));
  wrapper.appendChild(standaloneAddBtn);

  function refreshStandaloneButton() {
    standaloneAddBtn.classList.toggle('hidden', rows.children.length > 0);
  }

  function buildAddButton(insertNewRow) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-button add-author-btn';
    btn.innerHTML = PLUS_ICON;
    btn.title = addLabel;
    btn.setAttribute('aria-label', addLabel);
    btn.addEventListener('click', () => insertNewRow(buildRow(null)));
    return btn;
  }

  function buildRemoveButton(row) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-button remove-author-btn';
    btn.innerHTML = REMOVE_ICON;
    const removeLabel = t('import.removeSocialLink');
    btn.title = removeLabel;
    btn.setAttribute('aria-label', removeLabel);
    btn.addEventListener('click', () => {
      row.remove();
      refreshStandaloneButton();
    });
    return btn;
  }

  function buildRow(link) {
    const row = document.createElement('div');
    row.className = 'social-link-row';

    const platformInput = document.createElement('input');
    platformInput.type = 'text';
    platformInput.className = 'social-platform-input';
    platformInput.setAttribute('list', 'social-platform-suggestions');
    platformInput.setAttribute('autocomplete', 'off');
    platformInput.placeholder = t('import.socialPlatformPlaceholder');
    platformInput.value = (link && link.platform) || '';

    const urlInput = document.createElement('input');
    urlInput.type = 'url';
    urlInput.className = 'social-url-input';
    urlInput.placeholder = t('import.socialUrlPlaceholder');
    urlInput.value = (link && link.url) || '';

    row.appendChild(platformInput);
    row.appendChild(urlInput);
    row.appendChild(buildAddButton((newRow) => row.insertAdjacentElement('afterend', newRow)));
    row.appendChild(buildRemoveButton(row));
    return row;
  }

  (initialLinks && initialLinks.length ? initialLinks : []).forEach((link) => {
    rows.appendChild(buildRow(link));
  });
  refreshStandaloneButton();

  function getSocialLinkValues() {
    return [...rows.querySelectorAll('.social-link-row')]
      .map((row) => ({
        platform: row.querySelector('.social-platform-input').value.trim(),
        url: row.querySelector('.social-url-input').value.trim(),
      }))
      .filter((link) => link.platform && link.url);
  }

  return { wrapper, getSocialLinkValues };
}

async function generateAuthorBio(name, bioInput, statusEl, buttons) {
  buttons.forEach((b) => {
    b.disabled = true;
  });
  statusEl.textContent = t('import.generatingBio');
  try {
    const res = await fetch(`/api/authors/${encodeURIComponent(name)}/generate-bio`, {
      method: 'POST',
      headers: devUserHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('import.generateBioFailed'));
    }
    const data = await res.json();
    if (!bioInput.value.trim()) bioInput.value = data.bio;
    statusEl.textContent = '';
  } catch (err) {
    statusEl.textContent = t('common.errorPrefix') + err.message;
  } finally {
    buttons.forEach((b) => {
      b.disabled = false;
    });
  }
}

function buildAuthorInfoView(a) {
  const wrapper = document.createElement('div');
  wrapper.className = 'author-info-view';

  const headerRow = document.createElement('div');
  headerRow.className = 'author-info-header-row';

  const heading = document.createElement('h4');
  heading.className = 'author-info-heading';
  heading.textContent = a.name;
  headerRow.appendChild(heading);

  const photoCol = document.createElement('div');
  photoCol.className = 'author-info-photo-col';

  if (a.photo_url) {
    const img = document.createElement('img');
    img.src = a.photo_url;
    img.alt = a.name;
    img.className = 'author-photo';
    photoCol.appendChild(img);
  }

  headerRow.appendChild(photoCol);
  wrapper.appendChild(headerRow);
  wrapper.appendChild(buildAuthorBioSection(a));

  if (hasPflegerRole()) {
    const editRow = document.createElement('div');
    editRow.className = 'author-info-edit-row';
    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'icon-button author-info-edit-btn';
    const editLabel = t('common.editAuthor');
    editBtn.title = editLabel;
    editBtn.setAttribute('aria-label', editLabel);
    editBtn.innerHTML = EDIT_ICON;
    editBtn.addEventListener('click', () => {
      authorPanelEditMode = true;
      renderAuthorInfoPanel();
    });
    editRow.appendChild(editBtn);
    wrapper.appendChild(editRow);
  }

  return wrapper;
}

function renderAuthorInfoPanel() {
  const panel = document.getElementById('author-info-panel');
  const body = document.getElementById('quellen-liste-body');
  if (!filteredAuthorEntry) {
    panel.replaceChildren();
    panel.classList.add('hidden');
    body.classList.remove('quellen-liste-body--author-filtered');
    return;
  }
  body.classList.add('quellen-liste-body--author-filtered');
  panel.classList.remove('hidden');
  panel.replaceChildren(
    authorPanelEditMode ? buildAuthorEditPanel(filteredAuthorEntry) : buildAuthorInfoView(filteredAuthorEntry)
  );
}

function buildAuthorEditPanel(a) {
  const wrapper = document.createElement('div');
  wrapper.className = 'author-edit-panel';

  const form = document.createElement('form');
  const status = document.createElement('p');
  status.className = 'edit-status';

  function field(labelKey, idSuffix, value, type) {
    const label = document.createElement('label');
    label.textContent = t(labelKey);
    const input = document.createElement(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') input.type = type;
    else input.rows = 4;
    input.id = `edit-author-${idSuffix}-${a.name}`;
    input.value = value || '';
    label.appendChild(input);
    label.htmlFor = input.id;
    form.appendChild(label);
    return input;
  }

  const nameInput = field('import.fieldAuthorName', 'name', a.name, 'text');

  const bioInput = field('import.fieldBio', 'bio', a.bio, 'textarea');
  const magicButtons = [];
  const triggerGenerateBio = () => generateAuthorBio(a.name, bioInput, status, magicButtons);
  magicButtons.push(addMagicButton(bioInput, triggerGenerateBio, 'import.generateBioTitle'));

  const photoUrlInput = field('import.fieldPhotoUrl', 'photo-url', a.photo_url, 'url');
  const photoFieldRow = document.createElement('div');
  photoFieldRow.className = 'photo-field-row';
  photoUrlInput.parentNode.insertBefore(photoFieldRow, photoUrlInput);
  photoFieldRow.appendChild(photoUrlInput);

  const photoPreview = document.createElement('img');
  photoPreview.className = 'author-photo-preview';
  photoPreview.alt = a.name;
  photoPreview.hidden = !a.photo_url;
  if (a.photo_url) photoPreview.src = a.photo_url;
  // Bild lädt/existiert nicht (z.B. während der Eingabe noch unvollständige
  // URL) - dann lieber gar nichts zeigen statt ein kaputtes Bild-Icon.
  photoPreview.addEventListener('error', () => {
    photoPreview.hidden = true;
  });
  photoUrlInput.addEventListener('input', () => {
    const value = photoUrlInput.value.trim();
    photoPreview.hidden = !value;
    if (value) photoPreview.src = value;
  });
  photoFieldRow.appendChild(photoPreview);

  const websiteInput = field('import.fieldWebsite', 'website', a.website, 'url');

  const socialLabel = document.createElement('label');
  socialLabel.textContent = t('import.fieldSocialLinks');
  const { wrapper: socialWrapper, getSocialLinkValues } = buildSocialLinksField(a.social_links);
  socialLabel.appendChild(socialWrapper);
  form.appendChild(socialLabel);

  const actionsRow = document.createElement('div');
  actionsRow.className = 'edit-panel-actions';

  const primaryActions = document.createElement('div');
  const submitBtn = document.createElement('button');
  submitBtn.type = 'submit';
  submitBtn.textContent = t('import.updateButton');
  primaryActions.appendChild(submitBtn);

  const cancelBtn = document.createElement('button');
  cancelBtn.type = 'button';
  cancelBtn.className = 'link-button';
  cancelBtn.textContent = t('common.cancel');
  cancelBtn.addEventListener('click', () => {
    authorPanelEditMode = false;
    renderAuthorInfoPanel();
  });
  primaryActions.appendChild(cancelBtn);
  actionsRow.appendChild(primaryActions);

  form.appendChild(actionsRow);
  form.appendChild(status);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    status.textContent = t('import.updating');
    try {
      let currentName = a.name;
      const newName = nameInput.value.trim();
      if (newName && newName !== currentName) {
        const renameRes = await fetch(`/api/authors/${encodeURIComponent(currentName)}/rename`, {
          method: 'POST',
          headers: devUserHeaders(),
          body: JSON.stringify({ new_name: newName }),
        });
        if (!renameRes.ok) {
          const err = await renameRes.json().catch(() => ({}));
          throw new Error(err.detail || t('import.renameFailed'));
        }
        currentName = newName;
      }

      const res = await fetch(`/api/authors/${encodeURIComponent(currentName)}`, {
        method: 'PUT',
        headers: devUserHeaders(),
        body: JSON.stringify({
          bio: bioInput.value,
          photo_url: photoUrlInput.value,
          website: websiteInput.value,
          social_links: getSocialLinkValues(),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || t('import.updateFailed'));
      }
      authorPanelEditMode = false;
      await applyAuthorFilter(currentName);
      await loadAuthors();
    } catch (err) {
      status.textContent = t('common.errorPrefix') + err.message;
    }
  });

  wrapper.appendChild(form);
  return wrapper;
}

function buildAuthorListItem(a) {
  const li = document.createElement('li');
  const authorBtn = document.createElement('button');
  authorBtn.type = 'button';
  authorBtn.className = 'link-button';
  authorBtn.textContent = a.name;
  authorBtn.addEventListener('click', () => filterByAuthor(a.name));
  li.appendChild(authorBtn);
  const countKey = a.source_count === 1 ? 'common.sourceCountOne' : 'common.sourceCountMany';
  li.append(` (${t(countKey, { count: a.source_count })})`);
  return li;
}

document.getElementById('source-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const payload = {
    title: document.getElementById('title').value,
    authors: getCreateAuthorValues(),
    date: document.getElementById('date').value || null,
    url: document.getElementById('url').value || null,
    text: document.getElementById('text').value,
    restricted: document.getElementById('restricted').checked,
    pdf_upload_id: pendingUploadId,
  };
  const status = document.getElementById('import-status');
  if (payload.url) {
    const existing = findExistingSourceByUrl(payload.url);
    if (existing) {
      status.textContent = t('import.urlAlreadyExists', { title: existing.title });
      return;
    }
  }
  status.textContent = t('import.importing');
  try {
    const res = await fetch('/api/sources', {
      method: 'POST',
      headers: devUserHeaders(),
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('import.importFailed'));
    }
    const data = await res.json();
    status.textContent = t('import.importedStatus', { title: data.title, count: data.chunk_count });
    document.getElementById('source-form').reset();
    // form.reset() setzt bei den dynamisch erzeugten Autoren-Feldern nur den
    // Wert zurück, entfernt aber keine per "+" hinzugefügten Extra-Zeilen -
    // hier explizit auf ein einzelnes leeres Feld zurücksetzen.
    renderCreateAuthorDateRow([], '');
    pendingUploadId = null;
    importBereich.classList.add('hidden');
    // Die URL-Eingabe im "Von URL importieren"-Popover gehört NICHT zu
    // #source-form (separates Formular für /api/extract-url) und wurde
    // daher vom obigen reset() nicht mit geleert - beim nächsten Import
    // stand sonst noch die vorherige URL darin.
    document.getElementById('popover-url').value = '';
    document.getElementById('popover-status').textContent = '';
    loadSources();
    loadAuthors();
  } catch (err) {
    status.textContent = t('common.errorPrefix') + err.message;
  }
});

let getCreateAuthorValues = () => [];

function renderCreateAuthorDateRow(overrideAuthorValues, overrideDateValue) {
  const existingAuthor = document.getElementById('author');
  const existingDate = document.getElementById('date');
  const authorValues =
    overrideAuthorValues !== undefined
      ? overrideAuthorValues
      : existingAuthor
        ? getCreateAuthorValues()
        : [];
  const dateValue =
    overrideDateValue !== undefined ? overrideDateValue : existingDate ? existingDate.value : '';
  const target = existingAuthor
    ? existingAuthor.closest('.author-fields')
    : document.getElementById('create-author-date-row');
  const built = buildAuthorFields('author', authorValues, 'date', dateValue);
  target.replaceWith(built.wrapper);
  getCreateAuthorValues = built.getAuthorValues;
}

document.addEventListener('i18n:changed', () => {
  loadSources();
  loadAuthors();
  renderCreateAuthorDateRow();
});

// buildAuthorFields()/buildMarkupToolbar() rufen t() auf - das darf erst
// NACH await initI18n() passieren, sonst ist das Wörterbuch noch leer und
// es erscheinen die rohen Übersetzungsschlüssel statt echtem Text (genau
// dieser Fehler wurde hier gemeldet und behoben).
await initI18n();
await initAuth();
updateSourceManagementVisibility();
onAuthChange(() => {
  updateSourceManagementVisibility();
  loadSources();
});

renderCreateAuthorDateRow();

const createTextInput = document.getElementById('text');
const createToolbarRow = document.createElement('div');
createToolbarRow.className = 'markup-toolbar-row';
createToolbarRow.appendChild(buildMarkupToolbar(createTextInput));
createTextInput.parentNode.insertBefore(createToolbarRow, createTextInput);

await loadSources({ skipUrlHealthCheck: true });
loadAuthors();

// Deep-Link aus der Konversationsansicht (Stift-Icon an Zitat-Snippets, nur
// für Quellen-Pfleger:innen sichtbar): /import.html?edit=<source_id> öffnet
// die betreffende Quelle direkt im Bearbeiten-Modus und scrollt sie in den
// sichtbaren Bereich.
const deepLinkEditId = new URLSearchParams(window.location.search).get('edit');
if (deepLinkEditId && hasPflegerRole() && allSources.some((s) => s.id === deepLinkEditId)) {
  activeEditId = deepLinkEditId;
  renderSourceList(currentSourceList);
  requestAnimationFrame(() => {
    document
      .querySelector(`#source-list [data-source-id="${deepLinkEditId}"]`)
      ?.scrollIntoView({ block: 'center' });
  });
}

// Deep-Link aus der Konversationsansicht (Autor:innen-Links an Zitaten):
// /import.html?author=<name> filtert direkt auf die Texte dieser Person und
// zeigt ihr Profil (inkl. Vita) im Info-Panel an.
const deepLinkAuthor = new URLSearchParams(window.location.search).get('author');
if (deepLinkAuthor) {
  await filterByAuthor(deepLinkAuthor);
}

checkUrlHealth(allSources);
