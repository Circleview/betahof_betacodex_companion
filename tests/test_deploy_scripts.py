"""Deploy-Skripte (Idee 6b60ad86): Wrapper, deploy.sh, sshd-Vorlagen.

Skripte werden kopiert, Pfade per Textersetzung auf Test-Ordner gelegt
(keine Umgebungsvariable im Produktivpfad) und sudo/curl/pip/systemctl/sleep
per PATH-Stub ersetzt. Bash-3.2-kompatibel.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"
REAL_GIT = shutil.which("git")
BASH = shutil.which("bash")
SCRIPTS = ["deploy.sh", "companion-deploy"]


def _read(name):
    return (DEPLOY / name).read_text()


# ---------- Wrapper ----------

def _wrapper(tmp_path):
    stub = tmp_path / "deploy_stub.sh"
    stub.write_text('#!/bin/bash\necho "ARGS:$#:$1" >> "$(dirname "$0")/calls.log"\n')
    stub.chmod(0o755)
    w = tmp_path / "companion-deploy"
    text = _read("companion-deploy")
    assert "/usr/local/lib/companion/deploy.sh" in text
    w.write_text(text.replace("/usr/local/lib/companion/deploy.sh", str(stub)))
    return w, tmp_path / "calls.log"


def _run_wrapper(tmp_path, cmd):
    w, log = _wrapper(tmp_path)
    env = {"PATH": os.environ["PATH"]}
    if cmd is not None:
        env["SSH_ORIGINAL_COMMAND"] = cmd
    r = subprocess.run([BASH, str(w)], env=env, capture_output=True, text=True)
    return r, (log.read_text() if log.exists() else "")


@pytest.mark.parametrize("tag", ["v0.89.4", "v0.100.12"])
def test_wrapper_accepts_tag(tmp_path, tag):
    r, log = _run_wrapper(tmp_path, f"~/deploy.sh {tag}")
    assert r.returncode == 0, r.stderr
    assert log == f"ARGS:1:{tag}\n"


BAD = [
    None, "", "bash", "deploy.sh v0.89.4", "/home/betacodex/deploy.sh v0.89.4",
    "~/deploy.sh v0.89", "~/deploy.sh v0.89.4-rc1", "~/deploy.sh v0.89.4 extra",
    "~/deploy.sh v0.89.4; id", "~/deploy.sh $(id)", "~/deploy.sh `id`",
    "~/deploy.sh v0.89.4\nid", " ~/deploy.sh v0.89.4", "~/deploy.sh v0.89.4 ",
    "~/deploy.sh  v0.89.4", "~/deploy.sh 0.89.4",
]


@pytest.mark.parametrize("cmd", BAD)
def test_wrapper_rejects(tmp_path, cmd):
    r, log = _run_wrapper(tmp_path, cmd)
    assert r.returncode != 0
    assert log == ""
    assert "abgelehnt" in r.stderr


# ---------- deploy.sh ----------

class Env:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.base = tmp_path / "base"
        self.stubs = tmp_path / "stubs"
        self.log = tmp_path / "calls.log"
        self.origin = tmp_path / "origin"
        self.stubs.mkdir()
        self.base.mkdir()
        self.log.write_text("")
        self._stub("sudo", 'echo "sudo $*" >> "$LOG"; [ -f "$STUBS/sudo_fail" ] && exit 1; exit 0')
        self._stub("systemctl", 'echo "systemctl $*" >> "$LOG"')
        self._stub("pip", 'echo "pip $*" >> "$LOG"')
        self._stub("sleep", "exit 0")
        self._stub("git", 'echo "git $*" >> "$LOG"; exec ' + REAL_GIT + ' "$@"')
        self._stub(
            "curl",
            'echo "curl $*" >> "$LOG"\n'
            'case " $* " in *" @- "*) echo "curl-stdin $(cat)" >> "$LOG";; esac\n'
            'case "$*" in *api/version*) [ -f "$STUBS/unhealthy" ] && exit 22; echo \'{"version":"x"}\';; esac\n'
            "exit 0",
        )

    def _stub(self, name, body):
        p = self.stubs / name
        p.write_text('#!/bin/bash\nSTUBS="$(dirname "$0")"\nLOG="' + str(self.log) + '"\n' + body + "\n")
        p.chmod(0o755)

    def git(self, cwd, *a):
        subprocess.run([REAL_GIT, "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a],
                       cwd=cwd, check=True, capture_output=True)

    def setup(self, script_in_repo="same", active="blue", env_pw="geheim"):
        """origin: v0.0.5 <- v0.1.0 <- v0.2.0 ; Seitenzweig v0.1.1 von v0.0.5."""
        script = DEPLOY / "deploy.sh"
        self.script = self.tmp / "deploy-copy.sh"
        text = script.read_text()
        assert "BASE=/home/betacodex" in text
        self.script.write_text(text.replace("BASE=/home/betacodex", f"BASE={self.base}"))
        o = self.origin
        o.mkdir()
        self.git(o, "init", "-q", "-b", "main")

        def commit(tag, marker):
            (o / "f.txt").write_text(marker)
            if script_in_repo == "same":
                (o / "deploy").mkdir(exist_ok=True)
                shutil.copy(self.script, o / "deploy" / "deploy.sh")
            elif script_in_repo == "diff":
                (o / "deploy").mkdir(exist_ok=True)
                (o / "deploy" / "deploy.sh").write_text("# anders " + marker)
            self.git(o, "add", "-A")
            self.git(o, "commit", "-q", "-m", marker)
            self.git(o, "tag", tag)

        commit("v0.0.5", "a")
        commit("v0.1.0", "b")
        commit("v0.2.0", "c")
        self.git(o, "checkout", "-q", "-b", "side", "v0.0.5")
        commit("v0.1.1", "side")
        self.git(o, "checkout", "-q", "main")
        for color in ("blue", "green"):
            rel = self.base / "releases" / color
            subprocess.run([REAL_GIT, "clone", "-q", str(o), str(rel)], check=True, capture_output=True)
            (rel / "venv" / "bin").mkdir(parents=True)
            (rel / "venv" / "bin" / "activate").write_text("")
            (rel / "requirements.txt").write_text("")
        other = "green" if active == "blue" else "blue"
        self.git(self.base / "releases" / active, "checkout", "-q", "v0.1.0")
        self.git(self.base / "releases" / other, "checkout", "-q", "v0.0.5")
        (self.base / "active_color").write_text(active)
        (self.base / "shared").mkdir()
        (self.base / "shared" / ".env").write_text(f"EARLY_ACCESS_PASSWORD={env_pw}\n")
        # Datei "same" muss nach Textersetzung gleich sein -> bereits kopiert
        return self

    def run(self, tag, healthy=True, sudo_fail=False):
        if not healthy:
            (self.stubs / "unhealthy").write_text("")
        if sudo_fail:
            (self.stubs / "sudo_fail").write_text("")
        env = {"PATH": f"{self.stubs}:{os.environ['PATH']}", "HOME": str(self.tmp)}
        r = subprocess.run([BASH, str(self.script), tag], env=env, capture_output=True, text=True)
        return r, self.log.read_text()

    @property
    def active(self):
        return (self.base / "active_color").read_text()


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


@pytest.mark.parametrize("tag", ["", "v0.2", "v0.2.0-rc1", "0.2.0", "v0.2.0; id", "$(id)", "v0.2.0\nid", " v0.2.0"])
def test_deploy_rejects_bad_tag_before_git(env, tag):
    env.setup()
    r, log = env.run(tag)
    assert r.returncode != 0
    assert "git " not in log and "systemctl" not in log and "sudo" not in log
    assert env.active == "blue"


def test_deploy_requires_tag_argument(env):
    env.setup()
    r = subprocess.run([BASH, str(env.script)], env={"PATH": os.environ["PATH"]}, capture_output=True, text=True)
    assert r.returncode != 0


@pytest.mark.parametrize("tag", ["v0.0.5", "v0.1.1"])  # älter / Seitenzweig
def test_deploy_rejects_non_descendant_before_checkout(env, tag):
    env.setup()
    r, log = env.run(tag)
    assert r.returncode != 0
    assert "checkout" not in log
    assert "systemctl" not in log and "sudo" not in log
    assert env.active == "blue"
    head = subprocess.run([REAL_GIT, "describe", "--tags", "--exact-match"],
                          cwd=env.base / "releases" / "green", capture_output=True, text=True).stdout.strip()
    assert head == "v0.0.5"  # Ziel-Ordner unverändert


def test_deploy_fails_closed_without_exact_active_tag(env):
    env.setup()
    rel = env.base / "releases" / "blue"
    env.git(rel, "checkout", "-q", "--detach", "origin/main~0")
    (rel / "x").write_text("x")
    env.git(rel, "add", "x")
    env.git(rel, "commit", "-q", "-m", "ohne Tag")
    r, log = env.run("v0.2.0")
    assert r.returncode != 0
    assert "checkout" not in log
    assert "systemctl" not in log and "sudo" not in log
    assert env.active == "blue"


def test_deploy_success_switches_color(env):
    env.setup()
    r, log = env.run("v0.2.0")
    assert r.returncode == 0, r.stdout + r.stderr
    assert env.active == "green"
    lines = log.splitlines()
    assert "sudo -n /usr/bin/systemctl restart betacodex-green.service" in lines
    assert "sudo -n /usr/local/sbin/companion-farbe green" in lines
    assert "sudo -n /usr/bin/systemctl stop betacodex-blue.service" in lines
    assert "systemctl --user stop betacodex-blue.service" in lines  # Übergang
    assert lines.index("sudo -n /usr/local/sbin/companion-farbe green") < lines.index(
        "sudo -n /usr/bin/systemctl stop betacodex-blue.service")
    head = subprocess.run([REAL_GIT, "describe", "--tags", "--exact-match"],
                          cwd=env.base / "releases" / "green", capture_output=True, text=True).stdout.strip()
    assert head == "v0.2.0"
    assert "http://127.0.0.1:8001/" in log  # blue aktiv -> Ziel green = 8001


def test_deploy_target_blue_uses_port_8000(env):
    env.setup(active="green")
    r, log = env.run("v0.2.0")
    assert r.returncode == 0, r.stdout + r.stderr
    assert env.active == "blue"
    assert "http://127.0.0.1:8000/" in log
    assert "sudo -n /usr/local/sbin/companion-farbe blue" in log


def test_deploy_password_via_stdin_not_argument(env):
    env.setup(env_pw="Sup3rGeheim")
    r, log = env.run("v0.2.0")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "curl-stdin" in log and "Sup3rGeheim" in log
    for line in log.splitlines():
        if line.startswith("curl "):
            assert "Sup3rGeheim" not in line
    assert "Sup3rGeheim" not in r.stdout + r.stderr


def test_deploy_health_failure_rolls_back(env):
    env.setup()
    r, log = env.run("v0.2.0", healthy=False)
    assert r.returncode != 0
    assert env.active == "blue"
    lines = log.splitlines()
    assert "sudo -n /usr/bin/systemctl stop betacodex-green.service" in lines
    assert not any("companion-farbe" in x for x in lines)
    assert "sudo -n /usr/bin/systemctl stop betacodex-blue.service" not in lines


def test_deploy_caddy_switch_failure_keeps_old(env):
    env.setup()
    r, log = env.run("v0.2.0", sudo_fail=True)
    assert r.returncode != 0
    assert env.active == "blue"


def test_deploy_cmp_warning_when_repo_file_differs(env):
    env.setup(script_in_repo="diff")
    r, _ = env.run("v0.2.0")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "::warning::" in r.stdout + r.stderr


def test_deploy_cmp_warning_when_repo_file_missing(env):
    env.setup(script_in_repo="none")
    r, _ = env.run("v0.2.0")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "::warning::" in r.stdout + r.stderr


def test_deploy_no_warning_when_equal(env):
    env.setup(script_in_repo="same")
    r, _ = env.run("v0.2.0")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "::warning::" not in r.stdout + r.stderr


# ---------- statische Prüfungen ----------

@pytest.mark.parametrize("name", SCRIPTS)
def test_bash_syntax(name):
    r = subprocess.run([BASH, "-n", str(DEPLOY / name)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_deploy_sh_static_rules():
    t = _read("deploy.sh")
    for bad in ("CADDYFILE", "DOMAIN", "/etc/caddy"):
        assert bad not in t, bad
    assert t.count("XDG_RUNTIME_DIR") == 1  # nur Übergangszeile
    assert "systemctl --user restart" not in t
    sudo_calls = re.findall(r"sudo -n (\S+ ?\S* ?\S*)", t)
    assert sudo_calls
    for c in sudo_calls:
        assert c.startswith("/usr/local/sbin/companion-farbe") or c.startswith("/usr/bin/systemctl restart") \
            or c.startswith("/usr/bin/systemctl stop"), c
    assert "BASE=/home/betacodex" in t
    assert "${BASE" not in t.split("BASE=/home/betacodex")[0]  # BASE nicht aus der Umgebung
    assert "--data @-" in t
    for line in t.splitlines():
        if "curl" in line and not line.lstrip().startswith("#"):
            assert "early_access_password" not in line.split("curl", 1)[1]


def test_wrapper_static_rules():
    t = _read("companion-deploy")
    assert "LC_ALL=C" in t
    assert "exec /usr/local/lib/companion/deploy.sh" in t


def test_deploy_dir_has_no_secrets_or_hosts():
    ipv4 = re.compile(r"\b(?!127\.0\.0\.1\b)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
    for p in DEPLOY.rglob("*"):
        if not p.is_file():
            continue
        t = p.read_text()
        assert not re.search(r"ssh-(ed25519|rsa) AAAA", t), p
        assert not ipv4.search(t), p
        assert "betahof.com" not in t and "betahof.de" not in t, p


def test_sshd_template():
    t = _read("sshd-betacodex.conf")
    assert re.search(r"^Match User betacodex$", t, re.M)
    assert re.search(r"^\s*AuthorizedKeysFile /etc/ssh/authorized_keys/%u$", t, re.M)


def test_authorized_keys_example_restricts_key():
    lines = [l for l in _read("authorized_keys.example").splitlines() if l.strip() and not l.startswith("#")]
    assert len(lines) == 1
    assert lines[0].startswith('restrict,command="/usr/local/sbin/companion-deploy" ')
