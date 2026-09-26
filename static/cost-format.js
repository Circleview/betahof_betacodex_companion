import { t, getLang } from '/i18n.js';

// 2026-09-26: gemeinsame Kosten-Darstellung für die Kostenübersicht
// (costs.js) und den Schlüssel-Verbrauch auf der MCP-Seite (mcp.js).

export function formatCurrency(amount, currency) {
  return amount.toLocaleString(getLang() === 'de' ? 'de-DE' : 'en-GB', { style: 'currency', currency });
}

// Nutzerwunsch: immer beide Werte - EUR (Limits) und USD (wie abgerechnet).
export function formatMoney(eur, usd) {
  return `${formatCurrency(eur, 'EUR')} (${formatCurrency(usd, 'USD')})`;
}

// Konten ohne E-Mail: anonyme Aufrufe bzw. Hintergrundarbeiten (app/usage.py).
function accountLabel(account) {
  if (account === 'anonymous') return t('costs.accountAnonymous');
  if (account === 'system') return t('costs.accountSystem');
  return account;
}

export function buildSummaryTable(summary, { showAccounts = true } = {}) {
  const table = document.createElement('table');
  table.className = 'mcp-summary-table';
  const caption = document.createElement('caption');
  caption.textContent = fxText(summary.fx);
  table.appendChild(caption);
  const head = document.createElement('tr');
  [t('mcp.colScope'), t('mcp.colCalls'), t('mcp.colSearches'), t('mcp.colCost')].forEach((label) => {
    const th = document.createElement('th');
    th.textContent = label;
    head.appendChild(th);
  });
  table.appendChild(head);
  // Nutzerwunsch (2026-09-24): Gesamt, darunter als eigene Gruppen "nach
  // Kanal" und "nach Konto" - dieselben Aufrufe aus zwei Blickwinkeln, damit
  // die Zeilen nicht wie Summanden gelesen werden.
  function addRow(name, v, className) {
    const tr = document.createElement('tr');
    tr.className = className;
    [name, String(v.calls), String(v.web_search_requests), formatMoney(v.cost_eur, v.cost_usd)].forEach((text) => {
      const td = document.createElement('td');
      td.textContent = text;
      tr.appendChild(td);
    });
    table.appendChild(tr);
  }
  function addGroup(labelKey, entries) {
    if (!entries.length) return;
    const tr = document.createElement('tr');
    tr.className = 'mcp-summary-group';
    const th = document.createElement('th');
    th.colSpan = 4;
    th.scope = 'rowgroup';
    th.textContent = t(labelKey);
    tr.appendChild(th);
    table.appendChild(tr);
    entries.forEach(([name, v]) => addRow(name, v, 'mcp-summary-sub'));
  }
  addRow(t('mcp.total'), summary.total, 'mcp-summary-total');
  addGroup('mcp.groupChannel', Object.entries(summary.by_channel).map(([ch, v]) => [t(`mcp.channel.${ch}`), v]));
  if (showAccounts) {
    addGroup('mcp.groupAccount', Object.entries(summary.by_email).map(([account, v]) => [accountLabel(account), v]));
  }
  return table;
}

// Nutzerwunsch (2026-09-24): der Umrechnungskurs ist fester Teil der
// Übersicht (Tabellenüberschrift) - jüngster Kurs des Monats bzw. ohne
// Aufrufe der aktuelle Tageskurs; jeder einzelne Kurs steht im CSV.
export function fxText(fx) {
  const locale = getLang() === 'de' ? 'de-DE' : 'en-GB';
  const rate = fx.rate.toLocaleString(locale, { maximumFractionDigits: 5 });
  if (fx.source === 'fallback') return t('mcp.fxFallback', { rate });
  return t('mcp.fxNote', { rate, date: new Date(`${fx.date}T00:00:00`).toLocaleDateString(locale) });
}
