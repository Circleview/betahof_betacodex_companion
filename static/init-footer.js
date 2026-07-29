// Ausgelagert aus einem Inline-<script type="module"> in index.html/
// import.html (Backlog #58, Content-Security-Policy) - eine strikte CSP ohne
// 'unsafe-inline' für script-src erlaubt keine Inline-Skripte, unabhängig
// davon, wie trivial ihr Inhalt ist.
import { initFooter } from '/footer.js';
initFooter();
