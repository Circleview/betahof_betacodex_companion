// Autor:innen der Quellenseite: Liste, Profil-Ansicht und -Bearbeitung.
// Aus import.js herausgezogen (Idee 313ad93d).
import { t, getLang } from '/i18n.js';
import {
  EXTERNAL_LINK_ICON,
  jsonHeaders,
  addMagicButton,
  buildSocialLinksField,
  extractHostname,
  setKnownAuthors,
} from '/source-edit.js';
import { applyAuthorFilter, filterByAuthor, prependAiIcon, showTooManyRequests } from '/import-list.js';
import { EDIT_ICON, hasPflegerRole, state } from '/import-state.js';

export let allAuthors = [];

export async function loadAuthors() {
  const res = await fetch('/api/authors', { headers: { 'X-Lang': getLang() } });
  if (res.status === 429) return showTooManyRequests();
  if (!res.ok) return;
  allAuthors = await res.json();
  setKnownAuthors(allAuthors);
  renderAuthorList();

  const datalist = document.getElementById('author-suggestions');
  datalist.innerHTML = '';
  allAuthors.forEach((a) => {
    const option = document.createElement('option');
    option.value = a.name;
    datalist.appendChild(option);
  });
}

function renderAuthorList() {
  const list = document.getElementById('author-list');
  list.replaceChildren(...allAuthors.map(buildAuthorListItem));
}

function buildAuthorLink(url, label) {
  const link = document.createElement('a');
  link.href = url;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.className = 'author-link';
  const icon = document.createElement('span');
  icon.className = 'author-link-icon';
  icon.innerHTML = EXTERNAL_LINK_ICON;
  link.appendChild(icon);
  link.append(label);
  return link;
}

function buildAuthorBioSection(a) {
  const container = document.createElement('div');
  container.className = 'author-bio-section';

  if (a.bio) {
    const bioP = document.createElement('p');
    bioP.className = 'author-bio-text';
    bioP.textContent = a.bio;
    container.appendChild(bioP);
    if (a.bio_ai_generated) prependAiIcon(container, 'import.aiBioTooltip');
  }

  const linksRow = document.createElement('div');
  linksRow.className = 'author-links-row';
  if (a.website) linksRow.appendChild(buildAuthorLink(a.website, t('import.fieldWebsite')));
  (a.social_links || []).forEach((link) => {
    if (link.url) linksRow.appendChild(buildAuthorLink(link.url, link.platform || link.url));
  });
  if (linksRow.children.length) container.appendChild(linksRow);

  if (!a.bio && !linksRow.children.length && !a.photo_url) {
    const emptyP = document.createElement('p');
    emptyP.className = 'author-bio-text author-bio-text--empty';
    emptyP.textContent = t('import.authorProfileEmpty');
    container.appendChild(emptyP);
  }

  return container;
}

async function generateAuthorBio(name, bioInput, statusEl, buttons) {
  buttons.forEach((b) => {
    b.disabled = true;
  });
  statusEl.textContent = t('import.generatingBio');
  try {
    const res = await fetch(`/api/authors/${encodeURIComponent(name)}/generate-bio`, {
      method: 'POST',
      headers: jsonHeaders(),
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

// Nutzerfeedback (2026-08-26): manche Foto-URLs liegen auf technisch
// korrekten, aber für Leser:innen kaum erkennbaren CDN-Subdomains großer
// Plattformen (z.B. media.licdn.com) - auf den bekannten Plattformnamen
// abbilden, analog zu SOCIAL_PLATFORM_HOSTS/detectSocialPlatform oben.
// Bewusst NICHT enthalten: gstatic.com (Google-Bilder-Thumbnail-Cache) -
// die eigentliche Quelle ist aus so einer URL nicht mehr rekonstruierbar,
// das wird stattdessen Zug um Zug direkt in den Autor:innen-Profilen durch
// echte Quellen-URLs ersetzt statt hier beschönigt.
const PHOTO_HOST_LABELS = [
  { pattern: /(^|\.)licdn\.com$/, label: 'LinkedIn' },
  { pattern: /(^|\.)rgstatic\.net$/, label: 'ResearchGate' },
  { pattern: /(^|\.)googleusercontent\.com$/, label: 'Google' },
  { pattern: /(^|\.)media-amazon\.com$/, label: 'Amazon' },
  { pattern: /(^|\.)gravatar\.com$/, label: 'Gravatar' },
  { pattern: /(^|\.)wp\.com$/, label: 'WordPress' },
];

// Nutzerwunsch (2026-08-26): kleiner, unauffälliger Bildquellennachweis
// unter dem Autor:innen-Foto (siehe buildAuthorInfoView) - nennt die Domain
// der ORIGINALEN externen Foto-URL (a.photo_url), nicht den vollen Pfad und
// nicht die eigene, ggf. lokal gecachte photo_large-URL (siehe app/
// author_photos.py). "www." wird entfernt, da es für die Quellennennung
// keinen Mehrwert hat; bekannte CDN-Domains werden auf ihren Plattformnamen
// abgebildet (siehe PHOTO_HOST_LABELS oben).
function photoCreditDomain(url) {
  const hostname = extractHostname(url);
  if (!hostname) return null;
  const match = PHOTO_HOST_LABELS.find(({ pattern }) => pattern.test(hostname));
  return match ? match.label : hostname;
}

function buildAuthorInfoView(a) {
  const wrapper = document.createElement('div');
  wrapper.className = 'author-info-view';

  const headerRow = document.createElement('div');
  headerRow.className = 'author-info-header-row';

  const heading = document.createElement('h4');
  heading.className = 'author-info-heading';
  heading.textContent = a.name;
  headerRow.appendChild(heading);

  const photoCol = document.createElement('div');
  photoCol.className = 'author-info-photo-col';

  const vitaPhotoUrl = a.photo_large || a.photo_url;
  if (vitaPhotoUrl) {
    const img = document.createElement('img');
    img.src = vitaPhotoUrl;
    img.alt = a.name;
    img.className = 'author-photo';
    photoCol.appendChild(img);

    const creditDomain = photoCreditDomain(a.photo_url);
    if (creditDomain) {
      const credit = document.createElement('p');
      credit.className = 'author-photo-credit';
      credit.textContent = t('import.photoCreditLabel', { domain: creditDomain });
      photoCol.appendChild(credit);
    }
  }

  headerRow.appendChild(photoCol);
  wrapper.appendChild(headerRow);
  wrapper.appendChild(buildAuthorBioSection(a));

  if (hasPflegerRole()) {
    const editRow = document.createElement('div');
    editRow.className = 'author-info-edit-row';
    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'icon-button author-info-edit-btn';
    const editLabel = t('common.editAuthor');
    editBtn.title = editLabel;
    editBtn.setAttribute('aria-label', editLabel);
    editBtn.innerHTML = EDIT_ICON;
    editBtn.addEventListener('click', () => {
      state.authorPanelEditMode = true;
      renderAuthorInfoPanel();
    });
    editRow.appendChild(editBtn);
    wrapper.appendChild(editRow);
  }

  return wrapper;
}

export function renderAuthorInfoPanel() {
  const panel = document.getElementById('author-info-panel');
  const body = document.getElementById('quellen-liste-body');
  if (!state.filteredAuthorEntry) {
    panel.replaceChildren();
    panel.classList.add('hidden');
    body.classList.remove('quellen-liste-body--author-filtered');
    return;
  }
  body.classList.add('quellen-liste-body--author-filtered');
  panel.classList.remove('hidden');
  panel.replaceChildren(
    state.authorPanelEditMode ? buildAuthorEditPanel(state.filteredAuthorEntry) : buildAuthorInfoView(state.filteredAuthorEntry)
  );
}

function buildAuthorEditPanel(a) {
  const wrapper = document.createElement('div');
  wrapper.className = 'author-edit-panel';

  const form = document.createElement('form');
  const status = document.createElement('p');
  status.className = 'edit-status';

  function field(labelKey, idSuffix, value, type) {
    const label = document.createElement('label');
    label.textContent = t(labelKey);
    const input = document.createElement(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') input.type = type;
    else input.rows = 4;
    input.id = `edit-author-${idSuffix}-${a.name}`;
    input.value = value || '';
    label.appendChild(input);
    label.htmlFor = input.id;
    form.appendChild(label);
    return input;
  }

  const nameInput = field('import.fieldAuthorName', 'name', a.name, 'text');

  const bioInput = field('import.fieldBio', 'bio', a.bio, 'textarea');
  const magicButtons = [];
  const triggerGenerateBio = () => generateAuthorBio(a.name, bioInput, status, magicButtons);
  magicButtons.push(addMagicButton(bioInput, triggerGenerateBio, 'import.generateBioTitle'));

  const photoUrlInput = field('import.fieldPhotoUrl', 'photo-url', a.photo_url, 'url');
  const photoFieldRow = document.createElement('div');
  photoFieldRow.className = 'photo-field-row';
  photoUrlInput.parentNode.insertBefore(photoFieldRow, photoUrlInput);
  photoFieldRow.appendChild(photoUrlInput);

  const photoPreview = document.createElement('img');
  photoPreview.className = 'author-photo-preview';
  photoPreview.alt = a.name;
  photoPreview.hidden = !a.photo_url;
  if (a.photo_url) photoPreview.src = a.photo_url;
  // Bild lädt/existiert nicht (z.B. während der Eingabe noch unvollständige
  // URL) - dann lieber gar nichts zeigen statt ein kaputtes Bild-Icon.
  photoPreview.addEventListener('error', () => {
    photoPreview.hidden = true;
  });
  photoUrlInput.addEventListener('input', () => {
    const value = photoUrlInput.value.trim();
    photoPreview.hidden = !value;
    if (value) photoPreview.src = value;
  });
  photoFieldRow.appendChild(photoPreview);

  const websiteInput = field('import.fieldWebsite', 'website', a.website, 'url');

  const socialLabel = document.createElement('label');
  socialLabel.textContent = t('import.fieldSocialLinks');
  const { wrapper: socialWrapper, getSocialLinkValues } = buildSocialLinksField(a.social_links);
  socialLabel.appendChild(socialWrapper);
  form.appendChild(socialLabel);

  const actionsRow = document.createElement('div');
  actionsRow.className = 'edit-panel-actions';

  const primaryActions = document.createElement('div');
  const submitBtn = document.createElement('button');
  submitBtn.type = 'submit';
  submitBtn.textContent = t('import.updateButton');
  primaryActions.appendChild(submitBtn);

  const cancelBtn = document.createElement('button');
  cancelBtn.type = 'button';
  cancelBtn.className = 'link-button';
  cancelBtn.textContent = t('common.cancel');
  cancelBtn.addEventListener('click', () => {
    state.authorPanelEditMode = false;
    renderAuthorInfoPanel();
  });
  primaryActions.appendChild(cancelBtn);
  actionsRow.appendChild(primaryActions);

  form.appendChild(actionsRow);
  form.appendChild(status);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    submitBtn.disabled = true;
    submitBtn.textContent = t('import.updating');
    status.textContent = '';
    try {
      let currentName = a.name;
      const newName = nameInput.value.trim();
      if (newName && newName !== currentName) {
        const renameRes = await fetch(`/api/authors/${encodeURIComponent(currentName)}/rename`, {
          method: 'POST',
          headers: jsonHeaders(),
          body: JSON.stringify({ new_name: newName }),
        });
        if (!renameRes.ok) {
          const err = await renameRes.json().catch(() => ({}));
          throw new Error(err.detail || t('import.renameFailed'));
        }
        currentName = newName;
      }

      const res = await fetch(`/api/authors/${encodeURIComponent(currentName)}`, {
        method: 'PUT',
        headers: jsonHeaders(),
        body: JSON.stringify({
          bio: bioInput.value,
          photo_url: photoUrlInput.value,
          website: websiteInput.value,
          social_links: getSocialLinkValues(),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || t('import.updateFailed'));
      }
      state.authorPanelEditMode = false;
      await applyAuthorFilter(currentName);
      await loadAuthors();
    } catch (err) {
      status.textContent = t('common.errorPrefix') + err.message;
      submitBtn.disabled = false;
      submitBtn.textContent = t('import.updateButton');
    }
  });

  wrapper.appendChild(form);
  return wrapper;
}

function buildAuthorListItem(a) {
  const li = document.createElement('li');
  const authorBtn = document.createElement('button');
  authorBtn.type = 'button';
  authorBtn.className = 'link-button';
  authorBtn.textContent = a.name;
  authorBtn.addEventListener('click', () => filterByAuthor(a.name));
  li.appendChild(authorBtn);
  const countKey = a.source_count === 1 ? 'common.sourceCountOne' : 'common.sourceCountMany';
  li.append(` (${t(countKey, { count: a.source_count })})`);
  return li;
}
