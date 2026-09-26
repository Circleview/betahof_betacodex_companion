import { initI18n, t, getLang } from '/i18n.js';
import { initAuth, hasRole, onAuthChange, currentUserEmail } from '/auth.js';
import { buildSummaryTable } from '/cost-format.js';

// 2026-09-26: Kostenübersicht als eigene Seite (vorher Kostenblock auf der
// MCP-Seite). System-Admins: alle Kosten über alle Konten (/api/costs).
// Alle anderen Angemeldeten: nur die eigenen (/api/costs/mine).

await initI18n();
await initAuth();

const headingEl = document.getElementById('costs-heading');
const statusEl = document.getElementById('costs-status');
const contentEl = document.getElementById('costs-content');
const monthInput = document.getElementById('costs-month');
monthInput.value = new Date().toISOString().slice(0, 7);

async function refresh() {
  const all = hasRole('system_admin');
  headingEl.textContent = t(all ? 'costs.heading' : 'costs.mineHeading');
  if (!currentUserEmail()) {
    contentEl.classList.add('hidden');
    statusEl.textContent = t('costs.noAccess');
    statusEl.classList.remove('hidden');
    return;
  }
  const base = all ? '/api/costs' : '/api/costs/mine';
  const month = encodeURIComponent(monthInput.value);
  document.getElementById('costs-csv-link').href = `${base}.csv?month=${month}`;
  document.getElementById('costs-hint').textContent = t(all ? 'mcp.costScopeHint' : 'costs.mineHint');
  const res = await fetch(`${base}?month=${month}`, { headers: { 'X-Lang': getLang() } });
  if (!res.ok) {
    statusEl.textContent = t('common.errorPrefix') + res.statusText;
    statusEl.classList.remove('hidden');
    return;
  }
  const summary = await res.json();
  document.getElementById('costs-summary').replaceChildren(buildSummaryTable(summary, { showAccounts: all }));
  statusEl.classList.add('hidden');
  contentEl.classList.remove('hidden');
}

monthInput.addEventListener('change', refresh);
onAuthChange(refresh);
document.addEventListener('i18n:changed', refresh);
await refresh();
