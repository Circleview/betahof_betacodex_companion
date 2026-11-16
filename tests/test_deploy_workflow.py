"""Deploy-Gate in .github/workflows/deploy.yml (Idee 2aff0aa3).

Der Workflow läuft auch bei main-Pushes und per Zeitplan (Cache füllen und
warm halten). Deshalb muss der Deploy-Job hart auf Tags und auf grüne Tests
begrenzt bleiben. `gate_probleme` prüft ein geparstes Workflow-Dict; die
Tests füttern es mit präparierten schlechten Varianten und dem echten
Workflow."""
import copy
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TEXT = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
WF = yaml.safe_load(TEXT)

TAG_IF = "startsWith(github.ref, 'refs/tags/v')"
MAIN_PREFIX = "github.ref == 'refs/heads/main' &&"


def gate_probleme(wf):
    p = []
    jobs = wf["jobs"]
    dep = jobs["deploy"]
    if dep.get("needs") not in ("test", ["test"]):
        p.append("deploy braucht needs: test")
    if str(dep.get("if", "")).strip() != TAG_IF:
        p.append("deploy-if ist nicht exakt der Tag-Test")
    for name, job in jobs.items():
        if name != "deploy" and "secrets." in yaml.safe_dump(job):
            p.append(f"secrets in Job {name}")
    test = jobs["test"]
    if test.get("continue-on-error"):
        p.append("test-Job mit continue-on-error")
    steps = test["steps"]
    saves = [s for s in steps if "cache/save" in s.get("uses", "")]
    if not saves:
        p.append("kein cache/save")
    for s in saves:
        cond = str(s.get("if", ""))
        if not cond.startswith(MAIN_PREFIX) or "||" in cond:
            p.append(f"cache/save nicht strikt main-only: {cond!r}")
    for s in steps:
        if re.match(r"actions/cache@", s.get("uses", "")):
            p.append("actions/cache@ schreibt auf jedem Ref")
        if "cache" in (s.get("with") or {}) and "setup-python" in s.get("uses", ""):
            p.append("setup-python cache:")
        if "env.ImageOS" in str(s.get("with", "")):
            p.append("env.ImageOS ist im Cache-Schlüssel leer")
    return p


def _mit(mutation):
    wf = copy.deepcopy(WF)
    mutation(wf)
    return gate_probleme(wf)


def test_echter_workflow_ist_ohne_befund():
    assert gate_probleme(WF) == []


def test_deploy_if_muss_exakt_sein():
    assert _mit(lambda w: w["jobs"]["deploy"].update({"if": f"{TAG_IF} || always()"}))
    assert _mit(lambda w: w["jobs"]["deploy"].update({"if": f"always() && {TAG_IF}"}))
    assert _mit(lambda w: w["jobs"]["deploy"].pop("if"))


def test_cache_save_if_muss_mit_main_beginnen_ohne_oder():
    def schlecht(cond):
        def m(w):
            for s in w["jobs"]["test"]["steps"]:
                if "cache/save" in s.get("uses", ""):
                    s["if"] = cond
        return m
    assert _mit(schlecht("steps.venv.outputs.cache-hit != 'true' && github.ref == 'refs/heads/main'"))
    assert _mit(schlecht("github.ref == 'refs/heads/main' || true"))
    assert _mit(schlecht("github.ref != 'refs/heads/main'"))


def test_secrets_nur_im_deploy_job():
    assert _mit(lambda w: w["jobs"]["test"]["steps"].append({"run": "echo ${{ secrets.X }}"}))


def test_test_job_ohne_continue_on_error_und_ohne_schreibenden_cache():
    assert _mit(lambda w: w["jobs"]["test"].update({"continue-on-error": True}))
    assert _mit(lambda w: w["jobs"]["test"]["steps"].append({"uses": "actions/cache@v4"}))
    assert _mit(lambda w: w["jobs"]["test"]["steps"].append(
        {"uses": "actions/setup-python@v5", "with": {"cache": "pip"}}))


def test_venv_schluessel_ohne_env_imageos():
    assert "env.ImageOS" not in TEXT


def test_workflow_nur_lesend():
    assert WF["permissions"] == {"contents": "read"}


def test_trigger_main_tags_und_zeitplan():
    trig = WF.get("on", WF.get(True))
    assert trig["push"]["branches"] == ["main"]
    assert trig["push"]["tags"] == ["v*"]
    assert trig["schedule"] and trig["schedule"][0]["cron"]


def test_hf_schluessel_enthaelt_modellnamen():
    src = (ROOT / "app" / "embeddings.py").read_text()
    modell = re.search(r'^MODEL_NAME\s*=\s*"([^"]+)"', src, re.M).group(1)
    keys = [
        s["with"]["key"]
        for s in WF["jobs"]["test"]["steps"]
        if "cache/restore" in s.get("uses", "")
        and "huggingface" in str((s.get("with") or {}).get("path", ""))
    ]
    assert keys
    assert all(modell.replace("/", "-") in k for k in keys)
