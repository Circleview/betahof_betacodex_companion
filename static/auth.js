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

const CLOSE_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<line x1="18" y1="6" x2="6" y2="18"></line>' +
  '<line x1="6" y1="6" x2="18" y2="18"></line>' +
  '</svg>';

const ROLE_LABEL_KEYS = {
  quellen_pfleger: 'auth.roleQuellenPfleger',
  mcp_nutzer: 'auth.roleMcpNutzer',
  user_admin: 'auth.roleUserAdmin',
  system_admin: 'auth.roleSystemAdmin',
};
export const ALL_ROLES = Object.keys(ROLE_LABEL_KEYS);
// Gleiche Regel wie im Backend (app/main.py: set_user_roles/invite_user) -
// Admin-Rollen vergeben/entziehen nur System-Admins.
const ADMIN_ROLES = ['user_admin', 'system_admin'];

export function manageableRoles() {
  return hasRole('system_admin') ? ALL_ROLES : ALL_ROLES.filter((r) => !ADMIN_ROLES.includes(r));
}

let currentUser = { email: null, roles: [], name: null };
const listeners = [];

// Backlog #98 folgend: wo immer der/die eingeloggte User:in selbst
// dargestellt wird (Label unter dem Icon, Popover, Tooltip), den
// gepflegten Namen bevorzugen - fehlt er (noch), wie bisher auf die
// E-Mail zurückfallen.
function currentUserDisplayName() {
  return currentUser.name || currentUser.email;
}

export function roleLabel(role) {
  return t(ROLE_LABEL_KEYS[role] || role);
}

export function currentUserEmail() {
  return currentUser.email;
}

export function hasRole(role) {
  return currentUser.roles.includes('system_admin') || currentUser.roles.includes(role);
}

export function onAuthChange(callback) {
  listeners.push(callback);
}

function notifyAuthChanged() {
  listeners.forEach((cb) => cb());
}

async function refreshCurrentUser() {
  const res = await fetch('/api/auth/whoami');
  currentUser = res.ok ? await res.json() : { email: null, roles: [], name: null };
}

function buildLoggedInPanel() {
  const wrapper = document.createElement('div');

  const info = document.createElement('p');
  info.textContent = `${t('auth.loggedInAs')}: ${currentUserDisplayName()}`;
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

  // 2026-09-24: eigene Seite statt eines weiteren Header-Icons - Schlüssel
  // (MCP-Nutzung) bzw. Kostenübersicht (User-Admins).
  if (hasRole('mcp_nutzer') || hasRole('user_admin')) {
    const mcpLink = document.createElement('a');
    mcpLink.href = '/mcp.html';
    mcpLink.className = 'link-button auth-mcp-link';
    mcpLink.textContent = t('auth.mcpAccessLink');
    wrapper.appendChild(mcpLink);
  }

  // 2026-09-26: Nutzerverwaltung als eigene Seite (users.html) statt im
  // Popover - dort war es mit Rollen-Häkchen je Konto zu eng geworden.
  if (hasRole('user_admin')) {
    const usersLink = document.createElement('a');
    usersLink.href = '/users.html';
    usersLink.className = 'link-button auth-mcp-link';
    usersLink.textContent = t('auth.usersPageLink');
    wrapper.appendChild(usersLink);
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

// Backlog: gleiche Bildschirmbreite, ab der .popover auf position:static
// wechselt (siehe style.css) - unterhalb dieser Breite würde ein
// position:static-Popover als Flex-Item von .header-actions beim Öffnen
// alle anderen Icons der Kopfzeile verschieben (identisches, bereits
// gelöstes Problem wie bei #search-bar/#jobs-bar in import.js).
function isMobileAuthLayout() {
  return window.matchMedia('(max-width: 480px)').matches;
}

// Backlog #183: auf Mobile klappt der Login-/Konto-Bereich als eigenständiger,
// vollbreiter Block direkt unter der Kopfzeile auf statt als Popover -
// gleiches Muster wie .footer-feedback-panel/#search-bar/#jobs-bar. Bleibt
// über einen Seiten-Reload/erneutes renderWidget() hinweg dasselbe
// DOM-Element (per ID gesucht), damit nicht bei jedem Rendern ein weiterer
// Block hinter der Kopfzeile angehängt wird.
function ensureAuthFlowPanel() {
  let panel = document.getElementById('auth-flow-panel');
  if (!panel) {
    const header = document.getElementById('site-header');
    if (!header) return null;
    panel = document.createElement('div');
    panel.id = 'auth-flow-panel';
    panel.className = 'auth-flow-panel hidden';
    header.insertAdjacentElement('afterend', panel);
  }
  return panel;
}

function buildAuthFlowPanelCloseButton(panel) {
  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'auth-flow-panel-close';
  const label = t('import.closeButtonTitle');
  closeBtn.title = label;
  closeBtn.setAttribute('aria-label', label);
  closeBtn.innerHTML = CLOSE_ICON;
  closeBtn.addEventListener('click', () => panel.classList.add('hidden'));
  return closeBtn;
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
    ? `${t('auth.iconTitle')} (${currentUserDisplayName()})`
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
    usernameLabel.textContent = currentUser.name || currentUser.email.split('@')[0];
    container.appendChild(usernameLabel);
  }

  // Desktop: unverändertes Popover, relativ zum Icon positioniert.
  const popover = document.createElement('div');
  popover.className = 'popover auth-popover hidden';
  const arrow = document.createElement('div');
  arrow.className = 'popover-arrow';
  popover.appendChild(arrow);
  popover.appendChild(currentUser.email ? buildLoggedInPanel() : buildLoggedOutPanel(showExpiredNotice));
  container.appendChild(popover);

  // Mobile: eigener, vollbreiter Block unter der Kopfzeile (siehe oben) -
  // bekommt einen unabhängig aufgebauten Inhalt (eigene Formulare/Listener),
  // damit Popover und Flow-Panel sich nicht denselben DOM-Knoten teilen.
  const flowPanel = ensureAuthFlowPanel();
  if (flowPanel) {
    flowPanel.replaceChildren(
      buildAuthFlowPanelCloseButton(flowPanel),
      currentUser.email ? buildLoggedInPanel() : buildLoggedOutPanel(showExpiredNotice)
    );
    flowPanel.classList.add('hidden');
  }

  button.addEventListener('click', (e) => {
    e.stopPropagation();
    if (isMobileAuthLayout()) {
      popover.classList.add('hidden');
      flowPanel?.classList.toggle('hidden');
    } else {
      flowPanel?.classList.add('hidden');
      popover.classList.toggle('hidden');
    }
  });
  if (showExpiredNotice) {
    if (isMobileAuthLayout()) flowPanel?.classList.remove('hidden');
    else popover.classList.remove('hidden');
  }
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
