import { initI18n, t, getLang } from '/i18n.js';
import { initAuth, hasRole, onAuthChange, currentUserEmail } from '/auth.js';
import { buildSummaryTable, formatCurrency, formatMoney } from '/cost-format.js';

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

// Nutzerwunsch (2026-09-26): Monatsverlauf als Balkengrafik (eine Reihe,
// Gesamtkosten in EUR). Hover/Fokus zeigt einen Tooltip mit Kosten, Aufrufen
// und den größten Kanälen, Klick/Enter wählt den Monat für die Tabelle.
const SVG_NS = 'http://www.w3.org/2000/svg';
const CHART = { width: 960, height: 220, left: 64, right: 8, top: 12, bottom: 32 };
let history = [];

function svgEl(name, attrs) {
  const el = document.createElementNS(SVG_NS, name);
  Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
  return el;
}

function niceMax(value) {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 2.5, 5, 10].find((f) => f * magnitude >= value);
  return step * magnitude;
}

function monthLabel(month, withYear) {
  const locale = getLang() === 'de' ? 'de-DE' : 'en-GB';
  const date = new Date(`${month}-01T00:00:00`);
  return date.toLocaleDateString(locale, withYear ? { month: 'short', year: '2-digit' } : { month: 'short' });
}

function showTooltip(entry, x) {
  const tooltip = document.getElementById('costs-tooltip');
  const channels = Object.entries(entry.by_channel)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([ch, eur]) => `${t(`mcp.channel.${ch}`)}: ${formatCurrency(eur, 'EUR')}`);
  tooltip.replaceChildren(
    ...[
      [monthLabel(entry.month, true), 'costs-tooltip-title'],
      [formatMoney(entry.cost_eur, entry.cost_usd), 'costs-tooltip-value'],
      [t('costs.tooltipCalls', { n: entry.calls }), ''],
      ...channels.map((c) => [c, 'costs-tooltip-channel']),
    ].map(([text, className]) => {
      const line = document.createElement('div');
      line.textContent = text;
      if (className) line.className = className;
      return line;
    })
  );
  tooltip.style.left = `${(x / CHART.width) * 100}%`;
  tooltip.classList.remove('hidden');
}

function hideTooltip() {
  document.getElementById('costs-tooltip').classList.add('hidden');
}

function renderChart() {
  const { width, height, left, right, top, bottom } = CHART;
  const plotW = width - left - right;
  const plotH = height - top - bottom;
  const max = niceMax(Math.max(...history.map((h) => h.cost_eur)));
  const y = (v) => top + plotH - (v / max) * plotH;
  const slot = plotW / history.length;
  const barW = Math.min(slot * 0.62, 40);
  const svg = svgEl('svg', {
    viewBox: `0 0 ${width} ${height}`,
    role: 'img',
    'aria-label': t('costs.chartLabel'),
  });

  // Recessives Raster mit 4 Stufen, Beschriftung in EUR.
  for (let i = 0; i <= 4; i += 1) {
    const value = (max / 4) * i;
    svg.appendChild(svgEl('line', { x1: left, x2: width - right, y1: y(value), y2: y(value), class: 'costs-grid' }));
    const label = svgEl('text', { x: left - 8, y: y(value) + 4, class: 'costs-axis-label', 'text-anchor': 'end' });
    label.textContent = formatCurrency(value, 'EUR');
    svg.appendChild(label);
  }

  const selected = monthInput.value;
  history.forEach((entry, i) => {
    const cx = left + slot * i + slot / 2;
    const h = top + plotH - y(entry.cost_eur);
    if (h > 0) {
      // Oben 4px abgerundet, unten bündig an der Grundlinie.
      const r = Math.min(4, h, barW / 2);
      const x0 = cx - barW / 2;
      const yTop = y(entry.cost_eur);
      const base = top + plotH;
      svg.appendChild(
        svgEl('path', {
          d: `M${x0},${base} V${yTop + r} Q${x0},${yTop} ${x0 + r},${yTop} H${x0 + barW - r} Q${x0 + barW},${yTop} ${x0 + barW},${yTop + r} V${base} Z`,
          class: 'costs-bar',
        })
      );
    }
    const withYear = i === 0 || entry.month.endsWith('-01');
    const label = svgEl('text', {
      x: cx,
      y: height - 10,
      'text-anchor': 'middle',
      class: `costs-axis-label${entry.month === selected ? ' costs-axis-label--selected' : ''}`,
    });
    label.textContent = monthLabel(entry.month, withYear);
    svg.appendChild(label);

    // Trefferfläche über den ganzen Monats-Slot - größer als der Balken.
    const hit = svgEl('rect', {
      x: left + slot * i,
      y: top,
      width: slot,
      height: plotH,
      class: 'costs-hit',
      tabindex: 0,
      role: 'button',
      'aria-label': `${monthLabel(entry.month, true)}: ${formatMoney(entry.cost_eur, entry.cost_usd)}`,
    });
    const select = () => {
      monthInput.value = entry.month;
      loadMonth();
      renderChart();
    };
    hit.addEventListener('mouseenter', () => showTooltip(entry, cx));
    hit.addEventListener('focus', () => showTooltip(entry, cx));
    hit.addEventListener('mouseleave', hideTooltip);
    hit.addEventListener('blur', hideTooltip);
    hit.addEventListener('click', select);
    hit.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        select();
      }
    });
    svg.appendChild(hit);
  });
  svg.appendChild(svgEl('line', { x1: left, x2: width - right, y1: top + plotH, y2: top + plotH, class: 'costs-baseline' }));
  document.getElementById('costs-chart').replaceChildren(svg);
}

async function loadHistory(base) {
  const res = await fetch(`${base}/history`, { headers: { 'X-Lang': getLang() } });
  if (!res.ok) return;
  history = await res.json();
  renderChart();
}

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
  await Promise.all([loadMonth(), loadHistory(base)]);
}

async function loadMonth() {
  const all = hasRole('system_admin');
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

monthInput.addEventListener('change', () => {
  loadMonth();
  if (history.length) renderChart();
});
onAuthChange(refresh);
document.addEventListener('i18n:changed', refresh);
await refresh();
