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

function renderFooterLinks() {
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

// Der Hinweistext wandert nur dann in den Footer, wenn dort tatsächlich
// Platz ist (Footer bleibt einzeilig) - sonst bleibt er im Header stehen.
// Wird deshalb nach jedem Render neu vermessen statt per fester Breakpoint.
function fitTaglineIntoFooter() {
  const footer = document.getElementById('site-footer');
  const headerTagline = document.querySelector('.tagline');
  if (!footer || !headerTagline) return;

  headerTagline.style.display = '';
  const baseHeight = footer.offsetHeight;

  const taglineSpan = document.createElement('span');
  taglineSpan.className = 'footer-tagline';
  taglineSpan.textContent = t('index.tagline');
  footer.insertBefore(taglineSpan, footer.firstChild);

  if (footer.offsetHeight > baseHeight) {
    taglineSpan.remove();
  } else {
    headerTagline.style.display = 'none';
  }
}

function renderFooter() {
  renderFooterLinks();
  fitTaglineIntoFooter();
}

function debounce(fn, delayMs) {
  let timer;
  return () => {
    clearTimeout(timer);
    timer = setTimeout(fn, delayMs);
  };
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
  window.addEventListener('resize', debounce(renderFooter, 150));
}
