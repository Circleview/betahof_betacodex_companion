// Web-Allowlist und Quellen-Vorschläge der Quellenseite. Aus import.js
// herausgezogen (Idee 313ad93d).
import { t, getLang } from '/i18n.js';
import { jsonHeaders } from '/source-edit.js';
import { hasPflegerRole } from '/import-state.js';

// Backlog: LLM/Internet-Fallback bei dünner Quellenlage.
const webAllowlistForm = document.getElementById('web-allowlist-form');
const webAllowlistPendingList = document.getElementById('web-allowlist-pending-list');
const webAllowlistList = document.getElementById('web-allowlist-list');
const webAllowlistWarning = document.getElementById('web-allowlist-warning');
// Nutzerwunsch: proaktive Quellen-Vorschläge aus dem offenen Web.
const sourceSuggestionsBtn = document.getElementById('typ-source-suggestions');
const sourceSuggestionsBereich = document.getElementById('source-suggestions-bereich');
const sourceSuggestionsEmpty = document.getElementById('source-suggestions-empty');
const sourceSuggestionsList = document.getElementById('source-suggestions-list');

// Wird von import.js über initWebAllowlist gesetzt (import.js importiert dieses
// Modul - ein Rück-Import wäre ein Zyklus über das Einstiegsmodul).
let openUrlPopoverWithUrl;

// Nutzerwunsch (Positivselektion): macht sichtbar, wenn app/web_crawler.py
// für eine Website automatisch von "Negativselektion" (bereits indizierte
// Seiten bereinigen) auf "Positivselektion" (Kandidaten gezielt auswählen)
// umgeschaltet hat - Warndreieck statt des durchgestrichenen Ketten-Symbols
// (das steht für defekte Links, ein anderer Sachverhalt).
const POSITIVE_SELECTION_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M12 9v4"></path><path d="M12 17h.01"></path>' +
  '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"></path>' +
  "</svg>";

// Backlog: LLM/Internet-Fallback bei dünner Quellenlage - Pflege der
// freigegebenen externen Domains/Pfade (siehe app/web_allowlist.py).
let webAllowlistEntries = [];
// Nutzerwunsch: unmittelbar nach dem Anlegen soll sichtbar sein, dass die
// Website wirklich angelegt wurde UND die Verarbeitung begonnen hat - dafür
// wandert sie in eine eigene Pending-Liste direkt unterm Formular (statt nur
// den ohnehin schon vorhandenen "Wird indiziert..."-Badge in der normalen
// Liste zu zeigen, siehe weiter unten). Bewusst NICHT einfach "jeder Eintrag
// mit indexing_status === running", sonst würde auch eine bereits etablierte
// Website (z. B. 25 indizierte Seiten) beim ganz normalen wöchentlichen
// Sweep kurzzeitig aus der Liste verschwinden und wieder auftauchen - hier
// nur IDs, die in DIESER Sitzung tatsächlich frisch über das Formular
// angelegt wurden, verlassen die Menge automatisch wieder, sobald ihre
// Erstverarbeitung fertig ist (siehe renderWebAllowlistList).
let recentlyAddedWebAllowlistIds = new Set();
// Analog zu previousJobIds bei fetchImportJobs: die volle Liste wird beim
// Polling nur dann komplett neu aufgebaut (und riskiert damit ein offenes
// Akkordeon zu schließen), wenn sich die Menge der GERADE laufenden
// Einträge tatsächlich verändert hat - nicht bei jedem 3-Sekunden-Takt.
let previousRunningWebAllowlistIds = new Set();

function formatWebAllowlistDate(isoString) {
  if (!isoString) return t('import.webAllowlistNeverReviewed');
  return isoString.split('T')[0];
}

// Nutzerwunsch: einzelne indizierte Seiten einer Website sollen sich gezielt
// vom Fallback ausschließen (und wieder aufnehmen) lassen, ohne die ganze
// Freigabe zu löschen - Ausklapp-Liste je Eintrag, nach demselben <details>/
// <summary>-Muster wie die Quellenliste im Chat (siehe question.js:
// buildSourcesList). Seiten werden erst beim ersten Öffnen nachgeladen.
function formatWebIndexPageDate(page) {
  return page.date || t('import.webAllowlistPageNoDate');
}

function renderWebAllowlistPagesList(listEl, entryId, pages) {
  listEl.innerHTML = '';
  pages.forEach((page) => {
    const li = document.createElement('li');
    li.className = 'web-allowlist-page';
    li.classList.toggle('web-allowlist-page--excluded', page.excluded);

    const info = document.createElement('p');
    info.className = 'web-allowlist-page-info';
    const titleLink = document.createElement('a');
    titleLink.href = page.url;
    titleLink.target = '_blank';
    titleLink.rel = 'noopener noreferrer';
    titleLink.textContent = page.title;
    info.appendChild(titleLink);
    info.append(` · ${formatWebIndexPageDate(page)}`);
    li.appendChild(info);

    const toggleBtn = document.createElement('button');
    toggleBtn.type = 'button';
    toggleBtn.className = 'link-button';
    toggleBtn.textContent = t(
      page.excluded ? 'import.webAllowlistPageIncludeButton' : 'import.webAllowlistPageExcludeButton'
    );
    toggleBtn.addEventListener('click', async () => {
      toggleBtn.disabled = true;
      try {
        const action = page.excluded ? 'include' : 'exclude';
        const res = await fetch(`/api/web-allowlist/${entryId}/pages/${page.id}/${action}`, {
          method: 'POST',
          headers: jsonHeaders(),
        });
        if (res.ok) {
          page.excluded = !page.excluded;
          li.classList.toggle('web-allowlist-page--excluded', page.excluded);
          toggleBtn.textContent = t(
            page.excluded ? 'import.webAllowlistPageIncludeButton' : 'import.webAllowlistPageExcludeButton'
          );
        }
      } finally {
        toggleBtn.disabled = false;
      }
    });
    li.appendChild(toggleBtn);

    listEl.appendChild(li);
  });
}

function buildWebAllowlistPagesAccordion(entry) {
  const details = document.createElement('details');
  details.className = 'web-allowlist-pages';
  const summary = document.createElement('summary');
  summary.textContent = t('import.webAllowlistPagesToggle', { count: entry.page_count });
  details.appendChild(summary);
  const list = document.createElement('ul');
  list.className = 'web-allowlist-pages-list';
  details.appendChild(list);

  let loaded = false;
  details.addEventListener('toggle', async () => {
    if (!details.open || loaded) return;
    loaded = true;
    try {
      const res = await fetch(`/api/web-allowlist/${entry.id}/pages`, { headers: { 'X-Lang': getLang() } });
      if (!res.ok) return;
      renderWebAllowlistPagesList(list, entry.id, await res.json());
    } catch (err) {
      loaded = false;
    }
  });

  return details;
}

// Nutzerwunsch (Positivselektion): statt bereits indizierter Seiten (siehe
// buildWebAllowlistPagesAccordion) zeigt dieser Bereich gegen den
// bestehenden Quellenbestand bewertete VORSCHLÄGE, aus denen eine Pfleger:in
// gezielt einzelne für die Aufnahme auswählt - nur sichtbar, wenn
// entry.selection_mode === "positiv" (siehe renderWebAllowlistList). Lädt
// die komplette, bereits absteigend sortierte Liste einmalig und paginiert
// clientseitig in 10er-Schritten, statt bei jedem "mehr…"-Klick neu zu
// fragen.
const WEB_ALLOWLIST_CANDIDATES_PAGE_SIZE = 10;

function renderWebAllowlistCandidateRow(entryId, candidate, onDecided) {
  const li = document.createElement('li');
  li.className = 'web-allowlist-candidate';

  const info = document.createElement('p');
  info.className = 'web-allowlist-candidate-info';
  const titleLink = document.createElement('a');
  titleLink.href = candidate.url;
  titleLink.target = '_blank';
  titleLink.rel = 'noopener noreferrer';
  titleLink.textContent = candidate.title;
  info.appendChild(titleLink);
  li.appendChild(info);

  const snippet = document.createElement('p');
  snippet.className = 'web-allowlist-candidate-snippet';
  snippet.textContent = candidate.snippet;
  li.appendChild(snippet);

  const actions = document.createElement('div');
  actions.className = 'web-allowlist-candidate-actions';

  const approveBtn = document.createElement('button');
  approveBtn.type = 'button';
  approveBtn.className = 'link-button';
  approveBtn.textContent = t('import.webAllowlistCandidateApproveButton');

  const rejectBtn = document.createElement('button');
  rejectBtn.type = 'button';
  rejectBtn.className = 'link-button';
  rejectBtn.textContent = t('import.webAllowlistCandidateRejectButton');

  async function decide(action, btn) {
    approveBtn.disabled = true;
    rejectBtn.disabled = true;
    try {
      const res = await fetch(`/api/web-allowlist/${entryId}/candidates/${candidate.id}/${action}`, {
        method: 'POST',
        headers: jsonHeaders(),
      });
      if (res.ok) {
        onDecided();
        return;
      }
    } catch (err) {
      // fällt unten durch, Buttons werden wieder freigegeben
    }
    approveBtn.disabled = false;
    rejectBtn.disabled = false;
  }

  approveBtn.addEventListener('click', () => decide('approve', approveBtn));
  rejectBtn.addEventListener('click', () => decide('reject', rejectBtn));

  actions.appendChild(approveBtn);
  actions.appendChild(rejectBtn);
  li.appendChild(actions);

  return li;
}

function buildWebAllowlistCandidatesSection(entry) {
  const container = document.createElement('div');
  container.className = 'web-allowlist-candidates';

  const hint = document.createElement('p');
  hint.className = 'web-allowlist-candidates-hint';
  hint.innerHTML = POSITIVE_SELECTION_ICON;
  const hintText = document.createElement('span');
  hintText.textContent = t('import.webAllowlistPositiveSelectionHint');
  hint.appendChild(hintText);
  container.appendChild(hint);

  const list = document.createElement('ul');
  list.className = 'web-allowlist-candidates-list';
  container.appendChild(list);

  const moreBtn = document.createElement('button');
  moreBtn.type = 'button';
  moreBtn.className = 'link-button web-allowlist-candidates-more-btn hidden';
  moreBtn.textContent = t('import.webAllowlistCandidatesShowMore');
  container.appendChild(moreBtn);

  let allCandidates = [];
  let shownCount = 0;

  function renderVisible() {
    list.innerHTML = '';
    if (allCandidates.length === 0) {
      const empty = document.createElement('p');
      empty.className = 'web-allowlist-candidates-empty';
      empty.textContent = t('import.webAllowlistCandidatesEmpty');
      list.appendChild(empty);
      moreBtn.classList.add('hidden');
      return;
    }
    allCandidates.slice(0, shownCount).forEach((candidate) => {
      list.appendChild(
        renderWebAllowlistCandidateRow(entry.id, candidate, () => {
          // Entfernte Kandidaten rutschen die Liste einfach nach oben nach -
          // shownCount bleibt gleich, außer die Gesamtliste ist jetzt kürzer.
          allCandidates = allCandidates.filter((c) => c.id !== candidate.id);
          shownCount = Math.min(shownCount, allCandidates.length);
          renderVisible();
        })
      );
    });
    moreBtn.classList.toggle('hidden', shownCount >= allCandidates.length);
  }

  moreBtn.addEventListener('click', () => {
    shownCount = Math.min(allCandidates.length, shownCount + WEB_ALLOWLIST_CANDIDATES_PAGE_SIZE);
    renderVisible();
  });

  (async () => {
    try {
      const res = await fetch(`/api/web-allowlist/${entry.id}/candidates`, {
        headers: { 'X-Lang': getLang() },
      });
      if (!res.ok) return;
      allCandidates = await res.json();
      shownCount = Math.min(allCandidates.length, WEB_ALLOWLIST_CANDIDATES_PAGE_SIZE);
      renderVisible();
    } catch (err) {
      // Stiller Fehlschlag, wie beim übrigen Web-Allowlist-Bereich.
    }
  })();

  return container;
}

// Nutzerwunsch: kleine, bewusst schlichte Zeile pro Eintrag - keine Aktionen
// (Löschen/Als-geprüft-markieren/Akkordeon), die für einen Eintrag ohne
// jeden Inhalt noch keinen Sinn ergeben. Sobald die Erstverarbeitung fertig
// ist, verschwindet der Eintrag von hier und erscheint stattdessen ganz
// normal in der etablierten Liste (siehe renderWebAllowlistList).
function renderWebAllowlistPendingList(pendingEntries) {
  webAllowlistPendingList.innerHTML = '';
  webAllowlistPendingList.classList.toggle('hidden', pendingEntries.length === 0);
  pendingEntries.forEach((entry) => {
    const li = document.createElement('li');
    li.className = 'web-allowlist-pending-item';
    li.dataset.entryId = entry.id;

    const heading = document.createElement('p');
    heading.className = 'web-allowlist-pending-item-heading';
    const labelSpan = document.createElement('strong');
    labelSpan.textContent = entry.label;
    heading.appendChild(labelSpan);
    heading.append(` – ${entry.url_prefix}`);
    li.appendChild(heading);

    const badge = document.createElement('span');
    badge.className = 'restricted-badge';
    badge.textContent = t('import.webAllowlistIndexingBadge');
    li.appendChild(badge);

    webAllowlistPendingList.appendChild(li);
  });
}

function renderWebAllowlistList() {
  // Nutzerwunsch: nur in DIESER Sitzung frisch angelegte, noch laufende
  // Einträge zählen als "pending" - die Menge bereinigt sich hier von
  // selbst, sobald ein Eintrag fertig verarbeitet ist (indexing_status
  // nicht mehr "running"), damit ein späterer wöchentlicher Sweep desselben
  // Eintrags ihn nicht erneut in die Pending-Liste zurückholt.
  const pendingEntries = webAllowlistEntries.filter(
    (e) => recentlyAddedWebAllowlistIds.has(e.id) && e.indexing_status === 'running'
  );
  recentlyAddedWebAllowlistIds = new Set(pendingEntries.map((e) => e.id));
  renderWebAllowlistPendingList(pendingEntries);
  const pendingIds = new Set(pendingEntries.map((e) => e.id));

  webAllowlistList.innerHTML = '';
  webAllowlistEntries
    .filter((entry) => !pendingIds.has(entry.id))
    .forEach((entry) => {
    const li = document.createElement('li');
    li.className = 'web-allowlist-item';
    // Nutzerwunsch: der Indizierungs-Badge (siehe unten) muss auch beim
    // leichtgewichtigen Polling aktualisiert werden können, ohne die ganze
    // Liste neu aufzubauen (sonst würde ein offenes Seiten-Akkordeon bei
    // jedem Takt zuklappen, siehe pollWebAllowlistStatus-Kommentar) - dafür
    // braucht updateWebAllowlistIndexingBadges() ein stabiles Zuordnungsmerkmal.
    li.dataset.entryId = entry.id;

    // Nutzerwunsch: der Löschen-Link steht rechts oben neben dem Titel,
    // dezent/klein statt wie die übrigen Aktionen unterhalb - lädt so nicht
    // zum versehentlichen Klicken ein.
    const headingRow = document.createElement('div');
    headingRow.className = 'web-allowlist-item-heading-row';

    const heading = document.createElement('p');
    heading.className = 'web-allowlist-item-heading';
    const labelSpan = document.createElement('strong');
    labelSpan.textContent = entry.label;
    heading.appendChild(labelSpan);
    heading.append(` – ${entry.url_prefix}`);
    // Nutzerwunsch: wie bei PDF-/Audio-Quellen (import.processingBadge) soll
    // auch bei einer Website sichtbar sein, dass GENAU DIESER Eintrag gerade
    // indiziert wird - bisher gab es nur den globalen Fortschrittsring am
    // Icon (renderWebAllowlistIcon), der nicht verrät, welcher von mehreren
    // Einträgen betroffen ist.
    const indexingBadge = document.createElement('span');
    indexingBadge.className = 'restricted-badge web-allowlist-indexing-badge';
    indexingBadge.textContent = t('import.webAllowlistIndexingBadge');
    indexingBadge.classList.toggle('hidden', entry.indexing_status !== 'running');
    heading.appendChild(document.createTextNode(' '));
    heading.appendChild(indexingBadge);
    headingRow.appendChild(heading);

    // Nutzerwunsch: zweistufige Sicherheitsabfrage direkt am Link statt
    // eines nativen confirm()-Dialogs - erster Klick wandelt nur den Text
    // um, erst der zweite Klick (auf denselben, jetzt bestätigenden Link)
    // löst tatsächlich DELETE aus.
    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'web-allowlist-delete-link';
    deleteBtn.textContent = t('import.webAllowlistDeleteButton');
    let deleteConfirmPending = false;
    deleteBtn.addEventListener('click', async () => {
      if (!deleteConfirmPending) {
        deleteConfirmPending = true;
        deleteBtn.textContent = t('import.webAllowlistDeleteConfirmButton');
        return;
      }
      deleteBtn.disabled = true;
      try {
        await fetch(`/api/web-allowlist/${entry.id}`, { method: 'DELETE', headers: jsonHeaders() });
        await loadWebAllowlist();
      } finally {
        deleteBtn.disabled = false;
      }
    });
    headingRow.appendChild(deleteBtn);
    li.appendChild(headingRow);

    const meta = document.createElement('p');
    meta.className = 'web-allowlist-item-meta';
    const pageCountKey =
      entry.page_count === 1 ? 'import.webAllowlistPageCountOne' : 'import.webAllowlistPageCountMany';
    meta.textContent =
      `${t(pageCountKey, { count: entry.page_count })} · ` +
      `${t('import.webAllowlistReviewedAt', { date: formatWebAllowlistDate(entry.reviewed_at) })}`;
    if (entry.needs_review) {
      const badge = document.createElement('span');
      badge.className = 'web-allowlist-review-badge';
      badge.textContent = t('import.webAllowlistNeedsReview');
      meta.appendChild(document.createTextNode(' '));
      meta.appendChild(badge);
    }
    li.appendChild(meta);

    const reason = document.createElement('p');
    reason.className = 'web-allowlist-item-reason';
    reason.textContent = entry.reason;
    li.appendChild(reason);

    const actions = document.createElement('div');
    actions.className = 'web-allowlist-item-actions';

    // Nutzerfeedback: "Als geprüft markieren" setzt nur den reviewed_at-
    // Zeitstempel zurück (siehe mark-reviewed-Endpoint) - ohne fällige
    // Prüfung (needs_review) gibt es nichts zu bestätigen, der Link würde
    // nur verwirren.
    if (entry.needs_review) {
      const reviewBtn = document.createElement('button');
      reviewBtn.type = 'button';
      reviewBtn.className = 'link-button';
      reviewBtn.textContent = t('import.webAllowlistMarkReviewedButton');
      reviewBtn.addEventListener('click', async () => {
        reviewBtn.disabled = true;
        try {
          await fetch(`/api/web-allowlist/${entry.id}/mark-reviewed`, {
            method: 'POST',
            headers: jsonHeaders(),
          });
          await loadWebAllowlist();
        } finally {
          reviewBtn.disabled = false;
        }
      });
      actions.appendChild(reviewBtn);
    }

    li.appendChild(actions);
    li.appendChild(buildWebAllowlistPagesAccordion(entry));
    if (entry.selection_mode === 'positiv') {
      li.appendChild(buildWebAllowlistCandidatesSection(entry));
    }
    webAllowlistList.appendChild(li);
  });
}

// Warn-Icon am Toolbar-Button (Mouse-Over-Tooltip via title-Attribut) -
// nur für Quellen-Pfleger:innen/Admins überhaupt sichtbar (Button selbst
// wird bereits über updateSourceManagementVisibility()/#quelltyp-bereich
// für alle anderen ausgeblendet).
function updateWebAllowlistButton() {
  const needsReviewCount = webAllowlistEntries.filter((e) => e.needs_review).length;
  webAllowlistWarning.classList.toggle('hidden', needsReviewCount === 0);
  webAllowlistWarning.title =
    needsReviewCount > 0
      ? t('import.webAllowlistNeedsReviewTooltip', { count: needsReviewCount })
      : '';
}

// Nutzerwunsch: Indizierungsstatus als fortlaufender Kreis am Globus-Icon,
// analog zum Fortschrittsring bei #typ-jobs (siehe renderJobsIcon). Anders
// als bei Audio/PDF gibt es keine festen Verarbeitungsstufen - als grobe
// Annäherung dient das Verhältnis bereits indizierter Seiten zur
// eingestellten Obergrenze (max_pages). Läuft praktisch immer für höchstens
// einen Eintrag gleichzeitig (Sofort-Crawl und wöchentlicher Sweep
// verarbeiten Einträge nacheinander, siehe app/main.py).
const WEB_ALLOWLIST_RING_CIRCUMFERENCE = 87.9;

function renderWebAllowlistIcon(entries) {
  const ring = document.getElementById('web-allowlist-icon-ring');
  const progressCircle = document.getElementById('web-allowlist-icon-progress');
  const runningEntry = entries.find((e) => e.indexing_status === 'running');
  ring.classList.toggle('hidden', !runningEntry);
  if (runningEntry) {
    const fraction = Math.min((runningEntry.page_count || 0) / Math.max(runningEntry.max_pages, 1), 0.95);
    progressCircle.setAttribute(
      'stroke-dashoffset',
      String(WEB_ALLOWLIST_RING_CIRCUMFERENCE * (1 - fraction))
    );
  }
}

// Nutzerwunsch: proaktive Quellen-Vorschläge aus dem offenen Web (app/
// source_discovery.py) - "Annehmen" legt bewusst KEINE Quelle direkt an,
// sondern öffnet das bestehende URL-Popover vorausgefüllt (siehe
// extractAndFillFromUrl oben) - Extraktion/Review/Speichern laufen 1:1 wie
// beim manuellen Import.
//
// Nutzerwunsch (2026-08-23): die Liste soll IMMER SOURCE_SUGGESTIONS_
// VISIBLE_COUNT Vorschläge zeigen, sofern der Backend-Vorrat das hergibt -
// beim Annehmen/Ablehnen rückt sofort (ohne neue Websuche abzuwarten, siehe
// SOURCE_SUGGESTION_QUEUE_TARGET in app/main.py) der nächste Vorschlag aus
// dem beim Laden bereits mitgelieferten Rest nach. Zwei getrennte Arrays
// statt einer einzigen Liste: sourceSuggestionsVisible sind die aktuell
// gerenderten Zeilen, sourceSuggestionsReserve der noch nicht gezeigte
// Rest, aus dem genau EIN Element pro Entscheidung nachrückt.
const SOURCE_SUGGESTIONS_VISIBLE_COUNT = 5;
let sourceSuggestionsVisible = [];
let sourceSuggestionsReserve = [];

// Nutzerfeedback (2026-08-23): kein Warn-Badge am Lampen-Icon - da praktisch
// immer mindestens ein Vorschlag vorliegt, wäre es dauerhaft aktiv und damit
// bedeutungslos. Stattdessen verschwindet das Icon selbst vollständig,
// sobald es wirklich mal keine offenen Vorschläge gibt (weder sichtbar noch
// im Vorrat) - inkl. Schließen der Vorschlagsliste, falls die gerade offen
// war (sonst gäbe es keinen Weg mehr, sie zuzuklappen, da genau dieses Icon
// dafür fehlt).
function updateSourceSuggestionsButtonVisibility() {
  const hasAny = sourceSuggestionsVisible.length > 0 || sourceSuggestionsReserve.length > 0;
  sourceSuggestionsBtn.classList.toggle('hidden', !hasAny);
  if (!hasAny) sourceSuggestionsBereich.classList.add('hidden');
}

function renderSourceSuggestionRow(suggestion) {
  const li = document.createElement('li');
  li.className = 'web-allowlist-candidate';

  const info = document.createElement('p');
  info.className = 'web-allowlist-candidate-info';
  const link = document.createElement('a');
  link.href = suggestion.url;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  // Nutzerfeedback: Standard-Blau des Browsers passt nicht ins Design -
  // dieselbe Klasse wie bei Quellentitel-Links in der Konversationsansicht
  // (static/style.css), statt dem Browser-Default zu überlassen.
  link.className = 'citation-title-link';
  link.textContent = suggestion.title;
  info.appendChild(link);
  li.appendChild(info);

  const reason = document.createElement('p');
  reason.className = 'web-allowlist-candidate-snippet';
  reason.textContent = suggestion.reason;
  li.appendChild(reason);

  const actions = document.createElement('div');
  actions.className = 'web-allowlist-candidate-actions';
  const acceptBtn = document.createElement('button');
  acceptBtn.type = 'button';
  acceptBtn.className = 'link-button';
  acceptBtn.textContent = t('import.sourceSuggestionAcceptButton');
  const rejectBtn = document.createElement('button');
  rejectBtn.type = 'button';
  rejectBtn.className = 'link-button';
  rejectBtn.textContent = t('import.sourceSuggestionRejectButton');

  async function decide(action) {
    acceptBtn.disabled = true;
    rejectBtn.disabled = true;
    try {
      const res = await fetch(`/api/source-suggestions/${suggestion.id}/${action}`, {
        method: 'POST',
        headers: jsonHeaders(),
      });
      if (!res.ok) throw new Error('failed');
      // Nutzerwunsch: "Abgelehnte Quellen verschwinden mit einer einfachen
      // Transition" - gilt hier bewusst für beide Aktionen (Annehmen UND
      // Ablehnen), damit eine Zeile nie abrupt verschwindet. Erst nach
      // Ablauf der CSS-Transition (removeSourceSuggestionRow) tatsächlich
      // aus dem DOM entfernen und ggf. nachrücken lassen.
      removeSourceSuggestionRow(li, suggestion.id);
      if (action === 'accept') {
        openUrlPopoverWithUrl(suggestion.url);
      }
    } catch (err) {
      acceptBtn.disabled = false;
      rejectBtn.disabled = false;
    }
  }

  acceptBtn.addEventListener('click', () => decide('accept'));
  rejectBtn.addEventListener('click', () => decide('reject'));
  actions.appendChild(acceptBtn);
  actions.appendChild(rejectBtn);
  li.appendChild(actions);
  return li;
}

// Dauer MUSS zur CSS-Transition auf .web-allowlist-candidate--leaving
// passen (siehe style.css) - setTimeout statt transitionend, da dort
// mehrere Eigenschaften gleichzeitig übergehen (transitionend würde sonst
// mehrfach feuern) und "eine einfache Transition" (Nutzerwunsch) keinen
// Sonderfall-Code dafür braucht.
const SOURCE_SUGGESTION_LEAVE_MS = 200;

// Nutzerwunsch (2026-08-23): entfernt eine entschiedene Zeile mit
// Fade-Out und lässt danach - sofern vorhanden - sofort den nächsten
// Vorschlag aus dem bereits geladenen Vorrat mit Fade-In nachrücken, damit
// die Liste wenn möglich immer SOURCE_SUGGESTIONS_VISIBLE_COUNT Zeilen
// zeigt, ohne auf eine neue (mehrere Sekunden dauernde) Websuche zu warten.
function removeSourceSuggestionRow(li, id) {
  li.classList.add('web-allowlist-candidate--leaving');
  sourceSuggestionsVisible = sourceSuggestionsVisible.filter((s) => s.id !== id);
  setTimeout(() => {
    li.remove();
    if (sourceSuggestionsReserve.length > 0) {
      const next = sourceSuggestionsReserve.shift();
      sourceSuggestionsVisible.push(next);
      const nextLi = renderSourceSuggestionRow(next);
      nextLi.classList.add('web-allowlist-candidate--entering');
      sourceSuggestionsList.appendChild(nextLi);
    }
    sourceSuggestionsEmpty.classList.toggle('hidden', sourceSuggestionsVisible.length > 0);
    updateSourceSuggestionsButtonVisibility();
  }, SOURCE_SUGGESTION_LEAVE_MS);
}

function renderSourceSuggestionsList() {
  sourceSuggestionsList.replaceChildren();
  sourceSuggestionsEmpty.classList.toggle('hidden', sourceSuggestionsVisible.length > 0);
  sourceSuggestionsVisible.forEach((s) => sourceSuggestionsList.appendChild(renderSourceSuggestionRow(s)));
}

export async function loadSourceSuggestions() {
  if (!hasPflegerRole()) return;
  const res = await fetch('/api/source-suggestions', { headers: { 'X-Lang': getLang() } });
  if (!res.ok) return;
  const all = await res.json();
  sourceSuggestionsVisible = all.slice(0, SOURCE_SUGGESTIONS_VISIBLE_COUNT);
  sourceSuggestionsReserve = all.slice(SOURCE_SUGGESTIONS_VISIBLE_COUNT);
  renderSourceSuggestionsList();
  updateSourceSuggestionsButtonVisibility();
}

export async function loadWebAllowlist() {
  if (!hasPflegerRole()) return;
  const res = await fetch('/api/web-allowlist', { headers: { 'X-Lang': getLang() } });
  if (!res.ok) return;
  webAllowlistEntries = await res.json();
  renderWebAllowlistList();
  updateWebAllowlistButton();
  renderWebAllowlistIcon(webAllowlistEntries);
  previousRunningWebAllowlistIds = new Set(
    webAllowlistEntries.filter((e) => e.indexing_status === 'running').map((e) => e.id)
  );
}

// Bugfix (Nutzerfeedback): der 3-Sekunden-Poll-Takt (siehe
// pollBackgroundImportStatus) darf NICHT bei jedem Takt renderWebAllowlistList()
// aufrufen - das baut #web-allowlist-list komplett neu auf und riss dadurch
// ein gerade geöffnetes Seiten-Akkordeon (<details>) sofort wieder zu.
// Aktualisiert deshalb im Normalfall nur den Warn-Badge und den
// Fortschrittsring. Nur wenn sich die MENGE der gerade laufenden Einträge
// tatsächlich verändert (ein Crawl startet/endet), wird einmalig komplett
// neu aufgebaut - analog zum jobsChanged-Muster bei fetchImportJobs, damit
// z.B. ein frisch fertig gewordener Pending-Eintrag zeitnah (statt erst
// beim nächsten manuellen Neuladen) in die etablierte Liste wandert.
export async function pollWebAllowlistStatus() {
  if (!hasPflegerRole()) return;
  try {
    const res = await fetch('/api/web-allowlist', { headers: { 'X-Lang': getLang() } });
    if (!res.ok) return;
    webAllowlistEntries = await res.json();
    const currentRunningIds = new Set(
      webAllowlistEntries.filter((e) => e.indexing_status === 'running').map((e) => e.id)
    );
    const runningChanged =
      currentRunningIds.size !== previousRunningWebAllowlistIds.size ||
      [...currentRunningIds].some((id) => !previousRunningWebAllowlistIds.has(id));
    previousRunningWebAllowlistIds = currentRunningIds;
    if (runningChanged) {
      renderWebAllowlistList();
    }
    updateWebAllowlistButton();
    renderWebAllowlistIcon(webAllowlistEntries);
  } catch (err) {
    // Stille Hintergrund-Aktualisierung, wie bei fetchImportJobs.
  }
}

export function initWebAllowlist(callbacks) {
  openUrlPopoverWithUrl = callbacks.openUrlPopoverWithUrl;

  webAllowlistForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const status = document.getElementById('web-allowlist-status');
    const urlPrefixInput = document.getElementById('web-allowlist-url-prefix');
    const labelInput = document.getElementById('web-allowlist-label');
    const reasonInput = document.getElementById('web-allowlist-reason');
    const maxPagesInput = document.getElementById('web-allowlist-max-pages');
    status.textContent = '';
    try {
      const res = await fetch('/api/web-allowlist', {
        method: 'POST',
        headers: jsonHeaders(),
        body: JSON.stringify({
          url_prefix: urlPrefixInput.value.trim(),
          label: labelInput.value.trim(),
          reason: reasonInput.value.trim(),
          max_pages: parseInt(maxPagesInput.value, 10) || 50,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || t('import.webAllowlistAddFailed'));
      }
      // Nutzerwunsch: sofortiges Feedback, dass das Anlegen geklappt hat UND
      // die Verarbeitung begonnen hat - die neue ID merken wir uns hier, damit
      // renderWebAllowlistList() sie (solange indexing_status "running" ist)
      // in die eigene Pending-Liste einsortiert statt in die etablierte Liste.
      const created = await res.json();
      recentlyAddedWebAllowlistIds.add(created.id);
      webAllowlistForm.reset();
      maxPagesInput.value = '50';
      status.textContent = t('import.webAllowlistAddedStatus');
      await loadWebAllowlist();
    } catch (err) {
      status.textContent = t('common.errorPrefix') + err.message;
    }
  });
}

