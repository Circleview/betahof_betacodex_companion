import { initI18n, t, getLang } from '/i18n.js';

// Backlog #114: eigenständiges, bewusst schlankes Modul (kein auth.js/
// footer.js) - diese Seite wird von der Early-Access-Middleware (app/main.py)
// für JEDE Anfrage ausgeliefert, solange kein gültiges Freischalt-Cookie
// vorliegt, und darf deshalb nur von den ebenfalls freigeschalteten Assets
// abhängen (style.css, i18n.js, i18n/*.json - siehe die Ausnahme-Liste dort).

await initI18n();

const form = document.getElementById('early-access-form');
const passwordInput = document.getElementById('early-access-password');
const status = document.getElementById('early-access-status');

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  status.textContent = '';
  try {
    const res = await fetch('/api/early-access', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Lang': getLang() },
      body: JSON.stringify({ password: passwordInput.value }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || t('earlyAccess.genericError'));
    }
    // Middleware liefert nach erfolgreichem Setzen des Cookies dank
    // request.cookies wieder die ursprünglich angefragte Seite aus - ein
    // einfaches Neuladen genügt, kein clientseitiges Redirect-Ziel nötig.
    window.location.reload();
  } catch (err) {
    status.textContent = t('common.errorPrefix') + err.message;
  }
});
