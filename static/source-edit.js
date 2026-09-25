// Nutzerwunsch (2026-09-25): Bearbeiten-Formular einer Quelle als eigene
// Komponente - aus import.js herausgezogen, damit auch die Konversation
// (question.js, Stift-Icon an Zitaten/Seitenleiste) sie direkt aufrufen kann,
// statt die Quellenübersicht in einem neuen Tab zu öffnen. Alles, was an der
// Quellenliste hängt (Löschen mit Rückgängig, Neuladen), kommt über Callbacks
// in buildEditPanel(s, options) herein.
import { t, getLang } from '/i18n.js';

// Bekannte Autor:innen (GET /api/authors) - steuert, ob unter einem Namen
// "Autorenprofil pflegen" erscheint. Aufrufer setzen die Liste nach dem Laden.
let allAuthors = [];
export function setKnownAuthors(authors) {
  allAuthors = authors;
}

export function resetKnownTerms() {
  knownTermsCache = null;
}

export const EXTERNAL_LINK_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>' +
  '<polyline points="15 3 21 3 21 9"></polyline>' +
  '<line x1="10" y1="14" x2="21" y2="3"></line>' +
  "</svg>";

export const TRASH_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<polyline points="3 6 5 6 21 6"></polyline>' +
  '<path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>' +
  '<path d="M10 11v6"></path><path d="M14 11v6"></path>' +
  '<path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path>' +
  "</svg>";

export const MAGIC_ICON =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor" stroke="none">' +
  '<path d="M12 2l1.8 5.2L19 9l-5.2 1.8L12 16l-1.8-5.2L5 9l5.2-1.8L12 2z"></path>' +
  '<path d="M19 13l.9 2.1L22 16l-2.1.9L19 19l-.9-2.1L16 16l2.1-.9L19 13z"></path>' +
  "</svg>";

export const PLUS_ICON =
  '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<line x1="12" y1="5" x2="12" y2="19"></line>' +
  '<line x1="5" y1="12" x2="19" y2="12"></line>' +
  "</svg>";

export const REMOVE_ICON =
  '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<line x1="5" y1="12" x2="19" y2="12"></line>' +
  "</svg>";

export const UNDO_DURATION_MS = 30000;

export function wrapSelection(textarea, marker) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const before = textarea.value.slice(0, start);
  const selected = textarea.value.slice(start, end) || t('import.markupPlaceholder');
  const after = textarea.value.slice(end);
  textarea.value = `${before}${marker}${selected}${marker}${after}`;
  textarea.focus();
  textarea.selectionStart = start + marker.length;
  textarea.selectionEnd = start + marker.length + selected.length;
}

export function insertHeading(textarea) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const before = textarea.value.slice(0, start);
  const selected = textarea.value.slice(start, end) || t('import.markupPlaceholder');
  const after = textarea.value.slice(end);
  const lineStart = before.lastIndexOf('\n') + 1;
  textarea.value = `${before.slice(0, lineStart)}## ${before.slice(lineStart)}${selected}${after}`;
  textarea.focus();
}

export function buildMarkupToolbar(textarea) {
  const toolbar = document.createElement('div');
  toolbar.className = 'markup-toolbar';

  const buttons = [
    { text: 'B', className: 'markup-bold', titleKey: 'import.markupBold', action: () => wrapSelection(textarea, '**') },
    { text: 'I', className: 'markup-italic', titleKey: 'import.markupItalic', action: () => wrapSelection(textarea, '*') },
    { text: 'H', className: 'markup-heading', titleKey: 'import.markupHeading', action: () => insertHeading(textarea) },
  ];

  buttons.forEach((cfg) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `markup-button ${cfg.className}`;
    btn.textContent = cfg.text;
    btn.title = t(cfg.titleKey);
    btn.addEventListener('click', cfg.action);
    toolbar.appendChild(btn);
  });

  return toolbar;
}

// Backlog (2026-08-02): der Erreichbarkeits-Status kommt jetzt fertig
// berechnet aus GET /api/sources mit (url_reachable/url_reason_code/
// url_status_code, siehe app/main.py: wöchentlicher Hintergrund-Check),
// statt live pro Seitenaufruf per Fan-out über alle Quellen geprüft zu
// werden (vorheriges unreachableSourceInfo/checkUrlHealth, siehe
// Git-Historie) - urlErrorText liest deshalb direkt vom Source-Objekt.
//
// Backlog #163: reason_code (app/monitoring.py) auf übersetzten,
// menschenlesbaren Text abbilden - bei "http_error" wird der konkrete
// Statuscode eingesetzt.
export function urlErrorText(source) {
  switch (source.url_reason_code) {
    case 'http_error':
      return t('common.urlErrorHttp', { code: source.url_status_code });
    case 'timeout':
      return t('common.urlErrorTimeout');
    case 'dns_error':
      return t('common.urlErrorDns');
    case 'ssl_error':
      return t('common.urlErrorSsl');
    case 'connection_error':
      return t('common.urlErrorConnection');
    default:
      return t('common.urlErrorUnknown');
  }
}

export function jsonHeaders() {
  // Die Identität kommt über das Session-Cookie mit - hier nur Content-Type
  // und Sprache (Name früher devUserHeaders, als noch X-Dev-User gesendet wurde).
  return {
    'Content-Type': 'application/json',
    'X-Lang': getLang(),
  };
}

export function normalizeAuthor(name) {
  return name.trim().split(/\s+/).join(' ').toLowerCase();
}

export function buildFieldLabelWithId(labelKey, id, value, type) {
  const label = document.createElement('label');
  label.textContent = t(labelKey);
  const input = document.createElement(type === 'textarea' ? 'textarea' : 'input');
  if (type !== 'textarea') input.type = type;
  else input.rows = 10;
  input.id = id;
  input.value = value || '';
  label.appendChild(input);
  return { label, input };
}

// Aufklappbarer Bereich unterhalb eines Autor:innen-Feldes, der nur bei
// einer noch nicht erfassten Person sichtbar wird (siehe attachNewAuthorToggle
// weiter unten) - dieselben Felder wie im bestehenden Autor:innen-Profil
// (buildAuthorEditPanel). Die Person ist noch nicht als Autor:in registriert,
// es gibt also keine gespeicherten Quellen, aus denen sich per bestehendem
// /generate-bio-Endpunkt eine Vita generieren ließe - der KI-Vita-Button
// nutzt deshalb /api/authors/generate-bio-preview mit dem gerade im Formular
// stehenden Titel/Text der aktuellen Quelle als Grundlage (nameInput/
// getSourceText werden von attachNewAuthorToggle übergeben).
export function buildNewAuthorProfilePanel(nameInput, getSourceText) {
  const details = document.createElement('details');
  details.className = 'new-author-profile hidden';

  const summary = document.createElement('summary');
  summary.textContent = t('import.newAuthorProfileToggle');
  details.appendChild(summary);

  const body = document.createElement('div');
  body.className = 'new-author-profile-body';
  details.appendChild(body);

  function fieldRow(labelKey, type) {
    const label = document.createElement('label');
    const span = document.createElement('span');
    span.textContent = t(labelKey);
    label.appendChild(span);
    const input = document.createElement(type === 'textarea' ? 'textarea' : 'input');
    if (type === 'textarea') input.rows = 3;
    else input.type = type;
    label.appendChild(input);
    body.appendChild(label);
    return input;
  }

  const photoUrlInput = fieldRow('import.fieldPhotoUrl', 'url');
  const photoFieldRow = document.createElement('div');
  photoFieldRow.className = 'photo-field-row';
  photoUrlInput.parentNode.insertBefore(photoFieldRow, photoUrlInput);
  photoFieldRow.appendChild(photoUrlInput);
  const photoPreview = document.createElement('img');
  photoPreview.className = 'author-photo-preview';
  // Anders als beim Bearbeiten-Panel eines bestehenden Profils ist der Name
  // hier noch nicht final (wird gerade erst getippt) - deshalb ein
  // generisches Alt statt a.name.
  photoPreview.alt = t('import.newAuthorPhotoPreviewAlt');
  photoPreview.hidden = true;
  photoPreview.addEventListener('error', () => {
    photoPreview.hidden = true;
  });
  photoUrlInput.addEventListener('input', () => {
    const value = photoUrlInput.value.trim();
    photoPreview.hidden = !value;
    if (value) photoPreview.src = value;
  });
  photoFieldRow.appendChild(photoPreview);

  const websiteInput = fieldRow('import.fieldWebsite', 'url');

  const socialLabel = document.createElement('label');
  socialLabel.textContent = t('import.fieldSocialLinks');
  const { wrapper: socialWrapper, getSocialLinkValues } = buildSocialLinksField([]);
  socialLabel.appendChild(socialWrapper);
  body.appendChild(socialLabel);

  const bioInput = fieldRow('import.fieldBio', 'textarea');
  const bioStatus = document.createElement('p');
  bioStatus.className = 'edit-status';
  body.appendChild(bioStatus);
  const bioMagicButtons = [];
  const triggerGenerateBioPreview = () =>
    generateAuthorBioPreview(nameInput.value.trim(), getSourceText(), bioInput, bioStatus, bioMagicButtons);
  bioMagicButtons.push(addMagicButton(bioInput, triggerGenerateBioPreview, 'import.generateBioTitle'));

  function getProfileValues() {
    return {
      photo_url: photoUrlInput.value.trim(),
      website: websiteInput.value.trim(),
      social_links: getSocialLinkValues(),
      bio: bioInput.value.trim(),
    };
  }

  function hasAnyValue() {
    const v = getProfileValues();
    return !!(v.photo_url || v.website || v.social_links.length || v.bio);
  }

  return { details, getProfileValues, hasAnyValue };
}

// Wird sowohl im Bearbeiten- als auch im Neu-anlegen-Formular verwendet
// (siehe unten im Skript), damit Autor(en)/Datum an genau einer Stelle
// gepflegt werden und in beiden Masken automatisch gleich aussehen.
// Eine Quelle kann mehrere Autor:innen haben - das erste Feld steht mit dem
// Datum in einer Zeile, über das "+"-Icon lassen sich beliebig viele weitere
// Autoren-Zeilen darunter ergänzen (jede mit eigenem "+"), ab der zweiten
// Zeile zusätzlich mit einem "-"-Icon zum Entfernen.
//
// enableNewAuthorProfile: zeigt unter einer noch nicht erfassten Person
// "Autorenprofil pflegen" an (Backlog #86) - sowohl im Neu-anlegen- als auch
// im Bearbeiten-Formular (siehe renderCreateAuthorDateRow bzw. der Aufruf in
// buildEditPanel). Beide Formulare speichern die Profildaten nach dem
// erfolgreichen POST/PUT der Quelle direkt per PUT /api/authors/{name} -
// funktioniert in beiden Fällen, weil sowohl add_source als auch
// update_source neu hinzugefügte Autor:innen bereits synchron registrieren.
export function buildAuthorFields(
  authorId,
  authorValues,
  dateId,
  dateValue,
  enableNewAuthorProfile = false,
  getSourceText = () => ''
) {
  const values = authorValues && authorValues.length ? authorValues : [''];
  const profileEntries = [];

  function attachNewAuthorToggle(input, container) {
    if (!enableNewAuthorProfile) return;
    const { details, getProfileValues, hasAnyValue } = buildNewAuthorProfilePanel(input, getSourceText);
    container.appendChild(details);
    profileEntries.push({ input, getProfileValues, hasAnyValue });

    function refreshVisibility() {
      const name = input.value.trim();
      const isKnownOrEmpty = !name || allAuthors.some((a) => normalizeAuthor(a.name) === normalizeAuthor(name));
      details.classList.toggle('hidden', isKnownOrEmpty);
      if (isKnownOrEmpty) details.open = false;
    }
    input.addEventListener('input', refreshVisibility);
    refreshVisibility();
  }

  function buildAuthorInput(value) {
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'author-input';
    input.setAttribute('list', 'author-suggestions');
    input.setAttribute('autocomplete', 'off');
    input.value = value || '';
    return input;
  }

  function buildAddButton(insertNewRow) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-button add-author-btn';
    btn.innerHTML = PLUS_ICON;
    const label = t('import.addAuthor');
    btn.title = label;
    btn.setAttribute('aria-label', label);
    // Nutzerwunsch (2026-08-03): nach Klick auf "+" soll der Cursor direkt
    // im neuen Eingabefeld stehen, damit der Name ohne zusätzlichen Klick
    // eingetippt werden kann.
    btn.addEventListener('click', () => {
      const newRow = buildExtraRow('');
      insertNewRow(newRow);
      newRow.querySelector('.author-input')?.focus();
    });
    return btn;
  }

  function buildRemoveButton(group) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-button remove-author-btn';
    btn.innerHTML = REMOVE_ICON;
    const label = t('import.removeAuthor');
    btn.title = label;
    btn.setAttribute('aria-label', label);
    btn.addEventListener('click', () => group.remove());
    return btn;
  }

  function buildExtraRow(value) {
    // "group" hält Eingabezeile UND das dazugehörige "Autorenprofil
    // pflegen"-Panel zusammen, damit beide gemeinsam per "-" entfernt bzw.
    // per "+" als Einheit nach diesem Eintrag eingefügt werden.
    const group = document.createElement('div');
    group.className = 'author-extra-row-group';

    const row = document.createElement('div');
    row.className = 'author-extra-row';
    const input = buildAuthorInput(value);
    row.appendChild(input);
    row.appendChild(buildAddButton((newGroup) => group.insertAdjacentElement('afterend', newGroup)));
    row.appendChild(buildRemoveButton(group));
    group.appendChild(row);

    attachNewAuthorToggle(input, group);
    return group;
  }

  const extraRowsContainer = document.createElement('div');
  extraRowsContainer.className = 'author-extra-rows';
  values.slice(1).forEach((value) => {
    extraRowsContainer.appendChild(buildExtraRow(value));
  });

  const firstInput = buildAuthorInput(values[0]);
  firstInput.id = authorId;
  const authorInputGroup = document.createElement('span');
  authorInputGroup.className = 'author-input-group';
  authorInputGroup.appendChild(firstInput);
  authorInputGroup.appendChild(buildAddButton((newRow) => extraRowsContainer.prepend(newRow)));

  const authorLabel = document.createElement('label');
  authorLabel.textContent = t('import.fieldAuthor');
  authorLabel.appendChild(authorInputGroup);

  const dateField = buildFieldLabelWithId('import.fieldDate', dateId, dateValue, 'date');

  const row = document.createElement('div');
  row.className = 'field-row';
  row.appendChild(authorLabel);
  row.appendChild(dateField.label);

  const wrapper = document.createElement('div');
  wrapper.className = 'author-fields';
  wrapper.appendChild(row);
  attachNewAuthorToggle(firstInput, wrapper);
  wrapper.appendChild(extraRowsContainer);

  function getAuthorValues() {
    return [...wrapper.querySelectorAll('.author-input')]
      .map((input) => input.value.trim())
      .filter((value) => value);
  }

  // Liefert Profildaten NUR für Namen, die (a) noch nicht in allAuthors
  // erfasst sind UND (b) tatsächlich ausgefüllt wurden - ein leer
  // gelassenes, nur aufgeklapptes Panel erzeugt keinen Eintrag.
  function getNewAuthorProfiles() {
    const result = {};
    profileEntries.forEach(({ input, getProfileValues, hasAnyValue }) => {
      const name = input.value.trim();
      if (!name || !hasAnyValue()) return;
      const isKnown = allAuthors.some((a) => normalizeAuthor(a.name) === normalizeAuthor(name));
      if (isKnown) return;
      result[name] = getProfileValues();
    });
    return result;
  }

  return { wrapper, dateInput: dateField.input, getAuthorValues, getNewAuthorProfiles };
}

export function buildEditPanel(s, options = {}) {
  const pendingDeletion = !!options.pendingDeletion;
  // Fix (2026-09-22, gemeldeter Bug): im Autor:innen-Modus bekommt eine
  // Quelle mit mehreren Autor:innen pro Autor:in einen eigenen Zeilen-
  // Eintrag (siehe sortSources) - dieselbe Quelle kann also gleichzeitig
  // ZWEI offene Bearbeiten-Panels haben (activeEditId prüft nur s.id, nicht
  // die Zeile). Die Feld-IDs unten hingen bisher NUR an s.id, dadurch trugen
  // beide Panels identische HTML-IDs (ungültiges HTML) - ein Klick auf ein
  // <label> im ZWEITEN Panel fokussierte durch die id-Kollision das Feld im
  // ERSTEN. rowIndex (bereits für die Alphabet-Leiste eindeutig, siehe
  // Backlog #65/data-rowIndex) macht die ID pro Zeile statt pro Quelle
  // eindeutig. Betrifft nur die Bearbeiten-Ansicht - das Speichern selbst
  // las die Werte schon immer über die Feld-Referenzen, nie über die ID.
  const domIdKey = options.rowIndex === undefined ? s.id : `${s.id}-r${options.rowIndex}`;

  const li = document.createElement('li');
  li.className = 'source-edit-panel';
  if (pendingDeletion) {
    li.classList.add('source-edit-panel--pending-deletion');
  }

  const form = document.createElement('form');
  const status = document.createElement('p');
  status.className = 'edit-status';

  function buildFieldLabel(labelKey, idSuffix, value, type) {
    const label = document.createElement('label');
    label.textContent = t(labelKey);
    const input = document.createElement(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') input.type = type;
    else input.rows = 10;
    input.id = `edit-${idSuffix}-${domIdKey}`;
    input.value = value || '';
    label.appendChild(input);
    // Explizit setzen statt auf die implizite "erstes labelfähiges Kind"-Regel
    // zu vertrauen - sonst wird ein später in dieses Label eingefügter Button
    // (z.B. das Öffnen-Icon vor dem URL-Feld) zum Klick-Ziel des gesamten
    // Labels, und ein Klick irgendwo in der Zeile löst den Button aus statt
    // nur einen Klick direkt auf das Icon.
    label.htmlFor = input.id;
    return { label, input };
  }

  function field(labelKey, idSuffix, value, type) {
    const { label, input } = buildFieldLabel(labelKey, idSuffix, value, type);
    form.appendChild(label);
    return input;
  }

  const titleField = buildFieldLabel('import.fieldTitle', 'title', s.title, 'text');
  const titleInput = titleField.input;
  titleInput.required = true;

  // Backlog #51: Relevanz-Score (1-10) - nur für Quellen-Pfleger:innen/
  // System-Admins sichtbar (diese ganze Bearbeitungsansicht ist bereits auf
  // diese Rollen beschränkt) und bewusst auf Höhe des Titels platziert,
  // statt als eigene Zeile weiter unten - der Titel rückt dafür von voller
  // Breite auf 2/3 (Slider nimmt das übrige Drittel ein).
  const relevanceValue = s.relevance_score ?? 5;
  const relevanceRow = document.createElement('div');
  relevanceRow.className = 'title-relevance-row';
  const relevanceField = document.createElement('div');
  relevanceField.className = 'relevance-slider-field';
  const relevanceLabelRow = document.createElement('div');
  relevanceLabelRow.className = 'relevance-slider-label-row';
  const relevanceLabel = document.createElement('span');
  relevanceLabel.textContent = t('import.fieldRelevanceScore');
  const relevanceValueDisplay = document.createElement('span');
  relevanceValueDisplay.className = 'relevance-slider-value';
  relevanceValueDisplay.textContent = String(relevanceValue);
  relevanceLabelRow.append(relevanceLabel, relevanceValueDisplay);
  const relevanceInput = document.createElement('input');
  relevanceInput.type = 'range';
  relevanceInput.min = '1';
  relevanceInput.max = '10';
  relevanceInput.step = '1';
  relevanceInput.value = String(relevanceValue);
  relevanceInput.className = 'relevance-slider';
  relevanceInput.id = `edit-relevance-${domIdKey}`;
  const relevanceTitle = t('import.fieldRelevanceScore');
  relevanceInput.title = relevanceTitle;
  relevanceInput.setAttribute('aria-label', relevanceTitle);
  relevanceInput.addEventListener('input', () => {
    relevanceValueDisplay.textContent = relevanceInput.value;
  });
  relevanceField.append(relevanceLabelRow, relevanceInput);
  relevanceRow.append(titleField.label, relevanceField);
  form.appendChild(relevanceRow);

  // Lazy statt direkt gebunden: titleInput/textInput existieren an dieser
  // Stelle noch nicht (werden erst weiter unten deklariert) - der Getter wird
  // aber erst beim Klick auf den KI-Vita-Button ausgewertet, zu diesem
  // Zeitpunkt sind beide Variablen bereits zugewiesen.
  const getSourceText = () => `${titleInput.value}: ${textInput.value}`;
  const {
    wrapper: authorFieldsWrapper,
    dateInput,
    getAuthorValues,
    getNewAuthorProfiles,
  } = buildAuthorFields(
    `edit-author-${domIdKey}`,
    s.authors,
    `edit-date-${domIdKey}`,
    s.date,
    true,
    getSourceText
  );
  form.appendChild(authorFieldsWrapper);

  const urlField = buildFieldLabel('import.fieldUrl', 'url', s.url, 'url');
  const urlInput = urlField.input;
  const openUrlBtn = document.createElement('button');
  openUrlBtn.type = 'button';
  openUrlBtn.className = 'icon-button label-inline-icon';
  const openUrlLabel = t('common.openSource');
  openUrlBtn.title = openUrlLabel;
  openUrlBtn.setAttribute('aria-label', openUrlLabel);
  openUrlBtn.innerHTML = EXTERNAL_LINK_ICON;
  openUrlBtn.addEventListener('click', () => {
    const value = urlInput.value.trim();
    if (value) window.open(value, '_blank', 'noopener,noreferrer');
  });
  urlField.label.insertBefore(openUrlBtn, urlInput);
  form.appendChild(urlField.label);

  // Backlog #163: konkreter Fehlergrund als Statuszeile direkt im
  // Bearbeiten-Panel - im Gegensatz zum Tooltip auf dem Warn-Icon (nur
  // Hover, auf Mobile kaum nutzbar) hier immer sichtbar, genau dort, wo
  // der Link auch repariert wird.
  if (s.url_reachable === false) {
    const healthStatus = document.createElement('p');
    healthStatus.className = 'url-health-status';
    healthStatus.textContent = `${t('common.urlUnreachable')}: ${urlErrorText(s)}`;
    form.appendChild(healthStatus);

    // Nutzerwunsch (2026-09-01): der automatische Link-Check meldet
    // gelegentlich einen Link fälschlich als nicht erreichbar (z.B. blockt
    // eine Website automatisierte Anfragen von Server-IPs, funktioniert im
    // echten Browser aber einwandfrei). Statt den Warnhinweis bis zum
    // nächsten automatischen Lauf (bis zu einer Woche) stehen zu lassen,
    // kann eine Pflegerin/ein Pfleger den Link nach eigener manueller
    // Prüfung selbst als in Ordnung markieren - siehe verifySourceLink.
    const verifyBtn = document.createElement('button');
    verifyBtn.type = 'button';
    verifyBtn.className = 'verify-link-button';
    verifyBtn.textContent = t('import.markLinkVerified');
    verifyBtn.title = t('import.markLinkVerifiedTitle');
    verifyBtn.setAttribute('aria-label', t('import.markLinkVerifiedTitle'));
    verifyBtn.addEventListener('click', () => verifySourceLink(s.id, healthStatus, verifyBtn, options.onLinkVerified));
    form.appendChild(verifyBtn);
  }

  const listenUrlField = buildFieldLabel('import.fieldListenUrl', 'listen-url', s.listen_url, 'url');
  const listenUrlInput = listenUrlField.input;
  // Nutzerwunsch (2026-08-03): das Feld existiert im Datenmodell schon
  // lange fuer Audio-Quellen (Verweis auf die Podcast-/Anhoer-Seite) - PDFs
  // profitieren genauso davon (Verweis auf die Seite, auf der das PDF
  // abgerufen werden kann), nur der Audio-Player darunter bleibt
  // audio-spezifisch.
  if (s.has_audio || s.has_pdf) {
    form.appendChild(listenUrlField.label);
  }
  if (s.has_audio) {
    const audioPreviewLabel = document.createElement('label');
    const audioPreviewText = document.createElement('span');
    audioPreviewText.textContent = t('import.audioPreviewLabel');
    const audioPlayer = document.createElement('audio');
    audioPlayer.controls = true;
    audioPlayer.className = 'audio-preview-player';
    audioPlayer.src = `/api/sources/${s.id}/audio`;
    audioPreviewLabel.appendChild(audioPreviewText);
    audioPreviewLabel.appendChild(audioPlayer);
    form.appendChild(audioPreviewLabel);
  }

  const textInput = field('import.fieldText', 'text', s.text, 'textarea');
  if (s.restricted) {
    textInput.placeholder = t('import.restrictedTextPlaceholder');
  } else {
    textInput.required = true;
  }

  const toolbarRow = document.createElement('div');
  toolbarRow.className = 'markup-toolbar-row';
  toolbarRow.appendChild(buildMarkupToolbar(textInput));

  if (s.has_pdf) {
    const pdfBtn = document.createElement('button');
    pdfBtn.type = 'button';
    pdfBtn.className = 'link-button';
    pdfBtn.textContent = t('import.openPdf');
    pdfBtn.addEventListener('click', async () => {
      // Fenster MUSS synchron innerhalb des Klick-Handlers geöffnet werden -
      // ruft man window.open() erst nach einem await (fetch/blob), fehlt der
      // Bezug zur User-Geste und der Browser blockiert das Popup lautlos.
      const pdfWindow = window.open('', '_blank');
      try {
        const res = await fetch(`/api/sources/${s.id}/pdf`, { headers: jsonHeaders() });
        if (!res.ok) throw new Error(t('import.openPdfFailed'));
        const blob = await res.blob();
        if (pdfWindow) {
          pdfWindow.location = URL.createObjectURL(blob);
        } else {
          window.open(URL.createObjectURL(blob), '_blank');
        }
      } catch (err) {
        if (pdfWindow) pdfWindow.close();
        status.textContent = t('common.errorPrefix') + err.message;
      }
    });
    toolbarRow.appendChild(pdfBtn);
  }

  textInput.parentNode.insertBefore(toolbarRow, textInput);

  const restrictedLabel = document.createElement('label');
  restrictedLabel.className = 'checkbox-label';
  const restrictedInput = document.createElement('input');
  restrictedInput.type = 'checkbox';
  restrictedInput.checked = !!s.restricted;
  const restrictedText = document.createElement('span');
  restrictedText.textContent = t('import.restrictedLabel');
  restrictedLabel.appendChild(restrictedInput);
  restrictedLabel.appendChild(restrictedText);
  form.appendChild(restrictedLabel);

  const summaryInput = field('import.fieldSummary', 'summary', s.summary, 'textarea');
  summaryInput.rows = 4;
  const keyTermsInput = field(
    'import.fieldKeyTerms',
    'key-terms',
    (s.key_terms || []).join(', '),
    'text'
  );

  if (!pendingDeletion) {
    const magicButtons = [];
    const triggerGenerate = () =>
      generateSummaryFields(s.id, summaryInput, keyTermsInput, status, magicButtons);
    magicButtons.push(addMagicButton(summaryInput, triggerGenerate));
    // Eigener Button statt triggerGenerate: leitet Begriffe NUR aus dem
    // aktuell im Feld darüber stehenden (ggf. von Hand überarbeiteten)
    // Zusammenfassungstext ab und überschreibt sie unconditional - anders
    // als triggerGenerate (regeneriert beide Felder aus dem rohen
    // Quellentext, füllt aber nur leere Felder) hält das die Begriffsliste
    // gezielt mit einer manuellen Textüberarbeitung synchron.
    const triggerExtractKeyTerms = () =>
      extractKeyTermsFromSummary(summaryInput, keyTermsInput, status, magicButtons);
    magicButtons.push(
      addMagicButton(keyTermsInput, triggerExtractKeyTerms, 'import.generateKeyTermsFromSummaryTitle')
    );
    keyTermsInput.insertAdjacentElement('afterend', attachTagSuggestions(keyTermsInput));
  }

  if (pendingDeletion) {
    [
      titleInput,
      ...authorFieldsWrapper.querySelectorAll('.author-input'),
      dateInput,
      urlInput,
      listenUrlInput,
      textInput,
      restrictedInput,
      summaryInput,
      keyTermsInput,
      relevanceInput,
    ].forEach((input) => {
      input.disabled = true;
    });
  }

  const actionsRow = document.createElement('div');
  actionsRow.className = 'edit-panel-actions';

  let submitBtn = null;

  if (pendingDeletion) {
    const noticeRow = document.createElement('div');
    noticeRow.className = 'source-row-top';

    const noticeText = document.createElement('span');
    noticeText.textContent = t('common.deletingStatus', { title: s.title });
    noticeRow.appendChild(noticeText);

    const undoBtn = document.createElement('button');
    undoBtn.type = 'button';
    undoBtn.className = 'link-button';
    undoBtn.textContent = t('common.undo');
    undoBtn.addEventListener('click', () => options.onUndoDelete?.(s.id));
    noticeRow.appendChild(undoBtn);

    form.appendChild(noticeRow);

    const bar = document.createElement('div');
    bar.className = 'undo-bar';
    const fill = document.createElement('div');
    fill.className = 'undo-bar-fill';
    bar.appendChild(fill);
    form.appendChild(bar);

    requestAnimationFrame(() => {
      fill.style.transitionDuration = `${UNDO_DURATION_MS}ms`;
      fill.style.width = '0%';
    });
  } else {
    const primaryActions = document.createElement('div');

    submitBtn = document.createElement('button');
    submitBtn.type = 'submit';
    submitBtn.textContent = t('import.updateButton');
    primaryActions.appendChild(submitBtn);

    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'link-button';
    cancelBtn.textContent = t('common.cancel');
    cancelBtn.addEventListener('click', () => options.onCancel?.());
    primaryActions.appendChild(cancelBtn);

    actionsRow.appendChild(primaryActions);

    // Löschen nur dort, wo es eine Rückgängig-Zeile gibt (Quellenliste) -
    // die Konversation übergibt kein onDelete.
    if (options.onDelete) {
      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
      deleteBtn.className = 'icon-button delete-button';
      const deleteLabel = t('common.deleteSource');
      deleteBtn.title = deleteLabel;
      deleteBtn.setAttribute('aria-label', deleteLabel);
      deleteBtn.innerHTML = TRASH_ICON;
      deleteBtn.addEventListener('click', () => options.onDelete(s));
      actionsRow.appendChild(deleteBtn);
    }
  }

  form.appendChild(actionsRow);
  form.appendChild(status);

  if (!pendingDeletion) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      submitBtn.disabled = true;
      submitBtn.textContent = t('import.updating');
      status.textContent = '';
      try {
        const res = await fetch(`/api/sources/${s.id}`, {
          method: 'PUT',
          headers: jsonHeaders(),
          body: JSON.stringify({
            title: titleInput.value,
            authors: getAuthorValues(),
            date: dateInput.value || null,
            url: urlInput.value || null,
            listen_url: listenUrlInput.value || null,
            text: textInput.value,
            restricted: restrictedInput.checked,
            summary: summaryInput.value,
            key_terms: keyTermsInput.value
              .split(',')
              .map((term) => term.trim())
              .filter((term) => term),
            relevance_score: parseInt(relevanceInput.value, 10),
          }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || t('import.updateFailed'));
        }
        const updatedSource = await res.json();
        // update_source registriert neu hinzugefügte Autor:innen synchron
        // (authors.register_author), daher kann das Profil direkt im
        // Anschluss per PUT gespeichert werden - identisch zum Anlegen-Formular.
        const newAuthorProfiles = getNewAuthorProfiles();
        for (const [name, profile] of Object.entries(newAuthorProfiles)) {
          await fetch(`/api/authors/${encodeURIComponent(name)}`, {
            method: 'PUT',
            headers: jsonHeaders(),
            body: JSON.stringify(profile),
          }).catch(() => {});
        }
        options.onSaved?.(updatedSource);
      } catch (err) {
        status.textContent = t('common.errorPrefix') + err.message;
        submitBtn.disabled = false;
        submitBtn.textContent = t('import.updateButton');
      }
    });
  }

  li.appendChild(form);
  return li;
}

// Nutzerwunsch (2026-09-22): Schlagworte werden sonst frei getippt - mit der
// Zeit laufen Schreibweisen für dasselbe Thema auseinander ("Agilität" vs.
// "agile"), was das Netzwerk-Diagramm zerreißt (das gruppiert exakt nach
// String, siehe app/terms.py). Schlägt beim Tippen des gerade bearbeiteten,
// noch nicht durch Komma abgeschlossenen Tags passende, bereits im Bestand
// vorhandene Schlagworte vor. ponytail: bleibt bewusst EIN kommagetrenntes
// Textfeld (kein Chip-Widget wie beim Autoren-Feld) - nur das aktuell
// bearbeitete Segment wird ersetzt, add when: Nutzer will echte Chips.
let knownTermsCache = null;

export async function getKnownTerms() {
  if (!knownTermsCache) {
    knownTermsCache = fetch('/api/terms')
      .then((res) => res.json())
      .catch(() => []);
  }
  return knownTermsCache;
}

// Nutzerwunsch (2026-09-22, Nachtrag): "aktuelles Segment" hing bisher fix
// am LETZTEN Komma - beim nachträglichen Ändern eines Begriffs MITTEN in
// der Liste tippte man also ins zweite Segment, die Vorschläge bezogen sich
// aber weiterhin (wirkungslos) aufs letzte. Bestimmt das Segment stattdessen
// über die Cursor-Position: alles zwischen dem Komma davor und dem Komma
// danach (oder Textanfang/-ende, falls keins da ist).
export function currentTagSegmentBounds(value, cursorPos) {
  const commaBefore = value.lastIndexOf(',', cursorPos - 1);
  const start = commaBefore === -1 ? 0 : commaBefore + 1;
  const commaAfterIndex = value.indexOf(',', cursorPos);
  const end = commaAfterIndex === -1 ? value.length : commaAfterIndex;
  return { start, end };
}

// Nutzerwunsch (2026-09-23): dasselbe Vorschlags-Widget wird jetzt auch im
// Ähnliche-Schlagworte-Panel für ein frei eintippbares Zielschlagwort
// gebraucht (siehe renderTermMergeGroup) - dort gibt es aber kein
// Komma-getrenntes Mehrfach-Feld, nur EIN Begriff, und die relevante
// Sprache ist die der jeweiligen Gruppe, nicht zwingend die aktuelle
// UI-Sprache. `multi: false` schaltet die Komma-Segment-Logik ab (der
// gesamte Feldinhalt ist die Anfrage, ein Vorschlag ersetzt ihn komplett,
// kein automatisches ", " danach), `lang` überschreibt getLang().
// Gibt die Vorschlagsliste zurück, statt sie selbst per insertAdjacentElement
// einzuhängen - das setzt voraus, dass input bereits einen Elternknoten hat,
// was beim Ähnliche-Schlagworte-Panel (renderTermMergeGroup) nicht zutrifft,
// wenn attachTagSuggestions VOR dem ersten Einfügen ins DOM aufgerufen wird.
// Aufrufer entscheiden selbst, wo die Liste im Baum landet (bei
// buildEditPanel weiterhin direkt hinter dem Feld, siehe dortigen Aufruf).
let tagSuggestionListCount = 0;

export function attachTagSuggestions(input, options = {}) {
  const multi = options.multi !== false;
  const lang = options.lang || getLang();
  const list = document.createElement('ul');
  list.className = 'tag-suggestions hidden';
  list.id = `tag-suggestions-${++tagSuggestionListCount}`;
  list.setAttribute('role', 'listbox');
  input.setAttribute('aria-controls', list.id);
  input.setAttribute('aria-autocomplete', 'list');
  // Nutzerwunsch (2026-09-23): Pfeiltasten wählen einen Vorschlag, Enter
  // übernimmt ihn - -1 = keiner markiert, Enter gehört dann dem Feld selbst.
  let activeIndex = -1;
  let current = null; // { matches, start, end } der gerade angezeigten Liste

  function setActive(index) {
    activeIndex = index;
    [...list.children].forEach((li, i) => {
      li.classList.toggle('active', i === index);
      li.setAttribute('aria-selected', String(i === index));
    });
    const activeLi = list.children[index];
    if (activeLi) {
      input.setAttribute('aria-activedescendant', activeLi.id);
      activeLi.scrollIntoView({ block: 'nearest' });
    } else {
      input.removeAttribute('aria-activedescendant');
    }
  }

  function close() {
    list.classList.add('hidden');
    list.innerHTML = '';
    current = null;
    setActive(-1);
  }

  function applySuggestion(term, start, end) {
    if (!multi) {
      input.value = term;
      close();
      input.focus();
      return;
    }
    const before = input.value.slice(0, start);
    const after = input.value.slice(end);
    const segment = start === 0 ? term : ` ${term}`;
    let newValue = before + segment + after;
    let cursorPos = (before + segment).length;
    // Nur beim LETZTEN Segment (nichts folgt mehr) automatisch ", " anhängen,
    // um direkt zum nächsten Tag weiterschreiben zu können - mitten in der
    // Liste bleibt der Rest unangetastet, Cursor landet einfach dahinter.
    if (end === input.value.length) {
      newValue += ', ';
      cursorPos = newValue.length;
    }
    input.value = newValue;
    input.setSelectionRange(cursorPos, cursorPos);
    close();
    input.focus();
  }

  input.addEventListener('input', async () => {
    let start = 0;
    let end = input.value.length;
    if (multi) {
      ({ start, end } = currentTagSegmentBounds(input.value, input.selectionStart));
    }
    const query = input.value.slice(start, end).trim();
    if (!query) {
      close();
      return;
    }
    const otherSegments = multi ? (input.value.slice(0, start) + input.value.slice(end)).split(',') : [];
    const alreadyUsed = new Set(otherSegments.map((s) => normalizeTerm(s)).filter(Boolean));
    const terms = await getKnownTerms();
    // Feld während des Ladens verlassen (Escape/Wegklicken) - Liste nicht
    // nachträglich öffnen, der blur-Handler hat sie bereits geschlossen.
    if (document.activeElement !== input) return;
    const matches = terms
      .filter(
        (te) =>
          (te.langs || []).includes(lang) &&
          normalizeTerm(te.term).includes(normalizeTerm(query)) &&
          !alreadyUsed.has(normalizeTerm(te.term))
      )
      .slice(0, 8);
    if (!matches.length) {
      close();
      return;
    }
    list.innerHTML = '';
    current = { matches, start, end };
    matches.forEach((te, i) => {
      const li = document.createElement('li');
      li.id = `${list.id}-${i}`;
      li.setAttribute('role', 'option');
      li.textContent = te.term;
      // mousedown statt click: feuert VOR dem blur-Handler unten, der die
      // Liste sonst schon geschlossen hätte, bevor der Klick ankommt.
      li.addEventListener('mousedown', (e) => {
        e.preventDefault();
        applySuggestion(te.term, start, end);
      });
      list.appendChild(li);
    });
    list.classList.remove('hidden');
    setActive(-1);
  });

  input.addEventListener('blur', close);
  // Wird vor den keydown-Handlern der Aufrufer registriert (Enter speichert
  // dort bzw. schickt das Formular ab, Escape bricht ab) - solange die Liste
  // offen ist, gehören Pfeile/Enter/Escape ihr, stopImmediatePropagation
  // hält sie von den Aufrufer-Handlern fern.
  input.addEventListener('keydown', (e) => {
    if (!current) return;
    const count = current.matches.length;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const step = e.key === 'ArrowDown' ? 1 : -1;
      setActive(activeIndex < 0 && step < 0 ? count - 1 : (activeIndex + step + count) % count);
    } else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault();
      e.stopImmediatePropagation();
      applySuggestion(current.matches[activeIndex].term, current.start, current.end);
    } else if (e.key === 'Escape') {
      // preventDefault: im Bearbeiten-Dialog der Konversation (<dialog>)
      // würde Escape sonst gleich den ganzen Dialog schließen.
      e.preventDefault();
      e.stopImmediatePropagation();
      close();
    }
  });
  return list;
}

export function addMagicButton(input, onClick, titleKey = 'import.generateSummaryTitle') {
  const wrapper = document.createElement('div');
  wrapper.className = 'field-with-magic';
  input.parentNode.insertBefore(wrapper, input);
  wrapper.appendChild(input);

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'magic-button';
  const title = t(titleKey);
  btn.title = title;
  btn.setAttribute('aria-label', title);
  btn.innerHTML = MAGIC_ICON;
  btn.addEventListener('click', onClick);
  wrapper.appendChild(btn);
  return btn;
}

export async function generateSummaryFields(sourceId, summaryInput, keyTermsInput, statusEl, buttons) {
  buttons.forEach((b) => {
    b.disabled = true;
  });
  statusEl.textContent = t('import.generatingSummary');
  try {
    const res = await fetch(`/api/sources/${sourceId}/generate-summary`, {
      method: 'POST',
      headers: jsonHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('import.generateSummaryFailed'));
    }
    const data = await res.json();
    if (!summaryInput.value.trim()) summaryInput.value = data.summary;
    if (!keyTermsInput.value.trim()) keyTermsInput.value = data.key_terms.join(', ');
    statusEl.textContent = '';
  } catch (err) {
    statusEl.textContent = t('common.errorPrefix') + err.message;
  } finally {
    buttons.forEach((b) => {
      b.disabled = false;
    });
  }
}

// Nutzerwunsch (2026-09-01): siehe Kommentar bei der Verwendung oben
// (url-health-status-Block). onVerified (Quellenliste: loadSources) lädt danach den kompletten
// Bestand neu (identisches Muster wie nach dem normalen Speichern-Klick,
// siehe Formular-submit-Handler oben) - activeEditId bleibt dabei bewusst
// unverändert, das gerade offene Bearbeiten-Panel bleibt also offen und
// zeigt direkt den jetzt wieder grünen Zustand.
export async function verifySourceLink(sourceId, statusEl, button, onVerified) {
  button.disabled = true;
  statusEl.textContent = t('import.verifyingLink');
  try {
    const res = await fetch(`/api/sources/${sourceId}/verify-link`, {
      method: 'POST',
      headers: jsonHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('import.verifyLinkFailed'));
    }
    statusEl.remove();
    button.remove();
    onVerified?.();
  } catch (err) {
    statusEl.textContent = t('common.errorPrefix') + err.message;
    button.disabled = false;
  }
}

// Anders als generateSummaryFields (regeneriert Zusammenfassung UND Begriffe
// aus dem rohen Quellentext, füllt aber nur leere Felder): leitet Begriffe
// gezielt aus dem AKTUELLEN Inhalt von summaryInput ab (auch wenn er gerade
// von Hand überarbeitet und noch nicht gespeichert wurde) und überschreibt
// keyTermsInput unconditional - das ist der ganze Zweck dieses eigenen
// Buttons, siehe buildEditPanel.
export async function extractKeyTermsFromSummary(summaryInput, keyTermsInput, statusEl, buttons) {
  buttons.forEach((b) => {
    b.disabled = true;
  });
  statusEl.textContent = t('import.generatingKeyTerms');
  try {
    const res = await fetch('/api/sources/generate-key-terms-preview', {
      method: 'POST',
      headers: jsonHeaders(),
      body: JSON.stringify({ text: summaryInput.value }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('import.generateKeyTermsFailed'));
    }
    const data = await res.json();
    keyTermsInput.value = data.key_terms.join(', ');
    statusEl.textContent = '';
  } catch (err) {
    statusEl.textContent = t('common.errorPrefix') + err.message;
  } finally {
    buttons.forEach((b) => {
      b.disabled = false;
    });
  }
}

export function normalizeTerm(term) {
  return term.trim().toLowerCase();
}

// Plattform anhand der URL automatisch erkennen (siehe urlInput-Handler in
// buildRow weiter unten), statt sie manuell auswählen/eintippen zu müssen -
// das frühere Auswahl-Dropdown (Datalist) wurde deshalb wieder entfernt.
// Mastodon ist föderiert (beliebige Instanz-Domains) - "mastodon" im
// Hostnamen ist nur eine Best-effort-Heuristik, keine vollständige Erkennung.
export const SOCIAL_PLATFORM_HOSTS = [
  { pattern: /(^|\.)linkedin\.com$/, platform: 'LinkedIn' },
  { pattern: /(^|\.)(twitter|x)\.com$/, platform: 'X (Twitter)' },
  { pattern: /(^|\.)instagram\.com$/, platform: 'Instagram' },
  { pattern: /(^|\.)(facebook|fb)\.com$/, platform: 'Facebook' },
  { pattern: /(^|\.)(youtube\.com|youtu\.be)$/, platform: 'YouTube' },
  { pattern: /mastodon/, platform: 'Mastodon' },
  { pattern: /(^|\.)bsky\.app$/, platform: 'Bluesky' },
  { pattern: /(^|\.)tiktok\.com$/, platform: 'TikTok' },
];

export function detectSocialPlatform(url) {
  let hostname;
  try {
    hostname = new URL(url).hostname.toLowerCase();
  } catch {
    return '';
  }
  const match = SOCIAL_PLATFORM_HOSTS.find(({ pattern }) => pattern.test(hostname));
  return match ? match.platform : '';
}

// Nutzerwunsch (2026-08-26): kein manuelles Plattform-Feld mehr im Social-
// Links-Formular (siehe buildRow unten) - die Plattform wird beim
// Speichern automatisch aus der URL ermittelt. Bekannte Plattformen (siehe
// SOCIAL_PLATFORM_HOSTS) liefern ihren Namen, alles andere fällt auf die
// reine Domain zurück (extractHostname, siehe photoCreditDomain weiter
// unten) - damit geht kein eingetragener Link verloren, nur weil seine
// Plattform nicht in der Liste bekannter Hosts steht. Nur bei einer
// ungültigen URL bleibt als letzter Ausweg die rohe Eingabe selbst.
export function resolveSocialPlatform(url) {
  return detectSocialPlatform(url) || extractHostname(url) || url;
}

export function buildSocialLinksField(initialLinks) {
  const wrapper = document.createElement('div');
  wrapper.className = 'social-links-field';

  const rows = document.createElement('div');
  rows.className = 'social-link-rows';
  wrapper.appendChild(rows);

  // Ohne Zeilen gibt es nichts zu entfernen - dann steht ein einzelner
  // "+"-Button für sich, um die erste Zeile anzulegen (analog zum
  // Mehrfach-Autoren-Feld bei Quellen, das dieselben Icons verwendet).
  const standaloneAddBtn = document.createElement('button');
  standaloneAddBtn.type = 'button';
  standaloneAddBtn.className = 'icon-button add-author-btn';
  standaloneAddBtn.innerHTML = PLUS_ICON;
  const addLabel = t('import.addSocialLink');
  standaloneAddBtn.title = addLabel;
  standaloneAddBtn.setAttribute('aria-label', addLabel);
  standaloneAddBtn.addEventListener('click', () => {
    const row = buildRow(null);
    rows.appendChild(row);
    // Nutzerwunsch (2026-08-27): Cursor-Fokus direkt in die neue URL-Zeile,
    // damit sofort losgetippt werden kann statt erst manuell hinklicken zu
    // müssen.
    row.querySelector('.social-url-input').focus();
  });
  wrapper.appendChild(standaloneAddBtn);

  function refreshStandaloneButton() {
    standaloneAddBtn.classList.toggle('hidden', rows.children.length > 0);
  }

  function buildAddButton(insertNewRow) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-button add-author-btn';
    btn.innerHTML = PLUS_ICON;
    btn.title = addLabel;
    btn.setAttribute('aria-label', addLabel);
    btn.addEventListener('click', () => {
      const row = buildRow(null);
      insertNewRow(row);
      // Nutzerwunsch (2026-08-27): siehe standaloneAddBtn oben - Fokus direkt
      // in die neu eingefügte URL-Zeile.
      row.querySelector('.social-url-input').focus();
    });
    return btn;
  }

  function buildRemoveButton(row) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-button remove-author-btn';
    btn.innerHTML = REMOVE_ICON;
    const removeLabel = t('import.removeSocialLink');
    btn.title = removeLabel;
    btn.setAttribute('aria-label', removeLabel);
    btn.addEventListener('click', () => {
      row.remove();
      refreshStandaloneButton();
    });
    return btn;
  }

  function buildRow(link) {
    const row = document.createElement('div');
    row.className = 'social-link-row';

    // Nutzerwunsch (2026-08-26): kein separates Plattform-Feld mehr - nur
    // noch die URL eintragen, die Plattform wird beim Speichern automatisch
    // ermittelt (siehe resolveSocialPlatform).
    const urlInput = document.createElement('input');
    urlInput.type = 'url';
    urlInput.className = 'social-url-input';
    urlInput.placeholder = t('import.socialUrlPlaceholder');
    urlInput.value = (link && link.url) || '';

    row.appendChild(urlInput);
    row.appendChild(buildAddButton((newRow) => row.insertAdjacentElement('afterend', newRow)));
    row.appendChild(buildRemoveButton(row));
    return row;
  }

  (initialLinks && initialLinks.length ? initialLinks : []).forEach((link) => {
    rows.appendChild(buildRow(link));
  });
  refreshStandaloneButton();

  function getSocialLinkValues() {
    return [...rows.querySelectorAll('.social-link-row')]
      .map((row) => {
        const url = row.querySelector('.social-url-input').value.trim();
        return { platform: resolveSocialPlatform(url), url };
      })
      .filter((link) => link.url);
  }

  return { wrapper, getSocialLinkValues };
}

// Für Co-Autor:innen, die gerade erst im Formular eingetragen wurden (siehe
// buildNewAuthorProfilePanel) - anders als generateAuthorBio gibt es noch
// keine registrierte Person mit indizierten Quellen, deshalb der eigene
// Endpunkt mit Name+aktuellem Quellentext statt Name-in-URL.
export async function generateAuthorBioPreview(name, text, bioInput, statusEl, buttons) {
  buttons.forEach((b) => {
    b.disabled = true;
  });
  statusEl.textContent = t('import.generatingBio');
  try {
    const res = await fetch('/api/authors/generate-bio-preview', {
      method: 'POST',
      headers: jsonHeaders(),
      body: JSON.stringify({ name, text }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('import.generateBioFailed'));
    }
    const data = await res.json();
    if (!bioInput.value.trim()) bioInput.value = data.bio;
    statusEl.textContent = '';
  } catch (err) {
    statusEl.textContent = t('common.errorPrefix') + err.message;
  } finally {
    buttons.forEach((b) => {
      b.disabled = false;
    });
  }
}

// Nutzerwunsch (2026-08-26): Domain einer URL ohne "www."-Präfix und ohne
// Pfad - gemeinsame Basis für photoCreditDomain (import.js) sowie für die
// automatische Social-Media-Plattform-Erkennung (siehe resolveSocialPlatform
// weiter oben bei detectSocialPlatform).
export function extractHostname(url) {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return null;
  }
}
