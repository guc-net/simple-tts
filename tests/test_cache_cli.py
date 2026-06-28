"""Tests for cache_cli.py — the `/tts cache` backend (stats formatting)."""

import os

import audio_cache as ac
import cache_cli
import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "CACHE_DIR", str(tmp_path / "audiocache"))
    os.makedirs(ac.CACHE_DIR, exist_ok=True)


def _make(key, size, plays, last_used, text):
    with open(os.path.join(ac.CACHE_DIR, f"{key}.mp3"), "wb") as f:
        f.write(b"x" * size)

    def mutate(index):
        index[key] = {"text": text, "voice": "v", "rate": "+0%",
                      "plays": plays, "created": last_used,
                      "last_used": last_used, "size": size}
    ac._with_index(mutate)


def test_stats_shows_most_popular_section_first(capsys):
    _make("a", 10, plays=2, last_used=1000, text="rzadkie zdanie")
    _make("b", 10, plays=42, last_used=1000, text="ulubione zdanie")
    cache_cli.cmd_stats()
    out = capsys.readouterr().out
    assert "Najpopularniejsze" in out
    # the most-played phrase appears in the popular section, before the full list
    popular_idx = out.index("ulubione zdanie")
    rare_idx = out.index("rzadkie zdanie")
    assert popular_idx < rare_idx
    assert "42×" in out


def test_stats_handles_no_plays_yet(capsys):
    _make("a", 10, plays=0, last_used=1000, text="x")
    cache_cli.cmd_stats()
    out = capsys.readouterr().out
    assert "Najpopularniejsze" in out
    assert "jeszcze nic nie odtworzono" in out


def test_empty_cache_is_reported(capsys):
    cache_cli.cmd_stats()
    assert "(pusty)" in capsys.readouterr().out
