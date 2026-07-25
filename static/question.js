import { initI18n, t, getLang } from '/i18n.js';
import { renderMarkdown } from '/markdown.js';
import { initAuth, hasRole, onAuthChange } from '/auth.js';

// Spam-/Bot-Schutz für die Frage-Eingabe (Cloudflare Turnstile). Hier den
// Site-Key aus dem Cloudflare-Dashboard eintragen. Bleibt das Feld leer,
// bleibt das Widget einfach unsichtbar/inaktiv - der Backend-Check ist dann
// ebenfalls deaktiviert (siehe app/captcha.py), die App bleibt also auch
// ohne Turnstile-Setup voll nutzbar (z.B. lokale Entwicklung).
const TURNSTILE_SITE_KEY = '0x4AAAAAAD9q6Ufs_N8-KCI3';
let turnstileWidgetId = null;

window.onTurnstileLoad = function () {
  if (!TURNSTILE_SITE_KEY) return;
  const container = document.getElementById('turnstile-container');
  if (!container || !window.turnstile) return;
  // 'interaction-only': das Widget bleibt für die meisten Besucher:innen
  // unsichtbar und erscheint nur, wenn Cloudflare tatsächlich eine
  // Bestätigung braucht (Standard "always" würde die kleine Box dauerhaft
  // im Formular anzeigen, auch wenn sie im Hintergrund automatisch besteht).
  turnstileWidgetId = window.turnstile.render(container, {
    sitekey: TURNSTILE_SITE_KEY,
    appearance: 'interaction-only',
    // Cloudflare lässt das gelöste Widget im DOM stehen (der Container ist
    // dann nicht mehr :empty), es würde also ohne diesen Callback sichtbar
    // bleiben, obwohl die Bestätigung bereits abgeschlossen ist.
    callback: () => container.classList.add('turnstile-verified'),
  });
};

function getTurnstileToken() {
  if (turnstileWidgetId !== null && window.turnstile) {
    return window.turnstile.getResponse(turnstileWidgetId) || '';
  }
  return '';
}

function resetTurnstile() {
  if (turnstileWidgetId !== null && window.turnstile) {
    window.turnstile.reset(turnstileWidgetId);
  }
  // Nach dem Reset entscheidet Cloudflare neu, ob eine Interaktion nötig ist -
  // die Klasse muss weg, sonst bliebe das Widget auch bei einer künftig
  // tatsächlich nötigen Bestätigung dauerhaft ausgeblendet.
  const container = document.getElementById('turnstile-container');
  if (container) container.classList.remove('turnstile-verified');
}

const EXTERNAL_LINK_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>' +
  '<polyline points="15 3 21 3 21 9"></polyline>' +
  '<line x1="10" y1="14" x2="21" y2="3"></line>' +
  "</svg>";

const MAGIC_ICON =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor" stroke="none">' +
  '<path d="M12 2l1.8 5.2L19 9l-5.2 1.8L12 16l-1.8-5.2L5 9l5.2-1.8L12 2z"></path>' +
  '<path d="M19 13l.9 2.1L22 16l-2.1.9L19 19l-.9-2.1L16 16l2.1-.9L19 13z"></path>' +
  "</svg>";

const EDIT_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M12 20h9"></path>' +
  '<path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"></path>' +
  "</svg>";

function hasPflegerRole() {
  return hasRole('quellen_pfleger');
}

function appendEditSourceLink(container, sourceId) {
  if (!hasPflegerRole()) return;
  const a = document.createElement('a');
  a.href = `/import.html?edit=${encodeURIComponent(sourceId)}`;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.className = 'external-link';
  const label = t('common.editSource');
  a.title = label;
  a.setAttribute('aria-label', label);
  a.innerHTML = EDIT_ICON;
  container.appendChild(a);
}

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
  const authorLabel = s.authors && s.authors.length ? s.authors.join(', ') : t('common.unknownAuthor');
  heading.textContent = `${s.title} – ${authorLabel} (${formatYear(s.date)})`;
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
    excerpt.appendChild(a);
  }
  appendEditSourceLink(excerpt, s.source_id);

  return wrapper;
}

function buildSourcesList(sources) {
  const sourcesList = document.createElement('ol');
  sourcesList.className = 'chat-sources-list';
  sources.forEach((s) => {
    const li = document.createElement('li');
    const details = document.createElement('details');
    details.dataset.chunkId = s.chunk_id;
    const summaryToggle = document.createElement('summary');
    const authorLabel = s.authors && s.authors.length ? s.authors.join(', ') : t('common.unknownAuthor');
    summaryToggle.textContent = `${s.title} – ${authorLabel} (${formatYear(s.date)})`;
    details.appendChild(summaryToggle);
    const p = document.createElement('p');
    // Hier bewusst die KI-Zusammenfassung statt des Chunk-Ausschnitts (anders
    // als buildSourceInfo() in der Konversationsansicht) - fehlt sie (noch)
    // für eine Quelle, auf den Chunk-Ausschnitt zurückfallen.
    if (s.summary) {
      const icon = document.createElement('span');
      icon.className = 'source-summary-icon';
      const tooltip = t('import.aiSummaryTooltip');
      icon.title = tooltip;
      icon.setAttribute('aria-label', tooltip);
      icon.innerHTML = MAGIC_ICON;
      p.appendChild(icon);
      p.appendChild(document.createTextNode(' ' + s.summary));
    } else {
      p.textContent = truncateWords(s.text, 100);
    }
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
      p.appendChild(a);
    }
    appendEditSourceLink(p, s.source_id);
    details.appendChild(p);
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
    for (let i = 0; i < parts.length; i += 1) {
      const part = parts[i];
      const match = part.match(/^\[(\d+)\]$/);
      if (match) {
        const index = parseInt(match[1], 10) - 1;
        const source = sources[index];
        if (!source) {
          frag.appendChild(document.createTextNode(part));
          continue;
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
        // Satzzeichen, die direkt (ohne Leerzeichen) auf die Quellenangabe
        // folgen (z. B. "[1]."), sollen beim Zeilenumbruch nicht von ihr
        // getrennt werden - beides zusammen in einen nowrap-Wrapper packen,
        // im Zweifel bricht die ganze Einheit gemeinsam um.
        const wrap = document.createElement('span');
        wrap.className = 'citation-ref-wrap';
        wrap.appendChild(btn);
        const nextPart = parts[i + 1];
        if (nextPart) {
          const punctMatch = nextPart.match(/^[.,;:!?)]+/);
          if (punctMatch) {
            wrap.appendChild(document.createTextNode(punctMatch[0]));
            parts[i + 1] = nextPart.slice(punctMatch[0].length);
          }
        }
        frag.appendChild(wrap);
      } else if (part) {
        frag.appendChild(document.createTextNode(part));
      }
    }
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

// Nur Quellen, die im gerenderten Antworttext tatsächlich per "[n]" zitiert
// werden, sollen in der Sidebar auftauchen - data.sources enthält auch
// Top-K-Treffer, die die KI am Ende gar nicht zitiert hat.
function extractCitedSources(container, sources) {
  const matches = container.textContent.match(/\[(\d+)\]/g) || [];
  const cited = [];
  const seen = new Set();
  matches.forEach((m) => {
    const index = parseInt(m.slice(1, -1), 10) - 1;
    if (seen.has(index) || !sources[index]) return;
    seen.add(index);
    cited.push(sources[index]);
  });
  return cited;
}

await initI18n();
await initAuth();

const chatMessages = document.getElementById('chat-messages');
const questionInput = document.getElementById('question');
const sidebarSourcesList = document.getElementById('sidebar-sources-list');

// Baut sich über die gesamte Konversation auf (chunk_id -> Quelle) - einmal
// zitierte Quellen bleiben in der Sidebar stehen, auch wenn eine spätere
// Antwort sie nicht erneut zitiert.
const conversationCitedSources = new Map();

// Baut die Sidebar-Liste neu auf, behält dabei aber den Auf-/Zu-Zustand
// bereits aufgeklappter <details> bei (sonst klappt z.B. ein Sprachwechsel
// oder eine neue Antwort eine gerade gelesene Zusammenfassung wieder zu).
function renderSidebarSources() {
  const openChunkIds = new Set(
    [...sidebarSourcesList.querySelectorAll('details[open]')].map((d) => d.dataset.chunkId)
  );
  sidebarSourcesList.replaceChildren(
    ...buildSourcesList([...conversationCitedSources.values()]).children
  );
  sidebarSourcesList.querySelectorAll('details').forEach((d) => {
    if (openChunkIds.has(d.dataset.chunkId)) d.open = true;
  });
}

// Zeigt/versteckt die Bearbeiten-Icons in der Sidebar sofort passend zum
// Login-Status, ohne dass eine neue Antwort nötig ist.
onAuthChange(() => renderSidebarSources());

document.getElementById('question-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const question = questionInput.value.trim();
  if (!question) return;

  // Schaltet vom zentrierten Startzustand (nur Eingabefeld) auf die volle
  // Ansicht (Sidebar + Nachrichtenverlauf) um, sobald die erste Frage
  // gestellt wird - siehe .chat-started in style.css.
  document.body.classList.add('chat-started');

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
      body: JSON.stringify({ question, top_k: 5, turnstile_token: getTurnstileToken() }),
    });
    // Turnstile-Tokens sind Einweg-Token - nach jedem Versuch (egal ob
    // erfolgreich oder nicht) zurücksetzen, damit die nächste Frage ein
    // frisches Token bekommt.
    resetTurnstile();
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('index.askError'));
    }
    const data = await res.json();
    assistantBubble.innerHTML = renderMarkdown(data.answer);
    makeCitationsClickable(assistantBubble, data.sources);
    extractCitedSources(assistantBubble, data.sources).forEach((s) => {
      conversationCitedSources.set(s.chunk_id, s);
    });
    renderSidebarSources();
  } catch (err) {
    assistantBubble.textContent = t('common.errorPrefix') + err.message;
  }
  scrollChatToBottom(chatMessages);
});

async function refreshCitedSourceSummaries() {
  if (conversationCitedSources.size === 0) return;
  const res = await fetch('/api/sources', { headers: { 'X-Lang': getLang() } });
  if (!res.ok) return;
  const currentSources = await res.json();
  const summaryBySourceId = new Map(currentSources.map((s) => [s.id, s.summary]));
  conversationCitedSources.forEach((s) => {
    if (summaryBySourceId.has(s.source_id)) {
      s.summary = summaryBySourceId.get(s.source_id) || null;
    }
  });
  renderSidebarSources();
}

document.addEventListener('i18n:changed', () => {
  // Der Platzhalter wird normalerweise per data-i18n-placeholder gesetzt,
  // das kennt aber nicht den "fortsetzen"-Zustand nach der ersten Frage -
  // bei einem Sprachwechsel mitten im Gespräch sonst falsch zurückgesetzt.
  if (chatMessages.children.length > 0) {
    questionInput.placeholder = t('index.questionPlaceholderContinue');
  }
  // Die KI-Zusammenfassungen in der "Verwendete Quellen"-Sidebar sind
  // sprachabhängig (summary_de/summary_en) - bei Sprachwechsel neu laden,
  // statt die zuvor in der alten Sprache eingesammelten Texte stehen zu
  // lassen.
  refreshCitedSourceSummaries();
});
