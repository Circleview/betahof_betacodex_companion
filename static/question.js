import { initI18n, t, getLang } from '/i18n.js';
import { renderMarkdown } from '/markdown.js';

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

function buildSourceInfo(s) {
  const wrapper = document.createElement('div');
  wrapper.className = 'citation-card-content';

  const heading = document.createElement('p');
  heading.className = 'citation-card-heading';
  heading.textContent = `${s.title} – ${s.author || t('common.unknownAuthor')} (${s.date || t('common.noDate')})`;
  wrapper.appendChild(heading);

  const excerpt = document.createElement('p');
  excerpt.className = 'citation-card-text';
  excerpt.textContent = truncateWords(s.text, 100);
  wrapper.appendChild(excerpt);

  const citationUrl = s.listen_url || s.url;
  if (citationUrl) {
    const a = document.createElement('a');
    a.href = citationUrl;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.className = 'external-link';
    const label = t('common.openSource');
    a.title = label;
    a.setAttribute('aria-label', label);
    a.innerHTML = EXTERNAL_LINK_ICON;
    wrapper.appendChild(a);
  }

  return wrapper;
}

function renderSourcesList(sourcesList, sources) {
  sourcesList.innerHTML = '';
  sources.forEach((s) => {
    const li = document.createElement('li');
    const details = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = `${s.title} – ${s.author || t('common.unknownAuthor')} (${s.date || t('common.noDate')})`;
    details.appendChild(summary);
    const p = document.createElement('p');
    p.textContent = truncateWords(s.text, 100);
    details.appendChild(p);
    const citationUrl = s.listen_url || s.url;
    if (citationUrl) {
      const a = document.createElement('a');
      a.href = citationUrl;
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
}

function makeCitationsClickable(container, sources) {
  const openCards = new Map();
  const textNodes = [];
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node) {
    if (/\[\d+\]/.test(node.textContent)) {
      textNodes.push(node);
    }
    node = walker.nextNode();
  }

  textNodes.forEach((textNode) => {
    const parts = textNode.textContent.split(/(\[\d+\])/g);
    if (parts.length === 1) return;
    const frag = document.createDocumentFragment();
    parts.forEach((part) => {
      const match = part.match(/^\[(\d+)\]$/);
      if (match) {
        const index = parseInt(match[1], 10) - 1;
        const source = sources[index];
        if (!source) {
          frag.appendChild(document.createTextNode(part));
          return;
        }
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'citation-ref';
        btn.textContent = part;
        btn.addEventListener('click', () => {
          const paragraph = btn.closest('p') || container;
          if (openCards.has(index)) {
            openCards.get(index).remove();
            openCards.delete(index);
            return;
          }
          const card = document.createElement('div');
          card.className = 'citation-card';
          card.appendChild(buildSourceInfo(source));
          paragraph.insertAdjacentElement('afterend', card);
          openCards.set(index, card);
        });
        frag.appendChild(btn);
      } else if (part) {
        frag.appendChild(document.createTextNode(part));
      }
    });
    textNode.parentNode.replaceChild(frag, textNode);
  });
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
    answerDiv.innerHTML = renderMarkdown(data.answer);
    makeCitationsClickable(answerDiv, data.sources);
    renderSourcesList(sourcesList, data.sources);
  } catch (err) {
    answerDiv.textContent = t('common.errorPrefix') + err.message;
  }
});
