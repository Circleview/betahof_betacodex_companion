#!/usr/bin/env bash
# Server-Härtung BetaCodex Chat (Weg S: System-Units, Deploy-Key mit command=).
# Läuft als root auf dem Server. Ohne Blockname passiert nichts.
#
#   server-haertung.sh <block> [quelle] [host]
#
# Quelle = Ordner mit den Vorlagen (das deploy/-Verzeichnis des Repos). Pflicht für skripte, units,
# sshd. Er muss root gehören und darf für Gruppe/Andere nicht beschreibbar sein (sonst Abbruch).
# Aus dem Release-Ordner von betacodex wird nie gelesen. Host nur für die Hinweistexte.
# Ablauf für den Nutzer, vom Mac aus (Host als Platzhalter):
#   scp -r deploy root@<host>:/root/companion-deploy
#   ssh root@<host> 'bash /root/companion-deploy/server-haertung.sh <block> /root/companion-deploy <host>'
#
# Blöcke, in dieser Reihenfolge:
#   1. pruefen       nur lesen: Ist-Zustand, User-Units, systemd-analyze security beider Farben
#      probe         nur lesend: systemd-run mit den Properties der Unit (wie Produktion,
#                    gesperrte Syscalls = EPERM): torch-Import, ffmpeg-Segment, git describe
#   2. skripte       Wrapper nach /usr/local/sbin/companion-deploy, deploy.sh nach
#                    /usr/local/lib/companion/deploy.sh, Symlink ~betacodex/deploy.sh
#   3. units         System-Units + sudoers (visudo -c, systemd-analyze verify), enable ohne --now;
#                    User-Units werden mit disable (ohne stop) abgemeldet
#   4. sshd          Drop-in 50-betacodex.conf + /etc/ssh/authorized_keys/betacodex (sshd -t,
#                    sshd -T-Prüfung, reload)
#   -- nächster Release-Tag = erster Deploy mit System-Unit --
#   5. nach-deploy   User-Units stoppen, deaktivieren und wegsichern
# Jeder schreibende Block sichert vorher nach /root/companion-haertung/<Zeitstempel>/<Pfad> (root, 0700).
# Prüffehler im Block: automatisch zurück mit der Sicherung dieses Laufs. Jeder schreibende Block
# hat rueckweg-<block>; der manuelle Rückweg nimmt die älteste Sicherung je Datei.
# Schlüsselmaterial wird nie ausgegeben.
set -euo pipefail
export LC_ALL=C

# Pfade: im Test nach dem source überschrieben, im Betrieb nie per Umgebung.
B=/home/betacodex
BAKROOT=/root/companion-haertung
ROOTUSER=root
TS=$(date +%Y%m%d-%H%M%S)
SRC=""
HOST="<host>"
BLOCKS="pruefen probe skripte units sshd nach-deploy"
KEYCMD='restrict,command="/usr/local/sbin/companion-deploy"'

usage() {
  echo "Aufruf: $0 <block> [quelle] [host]"
  echo "Blöcke:"
  for b in $BLOCKS; do echo "  $b"; done
  for b in skripte units sshd nach-deploy; do echo "  rueckweg-$b"; done
}

# Quelle muss root gehören und darf nicht von Gruppe/Anderen beschreibbar sein (Ordner, Dateien, keine Links).
check_src() {
  [ -d "$1" ] || { echo "Quellordner fehlt: $1" >&2; return 1; }
  local bad
  bad=$(find "$1" \( -not -user "$ROOTUSER" -o -perm -020 -o -perm -002 -o -type l \) -print -quit) || { echo "find fehlgeschlagen" >&2; return 1; }
  [ -z "$bad" ] || { echo "Quelle nicht vertrauenswürdig (Besitzer/Rechte/Link): $bad" >&2; return 1; }
}

has_entry() { [ -e "$1$2" ] || [ -L "$1$2" ] || [ -e "$1$2.absent" ]; }

# Sicherung: Kopie (Links bleiben Links) oder Marker .absent, immer unter $BAKROOT/$TS.
backup() {
  local t="$BAKROOT/$TS$1"
  install -d -m 0700 "$BAKROOT" "$(dirname "$t")"
  if [ -e "$1" ] || [ -L "$1" ]; then cp -pP "$1" "$t"; else : > "$t.absent"; fi
}

# restore <datei> [ts]: mit ts die Sicherung dieses Laufs, sonst die älteste.
restore() {
  local f="$1" ts="${2:-}" d cand=""
  if [ -n "$ts" ]; then
    cand="$BAKROOT/$ts"
  else
    for d in $(ls -1 "$BAKROOT" 2>/dev/null | sort); do
      if has_entry "$BAKROOT/$d" "$f"; then cand="$BAKROOT/$d"; break; fi
    done
  fi
  if [ -z "$cand" ] || ! has_entry "$cand" "$f"; then echo "keine Sicherung für $f" >&2; return 0; fi
  rm -f "$f"
  if [ ! -e "$cand$f.absent" ]; then cp -pP "$cand$f" "$f"; fi
}

# Eine Schlüsselzeile: alte Optionen verwerfen, Typ + Schlüssel + Kommentar behalten, Optionen voranstellen.
restrict_key_line() {
  awk -v pre="$KEYCMD" '{ for (i = 1; i <= NF; i++) if ($i ~ /^(ssh-|ecdsa-|sk-)/) {
        out = ""; for (j = i; j <= NF; j++) out = out (j > i ? " " : "") $j; print pre " " out; next } }' "$1"
}

# Service-Direktiven einer Unit als Zeilen, ohne Start-/Neustart-Zeilen. SystemCallErrorNumber bleibt:
# ohne sie beendet sched_setaffinity (torch, @resources) die Probe per SIGSYS, Produktion läuft aber.
unit_props() {
  awk '/^\[/ { s = ($0 == "[Service]") }
       s && /^[A-Za-z]+=/ { k = $0; sub(/=.*/, "", k)
         if (k !~ /^(ExecStart|Restart|RestartSec|TimeoutStopSec)$/) print }' "$1"
}

reload_sshd() { systemctl reload ssh 2>/dev/null || systemctl reload sshd; }
ubuctl() { runuser -u betacodex -- env XDG_RUNTIME_DIR="/run/user/$(id -u betacodex)" systemctl --user "$@"; }
authkeysfile() { sshd -T -C "user=$1,host=localhost,addr=127.0.0.1" | grep -i '^authorizedkeysfile' || true; }
count_lines() { grep -c . "$1" || true; }

blk_pruefen() {
  echo "== aktive Farbe"; cat "$B/active_color"
  echo "== Dateien"
  ls -la /usr/local/sbin/companion-deploy /usr/local/lib/companion/deploy.sh "$B/deploy.sh" \
    /etc/ssh/sshd_config.d /etc/ssh/authorized_keys /etc/sudoers.d \
    /etc/systemd/system/betacodex-*.service "$B/.config/systemd/user" 2>&1 || true
  echo "== Anzahl Zeilen in ~/.ssh/authorized_keys (nur Zahl)"
  count_lines "$B/.ssh/authorized_keys" 2>&1 || true
  echo "== sshd-Einstellung"
  echo "betacodex: $(authkeysfile betacodex)"; echo "root: $(authkeysfile root)"
  echo "== System-Units"
  for c in blue green; do
    systemctl is-active "betacodex-$c.service" 2>&1 || true
    systemd-analyze security "betacodex-$c.service" --no-pager 2>&1 | tail -n 3 || true
  done
  echo "== User-Units (sollen nach units/nach-deploy disabled + inactive sein)"
  for c in blue green; do
    echo "$c: $(ubuctl is-enabled "betacodex-$c" 2>&1 || true) / $(ubuctl is-active "betacodex-$c" 2>&1 || true)"
  done
}

blk_probe() {
  local c u py mem fail=0; c=$(cat "$B/active_color")
  u=/etc/systemd/system/betacodex-$c.service
  if [ ! -e "$u" ]; then
    [ -n "$SRC" ] || { echo "Unit nicht installiert und keine Quelle angegeben." >&2; exit 1; }
    check_src "$SRC" || exit 1
    u="$SRC/systemd/betacodex-$c.service"
  fi
  local props=() l
  while IFS= read -r l; do props+=(-p "$l"); done < <(unit_props "$u")
  py="$B/releases/$c/venv/bin/python"
  probe() { echo "-- $1"; shift; systemd-run --quiet --wait --pipe --collect "${props[@]}" "$@" || { echo "FEHLER (Exit $?)"; fail=1; }; }
  probe "Python-Importe + torch" "$py" -c 'import torch, chromadb, fitz, pypdf, tiktoken, sentence_transformers; torch.set_num_threads(2); print(torch.ones(10).sum())'
  probe "ffmpeg-Segment in PrivateTmp" sh -c 'ffmpeg -nostdin -y -loglevel error -f lavfi -i sine=duration=3 -f segment -segment_time 1 /tmp/probe-%d.wav && ls /tmp/probe-*.wav'
  probe "git describe" git -C "$B/releases/$c" describe --tags --exact-match
  mem=$(awk '/^MemAvailable:/ { print $2 }' /proc/meminfo)
  if [ "$mem" -gt 2097152 ]; then echo "-- Modell-Laden: genug RAM, aber nur per echter Frage nach dem Deploy prüfbar."
  else echo "-- Modell-Laden übersprungen (MemAvailable <= 2 GB)."; fi
  [ "$fail" -eq 0 ]
}

blk_skripte() {
  local s="$SRC"
  bash -n "$s/companion-deploy" && bash -n "$s/deploy.sh" || { echo "Syntaxfehler, nichts geändert." >&2; exit 1; }
  for f in /usr/local/sbin/companion-deploy /usr/local/lib/companion/deploy.sh "$B/deploy.sh"; do backup "$f"; done
  install -o root -g root -m 0755 -D "$s/companion-deploy" /usr/local/sbin/companion-deploy
  install -o root -g root -m 0755 -D "$s/deploy.sh" /usr/local/lib/companion/deploy.sh
  rm -f "$B/deploy.sh"; ln -s /usr/local/lib/companion/deploy.sh "$B/deploy.sh"
  echo "skripte: ok"
}
blk_rueckweg_skripte() {
  for f in /usr/local/sbin/companion-deploy /usr/local/lib/companion/deploy.sh "$B/deploy.sh"; do restore "$f" "${1:-}"; done
  echo "rueckweg-skripte: ok"
}

SUDOERS_FILES="/etc/sudoers.d/betacodex-companion /etc/sudoers.d/betacodex-companion-farbe"
blk_units() {
  local s="$SRC" c f
  visudo -cf "$s/sudoers-betacodex" >/dev/null || { echo "sudoers ungültig, nichts geändert." >&2; exit 1; }
  for c in blue green; do backup "/etc/systemd/system/betacodex-$c.service"; done
  for f in $SUDOERS_FILES; do backup "$f"; done
  for c in blue green; do
    install -o root -g root -m 0644 "$s/systemd/betacodex-$c.service" "/etc/systemd/system/betacodex-$c.service"
  done
  install -o root -g root -m 0440 "$s/sudoers-betacodex" /etc/sudoers.d/betacodex-companion
  rm -f /etc/sudoers.d/betacodex-companion-farbe
  if ! visudo -c >/dev/null \
     || ! systemd-analyze verify /etc/systemd/system/betacodex-blue.service /etc/systemd/system/betacodex-green.service; then
    echo "Prüfung fehlgeschlagen, stelle zurück." >&2
    blk_rueckweg_units "$TS"; exit 1
  fi
  systemctl daemon-reload
  systemctl enable betacodex-blue.service betacodex-green.service   # ohne --now
  # Sonst starten die User-Units nach einem Reboot parallel (enabled + Linger). Kein stop: Dienst läuft weiter.
  ubuctl disable betacodex-blue betacodex-green || true
  echo "units: ok (System-Units nicht gestartet; erster Start durch den nächsten Release-Tag)"
}
blk_rueckweg_units() {
  systemctl disable betacodex-blue.service betacodex-green.service 2>/dev/null || true
  for f in /etc/systemd/system/betacodex-blue.service /etc/systemd/system/betacodex-green.service $SUDOERS_FILES; do
    restore "$f" "${1:-}"
  done
  systemctl daemon-reload
  ubuctl enable betacodex-blue betacodex-green 2>/dev/null || true   # User-Units wieder wie vorher
  visudo -c >/dev/null
  echo "rueckweg-units: ok"
}

AK=/etc/ssh/authorized_keys/betacodex
DROPIN=/etc/ssh/sshd_config.d/50-betacodex.conf
blk_sshd() {
  local s="$SRC" n root_vor
  [ -x /usr/local/sbin/companion-deploy ] || { echo "Erst Block skripte." >&2; exit 1; }
  n=$(count_lines "$B/.ssh/authorized_keys")
  [ "$n" -eq 1 ] || { echo "Erwartet genau 1 Schlüsselzeile in ~/.ssh/authorized_keys, gefunden: $n. Nichts geändert." >&2; exit 1; }
  root_vor=$(authkeysfile root)
  install -d -o root -g root -m 0755 /etc/ssh/authorized_keys
  backup "$AK"; backup "$DROPIN"; backup "$B/.ssh/authorized_keys"
  restrict_key_line "$B/.ssh/authorized_keys" > "$AK.neu"
  [ "$(count_lines "$AK.neu")" -eq 1 ] || { rm -f "$AK.neu"; echo "Schlüsselzeile nicht erkannt." >&2; exit 1; }
  chown root:root "$AK.neu"; chmod 0644 "$AK.neu"; mv "$AK.neu" "$AK"
  install -o root -g root -m 0644 "$s/sshd-betacodex.conf" "$DROPIN"
  if ! sshd -t \
     || ! authkeysfile betacodex | grep -qi '^authorizedkeysfile /etc/ssh/authorized_keys/betacodex' \
     || [ "$(authkeysfile root)" != "$root_vor" ]; then
    echo "sshd-Prüfung fehlgeschlagen, stelle zurück." >&2
    blk_rueckweg_sshd "$TS" || true; exit 1
  fi
  rm -f "$B/.ssh/authorized_keys"   # Original liegt gesichert unter $BAKROOT; kein Rückfall auf die alte Datei
  reload_sshd
  cat <<TXT
sshd: ok. Zweite root-Sitzung offen lassen. Jetzt vom Mac aus prüfen:
  1. ssh -i ~/.ssh/betacodex_deploy betacodex@$HOST id
     -> muss "abgelehnt" melden (keine id-Ausgabe).
  2. ssh root@$HOST   -> Login muss weiter gehen.
Das Skript kann das vom Server aus nicht testen. Bei Problemen: $0 rueckweg-sshd
TXT
}
blk_rueckweg_sshd() {
  restore "$DROPIN" "${1:-}"; restore "$AK" "${1:-}"; restore "$B/.ssh/authorized_keys" "${1:-}"
  sshd -t || { echo "rueckweg-sshd: sshd -t schlägt fehl, NICHT neu geladen." >&2; return 1; }
  reload_sshd || { echo "rueckweg-sshd: reload fehlgeschlagen." >&2; return 1; }
  echo "rueckweg-sshd: ok"
}

blk_nach_deploy() {
  local c f; c=$(cat "$B/active_color")
  systemctl is-active --quiet "betacodex-$c.service" \
    || { echo "System-Unit betacodex-$c läuft nicht. Erst Deploy abschließen." >&2; exit 1; }
  ubuctl stop betacodex-blue betacodex-green || true
  ubuctl disable betacodex-blue betacodex-green || true
  for c in blue green; do
    f="$B/.config/systemd/user/betacodex-$c.service"
    backup "$f"; rm -f "$f"
  done
  ubuctl daemon-reload || true
  echo "nach-deploy: ok"
}
blk_rueckweg_nach_deploy() {
  for c in blue green; do restore "$B/.config/systemd/user/betacodex-$c.service" "${1:-}"; done
  ubuctl daemon-reload || true
  ubuctl enable betacodex-blue betacodex-green || true   # ohne --now
  echo "rueckweg-nach-deploy: ok"
}

main() {
  local block="${1:-}"
  case "$block" in
    -h|--help) usage; exit 0 ;;
    pruefen|probe|skripte|units|sshd|nach-deploy|rueckweg-skripte|rueckweg-units|rueckweg-sshd|rueckweg-nach-deploy) ;;
    *) usage >&2; exit 2 ;;
  esac
  [ "$(id -u)" -eq 0 ] || { echo "Nur als root." >&2; exit 1; }
  SRC="${2:-}"; HOST="${3:-<host>}"
  case "$block" in
    skripte|units|sshd)
      [ -n "$SRC" ] || { echo "Block $block braucht den Quellordner als 2. Argument." >&2; exit 2; }
      check_src "$SRC" || exit 1 ;;
  esac
  "blk_${block//-/_}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main "$@"; fi
