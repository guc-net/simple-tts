#!/usr/bin/env python3
"""
On-disk audio cache for simple-tts' edge engine, with usage metadata and
size-based eviction.

Each synthesized phrase is stored as `<sha256(engine,voice,rate,text[,pitch])>.mp3`
in CACHE_DIR — pitch only joins the hash when it's non-default, so entries cached
before `edge_pitch` existed (or at the default pitch) keep resolving to the same
key instead of being silently orphaned by the new field. A single `index.json`
(guarded by flock) records per-entry metadata: the spoken text, voice, rate,
play count, and created / last-used timestamps.

Eviction is driven by a TOTAL SIZE budget (`cache_max_mb`), not a file count:
when the cache exceeds the budget, entries are removed least-used first, oldest
as the tie-break (`(plays, last_used)` ascending), and only as many as needed to
get back under budget. Entries whose mp3 has vanished are reconciled away; mp3s
with no index row are treated as plays=0, last_used=mtime so they still evict.
"""

import fcntl
import hashlib
import json
import os
import time

CACHE_DIR = os.path.expanduser("~/.claude/simple-tts-audio-cache")
INDEX_NAME = "index.json"
TMP_PREFIX = ".synthtmp-"
TMP_MAX_AGE = 60          # seconds; older temp files are orphans from a killed synth
DEFAULT_MAX_MB = 100


DEFAULT_PITCH = "+0Hz"


def key_for(payload):
    """Content-addressed key: SHA-256 over engine, voice, rate, text — plus
    pitch, but only when it's non-default, so pre-existing cache entries at
    the default pitch (all of them, before this field existed) still hit."""
    parts = ["edge", payload.get("edge_voice", ""),
             payload.get("edge_rate", "+0%"), payload.get("text", "")]
    pitch = payload.get("edge_pitch", DEFAULT_PITCH)
    if pitch != DEFAULT_PITCH:
        parts.append(pitch)
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


def cache_path(payload):
    return os.path.join(CACHE_DIR, f"{key_for(payload)}.mp3")


def env_path_for_key(key):
    """Ścieżka obwiedni głosu obok wpisu audio (ten sam hash frazy)."""
    return os.path.join(CACHE_DIR, f"{key}.env.json")


def read_env(key):
    """(dt, env) zapisanej obwiedni dla `key`, albo None gdy brak/uszkodzona."""
    try:
        with open(env_path_for_key(key)) as f:
            d = json.load(f)
        dt, env = float(d["dt"]), d["env"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(env, list) or not env:
        return None
    return (dt, env)


def store_env(key, dt, env):
    """Zapisz obwiednię obok pliku audio (atomowo). Cicho pomija błędy I/O i
    pustą obwiednię — obwiednia to tylko modulator nakładki, nie audio."""
    if not env:
        return
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = env_path_for_key(key)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump({"dt": dt, "env": env}, f)
        os.replace(tmp, path)
    except OSError:
        pass


def _unlink_env(key):
    """Usuń plik obwiedni danego wpisu (best-effort)."""
    try:
        os.unlink(env_path_for_key(key))
    except OSError:
        pass


def _prune_orphan_envs(live_keys):
    """Usuń pliki obwiedni, których mp3 już nie ma na dysku (np. skasowane z
    zewnątrz) — inaczej sieroty .env.json rosłyby bez końca."""
    try:
        names = os.listdir(CACHE_DIR)
    except OSError:
        return
    for name in names:
        if not name.endswith(".env.json"):
            continue
        if name[:-len(".env.json")] not in live_keys:
            try:
                os.unlink(os.path.join(CACHE_DIR, name))
            except OSError:
                pass


def _index_path():
    return os.path.join(CACHE_DIR, INDEX_NAME)


def _load_index():
    try:
        with open(_index_path()) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return {}


def _save_index(index):
    tmp = _index_path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(index, f, ensure_ascii=False)
    os.replace(tmp, _index_path())


def _with_index(mutator):
    """Run mutator(index) under an exclusive lock, then persist the index."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_index_path() + ".lock", "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        index = _load_index()
        result = mutator(index)
        _save_index(index)
        return result


def record_store(key, text, voice, rate, size, now=None):
    """Register a freshly stored entry (play count starts at 1)."""
    ts = time.time() if now is None else now

    def mutate(index):
        index[key] = {"text": text, "voice": voice, "rate": rate,
                      "plays": 1, "created": ts, "last_used": ts, "size": size}
    _with_index(mutate)


def record_hit(key, now=None):
    """Bump play count and last-used time for a cache hit."""
    ts = time.time() if now is None else now

    def mutate(index):
        entry = index.get(key)
        if entry:
            entry["plays"] = entry.get("plays", 0) + 1
            entry["last_used"] = ts
    _with_index(mutate)


def _disk_entries(index):
    """Reconcile index with the mp3 files actually on disk."""
    entries = []
    try:
        names = os.listdir(CACHE_DIR)
    except OSError:
        return entries
    for name in names:
        if not name.endswith(".mp3") or name.startswith(TMP_PREFIX):
            continue
        key = name[:-4]
        path = os.path.join(CACHE_DIR, name)
        try:
            size = os.path.getsize(path)
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        meta = index.get(key, {})
        entries.append({
            "key": key, "path": path, "size": size,
            "plays": meta.get("plays", 0),
            "last_used": meta.get("last_used", mtime),
            "created": meta.get("created", mtime),
            "text": meta.get("text", ""),
            "voice": meta.get("voice", ""),
        })
    return entries


def evict(max_bytes, now=None):
    """Delete least-used-then-oldest entries until total size <= max_bytes.

    Returns the number of bytes freed. Only removes what is necessary.
    """
    def mutate(index):
        entries = _disk_entries(index)
        # Drop index rows whose mp3 is gone.
        live = {e["key"] for e in entries}
        for stale in [k for k in index if k not in live]:
            del index[stale]
        _prune_orphan_envs(live)              # obwiednie bez mp3 (kasowane z zewnątrz)

        total = sum(e["size"] for e in entries)
        if total <= max_bytes:
            return 0

        # Least plays first, oldest last_used as the tie-break.
        entries.sort(key=lambda e: (e["plays"], e["last_used"]))
        freed = 0
        for e in entries:
            if total - freed <= max_bytes:
                break
            try:
                os.unlink(e["path"])
            except OSError:
                continue
            _unlink_env(e["key"])             # obwiednia znika razem z mp3
            index.pop(e["key"], None)
            freed += e["size"]
        return freed

    return _with_index(mutate)


def stats():
    """Return cache contents and totals, most-played first."""
    index = _load_index()
    entries = _disk_entries(index)
    entries.sort(key=lambda e: (e["plays"], e["last_used"]), reverse=True)
    return {
        "entries": entries,
        "count": len(entries),
        "total_bytes": sum(e["size"] for e in entries),
    }


def clear():
    """Remove every cache entry (mp3s, envelopes, temp files and the index)."""
    removed = 0
    try:
        names = os.listdir(CACHE_DIR)
    except OSError:
        return 0
    for name in names:
        if (name.endswith(".mp3") or name.endswith(".env.json")
                or name == INDEX_NAME or name.startswith(TMP_PREFIX)):
            try:
                os.unlink(os.path.join(CACHE_DIR, name))
                removed += 1
            except OSError:
                pass
    return removed


def sweep_temp(now=None):
    """Remove temp files orphaned by an interrupted synth (killpg/crash)."""
    ts = time.time() if now is None else now
    try:
        names = os.listdir(CACHE_DIR)
    except OSError:
        return
    for name in names:
        if not (name.startswith(TMP_PREFIX) and name.endswith(".mp3")):
            continue
        path = os.path.join(CACHE_DIR, name)
        try:
            if ts - os.path.getmtime(path) > TMP_MAX_AGE:
                os.unlink(path)
        except OSError:
            pass
