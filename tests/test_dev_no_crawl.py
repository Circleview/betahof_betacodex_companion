"""Lokale Dev-Server starten keinen Web-Crawl (Nutzerwunsch 2026-11-16).

Der wöchentliche Allowlist-Crawl (z. B. substack.com/@betacodex) lief bei jedem
lokalen Serverstart sofort los und überlebte als eigener Unterprozess das
Beenden des Servers - verwaiste Crawls blockierten /exit. Auf Dev gibt es ihn
deshalb nicht; die Produktion crawlt unverändert."""

import pytest

from app import main as main_module


def _started_targets(monkeypatch, is_dev):
    started = []

    class FakeThread:
        def __init__(self, target=None, args=(), daemon=None):
            self.target, self.args = target, args

        def start(self):
            started.append(self.args[0] if self.args else self.target)

    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", is_dev)
    monkeypatch.setattr(main_module.threading, "Thread", FakeThread)
    for name in (
        "_normalize_pflaeging_spelling_once", "_normalize_beta_kodex_spelling_once",
        "_repair_char_split_key_terms_once", "_backfill_term_languages_once",
        "_recover_interrupted_web_allowlist_indexing", "_recover_interrupted_processing_jobs",
    ):
        monkeypatch.setattr(main_module, name, lambda: None)
    monkeypatch.setattr(main_module.users, "ensure_bootstrap_admin", lambda email: None)
    main_module._start_background_workers()
    return started


def test_dev_server_starts_no_web_crawl(monkeypatch):
    started = _started_targets(monkeypatch, is_dev=True)
    assert main_module._run_web_allowlist_crawl_once not in started
    # Die übrigen Worker laufen auf Dev weiter.
    assert main_module._run_url_health_check_once in started


def test_production_still_crawls_weekly(monkeypatch):
    started = _started_targets(monkeypatch, is_dev=False)
    assert main_module._run_web_allowlist_crawl_once in started
