// Schlagwörter der Quellenseite: Zusammenführen ähnlicher Begriffe und
// Schlagwort-Übersicht. Aus import.js herausgezogen (Idee 313ad93d).
import { t, getLang } from '/i18n.js';
import { readNdjsonStream } from '/ndjson-stream.js';
import {
  TRASH_ICON,
  jsonHeaders,
  attachTagSuggestions,
  normalizeTerm,
  resetKnownTerms,
} from '/source-edit.js';
import {
  JUMP_ALPHABET,
  allSources,
  buildSourceEntries,
  closeSearchBar,
  filterByTerm,
  loadSources,
  showTooManyRequests,
} from '/import-list.js';
import { EDIT_ICON, hasPflegerRole } from '/import-state.js';

const importBereich = document.getElementById('import-bereich');
const urlPopover = document.getElementById('url-popover');
const filePopover = document.getElementById('file-popover');
const webAllowlistBereich = document.getElementById('web-allowlist-bereich');
const sourceSuggestionsBereich = document.getElementById('source-suggestions-bereich');

// Nutzerwunsch (2026-09-22): bestehende Schlagworte auf inhaltliche Nähe
// prüfen ("hierarchiefreie Organisationen" vs. "hierarchielose
// Organisation") und zusammenführen - Analyse startet bewusst erst auf
// Klick (kostenpflichtiger KI-Aufruf über beide Sprachen), keine Vorschläge
// werden ohne explizite Bestätigung pro Gruppe angewendet.
const termMergeBereich = document.getElementById('term-merge-bereich');
const termMergeList = document.getElementById('term-merge-list');
const termMergeStatus = document.getElementById('term-merge-status');
const termMergeEmpty = document.getElementById('term-merge-empty');
const termMergeAnalyzeBtn = document.getElementById('term-merge-analyze');

function renderTermMergeGroup(group) {
  const li = document.createElement('li');
  const text = document.createElement('p');
  text.className = 'jobs-list-title';
  li.appendChild(text);

  // Nutzerwunsch (2026-09-23): DE- und EN-Begriffe können sich in der
  // Schreibweise ähneln, ohne gleich zu sein - eigenes Sprach-Badge pro
  // Gruppe, damit auf einen Blick klar ist, aus welcher Sprache sie stammt
  // (gilt für Zielschlagwort UND alle Varianten gleichermaßen, eine Gruppe
  // wird immer nur innerhalb EINER Sprache gebildet, siehe
  // get_term_merge_suggestions in app/main.py).
  const langBadge = document.createElement('span');
  langBadge.className = 'restricted-badge';
  langBadge.textContent = group.lang.toUpperCase();

  // Nutzerwunsch (2026-09-23): nicht immer passt der vorgeschlagene
  // Zielbegriff ODER die vorgeschlagenen Varianten - das Zielschlagwort
  // lässt sich deshalb frei eintippen, mit demselben Vorschlags-Widget wie
  // beim manuellen Bearbeiten einer Quelle (siehe attachTagSuggestions),
  // damit ein neuer Zielbegriff nicht versehentlich zu einer weiteren
  // Schreibvariante eines längst vorhandenen Begriffs wird. Nutzerwunsch
  // (Nachtrag): ein dauerhaft sichtbares Eingabefeld wirkte im Fließtext zu
  // unruhig - normal nur Text, ein Klick aufs Stift-Icon (dasselbe wie beim
  // Quellen-Bearbeiten-Button) blendet stattdessen das Eingabefeld ein.
  // Alle Elemente EINMAL über die gesamte Lebensdauer der Zeile erzeugt
  // (nicht bei jedem renderGroupText()-Aufruf neu) - sonst würde jeder
  // Varianten-Tausch eine weitere Vorschlagsliste anhängen und eine gerade
  // laufende Eingabe verwerfen.
  const canonicalWrap = document.createElement('span');
  canonicalWrap.className = 'term-merge-canonical-wrap';

  const canonicalText = document.createElement('span');
  canonicalText.className = 'term-merge-canonical-text';

  const editCanonicalBtn = document.createElement('button');
  editCanonicalBtn.type = 'button';
  editCanonicalBtn.className = 'icon-button term-merge-edit-canonical';
  editCanonicalBtn.innerHTML = EDIT_ICON;
  const editCanonicalLabel = t('import.termMergeEditCanonicalTitle');
  editCanonicalBtn.title = editCanonicalLabel;
  editCanonicalBtn.setAttribute('aria-label', editCanonicalLabel);

  const canonicalInput = document.createElement('input');
  canonicalInput.type = 'text';
  canonicalInput.className = 'term-merge-canonical-input hidden';
  canonicalInput.title = t('import.termMergeCanonicalInputTitle');
  const canonicalSuggestions = attachTagSuggestions(canonicalInput, { multi: false, lang: group.lang });

  function enterCanonicalEditMode() {
    canonicalInput.value = canonicalText.textContent;
    canonicalText.classList.add('hidden');
    editCanonicalBtn.classList.add('hidden');
    canonicalInput.classList.remove('hidden');
    canonicalInput.focus();
    canonicalInput.select();
  }
  function exitCanonicalEditMode() {
    canonicalText.textContent = canonicalInput.value.trim() || group.canonical;
    canonicalInput.classList.add('hidden');
    canonicalText.classList.remove('hidden');
    editCanonicalBtn.classList.remove('hidden');
  }
  editCanonicalBtn.addEventListener('click', enterCanonicalEditMode);
  canonicalInput.addEventListener('blur', exitCanonicalEditMode);
  canonicalInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      canonicalInput.blur();
    }
  });
  canonicalWrap.append(canonicalText, editCanonicalBtn, canonicalInput, canonicalSuggestions);

  // "Zusammenführen" liest IMMER den aktuellen Feldinhalt statt group.
  // canonical - tippt man einen neuen, bisher unbeteiligten Begriff ein,
  // wandert der bisherige Zielbegriff automatisch mit in die zu
  // ersetzenden Varianten. "Alle Schlagworte löschen" bleibt bewusst an
  // group.canonical/group.variants (den ursprünglich erkannten Begriffen)
  // hängen - eine noch nicht bestätigte, frei eingetippte Zieleingabe soll
  // beim Löschen nicht versehentlich mitgelöscht werden.
  function effectiveCanonical() {
    return canonicalInput.value.trim() || group.canonical;
  }
  function effectiveVariants() {
    const canonical = effectiveCanonical();
    const variants = group.variants.filter((v) => v !== canonical);
    if (canonical !== group.canonical && !variants.includes(group.canonical)) {
      variants.push(group.canonical);
    }
    return variants;
  }

  // Nutzerwunsch (2026-09-23): das vorgeschlagene Zielschlagwort ist nur
  // eine KI-Einschätzung - ein Klick auf eines der "schlechten" Schlagworte
  // tauscht dessen Platz mit dem aktuellen Zielschlagwort. Ändert group.
  // canonical/group.variants direkt (nicht nur die Anzeige) - applyBtn/
  // deleteBtn unten lesen bei jedem Klick den aktuellen Stand von group,
  // der Tausch wirkt sich also unmittelbar auf Zusammenführen/Löschen aus.
  function renderGroupText() {
    canonicalText.textContent = group.canonical;
    canonicalInput.value = group.canonical;
    canonicalInput.classList.add('hidden');
    canonicalText.classList.remove('hidden');
    editCanonicalBtn.classList.remove('hidden');
    text.replaceChildren(langBadge, ' ', canonicalWrap, ' ← ');
    group.variants.forEach((variant, index) => {
      if (index > 0) text.append(', ');
      const variantWrap = document.createElement('span');
      variantWrap.className = 'term-merge-variant';

      const variantBtn = document.createElement('button');
      variantBtn.type = 'button';
      variantBtn.className = 'link-button';
      variantBtn.textContent = variant;
      variantBtn.title = t('import.termMergeMakeCanonicalTitle');
      variantBtn.addEventListener('click', () => {
        const oldCanonical = group.canonical;
        group.canonical = variant;
        group.variants = group.variants.map((v) => (v === variant ? oldCanonical : v));
        renderGroupText();
      });
      variantWrap.appendChild(variantBtn);

      // Nutzerwunsch (2026-09-23): eine Zusammenfassung passt oft
      // grundsätzlich, nur ein einzelnes Schlagwort in der Gruppe nicht -
      // eigenes "×" pro Variante entfernt NUR dieses eine, statt die ganze
      // Gruppe ignorieren zu müssen. Bewusst NICHT erst bei :hover
      // eingeblendet (auf Touch-Geräten gäbe es dafür kein Äquivalent) -
      // immer sichtbar, nur dezent gedimmt, per CSS kräftiger bei Hover/
      // Fokus (siehe .term-merge-remove-variant in style.css).
      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'term-merge-remove-variant';
      removeBtn.textContent = '×';
      removeBtn.title = t('import.termMergeRemoveVariantTitle');
      removeBtn.setAttribute('aria-label', t('import.termMergeRemoveVariantTitle'));
      removeBtn.addEventListener('click', () => {
        group.variants = group.variants.filter((v) => v !== variant);
        // Keine Varianten mehr übrig -> nichts mehr zum Zusammenführen da,
        // die ganze Zeile verschwindet wie bei "Ignorieren".
        if (!group.variants.length) {
          li.remove();
          return;
        }
        renderGroupText();
      });
      variantWrap.appendChild(removeBtn);

      text.appendChild(variantWrap);
    });
  }
  renderGroupText();

  const status = document.createElement('p');
  status.className = 'jobs-list-error hidden';

  const actions = document.createElement('div');
  actions.className = 'web-allowlist-candidate-actions';

  function setRowButtonsDisabled(disabled) {
    applyBtn.disabled = disabled;
    ignoreBtn.disabled = disabled;
    deleteBtn.disabled = disabled;
  }

  const applyBtn = document.createElement('button');
  applyBtn.type = 'button';
  applyBtn.className = 'link-button';
  applyBtn.textContent = t('import.termMergeApplyButton');
  applyBtn.addEventListener('click', async () => {
    setRowButtonsDisabled(true);
    status.classList.add('hidden');
    try {
      const res = await fetch('/api/terms/merge', {
        method: 'POST',
        headers: jsonHeaders(),
        body: JSON.stringify({ lang: group.lang, canonical: effectiveCanonical(), variants: effectiveVariants() }),
      });
      if (!res.ok) throw new Error();
      li.remove();
      resetKnownTerms(); // Tag-Vorschläge (attachTagSuggestions) sollen die geänderte Liste sehen.
    } catch {
      status.textContent = t('import.termMergeApplyFailed');
      status.classList.remove('hidden');
      setRowButtonsDisabled(false);
    }
  });

  const ignoreBtn = document.createElement('button');
  ignoreBtn.type = 'button';
  ignoreBtn.className = 'link-button';
  ignoreBtn.textContent = t('import.termMergeIgnoreButton');
  ignoreBtn.addEventListener('click', () => li.remove());

  // Nutzerwunsch (2026-09-22): eine als Rauschen erkannte Gruppe (z.B.
  // OCR-Artefakte) lässt sich statt eines Zusammenführens auch komplett
  // entfernen. Zweistufige Sicherheitsabfrage direkt am Link statt eines
  // nativen confirm()-Dialogs, analog zum Website-Löschen weiter unten in
  // dieser Datei - erster Klick wandelt nur den Text um, erst der zweite
  // Klick löst tatsächlich das Löschen aus. Änderung landet wie beim
  // Zusammenführen im Änderungs-Log und ist darüber pro Quelle rückgängig
  // machbar (siehe app/main.py: delete_terms).
  const deleteBtn = document.createElement('button');
  deleteBtn.type = 'button';
  deleteBtn.className = 'link-button';
  deleteBtn.textContent = t('import.termMergeDeleteButton');
  let deleteConfirmPending = false;
  deleteBtn.addEventListener('click', async () => {
    if (!deleteConfirmPending) {
      deleteConfirmPending = true;
      deleteBtn.textContent = t('import.termMergeDeleteConfirmButton');
      return;
    }
    setRowButtonsDisabled(true);
    status.classList.add('hidden');
    try {
      const res = await fetch('/api/terms/delete', {
        method: 'POST',
        headers: jsonHeaders(),
        body: JSON.stringify({ lang: group.lang, terms: [group.canonical, ...group.variants] }),
      });
      if (!res.ok) throw new Error();
      li.remove();
      resetKnownTerms();
    } catch {
      status.textContent = t('import.termMergeDeleteFailed');
      status.classList.remove('hidden');
      deleteConfirmPending = false;
      deleteBtn.textContent = t('import.termMergeDeleteButton');
      setRowButtonsDisabled(false);
    }
  });

  actions.append(applyBtn, ignoreBtn, deleteBtn);
  li.append(status, actions);
  return li;
}

// Nutzerwunsch (2026-09-22): bei ~1000+ Begriffen je Sprache dauerte ein
// kompletter Analyse-Durchlauf spürbar - erste Treffer sollen deutlich
// früher zur Bearbeitung erscheinen, statt bis zum Ende des gesamten
// Durchlaufs zu warten. /api/terms/merge-suggestions liefert die Treffer
// deshalb als NDJSON-Stream (Häppchen-weise, siehe app/main.py), gleiches
// Muster wie /api/ask (static/ndjson-stream.js) - jede Gruppe erscheint
// sofort, sobald sie ankommt. DE/EN laufen parallel, damit ein langsameres
// Sprach-Ergebnis das schnellere nicht ausbremst.
async function streamTermMergeSuggestions(lang, onGroup) {
  const res = await fetch('/api/terms/merge-suggestions', {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ lang }),
  });
  if (!res.ok) throw new Error();
  await readNdjsonStream(res, { group: onGroup });
}

// Nutzerwunsch (2026-09-23): Schlagwort-Übersicht - alle Begriffe der
// gerade gewählten Sprache, alphabetisch, mit eigener Alphabet-Sprungleiste
// (analog updateAlphabetJumpBar) und seitenweisem Rendern per Sentinel
// (analog renderSourceList). Pro Begriff aufklappbar die zugehörigen
// Quellen, die Menge zusätzlich als Balken proportional zum Maximum.
// Gezählt werden nur Quellen, die in allSources auch sichtbar sind.
const TERMS_PAGE_SIZE = 50;
let overviewTerms = [];
let visibleTermCount = TERMS_PAGE_SIZE;
let termListObserver = null;

function termLetter(term) {
  const letter = term.normalize('NFD')[0].toUpperCase();
  return JUMP_ALPHABET.includes(letter) ? letter : '';
}

function buildOverviewTerms(entries, sources, lang) {
  const sourceById = new Map(sources.map((s) => [s.id, s]));
  return entries
    .filter((e) => e.langs.includes(lang))
    .map((e) => ({ term: e.term, sources: e.source_ids.map((id) => sourceById.get(id)).filter(Boolean) }))
    .filter((e) => e.sources.length)
    .sort((a, b) => a.term.localeCompare(b.term, lang));
}

export async function loadTermOverview() {
  const res = await fetch('/api/terms');
  if (res.status === 429) return showTooManyRequests();
  if (!res.ok) return;
  overviewTerms = buildOverviewTerms(await res.json(), allSources, getLang());
  renderTermJumpBar();
  renderTermOverview();
}

function renderTermJumpBar() {
  const bar = document.getElementById('term-jump-bar');
  const available = new Set(overviewTerms.map((e) => termLetter(e.term)));
  bar.replaceChildren(
    ...JUMP_ALPHABET.map((letter) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'alphabet-jump-btn';
      btn.textContent = letter;
      if (available.has(letter)) {
        const label = t('import.termJumpToLetterTitle', { letter });
        btn.title = label;
        btn.setAttribute('aria-label', label);
        btn.addEventListener('click', () => jumpToTermLetter(letter));
      } else {
        btn.disabled = true;
      }
      return btn;
    })
  );
}

function jumpToTermLetter(letter) {
  const index = overviewTerms.findIndex((e) => termLetter(e.term) === letter);
  if (index >= visibleTermCount) {
    visibleTermCount = index + 1;
    renderTermOverview();
  }
  document
    .querySelector(`#term-overview-list [data-term-index="${index}"]`)
    ?.scrollIntoView({ block: 'start', behavior: 'smooth' });
}

export function renderTermOverview() {
  const list = document.getElementById('term-overview-list');
  document.getElementById('term-overview-empty').classList.toggle('hidden', overviewTerms.length > 0);
  const maxCount = Math.max(1, ...overviewTerms.map((e) => e.sources.length));
  list.replaceChildren(
    ...overviewTerms.slice(0, visibleTermCount).map((e, index) => buildTermOverviewItem(e, index, maxCount))
  );

  termListObserver?.disconnect();
  if (overviewTerms.length > visibleTermCount) {
    const sentinel = document.createElement('li');
    sentinel.className = 'term-overview-sentinel';
    list.appendChild(sentinel);
    termListObserver = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          termListObserver.disconnect();
          visibleTermCount += TERMS_PAGE_SIZE;
          renderTermOverview();
        }
      },
      { rootMargin: '400px' }
    );
    termListObserver.observe(sentinel);
  }
}

// Nutzerwunsch (2026-09-23): Quellen-Pfleger:innen können Schlagworte
// direkt in der Übersicht umbenennen (Stift wie beim Zielschlagwort im
// Zusammenführen-Panel) oder löschen (zweistufig wie dort). Umbenennen ist
// ein Zusammenführen auf den neuen Namen, beides über die bestehenden
// Endpunkte - landet damit im Änderungs-Log und ist pro Quelle rückgängig
// machbar. Übergeben werden alle Schreibweisen, die in den Quellen
// tatsächlich stehen (z.B. "Agile"/"agile" teilen sich einen Eintrag).
function termSpellings(entry) {
  const key = normalizeTerm(entry.term);
  const spellings = new Set([entry.term]);
  entry.sources.forEach((s) => (s.key_terms || []).forEach((k) => normalizeTerm(k) === key && spellings.add(k)));
  return [...spellings];
}

async function postTermChange(url, body, status, failedKey) {
  status.classList.add('hidden');
  try {
    const res = await fetch(url, { method: 'POST', headers: jsonHeaders(), body: JSON.stringify(body) });
    if (!res.ok) throw new Error();
    resetKnownTerms();
    await loadSources();
    return true;
  } catch {
    status.textContent = t(failedKey);
    status.classList.remove('hidden');
    setTermExpanded(status.closest('li'), true);
    return false;
  }
}

function buildTermRenameControls(entry, toggle, status) {
  const editBtn = document.createElement('button');
  editBtn.type = 'button';
  editBtn.className = 'icon-button term-merge-edit-canonical';
  editBtn.innerHTML = EDIT_ICON;
  const editLabel = t('import.termRenameTitle');
  editBtn.title = editLabel;
  editBtn.setAttribute('aria-label', editLabel);

  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'term-merge-canonical-input hidden';
  input.title = t('import.termRenameInputTitle');
  const suggestions = attachTagSuggestions(input, { multi: false, lang: getLang() });

  const wrap = document.createElement('span');
  wrap.className = 'term-merge-canonical-wrap term-overview-head';
  const deleteBtn = buildTermDeleteButton(entry, status);
  // Stift + Mülleimer als Einheit rechts neben dem Begriff, vertikal mittig
  // auch bei mehrzeiligen Begriffen (siehe .term-overview-head).
  const actions = document.createElement('span');
  actions.className = 'term-overview-actions';
  actions.append(editBtn, deleteBtn);
  wrap.append(toggle, actions, input, suggestions);

  function setEditing(editing) {
    toggle.classList.toggle('hidden', editing);
    actions.classList.toggle('hidden', editing);
    input.classList.toggle('hidden', !editing);
  }
  editBtn.addEventListener('click', () => {
    input.value = entry.term;
    setEditing(true);
    input.focus();
    input.select();
  });
  // Nur Enter speichert - Escape oder Wegklicken verwirft, damit nichts
  // versehentlich über alle Quellen hinweg umbenannt wird.
  input.addEventListener('blur', () => setEditing(false));
  input.addEventListener('keydown', async (e) => {
    if (e.key === 'Escape') input.blur();
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const canonical = input.value.trim();
    if (!canonical || canonical === entry.term) {
      input.blur();
      return;
    }
    input.disabled = true;
    const ok = await postTermChange(
      '/api/terms/merge',
      { lang: getLang(), canonical, variants: termSpellings(entry) },
      status,
      'import.termRenameFailed'
    );
    input.disabled = false;
    if (!ok) input.blur();
  });
  return wrap;
}

function buildTermDeleteButton(entry, status) {
  // Erster Klick aufs Mülleimer-Icon macht daraus die Rückfrage als Text
  // (wie "Alle Schlagworte löschen" im Zusammenführen-Panel), erst der
  // zweite löscht.
  const deleteBtn = document.createElement('button');
  deleteBtn.type = 'button';
  const label = t('import.termDeleteButton');
  function resetDeleteBtn() {
    confirmPending = false;
    deleteBtn.className = 'icon-button term-merge-edit-canonical';
    deleteBtn.innerHTML = TRASH_ICON;
    deleteBtn.title = label;
    deleteBtn.setAttribute('aria-label', label);
    deleteBtn.disabled = false;
  }
  let confirmPending = false;
  resetDeleteBtn();
  deleteBtn.addEventListener('click', async () => {
    if (!confirmPending) {
      confirmPending = true;
      deleteBtn.className = 'link-button term-overview-delete-confirm';
      deleteBtn.textContent = t('import.termDeleteConfirmButton');
      deleteBtn.removeAttribute('aria-label');
      return;
    }
    deleteBtn.disabled = true;
    const ok = await postTermChange(
      '/api/terms/delete',
      { lang: getLang(), terms: termSpellings(entry) },
      status,
      'import.termMergeDeleteFailed'
    );
    if (!ok) resetDeleteBtn();
  });
  return deleteBtn;
}

// Aufgeklappte Schlagworte überleben so jedes Neuzeichnen (z.B. nach dem
// Speichern einer Quelle im Bearbeiten-Formular darunter).
const expandedTermKeys = new Set();

function setTermExpanded(li, expanded) {
  if (expanded) li.fillSources();
  li.querySelector('.term-overview-toggle').setAttribute('aria-expanded', String(expanded));
  li.querySelector('.term-overview-panel').hidden = !expanded;
  if (expanded) expandedTermKeys.add(li.dataset.termKey);
  else expandedTermKeys.delete(li.dataset.termKey);
}

// Bewusst kein <details>/<summary>: Stift und Mülleimer sind eigene Buttons,
// und interaktive Elemente innerhalb eines <summary> sind per Tastatur/
// Screenreader nicht verlässlich bedienbar (Chrome-Issue). Stattdessen das
// Disclosure-Muster - nur der Begriff selbst ist der Aufklapp-Button.
function buildTermOverviewItem(entry, index, maxCount) {
  const li = document.createElement('li');
  li.dataset.termIndex = String(index);
  const termKey = normalizeTerm(entry.term);
  li.dataset.termKey = termKey;
  const expanded = expandedTermKeys.has(termKey);
  const row = document.createElement('div');
  row.className = 'term-overview-summary';

  const panel = document.createElement('div');
  panel.className = 'term-overview-panel';
  panel.id = `term-overview-panel-${index}`;
  panel.hidden = !expanded;

  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'term-overview-name term-overview-toggle';
  toggle.textContent = entry.term;
  toggle.setAttribute('aria-expanded', String(expanded));
  toggle.setAttribute('aria-controls', panel.id);
  toggle.addEventListener('click', () => setTermExpanded(li, panel.hidden));

  const bar = document.createElement('span');
  bar.className = 'term-overview-bar';
  const fill = document.createElement('span');
  fill.className = 'term-overview-bar-fill';
  fill.style.width = `${(entry.sources.length / maxCount) * 100}%`;
  bar.appendChild(fill);

  // Mobil nur die Zahl (Nutzerwunsch 2026-09-23) - der volle Text bleibt
  // dort für Screenreader erhalten (visuell ausgeblendet, siehe CSS).
  const count = document.createElement('span');
  count.className = 'term-overview-count';
  const countKey = entry.sources.length === 1 ? 'common.sourceCountOne' : 'common.sourceCountMany';
  const countFull = document.createElement('span');
  countFull.className = 'term-overview-count-full';
  countFull.textContent = t(countKey, { count: entry.sources.length });
  const countNum = document.createElement('span');
  countNum.className = 'term-overview-count-num';
  countNum.setAttribute('aria-hidden', 'true');
  countNum.textContent = String(entry.sources.length);
  count.append(countFull, countNum);

  const status = document.createElement('p');
  status.className = 'jobs-list-error hidden';
  row.append(toggle, bar, count);
  // Der Stift-Wrapper übernimmt toggle (verschiebt es aus row) und rückt an dessen Platz.
  if (hasPflegerRole()) row.prepend(buildTermRenameControls(entry, toggle, status));

  // Nutzerwunsch (2026-09-24): Quellen hier "vor Ort" aufklappen
  // (Kurzbeschreibung) und bearbeiten - dieselben Zeilen wie in der
  // Quellenliste. Nur für aufgeklappte Schlagworte gebaut.
  // Erst beim (ersten) Aufklappen gebaut - bei Hunderten sichtbarer
  // Schlagworte wären das sonst Tausende Zeilen samt Buttons vorab.
  const sourceList = document.createElement('ul');
  sourceList.className = 'term-overview-sources';
  li.fillSources = () => {
    if (sourceList.children.length) return;
    entry.sources.forEach((s, i) => {
      sourceList.append(...buildSourceEntries({ ...s, __editRowKey: `term:${termKey}` }, `t${index}-${i}`));
    });
  };
  if (expanded) li.fillSources();
  const filterBtn = document.createElement('button');
  filterBtn.type = 'button';
  filterBtn.className = 'link-button term-overview-filter';
  filterBtn.textContent = t('import.termOverviewFilter');
  filterBtn.addEventListener('click', () => filterByTerm(entry.term));
  panel.append(sourceList, filterBtn, status);

  li.append(row, panel);
  return li;
}

export function initTermMerge() {
  document.getElementById('typ-term-merge').addEventListener('click', () => {
    importBereich.classList.add('hidden');
    urlPopover.classList.add('hidden');
    filePopover.classList.add('hidden');
    webAllowlistBereich.classList.add('hidden');
    sourceSuggestionsBereich.classList.add('hidden');
    document.getElementById('jobs-popover').classList.add('hidden');
    document.getElementById('jobs-bar').classList.add('hidden');
    closeSearchBar();
    termMergeBereich.classList.toggle('hidden');
  });

  document.getElementById('term-merge-close').addEventListener('click', () => {
    termMergeBereich.classList.add('hidden');
  });

  termMergeAnalyzeBtn.addEventListener('click', async () => {
    // Nutzerwunsch (2026-09-23): "Wird analysiert..." steht im ausgegrauten
    // Button selbst, wie bei den anderen Aktions-Buttons (z.B. submitBtn im
    // Bearbeiten-Formular), statt in einem separaten Statustext daneben.
    termMergeAnalyzeBtn.disabled = true;
    termMergeAnalyzeBtn.textContent = t('import.termMergeAnalyzing');
    termMergeStatus.textContent = '';
    termMergeEmpty.classList.add('hidden');
    termMergeList.innerHTML = '';
    let anyGroup = false;
    try {
      await Promise.all(
        ['de', 'en'].map((lang) =>
          streamTermMergeSuggestions(lang, (group) => {
            anyGroup = true;
            termMergeList.appendChild(renderTermMergeGroup(group));
          })
        )
      );
      if (!anyGroup) termMergeEmpty.classList.remove('hidden');
    } catch {
      termMergeStatus.textContent = t('import.termMergeAnalyzeFailed');
    } finally {
      termMergeAnalyzeBtn.disabled = false;
      termMergeAnalyzeBtn.textContent = t('import.termMergeAnalyzeButton');
    }
  });
}

