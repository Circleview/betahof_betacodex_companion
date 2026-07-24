import { initI18n, t, getLang } from '/i18n.js';

const EXTERNAL_LINK_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>' +
  '<polyline points="15 3 21 3 21 9"></polyline>' +
  '<line x1="10" y1="14" x2="21" y2="3"></line>' +
  "</svg>";

function truncateWords(text, maxWords) {
  const words = text.trim().split(/\s+/);
  if (words.length <= maxWords) {
    return text.trim();
  }
  return words.slice(0, maxWords).join(' ') + '…';
}

await initI18n();

document.getElementById('question-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const question = document.getElementById('question').value;
  const answerDiv = document.getElementById('answer');
  const sourcesList = document.getElementById('answer-sources');
  answerDiv.textContent = t('index.searching');
  sourcesList.innerHTML = '';
  try {
    const res = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Lang': getLang() },
      body: JSON.stringify({ question, top_k: 5 }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('index.askError'));
    }
    const data = await res.json();
    answerDiv.textContent = data.answer;
    data.sources.forEach((s) => {
      const li = document.createElement('li');
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = `${s.title} – ${s.author || t('common.unknownAuthor')} (${s.date || t('common.noDate')})`;
      details.appendChild(summary);
      const p = document.createElement('p');
      p.textContent = truncateWords(s.text, 100);
      details.appendChild(p);
      if (s.url) {
        const a = document.createElement('a');
        a.href = s.url;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.className = 'external-link';
        const label = t('common.openSource');
        a.title = label;
        a.setAttribute('aria-label', label);
        a.innerHTML = EXTERNAL_LINK_ICON;
        details.appendChild(a);
      }
      li.appendChild(details);
      sourcesList.appendChild(li);
    });
  } catch (err) {
    answerDiv.textContent = t('common.errorPrefix') + err.message;
  }
});
