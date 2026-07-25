import { t, initI18n } from '/i18n.js';

let currentVersion = '';

function buildLink(href, text) {
  const a = document.createElement('a');
  a.href = href;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.textContent = text;
  return a;
}

function renderFooter() {
  const footer = document.getElementById('site-footer');
  if (!footer) return;

  const versionSpan = document.createElement('span');
  versionSpan.id = 'footer-version';
  versionSpan.className = 'footer-version';
  versionSpan.textContent = currentVersion;

  footer.replaceChildren(
    buildLink('https://betacodex.org', 'betacodex.org'),
    buildLink('https://github.com/Circleview/betahof_betacodex_companion', t('footer.github')),
    versionSpan,
    buildLink('https://betahof.de', 'Beta Hof'),
    buildLink('https://www.betahof.de/impressum/', t('footer.impressum')),
  );
}

export async function initFooter() {
  const footer = document.getElementById('site-footer');
  if (!footer) return;

  await initI18n();

  try {
    const res = await fetch('/api/version');
    const data = await res.json();
    currentVersion = data.version;
  } catch (err) {
    currentVersion = '';
  }

  renderFooter();
  document.addEventListener('i18n:changed', renderFooter);
}
