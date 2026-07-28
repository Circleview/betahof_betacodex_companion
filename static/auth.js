import { initI18n, t, getLang } from '/i18n.js';

// Gemeinsames Login-Widget für import.html und question.js - ersetzt den
// alten, unsicheren Dev-Rollen-Schalter (X-Dev-User-Header) durch echten,
// cookie-basierten Login. Login ist optional: ohne Login bleibt die ganze
// App nutzbar, nur zusätzliche Rechte (Quellen bearbeiten etc.) fehlen dann.

const AUTH_ICON =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>' +
  '<circle cx="12" cy="7" r="4"></circle>' +
  '</svg>';

// Angemeldeter Zustand: gleiches Personen-Icon plus kleines Haken-Abzeichen
// unten rechts, statt eines komplett anderen Icons - bleibt auf den ersten
// Blick als "derselbe" User-Button erkennbar, nur eben eingeloggt.
const AUTH_ICON_LOGGED_IN =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>' +
  '<circle cx="12" cy="7" r="4"></circle>' +
  '<circle cx="18.5" cy="18.5" r="4.5" fill="var(--color-accent)" stroke="var(--color-bg)" stroke-width="1.5"></circle>' +
  '<path d="M16.6 18.6l1.3 1.3 2.2-2.6" stroke="var(--color-bg)" stroke-width="1.6"></path>' +
  '</svg>';

const ROLE_LABEL_KEYS = {
  quellen_pfleger: 'auth.roleQuellenPfleger',
  user_admin: 'auth.roleUserAdmin',
  system_admin: 'auth.roleSystemAdmin',
};

let currentUser = { email: null, roles: [] };
const listeners = [];

function roleLabel(role) {
  return t(ROLE_LABEL_KEYS[role] || role);
}

export function hasRole(role) {
  return currentUser.roles.includes('system_admin') || currentUser.roles.includes(role);
}

export function getCurrentEmail() {
  return currentUser.email;
}

export function onAuthChange(callback) {
  listeners.push(callback);
}

function notifyAuthChanged() {
  listeners.forEach((cb) => cb());
}

async function refreshCurrentUser() {
  const res = await fetch('/api/auth/whoami');
  currentUser = res.ok ? await res.json() : { email: null, roles: [] };
}

const PENCIL_ICON =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M12 20h9"></path>' +
  '<path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"></path>' +
  '</svg>';

// Backlog #98: welche E-Mails sich gerade im "Name bearbeiten"-Zustand
// befinden - modulweiter Zustand (nicht pro Aufruf von refreshUserList),
// damit ein Refresh durch einen ANDEREN Eintrag (z.B. nach dem Einladen
// einer weiteren Person) einen bereits geöffneten Bearbeiten-Modus nicht
// versehentlich schließt.
const editingUserNames = new Set();

// Reines Rendering aus bereits geladenen Daten - KEIN eigener Netzwerk-
// Aufruf. Wird sowohl nach dem initialen Laden als auch für rein lokale
// Zustandswechsel (Stift-Icon auf/zu) verwendet, damit letzteres nicht bei
// jedem Klick eine komplette Server-Anfrage auslöst (das verursachte die
// spürbare Verzögerung beim Öffnen und - bei zwei sich überholenden
// Antworten - sogar verlorene, gerade erst gespeicherte Namen).
function renderUserList(listEl, entries) {
  listEl.replaceChildren(
    ...entries.map((u) => {
      const li = document.createElement('li');
      li.className = 'auth-user-list-item';

      const info = document.createElement('span');
      const statusLabel = t(u.status === 'active' ? 'auth.statusActive' : 'auth.statusInvited');
      info.textContent = `${u.email} – ${u.roles.map(roleLabel).join(', ')} (${statusLabel})`;
      li.appendChild(info);

      const nameRow = document.createElement('div');
      nameRow.className = 'auth-user-name-row';
      li.appendChild(nameRow);

      if (editingUserNames.has(u.email)) {
        // Bearbeiten-Modus: normales Eingabefeld statt window.prompt() -
        // analog zur bestehenden Autor:innen-Umbenennung.
        const nameForm = document.createElement('form');
        nameForm.className = 'auth-user-name-form';
        const nameInput = document.createElement('input');
        nameInput.type = 'text';
        nameInput.value = u.name || '';
        nameInput.placeholder = t('auth.namePlaceholder');
        const saveBtn = document.createElement('button');
        saveBtn.type = 'submit';
        saveBtn.textContent = t('auth.saveName');
        nameForm.append(nameInput, saveBtn);
        nameRow.appendChild(nameForm);

        nameForm.addEventListener('submit', async (e) => {
          e.preventDefault();
          const newName = nameInput.value.trim();
          const res = await fetch(`/api/auth/users/${encodeURIComponent(u.email)}/name`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', 'X-Lang': getLang() },
            body: JSON.stringify({ name: newName }),
          });
          if (res.ok) {
            // Optimistisch im schon geladenen Array aktualisieren statt
            // erneut komplett von /api/auth/users nachzuladen - der
            // Server hat exakt das gerade gesendete name-Feld übernommen.
            u.name = newName || null;
          }
          editingUserNames.delete(u.email);
          renderUserList(listEl, entries);
        });
        nameInput.focus();
      } else {
        // Anzeige-Modus: der zuletzt gespeicherte Name erscheint direkt
        // wieder als Text (statt dass das Eingabefeld einfach verschwindet)
        // - ein Stift-Icon öffnet erneut den Bearbeiten-Modus, z.B. um einen
        // Tippfehler zu korrigieren.
        const nameDisplay = document.createElement('span');
        nameDisplay.className = 'auth-user-name-display';
        nameDisplay.textContent = u.name || t('auth.addName');
        nameRow.appendChild(nameDisplay);

        const editBtn = document.createElement('button');
        editBtn.type = 'button';
        editBtn.className = 'auth-edit-name-btn';
        editBtn.innerHTML = PENCIL_ICON;
        editBtn.title = t('auth.editName');
        editBtn.setAttribute('aria-label', t('auth.editName'));
        editBtn.addEventListener('click', (e) => {
          // Ohne dies schließt sich das Popover: renderUserList() ersetzt
          // synchron die Liste inkl. dieses Buttons, bevor das Klick-Event
          // bis zum globalen "Klick außerhalb schließt Popover"-Handler auf
          // document hochgeblubbert ist - der prüft per .contains(), ob das
          // (durch die Ersetzung bereits aus dem DOM entfernte) Ziel noch im
          // Container steckt, und schließt sonst fälschlich das Popover.
          e.stopPropagation();
          editingUserNames.add(u.email);
          renderUserList(listEl, entries);
        });
        nameRow.appendChild(editBtn);
      }

      return li;
    })
  );
}

async function refreshUserList(listEl) {
  const res = await fetch('/api/auth/users');
  if (!res.ok) return;
  const entries = await res.json();
  renderUserList(listEl, entries);
}

function buildAdminSection() {
  const wrapper = document.createElement('div');
  wrapper.className = 'auth-admin-section';

  const inviteHeading = document.createElement('p');
  inviteHeading.className = 'auth-section-heading';
  inviteHeading.textContent = t('auth.inviteHeading');
  wrapper.appendChild(inviteHeading);

  const form = document.createElement('form');
  form.className = 'auth-invite-form';
  const nameInput = document.createElement('input');
  nameInput.type = 'text';
  nameInput.placeholder = t('auth.namePlaceholder');
  const emailInput = document.createElement('input');
  emailInput.type = 'email';
  emailInput.required = true;
  emailInput.placeholder = t('auth.emailPlaceholder');
  const roleSelect = document.createElement('select');
  const allowedRoles = hasRole('system_admin')
    ? ['quellen_pfleger', 'user_admin', 'system_admin']
    : ['quellen_pfleger'];
  allowedRoles.forEach((role) => {
    const option = document.createElement('option');
    option.value = role;
    option.textContent = roleLabel(role);
    roleSelect.appendChild(option);
  });
  const submitBtn = document.createElement('button');
  submitBtn.type = 'submit';
  submitBtn.textContent = t('auth.inviteSubmit');
  form.append(nameInput, emailInput, roleSelect, submitBtn);
  const status = document.createElement('p');
  status.className = 'auth-status';
  form.appendChild(status);
  wrapper.appendChild(form);

  const listHeading = document.createElement('p');
  listHeading.className = 'auth-section-heading';
  listHeading.textContent = t('auth.usersHeading');
  wrapper.appendChild(listHeading);
  const listEl = document.createElement('ul');
  listEl.className = 'auth-user-list';
  wrapper.appendChild(listEl);
  refreshUserList(listEl);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    status.textContent = '';
    try {
      const res = await fetch('/api/auth/invite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Lang': getLang() },
        body: JSON.stringify({
          email: emailInput.value.trim(),
          role: roleSelect.value,
          name: nameInput.value.trim() || null,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || t('index.askError'));
      nameInput.value = '';
      emailInput.value = '';
      await refreshUserList(listEl);
    } catch (err) {
      status.textContent = t('common.errorPrefix') + err.message;
    }
  });

  return wrapper;
}

function buildLoggedInPanel() {
  const wrapper = document.createElement('div');

  const info = document.createElement('p');
  info.textContent = `${t('auth.loggedInAs')}: ${currentUser.email}`;
  wrapper.appendChild(info);

  const statusRow = document.createElement('div');
  statusRow.className = 'auth-status-row';

  const rolesLine = document.createElement('span');
  rolesLine.className = 'auth-roles';
  rolesLine.textContent = currentUser.roles.map(roleLabel).join(', ');
  statusRow.appendChild(rolesLine);

  const logoutBtn = document.createElement('button');
  logoutBtn.type = 'button';
  logoutBtn.className = 'link-button';
  logoutBtn.textContent = t('auth.logout');
  logoutBtn.addEventListener('click', async () => {
    await fetch('/api/auth/logout', { method: 'POST' });
    await refreshCurrentUser();
    renderWidget();
    notifyAuthChanged();
  });
  statusRow.appendChild(logoutBtn);

  wrapper.appendChild(statusRow);

  if (hasRole('user_admin')) {
    wrapper.appendChild(buildAdminSection());
  }

  return wrapper;
}

function buildLoggedOutPanel(showExpiredNotice) {
  const wrapper = document.createElement('div');

  if (showExpiredNotice) {
    const notice = document.createElement('p');
    notice.className = 'auth-status';
    notice.textContent = t('auth.linkExpired');
    wrapper.appendChild(notice);
  }

  const form = document.createElement('form');
  form.className = 'auth-login-form';
  const input = document.createElement('input');
  input.type = 'email';
  input.required = true;
  input.placeholder = t('auth.emailPlaceholder');
  const submitBtn = document.createElement('button');
  submitBtn.type = 'submit';
  submitBtn.textContent = t('auth.sendLink');
  form.append(input, submitBtn);
  const status = document.createElement('p');
  status.className = 'auth-status';
  form.appendChild(status);
  wrapper.appendChild(form);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    status.textContent = '';
    try {
      const res = await fetch('/api/auth/request-link', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Lang': getLang() },
        body: JSON.stringify({ email: input.value.trim() }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || t('index.askError'));
      form.replaceChildren();
      const confirmation = document.createElement('p');
      confirmation.textContent = data.detail;
      form.appendChild(confirmation);
    } catch (err) {
      status.textContent = t('common.errorPrefix') + err.message;
    }
  });

  return wrapper;
}

function renderWidget(showExpiredNotice) {
  const container = document.getElementById('auth-widget');
  if (!container) return;
  container.replaceChildren();

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'icon-button auth-widget-button';
  if (currentUser.email) button.classList.add('auth-widget-button--active');
  const title = currentUser.email
    ? `${t('auth.iconTitle')} (${currentUser.email})`
    : t('auth.iconTitle');
  button.title = title;
  button.setAttribute('aria-label', title);
  button.innerHTML = currentUser.email ? AUTH_ICON_LOGGED_IN : AUTH_ICON;
  container.appendChild(button);

  if (currentUser.email) {
    // Absolut positioniert (relativ zu .auth-widget), damit der Name unter
    // dem Icon erscheint, ohne die Höhe der Icon-Zeile zu beeinflussen und
    // die anderen Icons daneben zu verschieben.
    const usernameLabel = document.createElement('span');
    usernameLabel.className = 'auth-username-label';
    usernameLabel.textContent = currentUser.email.split('@')[0];
    container.appendChild(usernameLabel);
  }

  const popover = document.createElement('div');
  popover.className = 'popover auth-popover hidden';
  const arrow = document.createElement('div');
  arrow.className = 'popover-arrow';
  popover.appendChild(arrow);
  popover.appendChild(currentUser.email ? buildLoggedInPanel() : buildLoggedOutPanel(showExpiredNotice));
  container.appendChild(popover);

  button.addEventListener('click', (e) => {
    e.stopPropagation();
    popover.classList.toggle('hidden');
  });
  if (showExpiredNotice) popover.classList.remove('hidden');
}

document.addEventListener('click', (e) => {
  const container = document.getElementById('auth-widget');
  if (container && !container.contains(e.target)) {
    container.querySelector('.popover')?.classList.add('hidden');
  }
});

export async function initAuth() {
  await initI18n();
  await refreshCurrentUser();

  const params = new URLSearchParams(window.location.search);
  const showExpiredNotice = params.get('auth') === 'expired' && !currentUser.email;
  renderWidget(showExpiredNotice);

  if (params.has('auth')) {
    params.delete('auth');
    const query = params.toString();
    window.history.replaceState({}, '', window.location.pathname + (query ? `?${query}` : ''));
  }

  document.addEventListener('i18n:changed', () => renderWidget());
}
