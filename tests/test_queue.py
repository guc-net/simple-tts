"""Testy prymitywów plikowej kolejki mowy (_queue_enqueue/_queue_pop/_queue_clear).

Prymitywy same nie mają locka — w produkcji wołane są wyłącznie pod flockiem
stanu (_locked_state na STATE_PATH); tu testujemy je bezpośrednio, bez locka,
bo to wystarcza do sprawdzenia ich zachowania na plikach.
"""

import json
import os
import sys
import time

HOOKS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
sys.path.insert(0, HOOKS_DIR)

import tts_utils  # noqa: E402


def test_enqueue_creates_dir_and_file_with_payload_and_timestamp(isolated_paths):
    tts_utils._queue_enqueue({"text": "cześć"})
    queue_dir = isolated_paths / "queue.d"
    assert queue_dir.is_dir()
    files = list(queue_dir.iterdir())
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["payload"] == {"text": "cześć"}
    assert isinstance(data["enqueued_at"], float)


def test_pop_returns_payloads_in_fifo_order_and_unlinks_files(isolated_paths):
    tts_utils._queue_enqueue({"text": "pierwszy"})
    time.sleep(0.001)  # różne time_ns() w tym samym procesie
    tts_utils._queue_enqueue({"text": "drugi"})
    queue_dir = isolated_paths / "queue.d"
    assert len(list(queue_dir.iterdir())) == 2

    first = tts_utils._queue_pop()
    assert first == {"text": "pierwszy"}
    assert len(list(queue_dir.iterdir())) == 1

    second = tts_utils._queue_pop()
    assert second == {"text": "drugi"}
    assert len(list(queue_dir.iterdir())) == 0


def test_pop_on_empty_dir_returns_none(isolated_paths):
    (isolated_paths / "queue.d").mkdir()
    assert tts_utils._queue_pop() is None


def test_pop_without_dir_returns_none(isolated_paths):
    assert not (isolated_paths / "queue.d").exists()
    assert tts_utils._queue_pop() is None


def test_pop_skips_and_removes_expired_entry(isolated_paths):
    tts_utils._queue_enqueue({"text": "stary"})
    queue_dir = isolated_paths / "queue.d"
    entry = next(queue_dir.iterdir())
    data = json.loads(entry.read_text())
    data["enqueued_at"] = time.time() - 60   # starszy niż QUEUE_TTL_SECS (40s)
    entry.write_text(json.dumps(data))

    assert tts_utils._queue_pop() is None
    assert not entry.exists()


def test_pop_skips_and_removes_corrupted_json(isolated_paths):
    queue_dir = isolated_paths / "queue.d"
    queue_dir.mkdir()
    broken = queue_dir / f"{time.time_ns()}-999.json"
    broken.write_text("{not valid json")

    tts_utils._queue_enqueue({"text": "świeży"})  # następny wpis, powinien wrócić

    result = tts_utils._queue_pop()
    assert result == {"text": "świeży"}
    assert not broken.exists()


def test_enqueue_enforces_queue_max_evicting_oldest(isolated_paths):
    for i in range(9):
        tts_utils._queue_enqueue({"text": f"wpis-{i}"})
        time.sleep(0.001)

    queue_dir = isolated_paths / "queue.d"
    files = list(queue_dir.iterdir())
    assert len(files) == tts_utils.QUEUE_MAX == 8

    payloads = []
    while True:
        p = tts_utils._queue_pop()
        if p is None:
            break
        payloads.append(p["text"])
    assert payloads == [f"wpis-{i}" for i in range(1, 9)]   # wpis-0 wypadł
    assert "wpis-0" not in payloads


def test_clear_removes_all_entries(isolated_paths):
    tts_utils._queue_enqueue({"text": "a"})
    tts_utils._queue_enqueue({"text": "b"})
    queue_dir = isolated_paths / "queue.d"
    assert len(list(queue_dir.iterdir())) >= 1

    tts_utils._queue_clear()
    assert list(queue_dir.iterdir()) == []


def test_clear_without_dir_does_not_raise(isolated_paths):
    assert not (isolated_paths / "queue.d").exists()
    tts_utils._queue_clear()   # nie rzuca
