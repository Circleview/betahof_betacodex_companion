import { initI18n, t, getLang } from '/i18n.js';
import { renderMarkdown } from '/markdown.js';

const EXTERNAL_LINK_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>' +
  '<polyline points="15 3 21 3 21 9"></polyline>' +
  '<line x1="10" y1="14" x2="21" y2="3"></line>' +
  "</svg>";

function formatYear(dateStr) {
  if (!dateStr) return t('common.noDate');
  return dateStr.split('-')[0];
}

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
  heading.textContent = `${s.title} – ${s.author || t('common.unknownAuthor')} (${formatYear(s.date)})`;
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

function buildSourcesList(sources) {
  const sourcesList = document.createElement('ol');
  sourcesList.className = 'chat-sources-list';
  sources.forEach((s) => {
    const li = document.createElement('li');
    const details = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = `${s.title} – ${s.author || t('common.unknownAuthor')} (${formatYear(s.date)})`;
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
  return sourcesList;
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

function buildChatMessage(role) {
  const message = document.createElement('div');
  message.className = `chat-message chat-message--${role}`;
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble';
  message.appendChild(bubble);
  return { message, bubble };
}

function buildTypingIndicator() {
  const typing = document.createElement('div');
  typing.className = 'chat-typing';
  for (let i = 0; i < 3; i += 1) {
    const dot = document.createElement('span');
    dot.className = 'chat-typing-dot';
    typing.appendChild(dot);
  }
  return typing;
}

function scrollChatToBottom(container) {
  container.scrollTop = container.scrollHeight;
}

await initI18n();

const chatMessages = document.getElementById('chat-messages');
const questionInput = document.getElementById('question');
const sidebarSourcesList = document.getElementById('sidebar-sources-list');

document.getElementById('question-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const question = questionInput.value.trim();
  if (!question) return;

  const { message: userMessage, bubble: userBubble } = buildChatMessage('user');
  userBubble.textContent = question;
  chatMessages.appendChild(userMessage);

  questionInput.value = '';
  questionInput.placeholder = t('index.questionPlaceholderContinue');
  questionInput.focus();

  const { message: assistantMessage, bubble: assistantBubble } = buildChatMessage('assistant');
  assistantBubble.setAttribute('aria-label', t('index.searching'));
  assistantBubble.appendChild(buildTypingIndicator());
  chatMessages.appendChild(assistantMessage);
  scrollChatToBottom(chatMessages);

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
    assistantBubble.innerHTML = renderMarkdown(data.answer);
    makeCitationsClickable(assistantBubble, data.sources);
    sidebarSourcesList.replaceChildren(...buildSourcesList(data.sources).children);
  } catch (err) {
    assistantBubble.textContent = t('common.errorPrefix') + err.message;
  }
  scrollChatToBottom(chatMessages);
});

document.addEventListener('i18n:changed', () => {
  // Der Platzhalter wird normalerweise per data-i18n-placeholder gesetzt,
  // das kennt aber nicht den "fortsetzen"-Zustand nach der ersten Frage -
  // bei einem Sprachwechsel mitten im Gespräch sonst falsch zurückgesetzt.
  if (chatMessages.children.length > 0) {
    questionInput.placeholder = t('index.questionPlaceholderContinue');
  }
});
