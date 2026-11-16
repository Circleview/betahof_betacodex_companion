// Meldet die Höhe des eingebetteten Chats an die Gastseite, damit deren iframe
// mitwächst. Externe Datei statt Inline-Skript: die CSP erlaubt kein
// 'unsafe-inline' (das Inline-Skript lief deshalb nie, v0.93.1).
function reportHeightToParent() {
  if (window.parent === window) return;
  const height = document.documentElement.scrollHeight;
  window.parent.postMessage({ type: 'betacodex-chat-embed-resize', height }, '*');
}
new ResizeObserver(reportHeightToParent).observe(document.documentElement);
