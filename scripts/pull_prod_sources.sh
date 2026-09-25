#!/usr/bin/env bash
# Holt den Quellenstand der Produktion ins lokale Dev-System (data/).
# Auf der Produktion wird nur gelesen. Personenbezogene Daten und Logs
# (users, question_log, usage_log, audit_log, mcp_keys) bleiben bewusst lokal.
# Vorher den Dev-Server stoppen - der Suchindex (chroma) wird komplett ersetzt.
set -euo pipefail

REMOTE="root@companion.betahof.com"
KEY="$HOME/.ssh/betacodex_hetzner"
SRC="/home/betacodex/shared/data"
cd "$(dirname "$0")/../data"

backup="../data.bak-$(date +%Y%m%d-%H%M%S)-before-prod-pull"
echo "Backup (ohne audio) nach $backup"
rsync -a --exclude audio ./ "$backup/"

sync() { rsync -az -e "ssh -i $KEY" "$@"; }
# Suchindex exakt spiegeln, Quelldateien nur ergänzen/aktualisieren.
sync --delete "$REMOTE:$SRC/chroma/" chroma/
for dir in pdfs audio author_photos; do sync "$REMOTE:$SRC/$dir/" "$dir/"; done
for f in sources.json authors.json author_profiles.json terms.json web_index.json \
         web_allowlist.json web_candidates.json source_suggestions.json source_suggestion_weights.json; do
  sync "$REMOTE:$SRC/$f" "$f"
done
echo "Fertig. Backup: $backup"
