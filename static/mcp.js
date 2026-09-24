import { initI18n, t, getLang } from '/i18n.js';
import { initAuth, hasRole, onAuthChange } from '/auth.js';

// 2026-09-24: MCP-Zugänge zum Kreativ-Modus (app/mcp_server.py). Konten mit
// der Rolle MCP-Nutzung legen hier eigene Schlüssel an (Klartext nur einmal
// sichtbar) und sehen ihren Verbrauch; User-Admins sehen zusätzlich alle
// Schlüssel, ändern Limits und exportieren die Monatskosten als CSV.

await initI18n();
await initAuth();

const statusEl = document.getElementById('mcp-status');
const ownEl = document.getElementById('mcp-own');
const adminEl = document.getElementById('mcp-admin');
const monthInput = document.getElementById('mcp-month');
const endpointUrl = `${window.location.origin}/mcp`;

function jsonHeaders() {
  return { 'Content-Type': 'application/json', 'X-Lang': getLang() };
}

function formatDate(iso) {
  return iso ? new Date(iso).toLocaleString(getLang() === 'de' ? 'de-DE' : 'en-GB') : '–';
}

function formatCurrency(amount, currency) {
  return amount.toLocaleString(getLang() === 'de' ? 'de-DE' : 'en-GB', { style: 'currency', currency });
}

// Nutzerwunsch: immer beide Werte - EUR (Limits) und USD (wie abgerechnet).
function formatMoney(eur, usd) {
  return `${formatCurrency(eur, 'EUR')} (${formatCurrency(usd, 'USD')})`;
}

// Widerrufen zweistufig wie das Löschen von Schlagworten (import.js).
function buildRevokeButton(key, onDone) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'link-button';
  btn.textContent = t('mcp.revoke');
  let confirmPending = false;
  btn.addEventListener('click', async () => {
    if (!confirmPending) {
      confirmPending = true;
      btn.textContent = t('mcp.revokeConfirm');
      return;
    }
    btn.disabled = true;
    const res = await fetch(`/api/mcp/keys/${encodeURIComponent(key.id)}`, { method: 'DELETE', headers: jsonHeaders() });
    if (res.ok) onDone();
    else btn.disabled = false;
  });
  return btn;
}

function buildLimitsEditor(key, onDone) {
  const form = document.createElement('form');
  form.className = 'mcp-limits-form';
  const calls = document.createElement('input');
  calls.type = 'number';
  calls.min = '0';
  calls.step = '1';
  calls.value = key.daily_call_limit;
  calls.title = t('mcp.dailyLimitTitle');
  calls.setAttribute('aria-label', t('mcp.dailyLimitTitle'));
  const eur = document.createElement('input');
  eur.type = 'number';
  eur.min = '0';
  eur.step = '0.5';
  eur.value = key.monthly_eur_limit;
  eur.title = t('mcp.monthlyLimitTitle');
  eur.setAttribute('aria-label', t('mcp.monthlyLimitTitle'));
  const save = document.createElement('button');
  save.type = 'submit';
  save.className = 'link-button';
  save.textContent = t('mcp.saveLimits');
  form.append(calls, ` ${t('mcp.perDay')} · `, eur, ` ${t('mcp.eurPerMonth')} `, save);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const res = await fetch(`/api/mcp/keys/${encodeURIComponent(key.id)}/limits`, {
      method: 'PUT',
      headers: jsonHeaders(),
      body: JSON.stringify({ daily_call_limit: Number(calls.value), monthly_eur_limit: Number(eur.value) }),
    });
    if (res.ok) onDone();
  });
  return form;
}

function buildKeyItem(key, { admin, onChange }) {
  const li = document.createElement('li');
  li.className = 'mcp-key-item';
  if (key.revoked_at) li.classList.add('mcp-key-item--revoked');

  const title = document.createElement('p');
  title.className = 'mcp-key-title';
  const label = document.createElement('strong');
  label.textContent = key.label;
  const hint = document.createElement('code');
  hint.textContent = `${key.key_hint}…`;
  title.append(label, ' ', hint);
  if (admin) title.append(` · ${key.email}`);
  if (key.revoked_at) {
    const badge = document.createElement('span');
    badge.className = 'restricted-badge';
    badge.textContent = t('mcp.revoked');
    title.append(' ', badge);
  }
  li.appendChild(title);

  const stats = document.createElement('p');
  stats.className = 'mcp-key-stats';
  stats.textContent = t('mcp.stats', {
    calls: key.calls_today,
    callLimit: key.daily_call_limit,
    cost: formatMoney(key.month_eur, key.month_usd),
    costLimit: formatCurrency(key.monthly_eur_limit, 'EUR'),
    lastUsed: formatDate(key.last_used_at),
  });
  li.appendChild(stats);

  if (!key.revoked_at) {
    const actions = document.createElement('div');
    actions.className = 'mcp-key-actions';
    if (admin) actions.appendChild(buildLimitsEditor(key, onChange));
    actions.appendChild(buildRevokeButton(key, onChange));
    li.appendChild(actions);
  }
  return li;
}

async function loadOwnKeys() {
  const res = await fetch('/api/mcp/keys', { headers: jsonHeaders() });
  if (!res.ok) return;
  const keys = await res.json();
  const list = document.getElementById('mcp-own-list');
  list.replaceChildren(...keys.map((k) => buildKeyItem(k, { admin: false, onChange: refresh })));
  document.getElementById('mcp-own-empty').classList.toggle('hidden', keys.length > 0);
}

function buildSummaryTable(summary) {
  const table = document.createElement('table');
  table.className = 'mcp-summary-table';
  const head = document.createElement('tr');
  [t('mcp.colScope'), t('mcp.colCalls'), t('mcp.colSearches'), t('mcp.colCost')].forEach((label) => {
    const th = document.createElement('th');
    th.textContent = label;
    head.appendChild(th);
  });
  table.appendChild(head);
  const rows = [
    [t('mcp.total'), summary.total],
    ...Object.entries(summary.by_channel).map(([ch, v]) => [t(`mcp.channel.${ch}`), v]),
    ...Object.entries(summary.by_email).map(([email, v]) => [email, v]),
  ];
  rows.forEach(([name, v]) => {
    const tr = document.createElement('tr');
    [name, String(v.calls), String(v.web_search_requests), formatMoney(v.cost_eur, v.cost_usd)].forEach((text) => {
      const td = document.createElement('td');
      td.textContent = text;
      tr.appendChild(td);
    });
    table.appendChild(tr);
  });
  return table;
}

async function loadAdmin() {
  const month = monthInput.value;
  document.getElementById('mcp-csv-link').href = `/api/mcp/usage.csv?month=${encodeURIComponent(month)}`;
  const [summaryRes, keysRes] = await Promise.all([
    fetch(`/api/mcp/usage?month=${encodeURIComponent(month)}`, { headers: jsonHeaders() }),
    fetch('/api/mcp/admin/keys', { headers: jsonHeaders() }),
  ]);
  if (!summaryRes.ok || !keysRes.ok) return;
  document.getElementById('mcp-summary').replaceChildren(buildSummaryTable(await summaryRes.json()));
  const keys = await keysRes.json();
  document
    .getElementById('mcp-admin-list')
    .replaceChildren(...keys.map((k) => buildKeyItem(k, { admin: true, onChange: refresh })));
  document.getElementById('mcp-admin-empty').classList.toggle('hidden', keys.length > 0);
}

async function refresh() {
  const own = hasRole('mcp_nutzer');
  const admin = hasRole('user_admin');
  ownEl.classList.toggle('hidden', !own);
  adminEl.classList.toggle('hidden', !admin);
  statusEl.textContent = own || admin ? '' : t('mcp.noAccess');
  statusEl.classList.toggle('hidden', own || admin);
  if (own) await loadOwnKeys();
  if (admin) await loadAdmin();
}

document.getElementById('mcp-endpoint-url').textContent = endpointUrl;
monthInput.value = new Date().toISOString().slice(0, 7);
monthInput.addEventListener('change', loadAdmin);

document.getElementById('mcp-create-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const labelInput = document.getElementById('mcp-create-label');
  const res = await fetch('/api/mcp/keys', {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ label: labelInput.value.trim() }),
  });
  if (!res.ok) return;
  const { secret } = await res.json();
  labelInput.value = '';
  document.getElementById('mcp-secret').textContent = secret;
  document.getElementById('mcp-claude-code-cmd').textContent =
    `claude mcp add --transport http betacodex ${endpointUrl} --header "Authorization: Bearer ${secret}"`;
  document.getElementById('mcp-secret-box').classList.remove('hidden');
  await refresh();
});

document.querySelectorAll('[data-copy]').forEach((btn) => {
  btn.addEventListener('click', async () => {
    const text = document.getElementById(btn.dataset.copy).textContent;
    try {
      await navigator.clipboard.writeText(text);
      btn.textContent = t('mcp.copied');
      setTimeout(() => {
        btn.textContent = t('mcp.copy');
      }, 1600);
    } catch (err) {
      // Zwischenablage nicht erlaubt - Text bleibt zum manuellen Kopieren stehen.
    }
  });
});

onAuthChange(refresh);
document.addEventListener('i18n:changed', refresh);
await refresh();
