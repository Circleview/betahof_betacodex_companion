export async function initFooter() {
  const versionSpan = document.getElementById('footer-version');
  if (!versionSpan) return;
  try {
    const res = await fetch('/api/version');
    const data = await res.json();
    versionSpan.textContent = data.version;
  } catch (err) {
    versionSpan.textContent = '';
  }
}
