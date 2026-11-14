"""Deploy-Vorlagen (Weg S): System-Units, sudoers, Härtungsskript."""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"
HOME = "/home/betacodex"
SCRIPT = DEPLOY / "server-haertung.sh"
BLOCKS = ["pruefen", "probe", "skripte", "units", "sshd", "nach-deploy"]
ROLLBACKS = ["rueckweg-" + b for b in BLOCKS if b not in ("pruefen", "probe")]


def farben_aus_deploy_sh():
    """Farbe -> Port, abgeleitet aus deploy/deploy.sh (Quelle der Wahrheit)."""
    text = (DEPLOY / "deploy.sh").read_text()
    pairs = dict(re.findall(r'target="(\w+)";\s*target_port=(\d+)', text))
    assert set(pairs) == {"blue", "green"}, pairs
    return pairs


def unit_text(farbe):
    return (DEPLOY / "systemd" / f"betacodex-{farbe}.service").read_text()


def parse(text):
    d = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "[")) and "=" in line:
            k, v = line.split("=", 1)
            d.setdefault(k, []).append(v)
    return d


def test_ports_aus_deploy_sh():
    assert farben_aus_deploy_sh() == {"blue": "8000", "green": "8001"}


@pytest.mark.parametrize("farbe", ["blue", "green"])
def test_unit_direktiven(farbe):
    port = farben_aus_deploy_sh()[farbe]
    u = parse(unit_text(farbe))
    erwartet = {
        "User": ["betacodex"], "Group": ["betacodex"], "UMask": ["0027"],
        "ProtectSystem": ["strict"], "ProtectHome": ["tmpfs"],
        "PrivateTmp": ["yes"], "PrivateDevices": ["yes"], "PrivateIPC": ["yes"],
        "ProtectKernelTunables": ["yes"], "ProtectKernelModules": ["yes"],
        "ProtectKernelLogs": ["yes"], "ProtectControlGroups": ["yes"],
        "ProtectClock": ["yes"], "ProtectHostname": ["yes"],
        "ProtectProc": ["invisible"], "KeyringMode": ["private"],
        "DevicePolicy": ["closed"], "NoNewPrivileges": ["yes"],
        "CapabilityBoundingSet": [""], "AmbientCapabilities": [""],
        "RestrictAddressFamilies": ["AF_UNIX AF_INET AF_INET6"],
        "SystemCallFilter": ["@system-service", "~@privileged @resources"],
        "SystemCallErrorNumber": ["EPERM"], "SystemCallArchitectures": ["native"], "LockPersonality": ["yes"],
        "RestrictRealtime": ["yes"], "RestrictSUIDSGID": ["yes"],
        "RestrictNamespaces": ["yes"],
        "BindReadOnlyPaths": [f"{HOME}/releases/{farbe}", f"{HOME}/shared", f"{HOME}/.cache"],
        "BindPaths": [f"{HOME}/shared/data"],
        "Environment": ["HF_HUB_OFFLINE=1"],
        "WorkingDirectory": [f"{HOME}/releases/{farbe}"],
        "ExecStart": [f"{HOME}/releases/{farbe}/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port {port}"],
        "Restart": ["on-failure"], "RestartSec": ["3"], "TimeoutStopSec": ["660"],
        "After": ["network-online.target"], "Wants": ["network-online.target"],
        "WantedBy": ["multi-user.target"],
    }
    for k, v in erwartet.items():
        assert u.get(k) == v, (k, u.get(k))


@pytest.mark.parametrize("farbe", ["blue", "green"])
def test_unit_keine_verbotenen_direktiven(farbe):
    u = parse(unit_text(farbe))
    for k in ("MemoryDenyWriteExecute", "IPAddressDeny", "IPAddressAllow",
              "PrivateNetwork", "PrivateUsers"):
        assert k not in u, k


def test_blue_green_nur_farbe_und_port_verschieden():
    ports = farben_aus_deploy_sh()
    gruen = unit_text("green").replace("green", "blue").replace(ports["green"], ports["blue"])
    assert gruen == unit_text("blue")


def test_sudoers_nur_exakte_befehle():
    zeilen = [z.strip() for z in (DEPLOY / "sudoers-betacodex").read_text().splitlines()
              if z.strip() and not z.strip().startswith("#")]
    assert len(zeilen) == 1, zeilen
    kopf, cmds = zeilen[0].split("NOPASSWD:")
    assert kopf.split()[0] == "betacodex"
    liste = [c.strip() for c in cmds.split(",")]
    erwartet = [f"/usr/local/sbin/companion-farbe {f}" for f in ("blue", "green")]
    erwartet += [f"/usr/bin/systemctl {a} betacodex-{f}.service"
                 for a in ("restart", "stop") for f in ("blue", "green")]
    assert sorted(liste) == sorted(erwartet)
    assert "*" not in cmds and "ALL" not in cmds


def run(*args):
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin"}, cwd="/", timeout=30)


def test_haertung_syntax():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_haertung_hilfe_listet_alle_bloecke():
    r = run("--help")
    assert r.returncode == 0
    for b in BLOCKS + ROLLBACKS:
        assert b in r.stdout, b


@pytest.mark.parametrize("args", [[], ["gibtsnicht"], ["rueckweg-pruefen"]])
def test_haertung_unbekannter_oder_fehlender_block(args):
    r = run(*args)
    assert r.returncode != 0
    assert "units" in r.stderr  # Nutzungshinweis nennt die gueltigen Bloecke


def test_haertung_nichts_hart_codiert():
    t = SCRIPT.read_text()
    assert not re.search(r"ssh-(ed25519|rsa) AAAA|ecdsa-sha2", t)
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", t.replace("127.0.0.1", ""))
    assert not re.search(r"[A-Za-z0-9-]+\.(de|com|org|net)\b", t)


# --- Logik des Härtungsskripts (Funktionen per source, Pfade im Test umgelenkt) ---
def sh(tmp_path, code):
    """Skript sourcen, Pfade auf tmp umlenken, dann `code` ausführen."""
    pre = (f'source "{SCRIPT}"; B="{tmp_path}/home"; BAKROOT="{tmp_path}/bak"; '
           f'ROOTUSER="$(id -un)"; TS=run2; mkdir -p "$B/.ssh"; ')
    return subprocess.run(["bash", "-c", pre + code], capture_output=True, text=True, timeout=30)


def test_sicherung_liegt_nicht_im_home_und_restore_stellt_her(tmp_path):
    r = sh(tmp_path, 'echo alt > $B/f; backup $B/f; echo neu > $B/f; restore $B/f; cat $B/f; ls -A $B')
    assert r.stdout.split() == ["alt", ".ssh", "f"], (r.stdout, r.stderr)
    assert (tmp_path / "bak" / "run2" / str(tmp_path).lstrip("/") / "home" / "f").exists()


def test_absent_marker_entfernt_neue_datei(tmp_path):
    r = sh(tmp_path, 'backup $B/neu; echo x > $B/neu; restore $B/neu; [ ! -e $B/neu ] && echo weg')
    assert r.stdout.strip() == "weg", r.stderr


def test_restore_folgt_keinem_untergeschobenen_symlink(tmp_path):
    ziel = tmp_path / "ziel"
    ziel.write_text("unberuehrt")
    r = sh(tmp_path, f'echo alt > $B/f; backup $B/f; rm $B/f; ln -s "{ziel}" $B/f; restore $B/f; cat $B/f; cat "{ziel}"')
    assert r.stdout.split() == ["alt", "unberuehrt"], r.stderr


def test_manueller_rueckweg_nimmt_aeltestes_auto_das_des_laufs(tmp_path):
    code = ('echo v1 > $B/f; TS=run1; backup $B/f; echo v2 > $B/f; TS=run2; backup $B/f; echo v3 > $B/f; '
            'restore $B/f run2; cat $B/f; restore $B/f; cat $B/f')
    r = sh(tmp_path, code)
    assert r.stdout.split() == ["v2", "v1"], r.stderr


def test_quellordner_pruefung(tmp_path):
    d = tmp_path / "q"
    d.mkdir()
    (d / "a").write_text("x")
    d.chmod(0o755)
    (d / "a").chmod(0o644)
    assert sh(tmp_path, f'check_src "{d}" && echo ok').stdout.strip() == "ok"
    (d / "a").chmod(0o666)  # von anderen beschreibbar
    assert sh(tmp_path, f'check_src "{d}" && echo ok').returncode != 0
    (d / "a").chmod(0o644)
    assert sh(tmp_path, f'ROOTUSER=gibtesnicht; check_src "{d}" && echo ok').returncode != 0
    assert sh(tmp_path, f'check_src "{tmp_path}/fehlt" && echo ok').returncode != 0


@pytest.mark.parametrize("zeile,erwartet", [
    ("ssh-ed25519 AAAAdummy github-actions-deploy", "ssh-ed25519 AAAAdummy github-actions-deploy"),
    ("ssh-ed25519 AAAAdummy", "ssh-ed25519 AAAAdummy"),
    ('command="x y",no-pty ssh-rsa AAAAdummy kommentar mit leer', "ssh-rsa AAAAdummy kommentar mit leer"),
])
def test_schluesselzeile_mit_neuen_optionen(tmp_path, zeile, erwartet):
    f = tmp_path / "ak"
    f.write_text(zeile + "\n")
    r = sh(tmp_path, f'restrict_key_line "{f}"')
    assert r.stdout == 'restrict,command="/usr/local/sbin/companion-deploy" ' + erwartet + "\n", r.stderr


def test_probe_properties_ohne_sperrdirektiven(tmp_path):
    r = sh(tmp_path, f'unit_props "{DEPLOY}/systemd/betacodex-blue.service"')
    zeilen = r.stdout.splitlines()
    assert "SystemCallFilter=~@privileged @resources" in zeilen
    assert "CapabilityBoundingSet=" in zeilen
    for k in ("SystemCallErrorNumber", "ExecStart", "Restart", "TimeoutStopSec"):
        assert not any(z.startswith(k + "=") for z in zeilen), k


def test_user_units_werden_in_units_und_nach_deploy_abgeschaltet():
    t = SCRIPT.read_text()
    assert re.search(r"blk_units\(\) \{.*?ubuctl disable betacodex-blue betacodex-green.*?\n\}", t, re.S)
    assert re.search(r"blk_nach_deploy\(\) \{.*?ubuctl stop .*?ubuctl disable .*?\n\}", t, re.S)
    assert re.search(r"blk_pruefen\(\) \{.*?ubuctl is-enabled.*?ubuctl is-active.*?\n\}", t, re.S)
