"""Deploy-Gate in .github/workflows/deploy.yml (Idee 2aff0aa3).

Der Workflow läuft jetzt auch bei main-Pushes (Cache füllen). Deshalb muss
der Deploy-Job hart auf Tags und auf grüne Tests begrenzt bleiben."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TEXT = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
WF = yaml.safe_load(TEXT)
JOBS = WF["jobs"]


def test_deploy_wartet_auf_tests():
    assert JOBS["deploy"]["needs"] == "test" or JOBS["deploy"]["needs"] == ["test"]


def test_deploy_nur_bei_tag_und_ohne_gate_umgehung():
    cond = str(JOBS["deploy"].get("if", ""))
    assert "startsWith(github.ref, 'refs/tags/v')" in cond
    for verboten in ("always(", "!cancelled(", "failure("):
        assert verboten not in cond


def test_deploy_schluessel_nur_im_deploy_job():
    assert "DEPLOY_SSH_KEY" not in yaml.safe_dump(JOBS["test"])
    assert "DEPLOY_SSH_KEY" in yaml.safe_dump(JOBS["deploy"])


def test_cache_wird_nur_von_main_gespeichert():
    saves = [s for s in JOBS["test"]["steps"] if "cache/save" in s.get("uses", "")]
    assert saves, "kein cache/save-Schritt"
    for s in saves:
        assert "refs/heads/main" in s.get("if", ""), s


def test_workflow_nur_lesend():
    assert WF["permissions"] == {"contents": "read"}


def test_main_push_ist_trigger():
    trig = WF.get("on", WF.get(True))
    assert trig["push"]["branches"] == ["main"]
    assert trig["push"]["tags"] == ["v*"]
