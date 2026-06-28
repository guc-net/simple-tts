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


def test_stats_lists_most_played_first(capsys):
    _make("a", 10, plays=2, last_used=1000, text="rzadkie zdanie")
    _make("b", 10, plays=42, last_used=1000, text="ulubione zdanie")
    cache_cli.cmd_stats()
    out = capsys.readouterr().out
    assert out.index("ulubione zdanie") < out.index("rzadkie zdanie")
    assert "42" in out


def test_stats_shows_only_top_10(capsys):
    for i in range(15):
        _make(f"k{i:02d}", 10, plays=i, last_used=1000, text=f"zdanie numer {i:02d}")
    cache_cli.cmd_stats()
    out = capsys.readouterr().out
    # top 10 by plays = 14..05 are shown; 04..00 are not
    assert "zdanie numer 14" in out
    assert "zdanie numer 05" in out
    assert "zdanie numer 04" not in out
    assert "i 5 więcej" in out


def test_empty_cache_is_reported(capsys):
    cache_cli.cmd_stats()
    assert "(pusty)" in capsys.readouterr().out
