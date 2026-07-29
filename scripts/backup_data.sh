#!/usr/bin/env bash
# Backlog #115: data/ enthält alle echten Nutzerdaten (Quellen, Nutzerkonten,
# hochgeladene Audios/PDFs, die ChromaDB-Vektordatenbank) und ist gitignored -
# ein Server-Fehler oder eine fehlerhafte Aktion würde sie sonst
# unwiederbringlich verlieren. Dieses Skript sichert data/ als komprimiertes
# Archiv außerhalb des Repos und hält nur die letzten KEEP_COUNT Sicherungen.
#
# Einrichtung auf dem Produktivserver (Cron, täglich um 3 Uhr):
#   crontab -e
#   0 3 * * * /pfad/zur/app/scripts/backup_data.sh >> /var/log/betacodex-backup.log 2>&1
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$APP_DIR/data"
BACKUP_DIR="${BACKUP_DIR:-$APP_DIR/backups}"
KEEP_COUNT="${KEEP_COUNT:-14}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

if [ ! -d "$DATA_DIR" ]; then
  echo "Fehler: $DATA_DIR existiert nicht - nichts zu sichern." >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

ARCHIVE="$BACKUP_DIR/data-$TIMESTAMP.tar.gz"
tar -czf "$ARCHIVE" -C "$APP_DIR" data
echo "Backup erstellt: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

# Nur die letzten KEEP_COUNT Archive behalten - ältere löschen.
BACKUPS_TO_DELETE=$(ls -1t "$BACKUP_DIR"/data-*.tar.gz 2>/dev/null | tail -n +"$((KEEP_COUNT + 1))")
if [ -n "$BACKUPS_TO_DELETE" ]; then
  echo "$BACKUPS_TO_DELETE" | xargs rm -f
  echo "Alte Backups entfernt (behalte die letzten $KEEP_COUNT)."
fi
