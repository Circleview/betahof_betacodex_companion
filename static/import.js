import { initI18n, t, getLang } from '/i18n.js';
import { renderMarkdown } from '/markdown.js';

const importBereich = document.getElementById('import-bereich');
const urlPopover = document.getElementById('url-popover');
const filePopover = document.getElementById('file-popover');
const quelltypBereich = document.getElementById('quelltyp-bereich');

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
let currentDisplayedSources = [];
let activeEditId = null;
let devUserList = [];
let currentUserRoles = [];
let pendingUploadId = null;
let currentSortMode = 'author';
const pendingDeletions = new Map();
const unreachableSourceIds = new Set();
const expandedSourceIds = new Set();

function hasPflegerRole() {
  return currentUserRoles.includes('quellen_pfleger') || currentUserRoles.includes('system_admin');
}

function getCurrentDevUser() {
  return localStorage.getItem('devUser') || 'anon';
}

function devUserHeaders() {
  return {
    'Content-Type': 'application/json',
    'X-Dev-User': getCurrentDevUser(),
    'X-Lang': getLang(),
  };
}

function updateCurrentUserRoles() {
  const match = devUserList.find((u) => u.id === getCurrentDevUser());
  currentUserRoles = match ? match.roles : [];
  quelltypBereich.classList.toggle('hidden', !hasPflegerRole());
  if (!hasPflegerRole()) {
    importBereich.classList.add('hidden');
    urlPopover.classList.add('hidden');
    filePopover.classList.add('hidden');
  }
}

async function initRoleSwitcher() {
  const select = document.getElementById('dev-role');
  const res = await fetch('/api/dev/users');
  devUserList = await res.json();
  select.innerHTML = '';
  devUserList.forEach((u) => {
    const option = document.createElement('option');
    option.value = u.id;
    option.textContent = u.name;
    select.appendChild(option);
  });
  if (!devUserList.some((u) => u.id === getCurrentDevUser())) {
    localStorage.setItem('devUser', devUserList[0] ? devUserList[0].id : 'anon');
  }
  select.value = getCurrentDevUser();
  updateCurrentUserRoles();
  select.addEventListener('change', () => {
    localStorage.setItem('devUser', select.value);
    updateCurrentUserRoles();
    loadSources();
  });
}

function showForm() {
  importBereich.classList.remove('hidden');
  urlPopover.classList.add('hidden');
  filePopover.classList.add('hidden');
}

function fillForm({
  title = '',
  author = '',
  date = '',
  url = '',
  text = '',
  restricted = false,
}) {
  document.getElementById('title').value = title;
  document.getElementById('author').value = author;
  document.getElementById('date').value = date;
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
    fillForm({ title: data.title, author: data.author, date: data.date, url, text: data.text });
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
      headers: { 'X-Dev-User': getCurrentDevUser(), 'X-Lang': getLang() },
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
    fillForm({ title: data.title, author: data.author, date: data.date, text: data.text });
    showForm();
  } catch (err) {
    status.textContent = t('common.errorPrefix') + err.message;
  }
});

function normalizeAuthor(name) {
  return name.trim().split(/\s+/).join(' ').toLowerCase();
}

function normalizeUrlForComparison(url) {
  return url.trim().replace(/\/+$/, '').toLowerCase();
}

function findExistingSourceByUrl(url) {
  const normalized = normalizeUrlForComparison(url);
  if (!normalized) return null;
  return allSources.find((s) => s.url && normalizeUrlForComparison(s.url) === normalized) || null;
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
    return { label, input };
  }

  function field(labelKey, idSuffix, value, type) {
    const { label, input } = buildFieldLabel(labelKey, idSuffix, value, type);
    form.appendChild(label);
    return input;
  }

  const titleInput = field('import.fieldTitle', 'title', s.title, 'text');
  titleInput.required = true;

  const authorField = buildFieldLabel('import.fieldAuthor', 'author', s.author, 'text');
  const authorInput = authorField.input;
  authorInput.setAttribute('list', 'author-suggestions');
  authorInput.setAttribute('autocomplete', 'off');
  const dateField = buildFieldLabel('import.fieldDate', 'date', s.date, 'date');
  const dateInput = dateField.input;
  const authorDateRow = document.createElement('div');
  authorDateRow.className = 'field-row';
  authorDateRow.appendChild(authorField.label);
  authorDateRow.appendChild(dateField.label);
  form.appendChild(authorDateRow);

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
      authorInput,
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
      renderSourceList(currentDisplayedSources);
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
            author: authorInput.value || null,
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

function addMagicButton(input, onClick) {
  const wrapper = document.createElement('div');
  wrapper.className = 'field-with-magic';
  input.parentNode.insertBefore(wrapper, input);
  wrapper.appendChild(input);

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'magic-button';
  const title = t('import.generateSummaryTitle');
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
  renderSourceList(currentDisplayedSources);
}

function cancelDeletion(id) {
  const entry = pendingDeletions.get(id);
  if (entry) {
    clearTimeout(entry.timeoutId);
    pendingDeletions.delete(id);
  }
  renderSourceList(currentDisplayedSources);
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

function sortSources(sources) {
  const copy = [...sources];
  if (currentSortMode === 'date') {
    copy.sort((a, b) => {
      if (!a.date && !b.date) return a.title.localeCompare(b.title);
      if (!a.date) return 1;
      if (!b.date) return -1;
      return b.date.localeCompare(a.date);
    });
  } else {
    copy.sort((a, b) => {
      const authorA = (a.author || '￿').toLowerCase();
      const authorB = (b.author || '￿').toLowerCase();
      if (authorA !== authorB) return authorA.localeCompare(authorB);
      if (!a.date && !b.date) return a.title.localeCompare(b.title);
      if (!a.date) return 1;
      if (!b.date) return -1;
      if (a.date !== b.date) return b.date.localeCompare(a.date);
      return a.title.localeCompare(b.title);
    });
  }
  return copy;
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

function prependAiIcon(container) {
  const icon = document.createElement('span');
  icon.className = 'source-summary-icon';
  icon.innerHTML = MAGIC_ICON;
  const tooltip = t('import.aiSummaryTooltip');
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
  const sorted = sortSources(sources);
  currentDisplayedSources = sorted;
  const list = document.getElementById('source-list');
  list.innerHTML = '';
  let lastMonthYear = null;
  let lastAuthorKey = null;
  const authorCounts = new Map();
  if (currentSortMode === 'author') {
    sorted.forEach((s) => {
      if (!s.author) return;
      const key = normalizeAuthor(s.author);
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
      const key = s.author ? normalizeAuthor(s.author) : null;
      const isNewAuthor = key && key !== lastAuthorKey;
      if (isNewAuthor && (authorCounts.get(key) || 0) > 1) {
        list.appendChild(buildAuthorMarker(s.author));
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
        renderSourceList(currentDisplayedSources, options);
      });
      textSpan.appendChild(titleBtn);
      textSpan.append(' – ');
    } else {
      textSpan.append(`${s.title} – `);
    }
    if (s.author) {
      const authorBtn = document.createElement('button');
      authorBtn.type = 'button';
      authorBtn.className = 'link-button';
      authorBtn.textContent = s.author;
      authorBtn.addEventListener('click', () => filterByAuthor(s.author));
      textSpan.appendChild(authorBtn);
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
          renderSourceList(currentDisplayedSources, options);
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
        renderSourceList(currentDisplayedSources, options);
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
        renderSourceList(currentDisplayedSources);
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
        renderSourceList(currentDisplayedSources);
      } else if (!isUnreachable && wasUnreachable) {
        unreachableSourceIds.delete(s.id);
        renderSourceList(currentDisplayedSources);
      }
    } catch (err) {
      // Netzwerkfehler beim Erreichbarkeits-Check ignorieren.
    }
  });
}

async function filterByAuthor(name) {
  const res = await fetch('/api/authors');
  const authorEntries = await res.json();
  const match = authorEntries.find((a) => normalizeAuthor(a.name) === normalizeAuthor(name));
  const ids = match ? match.source_ids : [];
  renderSourceList(allSources.filter((s) => ids.includes(s.id)));

  document.getElementById('source-filter-label').textContent = t('import.filteredByAuthor');
  document.getElementById('source-filter-name').textContent = match ? match.name : name;
  document.getElementById('source-filter-status').classList.remove('hidden');
}

function normalizeTerm(term) {
  return term.trim().toLowerCase();
}

async function filterByTerm(term) {
  const res = await fetch('/api/terms');
  const termEntries = await res.json();
  const match = termEntries.find((t2) => normalizeTerm(t2.term) === normalizeTerm(term));
  const ids = match ? match.source_ids : [];
  ids.forEach((id) => expandedSourceIds.add(id));
  renderSourceList(allSources.filter((s) => ids.includes(s.id)));

  document.getElementById('source-filter-label').textContent = t('import.filteredByTerm');
  document.getElementById('source-filter-name').textContent = match ? match.term : term;
  document.getElementById('source-filter-status').classList.remove('hidden');
}

document.getElementById('source-filter-clear').addEventListener('click', () => {
  renderSourceList(allSources);
  document.getElementById('source-filter-status').classList.add('hidden');
});

document.getElementById('sort-author').addEventListener('click', () => setSortMode('author'));
document.getElementById('sort-date').addEventListener('click', () => setSortMode('date'));

function setSortMode(mode) {
  currentSortMode = mode;
  document.getElementById('sort-author').classList.toggle('active', mode === 'author');
  document.getElementById('sort-date').classList.toggle('active', mode === 'date');
  document.getElementById('source-list').classList.toggle('timeline-mode', mode === 'date');
  renderSourceList(currentDisplayedSources);
}

async function loadSources() {
  const res = await fetch('/api/sources', {
    headers: { 'X-Dev-User': getCurrentDevUser(), 'X-Lang': getLang() },
  });
  allSources = await res.json();
  renderSourceList(allSources);
  checkUrlHealth(allSources);
}

async function loadAuthors() {
  const res = await fetch('/api/authors');
  const authorEntries = await res.json();

  const list = document.getElementById('author-list');
  list.innerHTML = '';
  authorEntries.forEach((a) => {
    const li = document.createElement('li');
    const authorBtn = document.createElement('button');
    authorBtn.type = 'button';
    authorBtn.className = 'link-button';
    authorBtn.textContent = a.name;
    authorBtn.addEventListener('click', () => filterByAuthor(a.name));
    li.appendChild(authorBtn);
    const countKey = a.source_count === 1 ? 'common.sourceCountOne' : 'common.sourceCountMany';
    li.append(` (${t(countKey, { count: a.source_count })})`);
    list.appendChild(li);
  });

  const datalist = document.getElementById('author-suggestions');
  datalist.innerHTML = '';
  authorEntries.forEach((a) => {
    const option = document.createElement('option');
    option.value = a.name;
    datalist.appendChild(option);
  });
}

document.getElementById('source-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const payload = {
    title: document.getElementById('title').value,
    author: document.getElementById('author').value || null,
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

document.addEventListener('i18n:changed', () => {
  loadSources();
  loadAuthors();
});

const createTextInput = document.getElementById('text');
const createToolbarRow = document.createElement('div');
createToolbarRow.className = 'markup-toolbar-row';
createToolbarRow.appendChild(buildMarkupToolbar(createTextInput));
createTextInput.parentNode.insertBefore(createToolbarRow, createTextInput);

await initI18n();
await initRoleSwitcher();
loadSources();
loadAuthors();
