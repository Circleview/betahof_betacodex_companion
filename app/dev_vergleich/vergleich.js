import { renderMarkdown } from '/markdown.js';

const LABELS = {
  basis: '1: ohne Stimme (Haiku)',
  stimme: '2: mit Stimme (Haiku)',
  sonnet: '3: mit Stimme (Sonnet)',
};
const histories = { basis: [], stimme: [], sonnet: [] };
const form = document.getElementById('vg-form');
const questionEl = document.getElementById('vg-question');
const sendEl = document.getElementById('vg-send');
const statusEl = document.getElementById('vg-status');
const columnsEl = document.getElementById('vg-columns');

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function column(variant) {
  let col = columnsEl.querySelector(`[data-variant="${variant}"]`);
  if (!col) {
    col = el('section', 'vg-col');
    col.dataset.variant = variant;
    col.append(el('h2', null, LABELS[variant]));
    columnsEl.append(col);
  }
  return col;
}

function metaLine(result) {
  const meta = el('p', 'vg-meta', `${result.words} Wörter, ${result.quote_count} Zitate`);
  if (!result.quote_count) meta.append(el('strong', 'vg-warn', ' Zitatblock fehlt'));
  return meta;
}

function addTurn(variant, question, sources, result) {
  const col = column(variant);
  const turn = el('article', 'vg-turn');
  turn.append(el('p', 'vg-question', question));
  if (result.error) {
    turn.append(el('p', 'vg-error', `Fehler: ${result.error}`));
  } else {
    const body = el('div', 'vg-answer');
    body.innerHTML = renderMarkdown(result.answer);
    turn.append(body, metaLine(result));
    histories[variant].push({ question, answer: result.answer });
  }
  if (sources) turn.append(el('p', 'vg-sources', `Quellen: ${sources}`));
  col.append(turn);
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const question = questionEl.value.trim();
  if (!question) return;
  const variants = ['basis', 'stimme'];
  if (document.getElementById('vg-sonnet').checked) variants.push('sonnet');
  sendEl.disabled = true;
  statusEl.textContent = 'Läuft ...';
  try {
    const response = await fetch('/api/dev/vergleich', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, variants, histories }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const sources = data.sources.join('; ');
    for (const variant of variants) addTurn(variant, question, variant === 'basis' ? sources : '', data.columns[variant]);
    questionEl.value = '';
    statusEl.textContent = '';
  } catch (err) {
    statusEl.textContent = `Fehler: ${err.message}`;
  } finally {
    sendEl.disabled = false;
  }
});

document.getElementById('vg-reset').addEventListener('click', () => {
  for (const key of Object.keys(histories)) histories[key] = [];
  columnsEl.replaceChildren();
  statusEl.textContent = '';
});
