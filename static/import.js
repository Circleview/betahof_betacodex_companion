import { initI18n, t, getLang } from '/i18n.js';

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

const WARNING_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"></path>' +
  '<line x1="12" y1="9" x2="12" y2="13"></line>' +
  '<line x1="12" y1="17" x2="12.01" y2="17"></line>' +
  "</svg>";

const UNDO_DURATION_MS = 30000;

let allSources = [];
let currentDisplayedSources = [];
let activeEditId = null;
let devUserList = [];
let currentUserRoles = [];
let pendingUploadId = null;
let currentSortMode = 'author';
const pendingDeletions = new Map();
const unreachableSourceIds = new Set();

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
    renderSourceList(currentDisplayedSources);
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
  listen_url = '',
  text = '',
  restricted = false,
}) {
  document.getElementById('title').value = title;
  document.getElementById('author').value = author;
  document.getElementById('date').value = date;
  document.getElementById('url').value = url;
  document.getElementById('listen_url').value = listen_url;
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

function buildEditPanel(s) {
  const li = document.createElement('li');
  li.className = 'source-edit-panel';

  const form = document.createElement('form');
  const status = document.createElement('p');
  status.className = 'edit-status';

  function field(labelKey, idSuffix, value, type) {
    const label = document.createElement('label');
    label.textContent = t(labelKey);
    const input = document.createElement(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') input.type = type;
    else input.rows = 10;
    input.id = `edit-${idSuffix}-${s.id}`;
    input.value = value || '';
    label.appendChild(input);
    form.appendChild(label);
    return input;
  }

  const titleInput = field('import.fieldTitle', 'title', s.title, 'text');
  titleInput.required = true;
  const authorInput = field('import.fieldAuthor', 'author', s.author, 'text');
  authorInput.setAttribute('list', 'author-suggestions');
  authorInput.setAttribute('autocomplete', 'off');
  const dateInput = field('import.fieldDate', 'date', s.date, 'date');
  const urlInput = field('import.fieldUrl', 'url', s.url, 'url');
  const listenUrlInput = field('import.fieldListenUrl', 'listen-url', s.listen_url, 'url');
  const textInput = field('import.fieldText', 'text', s.text, 'textarea');
  if (s.restricted) {
    textInput.placeholder = t('import.restrictedTextPlaceholder');
  } else {
    textInput.required = true;
  }

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
  deleteBtn.addEventListener('click', () => {
    activeEditId = null;
    scheduleDeletion(s);
  });
  actionsRow.appendChild(deleteBtn);

  form.appendChild(actionsRow);
  form.appendChild(status);

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

  return li;
}

function scheduleDeletion(s) {
  const timeoutId = setTimeout(async () => {
    pendingDeletions.delete(s.id);
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

function renderSummaryWithTerms(summaryText, keyTerms) {
  const p = document.createElement('p');
  p.className = 'source-summary-text';
  if (!keyTerms || keyTerms.length === 0) {
    p.textContent = summaryText;
    return p;
  }
  const pattern = new RegExp(`(${keyTerms.map(escapeRegExp).join('|')})`, 'gi');
  const parts = summaryText.split(pattern);
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
      p.appendChild(btn);
    } else {
      p.appendChild(document.createTextNode(part));
    }
  });
  return p;
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
      return a.title.localeCompare(b.title);
    });
  }
  return copy;
}

function renderSourceList(sources, options = {}) {
  const sorted = sortSources(sources);
  currentDisplayedSources = sorted;
  const list = document.getElementById('source-list');
  list.innerHTML = '';
  sorted.forEach((s) => {
    if (pendingDeletions.has(s.id)) {
      list.appendChild(buildUndoRow(s));
      return;
    }

    const li = document.createElement('li');
    li.className = 'source-row';
    li.dataset.sourceId = s.id;

    const header = document.createElement('div');
    header.className = 'source-row-header';

    const textSpan = document.createElement('span');
    textSpan.append(`${s.title} – `);
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
    textSpan.append(` (${s.date || t('common.noDate')}) [${t('common.chunkCount', { count: s.chunk_count })}]`);
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
      const warning = document.createElement('span');
      warning.className = 'icon-button';
      const warnLabel = t('common.urlUnreachable');
      warning.title = warnLabel;
      warning.setAttribute('aria-label', warnLabel);
      warning.innerHTML = WARNING_ICON;
      actions.appendChild(warning);
    }

    const citationUrl = s.listen_url || s.url;
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

    if (s.summary) {
      const details = document.createElement('details');
      details.className = 'source-summary';
      if (options.openSummaries) details.open = true;
      const summaryToggle = document.createElement('summary');
      summaryToggle.textContent = t('import.summaryLabel');
      details.appendChild(summaryToggle);
      details.appendChild(renderSummaryWithTerms(s.summary, s.key_terms));
      li.appendChild(details);
    }

    list.appendChild(li);

    if (activeEditId === s.id) {
      list.appendChild(buildEditPanel(s));
    }
  });
}

async function checkUrlHealth(sources) {
  if (!hasPflegerRole()) return;
  sources
    .filter((s) => s.url)
    .forEach(async (s) => {
      try {
        const res = await fetch(`/api/sources/${s.id}/check-url`, { headers: devUserHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        if (data.has_url && data.reachable === false) {
          unreachableSourceIds.add(s.id);
          const row = document.querySelector(`#source-list li[data-source-id="${s.id}"] .source-row-actions`);
          if (row && !row.querySelector('.unreachable-marker')) {
            renderSourceList(currentDisplayedSources);
          }
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
  renderSourceList(
    allSources.filter((s) => ids.includes(s.id)),
    { openSummaries: true }
  );

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
  const res = await fetch('/api/sources');
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
    listen_url: document.getElementById('listen_url').value || null,
    text: document.getElementById('text').value,
    restricted: document.getElementById('restricted').checked,
    pdf_upload_id: pendingUploadId,
  };
  const status = document.getElementById('import-status');
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

await initI18n();
await initRoleSwitcher();
loadSources();
loadAuthors();
