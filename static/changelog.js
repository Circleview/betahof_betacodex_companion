import { initI18n, t, getLang } from '/i18n.js';
import { initAuth } from '/auth.js';

// Backlog #99: Änderungs-Log mit Rückgängig-Funktion. Zeigt GET /api/audit-log
// chronologisch (neueste zuerst), nach Kalendertag gruppiert im selben
// Zeitstrahl-Grid wie die Datums-Ansicht der Quellenübersicht (siehe
// #changelog-list.timeline-mode in style.css, analog zu
// #source-list.timeline-mode/buildTimelineMarker in import.js).

await initI18n();
await initAuth();

const listEl = document.getElementById('changelog-list');
const statusEl = document.getElementById('changelog-status');

const PLUS_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<line x1="12" y1="5" x2="12" y2="19"></line>' +
  '<line x1="5" y1="12" x2="19" y2="12"></line>' +
  '</svg>';

const EDIT_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M12 20h9"></path>' +
  '<path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"></path>' +
  '</svg>';

const TRASH_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<polyline points="3 6 5 6 21 6"></polyline>' +
  '<path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>' +
  '<path d="M10 11v6"></path><path d="M14 11v6"></path>' +
  '<path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path>' +
  '</svg>';

const MAGIC_ICON =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor" stroke="none">' +
  '<path d="M12 2l1.8 5.2L19 9l-5.2 1.8L12 16l-1.8-5.2L5 9l5.2-1.8L12 2z"></path>' +
  '<path d="M19 13l.9 2.1L22 16l-2.1.9L19 19l-.9-2.1L16 16l2.1-.9L19 13z"></path>' +
  '</svg>';

const AUTH_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>' +
  '<circle cx="12" cy="7" r="4"></circle>' +
  '</svg>';

const DOCUMENT_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16.5a1 1 0 0 1-1 1H6.5A2.5 2.5 0 0 1 4 18V5.5Z"></path>' +
  '<path d="M6.5 3A2.5 2.5 0 0 0 4 5.5V18a2.5 2.5 0 0 0 2.5 2.5H19"></path>' +
  '<line x1="8" y1="7" x2="16" y2="7"></line>' +
  '<line x1="8" y1="11" x2="16" y2="11"></line>' +
  '</svg>';

const UNDO_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<polyline points="1 4 1 10 7 10"></polyline>' +
  '<path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path>' +
  '</svg>';

const ACTION_ICON = {
  source_created: { icon: PLUS_ICON, cls: 'created' },
  source_updated: { icon: EDIT_ICON, cls: 'updated' },
  source_deleted: { icon: TRASH_ICON, cls: 'deleted' },
  source_reprocessed: { icon: EDIT_ICON, cls: 'updated' },
  source_summary_generated: { icon: EDIT_ICON, cls: 'updated' },
  author_profile_updated: { icon: EDIT_ICON, cls: 'updated' },
  author_renamed: { icon: EDIT_ICON, cls: 'updated' },
  author_bio_generated: { icon: EDIT_ICON, cls: 'updated' },
  web_page_excluded: { icon: TRASH_ICON, cls: 'deleted' },
  web_page_included: { icon: PLUS_ICON, cls: 'created' },
};

const ACTION_LABEL_KEYS = {
  source_created: 'changelog.actionSourceCreated',
  source_updated: 'changelog.actionSourceUpdated',
  source_deleted: 'changelog.actionSourceDeleted',
  source_reprocessed: 'changelog.actionSourceReprocessed',
  source_summary_generated: 'changelog.actionSourceSummaryGenerated',
  author_profile_updated: 'changelog.actionAuthorProfileUpdated',
  author_renamed: 'changelog.actionAuthorRenamed',
  author_bio_generated: 'changelog.actionAuthorBioGenerated',
  web_page_excluded: 'changelog.actionWebPageExcluded',
  web_page_included: 'changelog.actionWebPageIncluded',
};

const FIELD_LABEL_KEYS = {
  title: 'changelog.fieldTitle',
  text: 'changelog.fieldText',
  authors: 'changelog.fieldAuthors',
  date: 'changelog.fieldDate',
  url: 'changelog.fieldUrl',
  listen_url: 'changelog.fieldListenUrl',
  restricted: 'changelog.fieldRestricted',
  summary_de: 'changelog.fieldSummaryDe',
  summary_en: 'changelog.fieldSummaryEn',
  key_terms_de: 'changelog.fieldKeyTermsDe',
  key_terms_en: 'changelog.fieldKeyTermsEn',
  bio_de: 'changelog.fieldBioDe',
  bio_en: 'changelog.fieldBioEn',
  photo_url: 'changelog.fieldPhotoUrl',
  website: 'changelog.fieldWebsite',
  social_links: 'changelog.fieldSocialLinks',
  relevance_score: 'changelog.fieldRelevanceScore',
};

// deleted_at/name werden nicht generisch aufgelistet - die Aktionsbeschreibung
// ("hat die Quelle gelöscht"/"hat umbenannt") plus target_label ("Alt →
// Neu") sagen bereits alles Nötige, ein zusätzliches "null → 2026-..."
// wäre nur verwirrend.
const SKIP_CHANGE_FIELDS = new Set(['deleted_at', 'name']);
const AI_ACTIONS = new Set(['source_summary_generated', 'author_bio_generated']);

function baseAction(action) {
  return action.endsWith('_reverted') ? action.slice(0, -'_reverted'.length) : action;
}

function isRevertAction(action) {
  return action.endsWith('_reverted');
}

function actionLabel(action) {
  const base = baseAction(action);
  const label = t(ACTION_LABEL_KEYS[base] || base);
  return isRevertAction(action) ? t('changelog.revertedPrefix', { action: label }) : label;
}

function truncate(value, max = 80) {
  const str = String(value);
  return str.length > max ? `${str.slice(0, max)}…` : str;
}

function formatValue(value) {
  if (Array.isArray(value)) return value.length ? value.join(', ') : '–';
  if (typeof value === 'boolean') return value ? t('changelog.valueYes') : t('changelog.valueNo');
  if (value === null || value === undefined || value === '') return '–';
  return truncate(String(value));
}

function buildFieldList(changes) {
  const rows = Object.entries(changes || {}).filter(([field]) => !SKIP_CHANGE_FIELDS.has(field));
  if (!rows.length) return null;
  const ul = document.createElement('ul');
  ul.className = 'changelog-field-list';
  rows.forEach(([field, diff]) => {
    const li = document.createElement('li');
    const strong = document.createElement('strong');
    strong.textContent = `${t(FIELD_LABEL_KEYS[field] || field)}: `;
    li.appendChild(strong);
    li.appendChild(document.createTextNode(`„${formatValue(diff.old)}“ → „${formatValue(diff.new)}“`));
    ul.appendChild(li);
  });
  return ul;
}

function isSameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function dayKey(date) {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

function formatDayLabel(date) {
  const today = new Date();
  if (isSameDay(date, today)) return t('changelog.today');
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  if (isSameDay(date, yesterday)) return t('changelog.yesterday');
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
  li.className = 'changelog-day-marker';
  li.textContent = label;
  return li;
}

async function submitRevert(entryId, button) {
  button.disabled = true;
  try {
    const res = await fetch(`/api/audit-log/${entryId}/revert`, {
      method: 'POST',
      headers: { 'X-Lang': getLang() },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('changelog.revertFailed'));
    }
    await loadChangelog();
  } catch (err) {
    statusEl.textContent = t('common.errorPrefix') + err.message;
    statusEl.classList.remove('hidden');
    button.disabled = false;
  }
}

function buildRevertRow(entry) {
  if (entry.reverted_at) {
    const row = document.createElement('div');
    row.className = 'changelog-revert-row';
    const label = document.createElement('span');
    label.className = 'changelog-reverted-label';
    label.textContent = t('changelog.revertedLabel');
    row.appendChild(label);
    return row;
  }

  if (!entry.revertible) return null;

  const row = document.createElement('div');
  row.className = 'changelog-revert-row';

  const revertBtn = document.createElement('button');
  revertBtn.type = 'button';
  revertBtn.className = 'link-button';
  revertBtn.textContent = t('changelog.revertButton');
  row.appendChild(revertBtn);

  revertBtn.addEventListener('click', () => {
    row.replaceChildren();
    const question = document.createElement('span');
    question.textContent = t('changelog.revertConfirmQuestion');
    const yesBtn = document.createElement('button');
    yesBtn.type = 'button';
    yesBtn.className = 'link-button';
    yesBtn.textContent = t('changelog.revertConfirmYes');
    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'link-button';
    cancelBtn.textContent = t('changelog.revertConfirmCancel');
    row.append(question, yesBtn, cancelBtn);

    cancelBtn.addEventListener('click', () => {
      row.replaceChildren(revertBtn);
    });
    yesBtn.addEventListener('click', () => submitRevert(entry.id, yesBtn));
  });

  return row;
}

function buildEntryElement(entry) {
  const li = document.createElement('li');
  li.className = 'changelog-entry';

  const header = document.createElement('div');
  header.className = 'changelog-entry-header';

  const base = baseAction(entry.action);
  // Ein Revert bekommt immer das Undo-Symbol statt des Icons der
  // ursprünglichen Aktion - sonst würde z.B. eine wiederhergestellte
  // Quelle wieder mit dem Papierkorb-Symbol der Löschung angezeigt, was auf
  // den ersten Blick wie eine erneute Löschung aussähe.
  const iconInfo = isRevertAction(entry.action)
    ? { icon: UNDO_ICON, cls: 'reverted' }
    : ACTION_ICON[base] || { icon: EDIT_ICON, cls: 'updated' };
  const actionIcon = document.createElement('span');
  actionIcon.className = `changelog-entry-icon changelog-entry-icon--${iconInfo.cls}`;
  actionIcon.innerHTML = iconInfo.icon;
  header.appendChild(actionIcon);

  const entityIcon = document.createElement('span');
  entityIcon.className = 'changelog-entity-icon';
  entityIcon.innerHTML = entry.entity_type === 'author' ? AUTH_ICON : DOCUMENT_ICON;
  const entityTooltip = t(entry.entity_type === 'author' ? 'changelog.entityAuthorTooltip' : 'changelog.entitySourceTooltip');
  entityIcon.title = entityTooltip;
  entityIcon.setAttribute('aria-label', entityTooltip);
  header.appendChild(entityIcon);

  if (AI_ACTIONS.has(base)) {
    const badge = document.createElement('span');
    badge.className = 'changelog-ai-badge';
    badge.innerHTML = MAGIC_ICON;
    const aiTooltip = t('changelog.aiGeneratedTooltip');
    badge.title = aiTooltip;
    badge.setAttribute('aria-label', aiTooltip);
    header.appendChild(badge);
  }

  const actor = document.createElement('strong');
  actor.className = 'changelog-actor';
  actor.textContent = entry.actor_name || entry.actor_email;
  header.appendChild(actor);

  const actionText = document.createElement('span');
  actionText.textContent = actionLabel(entry.action);
  header.appendChild(actionText);

  const target = document.createElement('span');
  target.className = 'changelog-target-label';
  target.textContent = `„${entry.target_label}“`;
  header.appendChild(target);

  const time = document.createElement('span');
  time.className = 'changelog-time';
  time.textContent = formatTime(new Date(entry.timestamp));
  header.appendChild(time);

  li.appendChild(header);

  const fieldList = buildFieldList(entry.changes);
  if (fieldList) li.appendChild(fieldList);

  const revertRow = buildRevertRow(entry);
  if (revertRow) li.appendChild(revertRow);

  return li;
}

function render(entries) {
  listEl.replaceChildren();
  if (!entries.length) {
    statusEl.textContent = t('changelog.empty');
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

async function loadChangelog() {
  statusEl.textContent = t('changelog.loading');
  statusEl.classList.remove('hidden');
  try {
    const res = await fetch('/api/audit-log', { headers: { 'X-Lang': getLang() } });
    if (res.status === 403) {
      listEl.replaceChildren();
      statusEl.textContent = t('changelog.noAccess');
      statusEl.classList.remove('hidden');
      return;
    }
    if (!res.ok) throw new Error();
    const entries = await res.json();
    render(entries);
  } catch (err) {
    statusEl.textContent = t('changelog.loadFailed');
    statusEl.classList.remove('hidden');
  }
}

loadChangelog();
