import { t, getLang } from '/i18n.js';
import { renderMarkdown } from '/markdown.js';
import { hasRole } from '/auth.js';
import { displayTitle, citationHref, citationLinkLabel, isHiddenForLang, translatedBadge } from '/source-lang.js';
import { createConversationHandoffToken } from '/conversation-handoff.js';
import {
  conversationHistory,
  conversationId,
  conversationCitedSources,
  saveConversationHistory,
  renderSidebarSources,
  refreshImageStrip,
  questionInput,
  questionForm,
} from '/question.js';

// Idee 313ad93d: Quellen-/Zitat-Darstellung aus question.js ausgelagert
// (Verhalten unverändert). Die Zyklus-Importe aus /question.js werden nur in
// Funktionen gelesen, nie beim Laden dieses Moduls.
const EXTERNAL_LINK_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>' +
  '<polyline points="15 3 21 3 21 9"></polyline>' +
  '<line x1="10" y1="14" x2="21" y2="3"></line>' +
  "</svg>";

// Backlog: LLM/Internet-Fallback bei dünner Quellenlage - dezente
// Kennzeichnung von Zitaten aus der Web-Fallback-Collection (siehe
// app/web_crawler.py), unterscheidbar von den kuratierten Quellen, aber
// bewusst klein/unaufdringlich (Nutzerwunsch).
const WEB_FALLBACK_ICON =
  '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<circle cx="12" cy="12" r="9"></circle>' +
  '<ellipse cx="12" cy="12" rx="4" ry="9"></ellipse>' +
  '<line x1="3" y1="12" x2="21" y2="12"></line>' +
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

// Backlog #75: eigenes Icon fürs reine Ansehen (statt EDIT_ICON zweckzu-
// entfremden, was "Bearbeiten" suggerieren würde) und statt EXTERNAL_LINK_ICON
// (steht bereits für den externen Original-Link direkt daneben) - ein Auge
// macht den Unterschied "unsere Quellenübersicht ansehen" vs. "Originalquelle
// öffnen" auf einen Blick klar.
const VIEW_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8Z"></path>' +
  '<circle cx="12" cy="12" r="3"></circle>' +
  "</svg>";

// Gleiches Muster wie .jobs-bar-close (import.js/style.css) und
// .footer-panel-close (footer.js) - Schließen-Kreuz oben rechts.
const CLOSE_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<line x1="18" y1="6" x2="6" y2="18"></line>' +
  '<line x1="6" y1="6" x2="18" y2="18"></line>' +
  '</svg>';

function hasPflegerRole() {
  return hasRole('quellen_pfleger');
}

// Nutzerwunsch (2026-08-30): "Quelle ansehen/bearbeiten" öffnet /import.html
// in einem neuen Tab (siehe Kommentar bei appendViewSourceLink unten) - dort
// ist die laufende Konversation bisher verloren. Statt window.open()/Klick-
// Interzeption (würde Mittelklick/Strg-Klick/"In neuem Fenster öffnen"
// brechen) wird a.href im Hintergrund um ein Handoff-Token ergänzt, sobald
// es bereit ist ("Href-Aufwertung") - klickt jemand vorher, öffnet sich der
// Link einfach ohne Übernahme (heutiges Verhalten, kein Regressionsrisiko).
// import.js liest das Token und schreibt die Historie in sessionStorage
// (kein eigenes Rendering dort nötig) - ein späterer Klick auf den
// "Konversation"-Link im gemeinsamen Header lädt sie dann im selben Tab.
function attachConversationHandoff(anchor) {
  if (conversationHistory.length === 0) return;
  createConversationHandoffToken(conversationHistory, conversationId).then((token) => {
    if (!token) return;
    const url = new URL(anchor.href, window.location.origin);
    url.searchParams.set('handoff', token);
    anchor.href = url.toString();
  });
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
  // Nutzerwunsch (2026-09-25): normaler Klick öffnet das Bearbeiten-Formular
  // direkt hier (Komponente aus source-edit.js), die Konversation bleibt
  // stehen. Mittelklick/Strg-Klick öffnen weiterhin die Quellenübersicht.
  a.addEventListener('click', (e) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    openSourceEditDialog(sourceId);
  });
  container.appendChild(a);
  attachConversationHandoff(a);
}

// Quelle (inkl. Volltext) und Autor:innen erst beim Öffnen laden, das Modul
// per dynamischem import() - normale Besucher:innen laden davon nichts.
// Gemeinsames Gerüst für Bearbeiten- und Lese-Dialog: Schließen-Kreuz,
// Ladehinweis, wird beim Schließen aus dem DOM entfernt.
function openSourceDialog(label) {
  const dialog = document.createElement('dialog');
  dialog.className = 'source-edit-dialog';
  dialog.setAttribute('aria-label', label);

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'jobs-bar-close';
  const closeLabel = t('import.closeButtonTitle');
  closeBtn.title = closeLabel;
  closeBtn.setAttribute('aria-label', closeLabel);
  closeBtn.innerHTML = CLOSE_ICON;
  closeBtn.addEventListener('click', () => dialog.close());

  const status = document.createElement('p');
  status.className = 'edit-status';
  status.textContent = t('common.loadingSource');

  dialog.append(closeBtn, status);
  dialog.addEventListener('close', () => dialog.remove());
  document.body.appendChild(dialog);
  dialog.showModal();
  return { dialog, status };
}

async function fetchSource(sourceId) {
  const res = await fetch(`/api/sources/${encodeURIComponent(sourceId)}`, { headers: { 'X-Lang': getLang() } });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

// Nutzerwunsch (2026-09-25): "Quelle ansehen" (Auge) öffnet eine Lese-
// Ansicht direkt in der Konversation statt der Quellenübersicht in einem
// neuen Tab - neue Tabs auf die eigene Domain fängt eine installierte App
// (manifest.json) ab und öffnet sie im App-Fenster. Geschützte Volltexte
// liefert der Server ohne Pfleger-Rolle leer (GET /api/sources/{id}).
async function openSourceViewDialog(sourceId) {
  const { dialog, status } = openSourceDialog(t('common.viewSource'));
  try {
    const s = await fetchSource(sourceId);
    status.remove();
    dialog.appendChild(buildSourceReader(s));
  } catch (err) {
    status.textContent = t('common.errorPrefix') + err.message;
  }
}

function buildSourceReader(s) {
  const article = document.createElement('article');
  article.className = 'source-reader';

  const heading = document.createElement('h2');
  heading.textContent = displayTitle(s);
  const readerBadge = translatedBadge(s);
  if (readerBadge) heading.append(' ', readerBadge);
  article.appendChild(heading);

  const meta = document.createElement('p');
  meta.className = 'source-reader-meta';
  const year = s.date ? s.date.split('-')[0] : null;
  meta.textContent = [(s.authors || []).join(', '), year].filter(Boolean).join(' · ');
  const url = citationHref(s);
  if (url) {
    const a = document.createElement('a');
    a.href = url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.className = 'external-link';
    const label = citationLinkLabel(s);
    a.title = label;
    a.setAttribute('aria-label', label);
    a.innerHTML = EXTERNAL_LINK_ICON;
    meta.appendChild(a);
  }
  article.appendChild(meta);

  function sectionHeading(labelKey) {
    const h3 = document.createElement('h3');
    h3.textContent = t(labelKey);
    return h3;
  }

  // Nutzerwunsch (2026-09-26): KI-Icon, solange Zusammenfassung bzw.
  // Schlagworte von der KI stammen und nicht von Hand überarbeitet sind.
  function aiIcon(tooltipKey) {
    const icon = document.createElement('span');
    icon.className = 'source-summary-icon';
    icon.innerHTML = MAGIC_ICON;
    const tooltip = t(tooltipKey);
    icon.title = tooltip;
    icon.setAttribute('aria-label', tooltip);
    return icon;
  }

  if (s.summary) {
    const p = document.createElement('p');
    p.textContent = s.summary;
    if (s.summary_ai_generated !== false) p.prepend(aiIcon('import.aiSummaryTooltip'), ' ');
    article.appendChild(sectionHeading('common.readerSummary'));
    article.appendChild(p);
  }
  if (s.key_terms && s.key_terms.length) {
    const p = document.createElement('p');
    p.className = 'source-reader-terms';
    p.textContent = s.key_terms.join(' · ');
    if (s.key_terms_ai_generated !== false) p.prepend(aiIcon('common.aiKeyTermsTooltip'), ' ');
    article.appendChild(sectionHeading('common.readerKeyTerms'));
    article.appendChild(p);
  }
  // Nutzerwunsch (2026-09-26): Volltext nur, wenn es gar keine Web-Quelle
  // gibt - sonst führt der Link oben zum Original.
  if (s.url || s.listen_url) return article;
  const text = document.createElement('div');
  text.className = 'source-reader-text';
  if (s.text) {
    // renderMarkdown escaped HTML (markdown.js), der Quelltext ist Nutzer-Inhalt.
    text.innerHTML = renderMarkdown(s.text);
  } else {
    text.textContent = t(s.restricted ? 'common.readerRestrictedNote' : 'common.readerNoText');
  }
  article.appendChild(sectionHeading('common.readerFullText'));
  article.appendChild(text);
  return article;
}

async function openSourceEditDialog(sourceId) {
  const { dialog, status } = openSourceDialog(t('common.editSource'));

  // buildAuthorFields verweist per list="author-suggestions" auf diese Liste.
  const datalist = document.createElement('datalist');
  datalist.id = 'author-suggestions';

  const list = document.createElement('ul');
  list.className = 'source-edit-dialog-list';
  dialog.append(datalist, list);

  try {
    const [module, source, authorsRes] = await Promise.all([
      import('/source-edit.js'),
      fetchSource(sourceId),
      fetch('/api/authors', { headers: { 'X-Lang': getLang() } }),
    ]);
    const authors = authorsRes.ok ? await authorsRes.json() : [];
    module.setKnownAuthors(authors);
    datalist.replaceChildren(
      ...authors.map((author) => {
        const option = document.createElement('option');
        option.value = author.name;
        return option;
      })
    );
    status.remove();

    // Löschen wie in der Quellenübersicht mit Rückgängig-Leiste. Wird der
    // Dialog währenddessen geschlossen, gilt das Löschen als bestätigt.
    let pendingDeletion = null;
    async function deleteNow() {
      clearTimeout(pendingDeletion);
      pendingDeletion = null;
      const res = await fetch(`/api/sources/${encodeURIComponent(sourceId)}`, {
        method: 'DELETE',
        headers: module.jsonHeaders(),
      }).catch(() => null);
      if (res?.ok) updateCitedSource(sourceId, { deleted: true });
      dialog.close();
    }
    function renderPanel(isPendingDeletion) {
      list.replaceChildren(
        module.buildEditPanel(source, {
          pendingDeletion: isPendingDeletion,
          onSaved: (updated) => {
            updateCitedSource(sourceId, {
              title: updated.title,
              authors: updated.authors,
              date: updated.date,
              url: updated.url,
              listen_url: updated.listen_url,
              summary: updated.summary,
              url_reachable: updated.url_reachable,
              restricted: updated.restricted,
              text_lang: updated.text_lang,
              title_en: updated.title_en,
              text_lang_ai_generated: updated.text_lang_ai_generated,
              title_en_ai_generated: updated.title_en_ai_generated,
            });
            dialog.close();
          },
          onCancel: () => dialog.close(),
          onDelete: () => {
            pendingDeletion = setTimeout(deleteNow, module.UNDO_DURATION_MS);
            renderPanel(true);
          },
          onUndoDelete: () => {
            clearTimeout(pendingDeletion);
            pendingDeletion = null;
            renderPanel(false);
          },
        })
      );
    }
    dialog.addEventListener('close', () => {
      if (pendingDeletion) deleteNow();
    });
    renderPanel(false);
  } catch (err) {
    status.textContent = t('common.errorPrefix') + err.message;
  }
}

// Überträgt Änderungen aus dem Bearbeiten-Dialog auf die Konversation:
// Verlauf, Seitenleiste und offene Zitat-Karten zeigen denselben Stand.
// conversationHistory, conversationCitedSources und die Zitat-Buttons teilen
// sich dieselben Quellen-Objekte - Object.assign reicht für alle drei.
function updateCitedSource(sourceId, changes) {
  conversationHistory.forEach((turn) =>
    (turn.sources || []).forEach((s) => {
      if (s.source_id === sourceId) Object.assign(s, changes);
    })
  );
  const cited = conversationCitedSources.get(sourceId);
  if (cited) Object.assign(cited, changes);
  saveConversationHistory();
  renderSidebarSources();
  document
    .querySelectorAll(`.citation-card-content[data-source-id="${CSS.escape(sourceId)}"]`)
    .forEach((wrapper) => {
      const heading = wrapper.querySelector('.citation-card-heading');
      heading.replaceChildren();
      appendCitationHeading(heading, cited || { source_id: sourceId, ...changes });
      if (changes.deleted) wrapper.querySelector('.citation-card-text .external-link:last-child')?.remove();
    });
}

// Backlog #75: Gegenstück zu appendEditSourceLink für alle anderen
// Besucher:innen (inkl. anonym, inkl. Embed-Widget) - öffnet dieselbe
// Quellenübersicht, aber nur zum Ansehen statt im Bearbeiten-Modus.
// target="_blank" bricht auch innerhalb eines <iframe>-Embeds zuverlässig in
// einen echten Browser-Tab auf der normalen Website aus.
function appendViewSourceLink(container, sourceId) {
  const a = document.createElement('a');
  a.href = `/import.html?source=${encodeURIComponent(sourceId)}`;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.className = 'external-link';
  const label = t('common.viewSource');
  a.title = label;
  a.setAttribute('aria-label', label);
  a.innerHTML = VIEW_ICON;
  // Normaler Klick: Lese-Dialog statt neuem Tab (siehe openSourceViewDialog).
  a.addEventListener('click', (e) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    openSourceViewDialog(sourceId);
  });
  container.appendChild(a);
  attachConversationHandoff(a);
}

function appendSourceLink(container, sourceId) {
  // Aus dem Bearbeiten-Dialog gelöscht (updateCitedSource) - Link liefe ins Leere.
  if (conversationCitedSources.get(sourceId)?.deleted) return;
  if (hasPflegerRole()) {
    appendEditSourceLink(container, sourceId);
  } else {
    appendViewSourceLink(container, sourceId);
  }
}

// Nutzerwunsch: Quellen-Pfleger:innen/System-Admins sollen eine erkennbar
// unpassende Web-Fallback-Quelle direkt aus der Konversationsansicht
// ausschließen können, ohne erst über die Quellenübersicht/den dortigen
// Seiten-Akkordeon (siehe import.js) navigieren zu müssen - "schnell und
// einfach", da der bestehende exclude-Endpoint ohnehin voll reversibel ist
// (kein Löschen, nur ein Flag, siehe app/web_index.py:set_excluded), reicht
// ein einzelner Klick ohne Sicherheitsabfrage. Bewusst KEIN appendSourceLink()
// wie bei kuratierten Quellen - Web-Fallback-Chunks stehen NICHT im
// Quellenverzeichnis (kein sources.json-Eintrag, /import.html?edit=...
// würde ins Leere laufen).
function appendExcludeWebPageButton(container, s) {
  if (!hasPflegerRole() || !s.allowlist_entry_id) return;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'external-link exclude-web-page-button';
  const label = t('common.excludeWebPage');
  btn.title = label;
  btn.setAttribute('aria-label', label);
  btn.innerHTML = EDIT_ICON;
  btn.addEventListener('click', async (e) => {
    // Verhindert, dass ein Klick innerhalb eines <summary> (siehe
    // buildSourcesList) zusätzlich das umgebende <details>-Element
    // auf-/zuklappt - analog appendAuthorLinks/appendTitleText.
    e.stopPropagation();
    if (btn.disabled) return;
    btn.disabled = true;
    try {
      const res = await fetch(
        `/api/web-allowlist/${s.allowlist_entry_id}/pages/${encodeURIComponent(s.source_id)}/exclude`,
        { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': getLang() } }
      );
      if (!res.ok) {
        btn.disabled = false;
        return;
      }
      const excludedLabel = t('common.webPageExcluded');
      btn.title = excludedLabel;
      btn.setAttribute('aria-label', excludedLabel);
      btn.classList.add('exclude-web-page-button--done');
    } catch (err) {
      btn.disabled = false;
    }
  });
  container.appendChild(btn);
}

// Nutzerwunsch: der Titel selbst soll anklickbar sein (nicht nur das kleine
// Icon am Ende des Chunk-Ausschnitts) - so wie appendAuthorLinks für
// Autor:innen-Namen, hier aber zur Original-URL statt zum internen
// Autor:innen-Profil. Gilt einheitlich für kuratierte UND Web-Fallback-
// Quellen, sofern eine URL vorhanden ist (listen_url hat Vorrang, siehe
// citationUrl-Definitionen weiter unten).
function appendTitleText(container, s) {
  // Nutzerwunsch (2026-09-23): eine Quelle mit erkanntem defektem Link
  // (url_reachable === false, siehe Quellenverwaltung) soll auch hier
  // nicht mehr verlinkt werden - fällt auf denselben Pfad wie eine Quelle
  // ganz ohne URL zurück (reiner Titeltext, kein Link/Icon).
  if (s.deleted) {
    const span = document.createElement('span');
    span.className = 'source-deleted-title';
    span.textContent = `${displayTitle(s)} (${t('common.sourceDeletedBadge')})`;
    container.appendChild(span);
    return;
  }
  const citationUrl = citationHref(s);
  const badge = translatedBadge(s);
  if (!citationUrl) {
    container.appendChild(document.createTextNode(displayTitle(s)));
    if (badge) container.append(' ', badge);
    return;
  }
  const a = document.createElement('a');
  a.href = citationUrl;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.className = 'citation-title-link';
  const label = citationLinkLabel(s);
  a.title = label;
  a.textContent = displayTitle(s);
  // Verhindert, dass ein Klick auf den Titel innerhalb eines <summary>
  // (siehe buildSourcesList) zusätzlich das umgebende <details>-Element
  // auf-/zuklappt - analog appendAuthorLinks.
  a.addEventListener('click', (e) => e.stopPropagation());
  container.appendChild(a);

  // Nutzerwunsch (2026-09-23): der Titel verlinkt bereits nach außen, das
  // war bisher rein optisch (nur Unterstreichung) nicht als externer Link
  // erkennbar - dasselbe Icon/dieselbe Klasse wie überall sonst im Code für
  // "öffnet extern" (z.B. am Ende des Chunk-Ausschnitts in buildSourceInfo).
  const icon = document.createElement('a');
  icon.href = citationUrl;
  icon.target = '_blank';
  icon.rel = 'noopener noreferrer';
  icon.className = 'external-link';
  icon.title = label;
  icon.setAttribute('aria-label', label);
  icon.innerHTML = EXTERNAL_LINK_ICON;
  icon.addEventListener('click', (e) => e.stopPropagation());
  container.appendChild(icon);
  if (badge) container.append(' ', badge);
}

function truncateWords(text, maxWords) {
  const words = text.trim().split(/\s+/);
  if (words.length <= maxWords) {
    return text.trim();
  }
  return words.slice(0, maxWords).join(' ') + '…';
}

function appendAuthorLinks(container, authorNames) {
  authorNames.forEach((name, index) => {
    if (index > 0) container.appendChild(document.createTextNode(', '));
    const a = document.createElement('a');
    a.href = `/import.html?author=${encodeURIComponent(name)}`;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.className = 'citation-author-link';
    const label = t('common.viewAuthorProfile', { name });
    a.title = label;
    a.setAttribute('aria-label', label);
    a.textContent = name;
    // Verhindert, dass ein Klick auf den Link innerhalb eines <summary>
    // (siehe buildSourcesList) zusätzlich das umgebende <details>-Element
    // auf-/zuklappt.
    a.addEventListener('click', (e) => e.stopPropagation());
    container.appendChild(a);
  });
}

// Nutzerwunsch: fehlende Autor:innen/Datum sollen in der Konversationsansicht
// NICHT als "unbekannt"/"(ohne Datum)" angezeigt werden - das Fehlen einer
// Angabe nützt Nutzer:innen nichts und schmälert nur unnötig das Vertrauen
// in die Quelle. Fehlt eine Angabe, wird der jeweilige Teil einfach
// weggelassen statt eines Platzhaltertexts (anders als in der
// Quellenverwaltung, static/import.js, wo Quellen-Pfleger:innen genau das
// Fehlen erkennen müssen, um es zu beheben).
function appendCitationHeading(container, s) {
  appendTitleText(container, s);
  if (s.authors && s.authors.length) {
    container.appendChild(document.createTextNode(' – '));
    appendAuthorLinks(container, s.authors);
  }
  const year = s.date ? s.date.split('-')[0] : null;
  if (year) {
    container.appendChild(document.createTextNode(` (${year})`));
  }
}

function findHighlightRange(text, highlight) {
  const exactIndex = text.indexOf(highlight);
  if (exactIndex !== -1) return [exactIndex, exactIndex + highlight.length];

  // Das KI-Zitat kann Zeilenumbrüche/Mehrfach-Leerzeichen aus der
  // Originalquelle (z.B. PDF-Layoutumbrüche) leicht anders normalisiert
  // wiedergeben als der exakte Chunk-Text - deshalb zusätzlich mit
  // whitespace-toleranter Suche versuchen, bevor ganz auf Highlighting
  // verzichtet wird.
  const pattern = highlight
    .trim()
    .split(/\s+/)
    .map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('\\s+');
  if (!pattern) return null;
  const match = text.match(new RegExp(pattern, 'i'));
  return match ? [match.index, match.index + match[0].length] : null;
}

// Chunks beginnen ggf. mit der Kapitelüberschrift als Markdown-Zeile
// (# bis ###, siehe app/chunking.py) - im Auszug als Überschrift ohne #.
function splitLeadingHeading(text) {
  const m = /^#{1,3} (\S[^\n]*)\n?/.exec(text);
  return m ? { heading: m[1].trim(), body: text.slice(m[0].length) } : { heading: '', body: text };
}

// Backend-split_sentences hängt die Überschrift an den ersten Satz - das
// Highlight bekommt daher dieselbe Befreiung wie der Text.
function prepareExcerpt(text, highlight) {
  const { heading, body } = splitLeadingHeading(text);
  return { heading, body, highlight: highlight ? splitLeadingHeading(highlight).body : highlight };
}

function appendTextWithHighlight(container, text, highlight) {
  const range = highlight ? findHighlightRange(text, highlight) : null;
  if (!range) {
    container.appendChild(document.createTextNode(text));
    return;
  }
  const [start, end] = range;
  if (start > 0) container.appendChild(document.createTextNode(text.slice(0, start)));
  const mark = document.createElement('mark');
  mark.className = 'citation-highlight';
  mark.textContent = text.slice(start, end);
  container.appendChild(mark);
  if (end < text.length) container.appendChild(document.createTextNode(text.slice(end)));
}

function buildSourceInfo(s, highlight) {
  const wrapper = document.createElement('div');
  wrapper.className = 'citation-card-content';
  wrapper.dataset.sourceId = s.source_id;

  const heading = document.createElement('p');
  heading.className = 'citation-card-heading';
  if (s.is_web_fallback) {
    const badge = document.createElement('span');
    badge.className = 'web-fallback-badge';
    badge.innerHTML = WEB_FALLBACK_ICON;
    const label = t('common.webFallbackSourceTitle');
    badge.title = label;
    badge.setAttribute('aria-label', label);
    heading.appendChild(badge);
  }
  appendCitationHeading(heading, s);
  wrapper.appendChild(heading);

  const excerpt = document.createElement('p');
  excerpt.className = 'citation-card-text';
  // Voller Chunk-Text statt Kappung bei 100 Wörtern - das ist der Teil, der
  // beim Beantworten tatsächlich als Quelle herangezogen wurde (Backlog #59).
  // Der beleg-relevante Satz (KI-Zitat oder lokales Fallback-Highlighting,
  // siehe app/main.py) wird darin zusätzlich optisch hervorgehoben - je
  // nachdem, WELCHES Vorkommen dieser Quelle im Antworttext aufgeklappt
  // wurde (`highlight`-Parameter), nicht pauschal dasselbe für die ganze
  // Quelle, da derselbe Chunk mehrere unterschiedliche Aussagen belegen kann.
  const { heading: chapter, body, highlight: bodyHighlight } = prepareExcerpt(s.text, highlight);
  if (chapter) {
    const chapterEl = document.createElement('strong');
    chapterEl.className = 'citation-card-chapter';
    chapterEl.textContent = chapter;
    excerpt.appendChild(chapterEl);
  }
  appendTextWithHighlight(excerpt, body, bodyHighlight);
  wrapper.appendChild(excerpt);

  // Nutzerwunsch (2026-09-23): eine Quelle mit erkanntem defektem Link soll
  // nirgendwo mehr verlinkt werden, auch nicht hier am Ende des Chunk-
  // Ausschnitts.
  const citationUrl = citationHref(s);
  if (citationUrl) {
    const a = document.createElement('a');
    a.href = citationUrl;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.className = 'external-link';
    const label = citationLinkLabel(s);
    a.title = label;
    a.setAttribute('aria-label', label);
    a.innerHTML = EXTERNAL_LINK_ICON;
    excerpt.appendChild(a);
  }
  // Web-Fallback-Chunks stehen NICHT im Quellenverzeichnis (kein
  // sources.json-Eintrag) - appendSourceLink würde auf einen 404 verlinken.
  // Der direkte Link zur Original-URL oben deckt "Quelle im Internet
  // aufsuchen" bereits ab, appendExcludeWebPageButton bietet stattdessen das
  // dortige Äquivalent zum Bearbeiten-Stift (schnelles Ausschließen einer
  // erkennbar unpassenden Quelle).
  if (s.is_web_fallback) {
    appendExcludeWebPageButton(excerpt, s);
  } else {
    appendSourceLink(excerpt, s.source_id);
  }

  return wrapper;
}

export function buildSourcesList(sources) {
  const sourcesList = document.createElement('ol');
  sourcesList.className = 'chat-sources-list';
  sources.filter((s) => !isHiddenForLang(s)).forEach((s) => {
    const li = document.createElement('li');
    const details = document.createElement('details');
    details.dataset.sourceId = s.source_id;
    const summaryToggle = document.createElement('summary');
    appendCitationHeading(summaryToggle, s);
    details.appendChild(summaryToggle);
    const p = document.createElement('p');
    // Hier bewusst die KI-Zusammenfassung statt des Chunk-Ausschnitts (anders
    // als buildSourceInfo() in der Konversationsansicht) - fehlt sie (noch)
    // für eine Quelle, auf den Chunk-Ausschnitt zurückfallen.
    if (s.summary && s.summary_ai_generated !== false) {
      const icon = document.createElement('span');
      icon.className = 'source-summary-icon';
      const tooltip = t('import.aiSummaryTooltip');
      icon.title = tooltip;
      icon.setAttribute('aria-label', tooltip);
      icon.innerHTML = MAGIC_ICON;
      p.appendChild(icon);
      p.appendChild(document.createTextNode(' ' + s.summary));
    } else if (s.summary) {
      p.textContent = s.summary;
    } else {
      p.textContent = truncateWords(s.text, 100);
    }
    // Nutzerwunsch (2026-09-23): eine Quelle mit erkanntem defektem Link
    // soll nirgendwo mehr verlinkt werden, auch nicht hier in der
    // Sidebar-Quellenliste.
    const citationUrl = citationHref(s);
    if (citationUrl) {
      const a = document.createElement('a');
      a.href = citationUrl;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.className = 'external-link';
      const label = citationLinkLabel(s);
      a.title = label;
      a.setAttribute('aria-label', label);
      a.innerHTML = EXTERNAL_LINK_ICON;
      p.appendChild(a);
    }
    // Bugfix: appendSourceLink() wurde hier bisher unbedingt aufgerufen -
    // bei Web-Fallback-Quellen (kein sources.json-Eintrag) verlinkte das auf
    // einen 404 (siehe analoge, bereits vorhandene Fallunterscheidung in
    // buildSourceInfo oben).
    if (s.is_web_fallback) {
      appendExcludeWebPageButton(p, s);
    } else {
      appendSourceLink(p, s.source_id);
    }
    details.appendChild(p);
    li.appendChild(details);
    sourcesList.appendChild(li);
  });
  return sourcesList;
}

export function makeCitationsClickable(container, sources) {
  // Entfernt Belegmarker ausgeblendeter Quellen (EN-UI, nicht übersetzbar, siehe
  // source-lang.js) samt davorstehendem Leerraum und lässt "[2, 3]"-Gruppen in
  // Einzelmarker zerfallen (nur wenn alle Nummern existieren). Die angezeigten
  // Nummern zählt diese Funktion ohnehin fortlaufend neu, Lücken entstehen
  // also nicht.
  const sourceAt = (n) => sources[parseInt(n, 10) - 1];
  function dropHiddenMarkers(text) {
    const expanded = text.replace(/\[(\d+(?:\s*,\s*\d+)+)\]/g, (m, group) => {
      const nums = group.split(/\s*,\s*/);
      return nums.every(sourceAt) ? nums.map((n) => `[${n}]`).join('') : m;
    });
    const keptMarkers = (run) =>
      run.match(/\[\d+\]/g).filter((marker) => {
        const source = sourceAt(marker.slice(1, -1));
        return !source || !isHiddenForLang(source);
      });
    // Klammerzusatz wie "(siehe [2])" fällt mit dem Marker ganz weg - nur
    // genau diese Klammer um den Marker, andere Klammern bleiben unberührt.
    const withoutParens = expanded.replace(/(\s*)\(([^()[\]]{0,20})((?:\[\d+\])+)\)/g, (m, space, lead, run) => {
      const kept = keptMarkers(run);
      if (kept.length === run.match(/\[\d+\]/g).length) return m;
      return kept.length ? `${space}(${lead}${kept.join('')})` : '';
    });
    return withoutParens.replace(/(\s*)((?:\[\d+\])+)/g, (m, space, run) => {
      const kept = keptMarkers(run);
      if (kept.length === run.match(/\[\d+\]/g).length) return m;
      return kept.length ? space + kept.join('') : '';
    });
  }

  // Schlüssel ist der tatsächliche INHALT (Chunk + Highlight), nicht die
  // Zitat-Nummer und nicht der einzelne Button: Verweisen zwei verschiedene
  // [n]-Vorkommen auf denselben Chunk mit demselben Highlight (z.B. dieselbe
  // Aussage wird zweimal referenziert), teilen sie sich eine Karte statt
  // dieselbe Box mehrfach aufzuklappen - haben sie dagegen unterschiedliche
  // Highlights (unterschiedliche Aussagen im selben Chunk), bleiben es
  // unabhängig auf-/zuklappbare Karten.
  const openCards = new Map();
  // Zählt pro Quellen-Index, das wievielte Mal sie im Antworttext auftaucht -
  // damit jedes Vorkommen sein eigenes, zu genau dieser Aussage passendes
  // Highlight bekommt (`source.highlighted_texts[occurrence]`), statt bei
  // Mehrfachzitaten derselben Quelle immer dasselbe erste Highlight zu
  // zeigen (siehe app/main.py: highlighted_texts ist pro Vorkommen sortiert).
  const occurrenceCounts = new Map();
  // Nutzerwunsch (2026-09-22): die Original-Zitatnummer aus dem Antworttext
  // (chunk-basiert, siehe app/main.py) wiederholt sich, sobald derselbe
  // Chunk mehrfach zitiert wird ("[1]" taucht zweimal auf) - das wirkte
  // verwirrend, auch wenn die Klick-Logik selbst (openCards/contentKey oben)
  // bereits korrekt zwischen unterschiedlichen und identischen Highlights
  // unterscheidet. Die ANGEZEIGTE Nummer zählt deshalb fortlaufend über den
  // gesamten Antworttext, unabhängig von der internen Quellen-/Chunk-Nummer -
  // jedes Zitat-Vorkommen bekommt so sein eigenes, eindeutiges [n]. Die
  // Quellenliste in der Sidebar (buildSourcesList) bleibt davon unberührt,
  // die dedupliziert ohnehin schon nach source_id, nicht nach Zitatnummer.
  let displayNumber = 0;
  const textNodes = [];
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node) {
    if (/\[\d+(?:\s*,\s*\d+)*\]/.test(node.textContent)) {
      textNodes.push(node);
    }
    node = walker.nextNode();
  }

  textNodes.forEach((textNode) => {
    const cleaned = dropHiddenMarkers(textNode.textContent);
    if (cleaned !== textNode.textContent) textNode.textContent = cleaned;
    const parts = cleaned.split(/(\[\d+\])/g);
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
        // Zum Erstellungszeitpunkt festhalten, nicht erst im Klick-Handler
        // lesen - sonst würde bei einem späteren Klick der inzwischen schon
        // weitergezählte, falsche Vorkommens-Index verwendet.
        const myOccurrence = occurrenceCounts.get(index) || 0;
        occurrenceCounts.set(index, myOccurrence + 1);

        displayNumber += 1;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'citation-ref';
        // Echter Index in sources (btn.textContent zählt dagegen fortlaufend).
        btn.dataset.sourceIndex = String(index);
        btn.textContent = `[${displayNumber}]`;
        // Bug (2026-08-03): source.highlighted_texts wurde bisher SCHON HIER
        // beim Bauen des Buttons gelesen und als "highlight" fest in den
        // Klick-Handler eingefroren. Seit source.highlighted_texts erst
        // verzoegert nachtraeglich befuellt wird (frühes "sources"-Event vor
        // den eigentlichen Hervorhebungen, siehe attachAnswerSources im
        // submit-Handler), war highlight beim Erzeugen des Buttons IMMER
        // leer - die spaeter nachgetragenen Werte kamen nie mehr an.
        // Fix: erst im Klick-Handler selbst lesen, dann steht der aktuelle
        // Stand zur Verfuegung. openKey merkt sich (pro Button), unter
        // welchem Content-Schluessel die eigene Karte in openCards liegt -
        // unabhaengig davon, ob eine sich zwischenzeitlich aendernde
        // Hervorhebung beim naechsten Klick einen anderen Schluessel
        // ergeben wuerde.
        //
        // Bug (2026-08-20, per Screenshot gemeldet): das ehemalige
        // zusätzliche `openKey` je Button geriet aus dem Takt, sobald ZWEI
        // verschiedene Vorkommen denselben contentKey ergaben (z.B. dieselbe
        // Aussage zweimal zitiert - seit dem Folgefrage-Fix vom selben Tag
        // deutlich häufiger, da jetzt öfter mehrfach auf denselben, wirklich
        // treffenden Chunk verwiesen wird). Klick auf Button A öffnete die
        // Karte und setzte NUR A.openKey; Button B (gleicher Schlüssel) las
        // beim eigenen Klick openCards.has() als "schon offen" und übernahm
        // den Schlüssel nur in seine eigene, bis dahin leere openKey-Variable
        // - schloss A die Karte danach, blieb B.openKey auf den inzwischen
        // entfernten Schlüssel eingefroren: ein erneuter Klick auf B fand
        // dort nichts mehr zum Entfernen und öffnete auch nichts Neues mehr.
        // Fix: der Offen/Zu-Zustand lebt jetzt ausschließlich in openCards
        // (Wahrheit an einer Stelle statt zwei Kopien je Button/Map).
        btn.addEventListener('click', () => {
          const highlights = source.highlighted_texts || [];
          const highlight = highlights[myOccurrence] ?? highlights[0] ?? null;
          const contentKey = `${source.chunk_id}::${highlight || ''}`;
          const existingCard = openCards.get(contentKey);
          if (existingCard) {
            existingCard.remove();
            openCards.delete(contentKey);
            return;
          }
          const paragraph = btn.closest('p') || container;
          const card = document.createElement('div');
          card.className = 'citation-card';
          const closeBtn = document.createElement('button');
          closeBtn.type = 'button';
          closeBtn.className = 'jobs-bar-close';
          const closeLabel = t('import.closeButtonTitle');
          closeBtn.title = closeLabel;
          closeBtn.setAttribute('aria-label', closeLabel);
          closeBtn.innerHTML = CLOSE_ICON;
          closeBtn.addEventListener('click', () => {
            card.remove();
            openCards.delete(contentKey);
          });
          card.appendChild(closeBtn);
          card.appendChild(buildSourceInfo(source, highlight));
          paragraph.insertAdjacentElement('afterend', card);
          openCards.set(contentKey, card);
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

// Nutzerwunsch (2026-08-25): fett hervorgehobene Begriffe in einer Antwort
// (siehe app/llm.py-Systemprompt "fett für zentrale Begriffe") sollen
// klickbar sein - ein Klick vertieft den Begriff als neue Folgefrage,
// eingebettet in den bestehenden, verlaufsbewussten Frage-Mechanismus
// (dieselbe questionForm/questionInput, dieselbe Historie), statt eine
// eigene, parallele Anfrage-Logik aufzubauen. `strong.md-heading` (echte
// "#"-Markdown-Überschriften, siehe markdown.js) bleibt bewusst ausgenommen -
// das sind keine "Begriffe", sondern Gliederungselemente.
export function makeTermsClickable(container) {
  container.querySelectorAll('strong:not(.md-heading)').forEach((el) => {
    const term = el.textContent.trim();
    if (!term) return;
    // Nutzerfeedback (2026-09-11): das Modell formatiert Zwischenüberschriften
    // ohne "#"-Syntax gelegentlich nur als fett gesetzte, eigene Zeile - mal
    // als kompletter Absatz ("**Titel**" allein zwischen Leerzeilen), mal als
    // erste Zeile EINES mehrzeiligen Absatzes ("**§1 Titel**<br>Fließtext
    // danach", per einfachem Zeilenumbruch statt neuem Absatz). Ein <strong>,
    // das seine Zeile komplett für sich allein einnimmt (davor/danach nur
    // Zeilenumbruch oder Absatzgrenze, kein Fließtext), wird deshalb wie eine
    // echte Überschrift behandelt (schwarz, nicht klickbar) statt wie ein
    // einzelnes Fachbegriff-Schlagwort mitten im Text.
    const isLineBoundary = (node) =>
      !node || node.nodeName === 'BR' || (node.nodeType === Node.TEXT_NODE && !node.textContent.trim());
    if (isLineBoundary(el.previousSibling) && isLineBoundary(el.nextSibling)) return;
    el.classList.add('term-followup');
    el.title = t('index.termFollowUpTitle', { term });
    el.addEventListener('click', (event) => {
      // Ein Zitat-Verweis "[n]" kann zufällig innerhalb eines fett
      // hervorgehobenen Satzteils liegen (makeCitationsClickable wrapt den
      // dann VERSCHACHTELT in diesem <strong>) - dessen eigener Klick soll
      // nur die Zitat-Karte öffnen, nicht zusätzlich eine Folgefrage
      // auslösen.
      if (event.target.closest('.citation-ref')) return;
      questionInput.value = t('index.termFollowUpQuestion', { term });
      questionForm.requestSubmit();
    });
  });
}

export function buildChatMessage(role) {
  const message = document.createElement('div');
  message.className = `chat-message chat-message--${role}`;
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble';
  message.appendChild(bubble);
  return { message, bubble };
}

export function buildTypingIndicator() {
  const typing = document.createElement('div');
  typing.className = 'chat-typing';
  for (let i = 0; i < 3; i += 1) {
    const dot = document.createElement('span');
    dot.className = 'chat-typing-dot';
    typing.appendChild(dot);
  }
  return typing;
}

export function scrollQuestionIntoView(element) {
  // Verankert die gerade gestellte Frage oben im sichtbaren Bereich, statt
  // ans Ende der (noch wachsenden) Antwort zu scrollen - vorher sprang der
  // Fokus sichtbar hoch und runter, weil einmal direkt nach dem Absenden
  // (kurzer Tippindikator) und ein zweites Mal nach Eintreffen der oft viel
  // längeren Antwort ans jeweilige Element-Ende gescrollt wurde. So bleibt
  // die eigene Frage als Orientierungspunkt stehen, während die Antwort
  // darunter erscheint - besonders auf dem Handy wichtig, wo sonst der
  // Überblick verloren geht. scrollIntoView statt container.scrollTop, weil
  // ab 900px die Chat-Box mit dem Antworttext mitwächst statt intern zu
  // scrollen (siehe style.css) - der scrollende Bereich ist dann die Seite
  // selbst, nicht mehr #chat-messages; scrollIntoView findet den jeweils
  // richtigen scrollenden Vorfahren automatisch und funktioniert daher für
  // beide Layouts.
  element.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Wiederholt den Scroll einmal, sobald die Tastatur geschlossen ist
// (visualViewport-resize), spätestens nach 400 ms - ohne visualViewport oder
// Resize-Ereignis hängt nichts. Genau ein Aufruf, egal welcher Auslöser zuerst kommt.
export function rescrollAfterKeyboard(viewport, setTimeoutFn, scrollFn) {
  let done = false;
  const run = () => {
    if (done) return;
    done = true;
    viewport?.removeEventListener('resize', run);
    scrollFn();
  };
  viewport?.addEventListener('resize', run, { once: true });
  setTimeoutFn(run, 400);
}

// Nur Quellen, die im gerenderten Antworttext tatsächlich per "[n]" zitiert
// werden, sollen in der Sidebar auftauchen - data.sources enthält auch
// Top-K-Treffer, die die KI am Ende gar nicht zitiert hat. Liest den echten
// Index aus data-source-index der Zitat-Buttons (der sichtbare Text zählt
// fortlaufend und stimmt nicht mit dem Quellen-Index überein).
export function extractCitedSources(container, sources) {
  const cited = [];
  const seen = new Set();
  container.querySelectorAll('.citation-ref').forEach((btn) => {
    const index = parseInt(btn.dataset.sourceIndex, 10);
    if (seen.has(index) || !sources[index]) return;
    seen.add(index);
    cited.push(sources[index]);
  });
  return cited;
}

// Bild-URLs: https oder der eigene Bildendpunkt (relativer Pfad).
function safeImageSrc(value) {
  if (typeof value !== 'string') return null;
  if (/^\/api\/sources\/[^/?#\\]+\/images\/[0-9a-f]{32}\.webp$/.test(value)) return value;
  try {
    const u = new URL(value);
    return u.protocol === 'https:' ? u.href : null;
  } catch {
    return null;
  }
}

// Eine Bildfigur (Bildleiste und Inline-Bild): Bild + Unterschrift mit Quellentitel,
// verlinkt auf die Quelle (PDF mit #page). Nur DOM-API, nie innerHTML (Alt/Titel
// sind fremder Inhalt). inline: eigenes Skeleton bis das Bild geladen ist.
function buildImageFigure({ src, alt, page }, source, { inline = false, onError, onLoad } = {}) {
  const figure = document.createElement('figure');
  figure.className = inline ? 'inline-source-image is-loading' : 'source-image';
  if (inline) figure.dataset.src = src;
  const img = document.createElement('img');
  img.src = src;
  img.alt = alt;
  img.loading = inline ? 'eager' : 'lazy';
  img.referrerPolicy = 'no-referrer';
  img.addEventListener('error', () => {
    figure.remove();
    if (onError) onError();
  });
  if (inline) {
    img.addEventListener('load', () => {
      figure.classList.remove('is-loading');
      if (onLoad) onLoad(img);
    });
  }
  const caption = document.createElement('figcaption');
  caption.textContent =
    page === null ? displayTitle(source) : `${displayTitle(source)} · ${t('index.sourceImagePage', { n: page })}`;

  let href = citationHref(source);
  if (href && page !== null && /\.pdf$/i.test(new URL(href).pathname) && !new URL(href).hash) {
    href += `#page=${page}`;
  }
  let host = figure;
  if (href) {
    host = document.createElement('a');
    host.href = href;
    host.target = '_blank';
    host.rel = 'noopener noreferrer';
    host.title = t('index.sourceImageTooltip');
    figure.appendChild(host);
  }
  host.appendChild(img);
  host.appendChild(caption);
  return figure;
}

// Bildleiste unter der Antwort: Bilder der zitierten Quellen, entdoppelt,
// höchstens 6, ohne das Inline-Bild (excludeSrc). Ohne darstellbare Bilder:
// null (kein Element).
export function buildImageStrip(sources, excludeSrc) {
  const seen = new Set([excludeSrc]);
  const items = [];
  sources.forEach((s) => {
    (Array.isArray(s.images) ? s.images : []).forEach((img) => {
      const src = safeImageSrc(img && img.src);
      if (!src || seen.has(src) || items.length >= 6) return;
      seen.add(src);
      items.push({ src, alt: img.alt || '', page: Number.isInteger(img.page) ? img.page : null, source: s });
    });
  });
  if (!items.length) return null;

  const strip = document.createElement('div');
  strip.className = 'source-image-strip';
  items.forEach((item) => {
    const figure = buildImageFigure(item, item.source, {
      onError: () => {
        if (!strip.querySelectorAll('.source-image').length) strip.remove();
      },
    });
    strip.appendChild(figure);
  });
  return strip;
}

// Inline-Bild (Idee fe44f080): das Modell setzt höchstens einen Marker
// [bild:n.m] (n = Ausschnitt wie [n], m = 1-basiertes Bild der Quelle n).
const INLINE_MARKER_RE = /\[bild:(\d{1,2})\.(\d{1,2})\]/;

function inlineMarkerNodes(bubble) {
  const nodes = [];
  const walker = document.createTreeWalker(bubble, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (INLINE_MARKER_RE.test(node.textContent)) nodes.push(node);
  }
  return nodes;
}

// Marker samt einem angrenzenden <br> entfernen; ein dadurch leerer Absatz fällt weg.
function removeInlineMarkers(bubble, nodes) {
  nodes.forEach((node) => {
    let block = node;
    while (block.parentNode !== bubble) block = block.parentNode;
    node.textContent = node.textContent.replace(/\[bild:\d{1,2}\.\d{1,2}\]/g, '');
    if (node.textContent.trim() === '') {
      const next = node.nextSibling;
      const prev = node.previousSibling;
      if (next && next.localName === 'br') next.remove();
      else if (prev && prev.localName === 'br') prev.remove();
      node.remove();
    }
    if (block.textContent.trim() === '' && !block.querySelectorAll('.inline-source-image').length) block.remove();
  });
}

// Skeleton-Fläche für ein angekündigtes, noch nicht ladbares Bild (Live-Stream).
function buildImagePlaceholder() {
  const placeholder = document.createElement('div');
  placeholder.className = 'inline-source-image is-loading';
  placeholder.setAttribute('aria-hidden', 'true');
  // Shimmer läuft über Neu-Rendern hinweg im Takt weiter (CSSOM, CSP-konform).
  placeholder.style.animationDelay = `-${Date.now() % 1500}ms`;
  return placeholder;
}

// Setzt Figur (sources) bzw. Platzhalter (sources === null) hinter den Absatz
// mit dem ersten Marker; alle Marker verschwinden. Unbekannte Marker, unsichere
// src oder ausgeblendete Quelle: kein Bild.
const MIN_INLINE_IMAGE_PX = 480;

export function placeInlineImage(bubble, sources) {
  const nodes = inlineMarkerNodes(bubble);
  if (!nodes.length) return;
  bubble.querySelectorAll('.inline-source-image').forEach((el) => el.remove());
  const [, n, m] = nodes[0].textContent.match(INLINE_MARKER_RE);
  let block = nodes[0];
  while (block.parentNode !== bubble) block = block.parentNode;
  let element = null;
  if (!sources) {
    element = buildImagePlaceholder();
  } else {
    const source = sources[parseInt(n, 10) - 1];
    const image = source && Array.isArray(source.images) ? source.images[parseInt(m, 10) - 1] : null;
    const src = image && safeImageSrc(image.src);
    if (src && !isHiddenForLang(source)) {
      element = buildImageFigure(
        { src, alt: image.alt || '', page: Number.isInteger(image.page) ? image.page : null },
        source,
        {
          inline: true,
          // Fix v0.94.1: zu kleine Bilder (z. B. 300-px-Vorschauen) wirken im
          // Text unscharf - sie wandern in die Bildleiste.
          onLoad: (img) => {
            if (img.naturalWidth >= MIN_INLINE_IMAGE_PX) return;
            element.remove();
            refreshImageStrip(bubble, extractCitedSources(bubble, sources), sources);
          },
        }
      );
    }
  }
  if (element) block.insertAdjacentElement('afterend', element);
  removeInlineMarkers(bubble, nodes);
}
