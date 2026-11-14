#!/usr/bin/env bash
# Server-Härtung BetaCodex Chat (Weg S: System-Units, Deploy-Key mit command=).
# Läuft als root auf dem Server. Ohne Blockname passiert nichts.
#
#   server-haertung.sh <block> [host]
#   z. B.  ssh root@<host> 'bash -s' -- units <host> < deploy/server-haertung.sh
#
# Der Host dient nur den Hinweistexten.
#
# Ablauf (Dateien kommen aus dem Release-Ordner der aktiven Farbe, daher erst Merge + Tag):
#   1. pruefen       nur lesen: Ist-Zustand, systemd-analyze security beider Farben
#   2. skripte       Wrapper nach /usr/local/sbin/companion-deploy, deploy.sh nach
#                    /usr/local/lib/companion/deploy.sh, Symlink ~betacodex/deploy.sh
#   3. units         System-Units + sudoers (visudo -c, systemd-analyze verify), enable ohne --now
#   4. sshd          Drop-in 50-betacodex.conf + /etc/ssh/authorized_keys/betacodex (sshd -t, reload)
#   -- nächster Release-Tag = erster Deploy mit System-Unit --
#   5. nach-deploy   User-Units abschalten und wegsichern
# Jeder schreibende Block: Backup <datei>.bak-<Zeitstempel>, Prüfung, bei Prüffehler
# automatisch zurück. Jeder schreibende Block hat rueckweg-<block> (stellt die älteste Sicherung her).
# Schlüsselmaterial wird nie ausgegeben.
set -euo pipefail
export LC_ALL=C

B=/home/betacodex
TS=$(date +%Y%m%d-%H%M%S)
BLOCKS="pruefen skripte units sshd nach-deploy"
HOST="${2:-<host>}"

usage() {
  echo "Aufruf: $0 <block> [host]"
  echo "Blöcke:"
  for b in $BLOCKS; do echo "  $b"; done
  for b in skripte units sshd nach-deploy; do echo "  rueckweg-$b"; done
}

block="${1:-}"
case "$block" in
  -h|--help) usage; exit 0 ;;
  pruefen|skripte|units|sshd|nach-deploy|rueckweg-skripte|rueckweg-units|rueckweg-sshd|rueckweg-nach-deploy) ;;
  *) usage >&2; exit 2 ;;
esac
[ "$(id -u)" -eq 0 ] || { echo "Nur als root." >&2; exit 1; }

src() {
  local c; c=$(cat "$B/active_color") || exit 1
  echo "$B/releases/$c/deploy"
}

# Sicherung: Kopie, oder Marker .absent, wenn die Datei noch nicht existiert.
backup() {
  if [ -e "$1" ] || [ -L "$1" ]; then cp -pP "$1" "$1.bak-$TS"; else : > "$1.bak-$TS.absent"; fi
}

# Älteste Sicherung zurückspielen (= Zustand vor dem ersten Lauf).
restore() {
  local f="$1" first
  first=$(ls -1 "$f".bak-* 2>/dev/null | sort | head -n 1 || true)
  [ -n "$first" ] || { echo "keine Sicherung für $f" >&2; return 0; }
  rm -f "$f"
  case "$first" in *.absent) ;; *) cp -pP "$first" "$f" ;; esac
}

reload_sshd() { systemctl reload ssh 2>/dev/null || systemctl reload sshd; }
ubuctl() { runuser -u betacodex -- env XDG_RUNTIME_DIR="/run/user/$(id -u betacodex)" systemctl --user "$@"; }

blk_pruefen() {
  echo "== aktive Farbe"; cat "$B/active_color"
  echo "== Dateien"
  ls -la /usr/local/sbin/companion-deploy /usr/local/lib/companion/deploy.sh "$B/deploy.sh" \
    /etc/ssh/sshd_config.d /etc/ssh/authorized_keys /etc/sudoers.d \
    /etc/systemd/system/betacodex-*.service "$B/.config/systemd/user" 2>&1 || true
  echo "== Anzahl Zeilen in ~/.ssh/authorized_keys (nur Zahl)"
  grep -c . "$B/.ssh/authorized_keys" 2>&1 || true
  echo "== sshd-Einstellung für betacodex"
  sshd -T -C user=betacodex,host=localhost,addr=127.0.0.1 2>&1 | grep -i authorizedkeysfile || true
  echo "== Units"
  for c in blue green; do
    systemctl is-active "betacodex-$c.service" 2>&1 || true
    systemd-analyze security "betacodex-$c.service" --no-pager 2>&1 | tail -n 3 || true
  done
}

blk_skripte() {
  local s; s=$(src)
  bash -n "$s/companion-deploy" && bash -n "$s/deploy.sh" || { echo "Syntaxfehler, nichts geändert." >&2; exit 1; }
  for f in /usr/local/sbin/companion-deploy /usr/local/lib/companion/deploy.sh "$B/deploy.sh"; do backup "$f"; done
  install -o root -g root -m 0755 -D "$s/companion-deploy" /usr/local/sbin/companion-deploy
  install -o root -g root -m 0755 -D "$s/deploy.sh" /usr/local/lib/companion/deploy.sh
  rm -f "$B/deploy.sh"; ln -s /usr/local/lib/companion/deploy.sh "$B/deploy.sh"
  echo "skripte: ok"
}
blk_rueckweg_skripte() {
  for f in /usr/local/sbin/companion-deploy /usr/local/lib/companion/deploy.sh "$B/deploy.sh"; do restore "$f"; done
  echo "rueckweg-skripte: ok"
}

blk_units() {
  local s c f; s=$(src)
  visudo -cf "$s/sudoers-betacodex" >/dev/null || { echo "sudoers ungültig, nichts geändert." >&2; exit 1; }
  for c in blue green; do
    f=/etc/systemd/system/betacodex-$c.service
    backup "$f"
  done
  backup /etc/sudoers.d/betacodex-companion
  backup /etc/sudoers.d/betacodex-companion-farbe
  for c in blue green; do
    install -o root -g root -m 0644 "$s/systemd/betacodex-$c.service" "/etc/systemd/system/betacodex-$c.service"
  done
  install -o root -g root -m 0440 "$s/sudoers-betacodex" /etc/sudoers.d/betacodex-companion
  rm -f /etc/sudoers.d/betacodex-companion-farbe
  if ! visudo -c >/dev/null \
     || ! systemd-analyze verify /etc/systemd/system/betacodex-blue.service /etc/systemd/system/betacodex-green.service; then
    echo "Prüfung fehlgeschlagen, stelle zurück." >&2
    blk_rueckweg_units; exit 1
  fi
  systemctl daemon-reload
  systemctl enable betacodex-blue.service betacodex-green.service   # ohne --now
  echo "units: ok (nicht gestartet; erster Start durch den nächsten Release-Tag)"
}
blk_rueckweg_units() {
  systemctl disable betacodex-blue.service betacodex-green.service 2>/dev/null || true
  for f in /etc/systemd/system/betacodex-blue.service /etc/systemd/system/betacodex-green.service \
           /etc/sudoers.d/betacodex-companion /etc/sudoers.d/betacodex-companion-farbe; do restore "$f"; done
  systemctl daemon-reload
  visudo -c >/dev/null
  echo "rueckweg-units: ok"
}

AK=/etc/ssh/authorized_keys/betacodex
DROPIN=/etc/ssh/sshd_config.d/50-betacodex.conf
blk_sshd() {
  local s n; s=$(src)
  [ -x /usr/local/sbin/companion-deploy ] || { echo "Erst Block skripte." >&2; exit 1; }
  n=$(grep -c . "$B/.ssh/authorized_keys")
  [ "$n" -eq 1 ] || { echo "Erwartet genau 1 Schlüsselzeile, gefunden: $n. Nichts geändert." >&2; exit 1; }
  install -d -o root -g root -m 0755 /etc/ssh/authorized_keys
  backup "$AK"; backup "$DROPIN"; backup "$B/.ssh/authorized_keys"
  # Typ + Schlüssel (+ Kommentar) übernehmen, alte Optionen verwerfen, neue voranstellen.
  awk '{ for (i = 1; i <= NF; i++) if ($i ~ /^(ssh-|ecdsa-|sk-)/) { out = ""; for (j = i; j <= NF; j++) out = out (j > i ? " " : "") $j;
         print "restrict,command=\"/usr/local/sbin/companion-deploy\" " out; next } }' \
    "$B/.ssh/authorized_keys" > "$AK.neu"
  [ "$(grep -c . "$AK.neu")" -eq 1 ] || { rm -f "$AK.neu"; echo "Schlüsselzeile nicht erkannt." >&2; exit 1; }
  chown root:root "$AK.neu"; chmod 0644 "$AK.neu"; mv "$AK.neu" "$AK"
  install -o root -g root -m 0644 "$s/sshd-betacodex.conf" "$DROPIN"
  if ! sshd -t; then echo "sshd -t fehlgeschlagen, stelle zurück." >&2; blk_rueckweg_sshd; exit 1; fi
  mv "$B/.ssh/authorized_keys" "$B/.ssh/authorized_keys.bak-$TS"   # kein Rückfall auf die alte Datei
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
  restore "$DROPIN"; restore "$AK"; restore "$B/.ssh/authorized_keys"
  sshd -t && reload_sshd
  echo "rueckweg-sshd: ok"
}

blk_nach_deploy() {
  local c; c=$(cat "$B/active_color")
  systemctl is-active --quiet "betacodex-$c.service" \
    || { echo "System-Unit betacodex-$c läuft nicht. Erst Deploy abschließen." >&2; exit 1; }
  ubuctl disable betacodex-blue betacodex-green || true
  for c in blue green; do
    f="$B/.config/systemd/user/betacodex-$c.service"
    if [ -e "$f" ]; then backup "$f"; rm -f "$f"; fi
  done
  ubuctl daemon-reload || true
  echo "nach-deploy: ok"
}
blk_rueckweg_nach_deploy() {
  for c in blue green; do restore "$B/.config/systemd/user/betacodex-$c.service"; done
  ubuctl daemon-reload || true
  ubuctl enable betacodex-blue betacodex-green || true   # ohne --now
  echo "rueckweg-nach-deploy: ok"
}

"blk_${block//-/_}"
