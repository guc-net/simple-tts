# Busy-aware notification suppression + question read-aloud — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nie wypowiadać fałszywego „Czekam na odpowiedź", gdy agent nadal pracuje (tura trwa), a zamiast tego od razu czytać treść realnego pytania decyzyjnego.

**Architecture:** Dwie niezależne części. (A) Filtr w `notification_tts.py`: bezczynne zdarzenia `waiting` są wyciszane, gdy znacznik `busy` tej sesji jest świeży; prośby o zgodę (`permission`) mówimy zawsze. (B) Nowy hook `ask_question_tts.py` na PreToolUse (`AskUserQuestion|ExitPlanMode`) wypowiadający treść pytania natychmiast. Nowy helper `session_busy_fresh` w `tts_utils.py`.

**Tech Stack:** Python 3 stdlib; pytest (`uvx --with pytest pytest`); ruff (`uvx ruff check .`). Hooki rejestrowane w `hooks/hooks.json`.

## Global Constraints

- Hooki są **stdlib-only** — żadnych zależności zewnętrznych w `hooks/`.
- Każdy hook jest **cichym no-opem**, gdy `load_config()` zwróci `None` (plugin włączony, setup nie uruchomiony).
- Testy nigdy nie mówią ani nie dotykają realnego `~/.claude` — `conftest.py` przekierowuje ścieżki i podmienia `subprocess.Popen`. Hooki w testach woła się przez `monkeypatch` na module-level `read_hook_input`/`speak`, a `main()` kończy się `SystemExit` (asercja `pytest.raises(SystemExit)`).
- `speak()` sam sanitizuje tekst (`sanitize_for_tts`) — **nie** sanitizować drugi raz przed wywołaniem `speak`.
- Katalogi fraz per język pokrywają klucze: `pl`, `en`, `de`, `fr` (spójnie z `MESSAGES` w `notification_tts.py`).
- Commit messages kończą się linią `Claude-Session: https://claude.ai/code/session_01ScuQQ7XP6A9Arkp7U9KvEf`.

**Pre-flight (opcjonalny de-risk, nieblokujący):** przed implementacją można raz ustawić `"debug": true` w `~/.claude/simple-tts-config.json` i potwierdzić na żywej sesji, że fałszywe `waiting` ma świeży busy oraz że PreToolUse odpala się dla `AskUserQuestion`. Implementacja jest bezpieczna niezależnie od wyniku (gdy Część B się nie odpali, nic się nie psuje).

---

### Task 1: Helper `session_busy_fresh` w `tts_utils.py`

**Files:**
- Modify: `hooks/tts_utils.py` (dodać stałą `BUSY_STALE_SECS` i funkcję `session_busy_fresh` obok `_busy_marker` / `set_session_busy`, ok. linii 307–331)
- Test: `tests/test_busy.py`

**Interfaces:**
- Consumes: `_busy_marker(session_id)`, moduły `os`, `time` (już importowane w `tts_utils`).
- Produces: `BUSY_STALE_SECS = 900`; `session_busy_fresh(session_id, max_age=BUSY_STALE_SECS) -> bool`.

- [ ] **Step 1: Write the failing tests**

W `tests/test_busy.py` dodaj `import time` na górze (obok istniejących importów) oraz na końcu pliku:

```python
def test_session_busy_fresh_true_when_recent(isolated_paths):
    tts_utils.set_session_busy("s1", True)
    assert tts_utils.session_busy_fresh("s1") is True


def test_session_busy_fresh_false_when_absent(isolated_paths):
    assert tts_utils.session_busy_fresh("nope") is False


def test_session_busy_fresh_false_when_stale(isolated_paths):
    tts_utils.set_session_busy("s2", True)
    marker = isolated_paths / "busy.d" / "s2"
    marker.write_text(str(int(time.time()) - 20 * 60))   # znacznik sprzed 20 min
    assert tts_utils.session_busy_fresh("s2") is False


def test_session_busy_fresh_none_session_is_false(isolated_paths):
    assert tts_utils.session_busy_fresh(None) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uvx --with pytest pytest tests/test_busy.py -q -k session_busy_fresh`
Expected: FAIL — `AttributeError: module 'tts_utils' has no attribute 'session_busy_fresh'`.

- [ ] **Step 3: Write minimal implementation**

W `hooks/tts_utils.py`, tuż po funkcji `_busy_marker` (ok. linii 309) dodaj:

```python
BUSY_STALE_SECS = 15 * 60  # okno świeżości znacznika busy (jak overlay/kitt_state)


def session_busy_fresh(session_id, max_age=BUSY_STALE_SECS):
    """True, gdy znacznik busy tej sesji istnieje i jego timestamp jest
    świeższy niż max_age sekund. Timestamp czytamy z treści pliku
    (int(time.time()) zapisany przez _set_session_marker); przy pustej/
    niepoprawnej treści wracamy do st_mtime. Fail-safe: brak pliku / dowolny
    błąd → False (mowa zostaje włączona)."""
    marker = _busy_marker(session_id)
    try:
        try:
            with open(marker) as f:
                ts = int(f.read().strip())
        except (ValueError, OSError):
            ts = int(os.stat(marker).st_mtime)
        return (time.time() - ts) < max_age
    except OSError:
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uvx --with pytest pytest tests/test_busy.py -q -k session_busy_fresh`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add hooks/tts_utils.py tests/test_busy.py
git commit -m "feat: session_busy_fresh helper for busy-aware TTS gating

Claude-Session: https://claude.ai/code/session_01ScuQQ7XP6A9Arkp7U9KvEf"
```

---

### Task 2: Filtr busy w `notification_tts.py`

**Files:**
- Modify: `hooks/notification_tts.py` (import + `main()`, linie 16–22 oraz 102–118)
- Test: `tests/test_busy.py`

**Interfaces:**
- Consumes: `session_busy_fresh` (Task 1), `set_session_attention`, `speak`, `translate_notification`, `MESSAGES`.
- Produces: zmienione zachowanie `main()` — brak nowych symboli publicznych.

- [ ] **Step 1: Write the failing tests**

Na końcu `tests/test_busy.py` dodaj:

```python
def test_notification_suppressed_when_busy(write_config, isolated_paths, monkeypatch):
    """Bezczynne 'waiting' w trakcie trwającej tury (świeży busy) -> cisza,
    bez zapalania attention."""
    write_config()
    tts_utils.set_session_busy("sB", True)
    import notification_tts
    spoke = []
    monkeypatch.setattr(notification_tts, "read_hook_input", lambda: {
        "session_id": "sB", "message": "Claude is waiting for your input"})
    monkeypatch.setattr(notification_tts, "speak", lambda *a, **k: spoke.append(a))
    with pytest.raises(SystemExit):
        notification_tts.main()
    assert spoke == []
    assert not (isolated_paths / "attention.d" / "sB").exists()


def test_notification_permission_speaks_even_when_busy(write_config, isolated_paths, monkeypatch):
    """Prośba o zgodę mówi zawsze, nawet w trakcie trwającej tury."""
    write_config()
    tts_utils.set_session_busy("sP", True)
    import notification_tts
    spoke = []
    monkeypatch.setattr(notification_tts, "read_hook_input", lambda: {
        "session_id": "sP", "message": "Claude needs your permission to use Bash"})
    monkeypatch.setattr(notification_tts, "speak", lambda *a, **k: spoke.append(a))
    with pytest.raises(SystemExit):
        notification_tts.main()
    assert spoke                                            # coś powiedziano
    assert (isolated_paths / "attention.d" / "sP").exists()


def test_notification_speaks_when_not_busy(write_config, isolated_paths, monkeypatch):
    """Realne bezczynne czekanie (brak busy = tura się skończyła) -> mówi."""
    write_config()
    import notification_tts
    spoke = []
    monkeypatch.setattr(notification_tts, "read_hook_input", lambda: {
        "session_id": "sN", "message": "Claude is waiting for your input"})
    monkeypatch.setattr(notification_tts, "speak", lambda *a, **k: spoke.append(a))
    with pytest.raises(SystemExit):
        notification_tts.main()
    assert spoke
    assert (isolated_paths / "attention.d" / "sN").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uvx --with pytest pytest tests/test_busy.py -q -k notification`
Expected: FAIL — `test_notification_suppressed_when_busy` mówi/ustawia attention (obecny kod nie filtruje), więc asercje `spoke == []` / brak markera nie przechodzą. Pozostałe dwa mogą już przechodzić.

- [ ] **Step 3: Write minimal implementation**

W `hooks/notification_tts.py` rozszerz import (linie 16–22) o `session_busy_fresh`:

```python
from tts_utils import (
    language_code,
    load_config,
    read_hook_input,
    session_busy_fresh,
    set_session_attention,
    speak,
)
```

Zamień treść `main()` (linie 102–118) na:

```python
def main():
    config = load_config()
    if config is None:
        sys.exit(0)

    input_data = read_hook_input()
    debug(input_data, config.get('debug', False))

    session_id = input_data.get('session_id')
    message = input_data.get('message', '')

    # Prośby o zgodę mówimy zawsze (realna decyzja użytkownika). Pozostałe
    # zdarzenia (bezczynne "waiting" itp.) w trakcie trwającej tury są fałszywe
    # — agent nadal pracuje (np. czeka na subagentów) — więc milczymy i nie
    # zapalamy trybu "attention" w nakładce.
    is_permission = 'permission' in message.lower()
    if not is_permission and session_busy_fresh(session_id):
        sys.exit(0)

    # Sesja czeka na użytkownika -> tryb "attention" nakładki. Znacznik idzie
    # niezależnie od mute/quiet hours (wizual jest osobny od mowy); zdejmuje go
    # nowy prompt, wykonanie narzędzia (zgoda udzielona) albo koniec tury.
    set_session_attention(session_id, True)

    msgs = MESSAGES.get(language_code(config), MESSAGES['en'])
    tts_text = translate_notification(message, msgs)
    speak(tts_text, priority=True)
    sys.exit(0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uvx --with pytest pytest tests/test_busy.py -q`
Expected: PASS (wszystkie, łącznie z istniejącym `test_notification_hook_sets_attention` — używa wiadomości `permission`, więc mówi mimo braku busy).

- [ ] **Step 5: Commit**

```bash
git add hooks/notification_tts.py tests/test_busy.py
git commit -m "feat: suppress false 'waiting' notification while turn is busy

Prośby o zgodę mówimy zawsze; bezczynne 'waiting' w trakcie trwającej tury
(świeży busy) jest wyciszane, bez zapalania trybu attention nakładki.

Claude-Session: https://claude.ai/code/session_01ScuQQ7XP6A9Arkp7U9KvEf"
```

---

### Task 3: Hook `ask_question_tts.py` (PreToolUse) czytający treść pytania

**Files:**
- Create: `hooks/ask_question_tts.py`
- Test: `tests/test_ask_question_tts.py`

**Interfaces:**
- Consumes: `load_config`, `language_code`, `read_hook_input`, `set_session_attention`, `speak` z `tts_utils`.
- Produces: `MAX_LEN = 140`; `PHRASES` (dict per język, klucze `plan`, `several`); `build_phrase(tool_name, tool_input, phrases) -> str | None`; `main()`.

- [ ] **Step 1: Write the failing tests**

Utwórz `tests/test_ask_question_tts.py`:

```python
"""Testy hooka PreToolUse czytającego treść realnego pytania decyzyjnego."""

import io
import os
import sys

import pytest

HOOKS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
sys.path.insert(0, HOOKS_DIR)

import ask_question_tts  # noqa: E402


class TestBuildPhrase:
    def setup_method(self):
        self.p = ask_question_tts.PHRASES['pl']

    def test_single_question(self):
        ti = {"questions": [{"question": "Której biblioteki użyć?"}]}
        assert ask_question_tts.build_phrase("AskUserQuestion", ti, self.p) == \
            "Której biblioteki użyć?"

    def test_several_questions_reads_first(self):
        ti = {"questions": [{"question": "Pierwsze pytanie?"},
                            {"question": "Drugie pytanie?"}]}
        out = ask_question_tts.build_phrase("AskUserQuestion", ti, self.p)
        assert out == "Mam kilka pytań, pierwsze: Pierwsze pytanie?"

    def test_exit_plan_mode(self):
        assert ask_question_tts.build_phrase("ExitPlanMode", {}, self.p) == \
            "Plan gotowy, zatwierdzić?"

    def test_empty_questions_returns_none(self):
        assert ask_question_tts.build_phrase(
            "AskUserQuestion", {"questions": []}, self.p) is None

    def test_other_tool_returns_none(self):
        assert ask_question_tts.build_phrase("Bash", {"command": "ls"}, self.p) is None

    def test_long_question_truncated(self):
        ti = {"questions": [{"question": "słowo " * 60}]}
        out = ask_question_tts.build_phrase("AskUserQuestion", ti, self.p)
        assert len(out) <= ask_question_tts.MAX_LEN + 1     # +1 na znak …
        assert out.endswith("…")


def test_all_phrase_catalogs_have_same_keys():
    for lang in ("pl", "en", "de", "fr"):
        assert set(ask_question_tts.PHRASES[lang]) == set(ask_question_tts.PHRASES["en"])


def test_hook_speaks_and_sets_attention(write_config, isolated_paths, monkeypatch):
    write_config()
    spoke = []
    monkeypatch.setattr(ask_question_tts, "read_hook_input", lambda: {
        "session_id": "q1", "tool_name": "AskUserQuestion",
        "tool_input": {"questions": [{"question": "Czy wdrażamy?"}]}})
    monkeypatch.setattr(ask_question_tts, "speak",
                        lambda text, **k: spoke.append((text, k)))
    with pytest.raises(SystemExit):
        ask_question_tts.main()
    assert spoke and "Czy wdrażamy?" in spoke[0][0]
    assert spoke[0][1].get("priority") is True
    assert (isolated_paths / "attention.d" / "q1").exists()


def test_hook_noop_without_config(isolated_paths, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO('{"tool_name": "AskUserQuestion"}'))
    with pytest.raises(SystemExit):
        ask_question_tts.main()
    assert not (isolated_paths / "attention.d").exists()


def test_hook_noop_for_other_tool(write_config, isolated_paths, monkeypatch):
    write_config()
    spoke = []
    monkeypatch.setattr(ask_question_tts, "read_hook_input", lambda: {
        "session_id": "q2", "tool_name": "Bash", "tool_input": {"command": "ls"}})
    monkeypatch.setattr(ask_question_tts, "speak", lambda *a, **k: spoke.append(a))
    with pytest.raises(SystemExit):
        ask_question_tts.main()
    assert spoke == []
    assert not (isolated_paths / "attention.d" / "q2").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uvx --with pytest pytest tests/test_ask_question_tts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ask_question_tts'`.

- [ ] **Step 3: Write minimal implementation**

Utwórz `hooks/ask_question_tts.py`:

```python
#!/usr/bin/env python3
"""Claude Code PreToolUse hook (AskUserQuestion / ExitPlanMode): wypowiada treść
realnego pytania decyzyjnego od razu, gdy agent je zadaje — zamiast czekać na
bezczynne "waiting" po ~60 s. Ustawia też znacznik 'attention' nakładki. Cichy
no-op bez configu i dla innych narzędzi (matcher w hooks.json zawęża, ale hook
broni się też sam)."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from tts_utils import (
    language_code,
    load_config,
    read_hook_input,
    set_session_attention,
    speak,
)

MAX_LEN = 140

PHRASES = {
    'pl': {'plan': "Plan gotowy, zatwierdzić?",
           'several': "Mam kilka pytań, pierwsze: {q}"},
    'en': {'plan': "Plan ready, approve it?",
           'several': "I have a few questions, first: {q}"},
    'de': {'plan': "Plan fertig, genehmigen?",
           'several': "Ich habe mehrere Fragen, erste: {q}"},
    'fr': {'plan': "Plan prêt, approuver ?",
           'several': "J'ai plusieurs questions, la première : {q}"},
}


def _truncate(text, limit=MAX_LEN):
    """Zbij whitespace i przytnij na granicy słowa, dokładając '…'."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def build_phrase(tool_name, tool_input, phrases):
    """Fraza do wypowiedzenia albo None, gdy nie ma czego mówić."""
    if tool_name == "ExitPlanMode":
        return phrases['plan']
    if tool_name == "AskUserQuestion":
        questions = (tool_input or {}).get("questions") or []
        texts = [q.get("question", "").strip() for q in questions
                 if isinstance(q, dict) and q.get("question", "").strip()]
        if not texts:
            return None
        if len(texts) == 1:
            return _truncate(texts[0])
        return phrases['several'].format(q=_truncate(texts[0]))
    return None


def main():
    config = load_config()
    if config is None:
        sys.exit(0)

    input_data = read_hook_input()
    phrases = PHRASES.get(language_code(config), PHRASES['en'])
    text = build_phrase(input_data.get("tool_name", ""),
                        input_data.get("tool_input", {}), phrases)
    if not text:
        sys.exit(0)

    # Realne pytanie -> sesja czeka na użytkownika (tryb attention nakładki).
    set_session_attention(input_data.get("session_id"), True)
    speak(text, priority=True)   # speak() sam sanitizuje tekst
    sys.exit(0)


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uvx --with pytest pytest tests/test_ask_question_tts.py -q`
Expected: PASS (wszystkie).

- [ ] **Step 5: Commit**

```bash
git add hooks/ask_question_tts.py tests/test_ask_question_tts.py
git commit -m "feat: PreToolUse hook speaking the actual decision question

AskUserQuestion / ExitPlanMode -> od razu czyta treść pytania (priority),
zamiast czekać na bezczynne 'waiting'. Ustawia znacznik attention.

Claude-Session: https://claude.ai/code/session_01ScuQQ7XP6A9Arkp7U9KvEf"
```

---

### Task 4: Rejestracja hooka + dokumentacja

**Files:**
- Modify: `hooks/hooks.json` (dodać blok `PreToolUse`)
- Modify: `CLAUDE.md` (opis nowego hooka i zmian)

**Interfaces:**
- Consumes: `hooks/ask_question_tts.py` (Task 3).
- Produces: rejestracja hooka w Claude Code przez `${CLAUDE_PLUGIN_ROOT}`.

- [ ] **Step 1: Dodaj blok PreToolUse do `hooks/hooks.json`**

Wewnątrz obiektu `"hooks"`, obok pozostałych zdarzeń (np. po bloku `"PostToolUse"`, pamiętając o przecinku między blokami), dodaj:

```json
    "PreToolUse": [
      {
        "matcher": "AskUserQuestion|ExitPlanMode",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/ask_question_tts.py\"",
            "timeout": 5000
          }
        ]
      }
    ]
```

- [ ] **Step 2: Zweryfikuj, że `hooks.json` jest poprawnym JSON-em i zawiera wpis**

Run:
```bash
python3 -c "import json; h=json.load(open('hooks/hooks.json'))['hooks']; assert h['PreToolUse'][0]['matcher']=='AskUserQuestion|ExitPlanMode'; assert 'ask_question_tts.py' in h['PreToolUse'][0]['hooks'][0]['command']; print('hooks.json OK')"
```
Expected: `hooks.json OK`.

- [ ] **Step 3: Zaktualizuj `CLAUDE.md`**

W sekcji „Architecture" dodaj punkt opisujący `hooks/ask_question_tts.py` (PreToolUse na `AskUserQuestion|ExitPlanMode`, czyta treść pytania, `priority`, ustawia attention) oraz uzupełnij opis `hooks/notification_tts.py` o filtr busy (bezczynne `waiting` w trakcie trwającej tury → cisza; `permission` zawsze mówione). W „Key design decisions" dopisz zdanie o `session_busy_fresh` i regule: podczas trwającej tury jedynymi user-actionable zdarzeniami są `permission` (mówione) i `AskUserQuestion` (ogłaszane od razu przez PreToolUse), więc wyciszenie pozostałych `waiting` jest bezpieczne.

- [ ] **Step 4: Pełny lint + testy**

Run: `uvx ruff check . && uvx --with pytest pytest tests/ -q`
Expected: ruff czysto; wszystkie testy PASS.

- [ ] **Step 5: Commit**

```bash
git add hooks/hooks.json CLAUDE.md
git commit -m "feat: register ask_question_tts PreToolUse hook + docs

Claude-Session: https://claude.ai/code/session_01ScuQQ7XP6A9Arkp7U9KvEf"
```

---

## Self-Review

**Spec coverage:**
- Część A (filtr busy w notification) → Task 1 (helper) + Task 2 (filtr). ✔
- Część B (czytanie pytania, PreToolUse) → Task 3 (hook) + Task 4 (rejestracja). ✔
- Rejestracja hooks.json → Task 4. ✔
- Testy wg spec (permission mówi; waiting+busy cisza+brak attention; waiting+brak busy mówi; waiting+stale busy mówi; AskUserQuestion czyta pytanie; ExitPlanMode; brak configu; inny tool no-op) → pokryte w Task 1–3. ✔
- Dokumentacja (CLAUDE.md) → Task 4. ✔
- Edge case „brak session_id → fail-open" → `session_busy_fresh(None)` test w Task 1. ✔

**Placeholder scan:** brak TBD/TODO; cały kod i komendy podane wprost. ✔

**Type consistency:** `session_busy_fresh(session_id, max_age=BUSY_STALE_SECS) -> bool` używane identycznie w Task 1 i Task 2; `build_phrase(tool_name, tool_input, phrases)`, `PHRASES`, `MAX_LEN` spójne między Task 3 (impl) a testami. ✔

**Znane, świadome uproszczenia:** twardy kill sesji może zostawić świeży-stary busy → realne „Czekam" wyciszone maks. 15 min (`BUSY_STALE_SECS`). Zaakceptowane w spec.
