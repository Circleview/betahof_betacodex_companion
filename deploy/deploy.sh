#!/usr/bin/env bash
# Blue/Green-Deploy. Server: /usr/local/lib/companion/deploy.sh, root:root 0755
# (Aufruf nur ueber /usr/local/sbin/companion-deploy). Repo-Vorlage: deploy/deploy.sh.
set -euo pipefail
TAG="${1:?Usage: deploy.sh <git-tag>}"
tag_re='^v[0-9]+\.[0-9]+\.[0-9]+$'
[[ "$TAG" =~ $tag_re ]] || { echo "FEHLER: ungueltiger Tag '$TAG'" >&2; exit 1; }
BASE=/home/betacodex
ACTIVE_FILE="$BASE/active_color"
COOKIE_JAR="$(mktemp)"
trap 'rm -f "$COOKIE_JAR"' EXIT
current="$(cat "$ACTIVE_FILE")"
if [ "$current" = "blue" ]; then target="green"; target_port=8001; else target="blue"; target_port=8000; fi
echo "==> Aktuell aktiv: $current | Deploy-Ziel: $target (Port $target_port), Tag $TAG"
# Nur Nachfahren des aktiven Tags (kein Rollback, kein Seitenzweig); ohne exakten Tag: Abbruch.
active_tag="$(git -C "$BASE/releases/$current" describe --tags --exact-match 2>/dev/null)" || {
  echo "FEHLER: aktiver Release ($current) hat keinen exakten Tag - Abbruch." >&2; exit 1; }
cd "$BASE/releases/$target"
git fetch --tags -q
git merge-base --is-ancestor "refs/tags/$active_tag" "refs/tags/$TAG" || {
  echo "FEHLER: $TAG ist kein Nachfahre des aktiven Tags $active_tag - Abbruch." >&2; exit 1; }
git checkout -q "refs/tags/$TAG"
cmp -s "$(realpath "${BASH_SOURCE[0]}")" deploy/deploy.sh || echo "::warning::deploy.sh weicht vom Repo ab"
source venv/bin/activate
pip install -q -r requirements.txt
deactivate
echo "==> Starte $target neu"
# ponytail: Übergang User→System-Unit, nach Abschluss entfernen (alte User-Unit der Zielfarbe belegt nach Reboot den Port)
XDG_RUNTIME_DIR="/run/user/$(id -u)" systemctl --user stop "betacodex-$target.service" 2>/dev/null || true
sudo -n /usr/bin/systemctl restart "betacodex-$target.service"
# Early-Access-Login (Backlog #114): Passwort nur per stdin an curl, nie als Argument.
early_access_password="$(grep -m1 '^EARLY_ACCESS_PASSWORD=' "$BASE/shared/.env" | cut -d= -f2-)"
echo "==> Warte auf Health-Check (bis zu 60s)"
healthy=false
for _ in $(seq 1 30); do
  if [ -n "$early_access_password" ]; then
    printf '{"password":"%s"}' "$early_access_password" | curl -sf -c "$COOKIE_JAR" -X POST "http://127.0.0.1:$target_port/api/early-access" -H "Content-Type: application/json" --data @- > /dev/null 2>&1 || true
  fi
  if response="$(curl -sf -b "$COOKIE_JAR" "http://127.0.0.1:$target_port/api/version" 2>/dev/null)" && printf '%s' "$response" | grep -qF "\"$TAG\""; then healthy=true; break; fi
  sleep 2
done
if [ "$healthy" != "true" ]; then echo "FEHLER: $target antwortet nicht auf /api/version - Cutover abgebrochen, $current bleibt live." >&2; sudo -n /usr/bin/systemctl stop "betacodex-$target.service" || true; exit 1; fi
echo "==> Health-Check OK - schalte Caddy auf Port $target_port um"
sudo -n /usr/local/sbin/companion-farbe "$target" || { echo "FEHLER: Caddy-Umschaltung auf $target gescheitert - $current bleibt live." >&2; sudo -n /usr/bin/systemctl stop "betacodex-$target.service" || true; exit 1; }
echo -n "$target" > "$ACTIVE_FILE"
echo "==> Stoppe alte Farbe ($current)"
sudo -n /usr/bin/systemctl stop "betacodex-$current.service"
# ponytail: Übergang User→System-Unit, nach Abschluss entfernen
XDG_RUNTIME_DIR="/run/user/$(id -u)" systemctl --user stop "betacodex-$current.service" 2>/dev/null || true
echo "==> Deploy abgeschlossen: $target ist jetzt aktiv (Tag $TAG)"
