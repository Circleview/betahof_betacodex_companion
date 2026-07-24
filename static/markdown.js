function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value;
  return div.innerHTML;
}

export function renderMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>');
  html = html.replace(/^### (.+)$/gm, '<strong class="md-heading">$1</strong>');
  html = html.replace(/^## (.+)$/gm, '<strong class="md-heading">$1</strong>');
  html = html.replace(/^# (.+)$/gm, '<strong class="md-heading">$1</strong>');
  html = html.replace(/^[-*] (.+)$/gm, '&bull;&nbsp;$1');
  html = html.replace(/\n{2,}/g, '</p><p>');
  html = html.replace(/\n/g, '<br>');
  return `<p>${html}</p>`;
}
