"""Idee 313ad93d: Namen, die Tests/Tools auf app.main patchen, dürfen in den
ausgelagerten Modulen nur als `main.NAME` gelesen werden - sonst greift der
Patch dort nicht."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _main_aliases(tree) -> set[str]:
    return {
        a.asname or a.name
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module == "app"
        for a in n.names
        if a.name == "main"
    }


def _patched_names() -> set[str]:
    names = set()
    for path in [*(ROOT / "tests").glob("*.py"), *(ROOT / "tools").glob("*.py")]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = _main_aliases(tree)
        for n in ast.walk(tree):
            if (
                isinstance(n, ast.Call)
                and len(n.args) > 1
                and isinstance(n.args[0], ast.Name)
                and n.args[0].id in aliases
                and isinstance(n.args[1], ast.Constant)
                and isinstance(n.args[1].value, str)
                and ast.unparse(n.func).endswith(("setattr", "delattr", "patch.object"))
            ):
                names.add(n.args[1].value)
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id in aliases:
                        names.add(t.attr)
    return names


def test_patched_main_names_are_only_read_via_main_in_other_modules():
    patched = _patched_names()
    assert "_load_sources" in patched  # Selbstprüfung des Sammlers
    bad = []
    for path in sorted((ROOT / "app").glob("*.py")):
        if path.name == "main.py":
            continue
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in patched:
                bad.append(f"{path.name}:{n.lineno} {n.id}")
    assert not bad, bad
