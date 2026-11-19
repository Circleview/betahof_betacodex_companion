import { t, getLang } from '/i18n.js';

// Nutzerwunsch (2026-11-19): Bilder einer Quelle von Hand zeigen/ausblenden.
// KI-Urteil `relevant` (null = ungeprüft, wird gezeigt); `manual` = von Hand
// gesetzt, die KI-Prüfung überschreibt das nie. Ohne Bilder: leerer Platzhalter.
export function isImageShown(image) {
  return image.relevant !== false;
}

export function buildImagePanel(sourceId) {
  const details = document.createElement('details');
  details.className = 'source-images-panel hidden';
  const summary = document.createElement('summary');
  details.appendChild(summary);
  const filters = document.createElement('div');
  filters.className = 'source-images-filter';
  filters.setAttribute('role', 'group');
  details.appendChild(filters);
  const grid = document.createElement('ul');
  grid.className = 'source-images-grid';
  details.appendChild(grid);
  const status = document.createElement('p');
  status.className = 'edit-status';
  status.setAttribute('aria-live', 'polite');
  details.appendChild(status);

  let images = [];
  let filter = 'all';
  details.addEventListener('toggle', () => images.length && render());

  function render() {
    const shown = images.filter(isImageShown).length;
    // Zugeklappt sichtbar (Nutzerwunsch 2026-11-19: "zu unscheinbar"):
    // Titel, Zähler, Vorschau der ersten Bilder (gezeigte zuerst) und Aufklapp-Hinweis.
    const title = document.createElement('span');
    title.className = 'source-images-title';
    title.textContent = t('import.imagesTitle');
    const count = document.createElement('span');
    count.className = 'source-images-count';
    count.textContent = t('import.imagesCount', { shown, hidden: images.length - shown });
    const thumbs = document.createElement('span');
    thumbs.className = 'source-images-thumbs';
    thumbs.setAttribute('aria-hidden', 'true');
    [...images.filter(isImageShown), ...images.filter((i) => !isImageShown(i))].slice(0, 6).forEach((img) => {
      const th = document.createElement('img');
      th.src = img.src;
      th.alt = '';
      th.loading = 'lazy';
      th.referrerPolicy = 'no-referrer';
      th.classList.toggle('source-images-thumb--hidden', !isImageShown(img));
      thumbs.appendChild(th);
    });
    const hint = document.createElement('span');
    hint.className = 'source-images-hint';
    hint.textContent = details.open ? t('import.imagesHintClose') : t('import.imagesHintOpen');
    summary.replaceChildren(title, count, thumbs, hint);
    filters.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.filter === filter)));
    grid.replaceChildren();
    images
      .filter((img) => filter === 'all' || (filter === 'shown') === isImageShown(img))
      .forEach((img) => grid.appendChild(buildTile(img)));
  }

  function buildTile(img) {
    const li = document.createElement('li');
    li.className = 'source-image-tile';
    li.classList.toggle('source-image-tile--hidden', !isImageShown(img));
    const pic = document.createElement('img');
    pic.src = img.src;
    pic.alt = img.alt;
    pic.loading = 'lazy';
    pic.referrerPolicy = 'no-referrer';
    li.appendChild(pic);
    const meta = document.createElement('p');
    meta.className = 'source-image-tile-meta';
    const state = isImageShown(img) ? t('import.imageShown') : t('import.imageHidden');
    meta.textContent = (img.page ? `${t('import.imagePage', { page: img.page })} · ` : '') + state;
    if (img.manual) {
      const hand = document.createElement('span');
      hand.className = 'source-image-manual';
      hand.textContent = ' ✋';
      hand.title = t('import.imageManualTitle');
      hand.setAttribute('aria-label', t('import.imageManualTitle'));
      meta.appendChild(hand);
    }
    li.appendChild(meta);
    if (img.alt) {
      const alt = document.createElement('p');
      alt.className = 'source-image-tile-alt';
      alt.textContent = img.alt;
      li.appendChild(alt);
    }
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'link-button';
    btn.textContent = isImageShown(img) ? t('import.imageHide') : t('import.imageShow');
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        const res = await fetch(`/api/sources/${sourceId}/images`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', 'X-Lang': getLang() },
          body: JSON.stringify({ key: img.key, relevant: !isImageShown(img) }),
        });
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
        const updated = await res.json();
        images = images.map((i) => (i.key === updated.key ? updated : i));
        status.textContent = '';
        render();
      } catch (err) {
        btn.disabled = false;
        status.textContent = t('common.errorPrefix') + err.message;
      }
    });
    li.appendChild(btn);
    return li;
  }

  ['all', 'shown', 'hidden'].forEach((key) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'source-images-filter-button';
    b.dataset.filter = key;
    b.textContent = t(`import.imagesFilter_${key}`);
    b.addEventListener('click', () => {
      filter = key;
      render();
    });
    filters.appendChild(b);
  });

  fetch(`/api/sources/${sourceId}/images`, { headers: { 'Content-Type': 'application/json', 'X-Lang': getLang() } })
    .then((res) => (res.ok ? res.json() : []))
    .then((data) => {
      images = Array.isArray(data) ? data : [];
      if (!images.length) return;
      details.classList.remove('hidden');
      render();
    })
    .catch(() => {});
  return details;
}
