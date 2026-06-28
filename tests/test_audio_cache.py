"""Tests for audio_cache.py — usage metadata and size-based eviction."""

import os

import audio_cache as ac
import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "CACHE_DIR", str(tmp_path / "audiocache"))
    os.makedirs(ac.CACHE_DIR, exist_ok=True)


def _make(key, size, plays, last_used, text="zdanie"):
    """Create an mp3 of `size` bytes plus its index row."""
    with open(os.path.join(ac.CACHE_DIR, f"{key}.mp3"), "wb") as f:
        f.write(b"x" * size)

    def mutate(index):
        index[key] = {"text": text, "voice": "v", "rate": "+0%",
                      "plays": plays, "created": last_used,
                      "last_used": last_used, "size": size}
    ac._with_index(mutate)


def _keys_on_disk():
    return sorted(n[:-4] for n in os.listdir(ac.CACHE_DIR) if n.endswith(".mp3"))


def test_cache_path_is_deterministic_and_voice_specific():
    p = {"edge_voice": "Marek", "edge_rate": "+0%", "text": "cześć"}
    assert ac.cache_path(p) == ac.cache_path(dict(p))
    assert ac.cache_path(p) != ac.cache_path({**p, "edge_voice": "Zofia"})


def test_record_store_then_stats():
    ac.record_store("k1", "dzień dobry", "Marek", "+0%", 1234, now=1000)
    s = ac.stats()
    assert s["count"] == 0  # no mp3 on disk yet → reconciled out
    open(os.path.join(ac.CACHE_DIR, "k1.mp3"), "wb").write(b"x" * 1234)
    s = ac.stats()
    assert s["count"] == 1
    assert s["entries"][0]["plays"] == 1
    assert s["entries"][0]["text"] == "dzień dobry"


def test_record_hit_increments_plays():
    _make("k", 10, plays=1, last_used=1000)
    ac.record_hit("k", now=2000)
    ac.record_hit("k", now=3000)
    entry = ac.stats()["entries"][0]
    assert entry["plays"] == 3
    assert entry["last_used"] == 3000


def test_evict_removes_least_played_first():
    _make("hot", 100, plays=5, last_used=1000)
    _make("cold", 100, plays=1, last_used=1000)
    freed = ac.evict(100)  # 200 total, budget 100 → drop one
    assert freed == 100
    assert _keys_on_disk() == ["hot"]  # kept the more-played one


def test_evict_tie_break_is_oldest():
    _make("old", 100, plays=2, last_used=1000)
    _make("new", 100, plays=2, last_used=5000)
    ac.evict(100)
    assert _keys_on_disk() == ["new"]  # same plays → older evicted


def test_evict_only_removes_what_is_necessary():
    _make("a", 100, plays=1, last_used=1000)
    _make("b", 100, plays=2, last_used=1000)
    _make("c", 100, plays=3, last_used=1000)
    freed = ac.evict(150)  # 300 -> must drop 2 to reach <=150
    assert freed == 200
    assert _keys_on_disk() == ["c"]  # the most-played survives


def test_evict_noop_when_under_budget():
    _make("a", 100, plays=1, last_used=1000)
    assert ac.evict(1024 * 1024) == 0
    assert _keys_on_disk() == ["a"]


def test_orphan_mp3_without_metadata_is_evictable():
    with open(os.path.join(ac.CACHE_DIR, "orphan.mp3"), "wb") as f:
        f.write(b"x" * 200)
    _make("tracked", 100, plays=9, last_used=9000)
    ac.evict(150)  # 300 total -> drop orphan (plays=0) first
    assert _keys_on_disk() == ["tracked"]


def test_clear_empties_everything():
    _make("a", 100, plays=1, last_used=1000)
    _make("b", 100, plays=1, last_used=1000)
    ac.clear()
    assert _keys_on_disk() == []
    assert ac.stats()["count"] == 0
