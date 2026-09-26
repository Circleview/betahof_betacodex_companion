import { initI18n, t, getLang } from '/i18n.js';
import { initAuth, hasRole, onAuthChange, ALL_ROLES, manageableRoles, roleLabel, currentUserEmail } from '/auth.js';

// 2026-09-26: Nutzerverwaltung als eigene Seite (vorher im Login-Popover,
// static/auth.js). Einladen mit mehreren Rollen, Rollen je Konto per Häkchen,
// Namen bearbeiten, Einladung erneut senden, Konto entfernen. Rechteregeln
// prüft das Backend (app/main.py) - hier nur passend ein-/ausgeblendet.

await initI18n();
await initAuth();

const statusEl = document.getElementById('users-status');
const adminEl = document.getElementById('users-admin');
const listEl = document.getElementById('users-list');
const inviteForm = document.getElementById('users-invite-form');
const inviteRolesEl = document.getElementById('users-invite-roles');
const inviteStatus = document.getElementById('users-invite-status');

const PENCIL_ICON =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" ' +
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

const ADMIN_ROLES = ['user_admin', 'system_admin'];
let entries = [];
// Welche Konten gerade im Namens-Bearbeiten-Modus sind - überlebt ein
// Neuzeichnen der Liste (z. B. nach dem Einladen einer weiteren Person).
const editingNames = new Set();

function jsonHeaders() {
  return { 'Content-Type': 'application/json', 'X-Lang': getLang() };
}

function formatDate(iso) {
  return iso ? new Date(iso).toLocaleDateString(getLang() === 'de' ? 'de-DE' : 'en-GB') : '–';
}

async function errorDetail(res) {
  const data = await res.json().catch(() => ({}));
  return data.detail || t('index.askError');
}

function iconButton(icon, titleKey, onClick) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'icon-button';
  btn.innerHTML = icon;
  btn.title = t(titleKey);
  btn.setAttribute('aria-label', t(titleKey));
  btn.addEventListener('click', onClick);
  return btn;
}

function cell(labelKey) {
  const td = document.createElement('td');
  if (labelKey) td.dataset.label = t(labelKey);
  return td;
}

function buildNameCell(u) {
  const td = cell('users.colName');
  const wrap = document.createElement('div');
  wrap.className = 'users-name-cell';
  td.appendChild(wrap);
  if (editingNames.has(u.email)) {
    const form = document.createElement('form');
    const input = document.createElement('input');
    input.type = 'text';
    input.value = u.name || '';
    input.placeholder = t('auth.namePlaceholder');
    const save = document.createElement('button');
    save.type = 'submit';
    save.textContent = t('auth.saveName');
    form.append(input, save);
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const res = await fetch(`/api/auth/users/${encodeURIComponent(u.email)}/name`, {
        method: 'PUT',
        headers: jsonHeaders(),
        body: JSON.stringify({ name: input.value.trim() }),
      });
      if (res.ok) u.name = (await res.json()).name;
      editingNames.delete(u.email);
      render();
    });
    wrap.appendChild(form);
    requestAnimationFrame(() => input.focus());
  } else {
    const name = document.createElement('span');
    name.textContent = u.name || t('auth.addName');
    if (!u.name) name.className = 'users-name-empty';
    wrap.append(
      name,
      iconButton(PENCIL_ICON, 'auth.editName', () => {
        editingNames.add(u.email);
        render();
      })
    );
  }
  return td;
}

function buildRolesCell(u, rowStatus) {
  const td = cell('users.colRoles');
  const row = document.createElement('div');
  row.className = 'users-role-checkboxes';
  const allowed = manageableRoles();
  ALL_ROLES.forEach((role) => {
    const label = document.createElement('label');
    label.className = 'checkbox-label';
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = u.roles.includes(role);
    box.disabled = !allowed.includes(role);
    box.addEventListener('change', async () => {
      rowStatus.textContent = '';
      const roles = box.checked ? [...u.roles, role] : u.roles.filter((r) => r !== role);
      const res = await fetch(`/api/auth/users/${encodeURIComponent(u.email)}/roles`, {
        method: 'PUT',
        headers: jsonHeaders(),
        body: JSON.stringify({ roles }),
      });
      if (res.ok) {
        u.roles = (await res.json()).roles;
      } else {
        box.checked = !box.checked;
        rowStatus.textContent = t('common.errorPrefix') + (await errorDetail(res));
      }
    });
    label.append(box, roleLabel(role));
    row.appendChild(label);
  });
  td.appendChild(row);
  return td;
}

// Entfernen zweistufig (erster Klick fragt nach, zweiter löscht) - wie das
// Widerrufen von MCP-Schlüsseln, ohne Browser-Dialog.
function buildActionsCell(u, rowStatus) {
  const td = cell();
  const actions = document.createElement('div');
  actions.className = 'users-actions';
  td.append(actions, rowStatus);

  if (u.status === 'invited') {
    const resend = document.createElement('button');
    resend.type = 'button';
    resend.className = 'link-button';
    resend.textContent = t('users.resend');
    resend.title = t('users.resendTitle');
    resend.addEventListener('click', async () => {
      resend.disabled = true;
      const res = await fetch(`/api/auth/users/${encodeURIComponent(u.email)}/resend-invite`, {
        method: 'POST',
        headers: jsonHeaders(),
      });
      rowStatus.textContent = res.ok ? t('users.resendDone') : t('common.errorPrefix') + (await errorDetail(res));
      resend.disabled = false;
    });
    actions.appendChild(resend);
  }

  const isSelf = u.email === currentUserEmail();
  const isAdminAccount = u.roles.some((r) => ADMIN_ROLES.includes(r));
  if (!isSelf && (!isAdminAccount || hasRole('system_admin'))) {
    const del = iconButton(TRASH_ICON, 'users.delete', () => {
      del.classList.add('hidden');
      confirm.classList.remove('hidden');
      confirm.focus();
    });
    const confirm = document.createElement('button');
    confirm.type = 'button';
    confirm.className = 'link-button hidden';
    confirm.textContent = t('users.deleteConfirm');
    confirm.addEventListener('click', async () => {
      confirm.disabled = true;
      const res = await fetch(`/api/auth/users/${encodeURIComponent(u.email)}`, {
        method: 'DELETE',
        headers: jsonHeaders(),
      });
      if (res.ok) {
        entries = entries.filter((e) => e.email !== u.email);
        render();
      } else {
        rowStatus.textContent = t('common.errorPrefix') + (await errorDetail(res));
        confirm.disabled = false;
      }
    });
    actions.append(del, confirm);
  }
  return td;
}

function buildRow(u) {
  const tr = document.createElement('tr');
  const rowStatus = document.createElement('p');
  rowStatus.className = 'users-row-status';

  const email = cell('users.colEmail');
  email.textContent = u.email;
  const status = cell('users.colStatus');
  status.textContent = t(u.status === 'active' ? 'auth.statusActive' : 'auth.statusInvited');
  const invited = cell('users.colInvited');
  invited.className = 'users-muted';
  invited.textContent = formatDate(u.invited_at);
  const lastLogin = cell('users.colLastLogin');
  lastLogin.className = 'users-muted';
  lastLogin.textContent = formatDate(u.last_login_at);

  tr.append(
    buildNameCell(u),
    email,
    status,
    buildRolesCell(u, rowStatus),
    invited,
    lastLogin,
    buildActionsCell(u, rowStatus)
  );
  return tr;
}

function render() {
  listEl.replaceChildren(...entries.map(buildRow));
}

function renderInviteRoles() {
  const allowed = manageableRoles();
  inviteRolesEl.replaceChildren(
    ...allowed.map((role) => {
      const label = document.createElement('label');
      label.className = 'checkbox-label';
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.value = role;
      label.append(box, roleLabel(role));
      return label;
    })
  );
}

async function refresh() {
  if (!hasRole('user_admin')) {
    adminEl.classList.add('hidden');
    statusEl.textContent = t('users.noAccess');
    statusEl.classList.remove('hidden');
    return;
  }
  const res = await fetch('/api/auth/users', { headers: jsonHeaders() });
  if (!res.ok) {
    statusEl.textContent = t('common.errorPrefix') + (await errorDetail(res));
    return;
  }
  entries = await res.json();
  statusEl.classList.add('hidden');
  adminEl.classList.remove('hidden');
  renderInviteRoles();
  render();
}

inviteForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  inviteStatus.textContent = '';
  const email = document.getElementById('users-invite-email');
  const name = document.getElementById('users-invite-name');
  const roles = [...inviteRolesEl.querySelectorAll('input:checked')].map((box) => box.value);
  const res = await fetch('/api/auth/invite', {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ email: email.value.trim(), roles, name: name.value.trim() || null }),
  });
  if (!res.ok) {
    inviteStatus.textContent = t('common.errorPrefix') + (await errorDetail(res));
    return;
  }
  inviteStatus.textContent = t('users.inviteSent', { email: email.value.trim() });
  email.value = '';
  name.value = '';
  await refresh();
});

onAuthChange(refresh);
document.addEventListener('i18n:changed', refresh);
await refresh();
