// Ausgelagert aus einem Inline-<script type="module"> in index.html/
// import.html (Backlog #58, Content-Security-Policy) - eine strikte CSP ohne
// 'unsafe-inline' für script-src erlaubt keine Inline-Skripte, unabhängig
// davon, wie trivial ihr Inhalt ist.
import { initFooter } from '/footer.js';
initFooter();

// Fix: Klick auf den Marken-Namen "BetaCodex Companion" oben links soll
// immer eine LEERE Konversation öffnen, statt (wie ein normaler Klick auf
// "/") die zuletzt gespeicherte Konversation wiederherzustellen (siehe
// CONVERSATION_STORAGE_KEY in question.js) - anders als der bewusst
// erhaltende "Zurück zur Konversation"-Link auf import.html/404.html, der
// unverändert bleibt. Der Schlüsselname muss mit question.js übereinstimmen.
document.getElementById('brand-link')?.addEventListener('click', () => {
  sessionStorage.removeItem('conversationHistory');
});
