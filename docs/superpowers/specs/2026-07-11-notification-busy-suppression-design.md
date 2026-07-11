# Wyciszanie fałszywego „Czekam na odpowiedź" + czytanie realnego pytania

**Data:** 2026-07-11
**Status:** zatwierdzony projekt, gotowy do planu implementacji

## Problem

Gdy główny agent orkiestruje subagentów (`Task`) i czeka na nich dłużej niż
~60 s, Claude Code widzi bezczynny prompt i emituje zdarzenie Notification
„Claude is waiting for your input". Hook `notification_tts.py` mapuje je na
`waiting` i wypowiada „Czekam na odpowiedź" — mimo że agent realnie pracuje i
czeka jeszcze na kolejnych subagentów. Użytkownik dostaje mylący komunikat.

Cel:
1. **Nie mówić** fałszywego „Czekam", gdy agent nadal pracuje (tura trwa).
2. **Nadal mówić**, gdy naprawdę czekamy na decyzję użytkownika — a przy pytaniu
   agenta **przeczytać samą treść pytania**.

## Decyzje projektowe (ustalone z użytkownikiem)

- **Zakres wyciszenia:** „busy, ale z wyjątkiem realnych pytań" — jeśli tura
  trwa (znacznik `busy` tej sesji świeży), bezczynne `waiting` jest wyciszane;
  wyjątkiem są realne pytania/decyzje (permission, AskUserQuestion), które i tak
  są wypowiadane.
- **Treść przy decyzji:** przy pytaniu agenta czytamy **konkretną treść pytania**
  (nie tylko krótki sygnał).

## Architektura — dwie niezależne części

### Część A — filtr w `notification_tts.py`

Po sklasyfikowaniu `message` przez `translate_notification`:

| Kategoria zdarzenia | Zachowanie |
|---|---|
| `permission` (w `message` jest `permission`) | **mów** (nazwij narzędzie, jak dziś) + `set_session_attention(True)` |
| pozostałe (`waiting`/`input`/`error`/generic) **i** `session_busy_fresh(session_id)` | **cisza**: `return` bez `speak()`, **bez** ustawiania attention (overlay zostaje w trybie „think") |
| pozostałe **i** brak/nieświeży busy | **mów** (jak dziś) + `set_session_attention(True)` |

Uzasadnienie: podczas całej tury (także czekania na subagentów) znacznik `busy`
jest ustawiony (UserPromptSubmit → busy=True, Stop → busy=False). Jedyne
user-actionable zdarzenia w trakcie tury to `permission` (obsłużone osobno) oraz
`AskUserQuestion` (obsłużone w Części B, ogłaszane natychmiast). Zatem wyciszenie
pozostałych `waiting` w trakcie tury jest bezpieczne.

Nowy helper w `tts_utils.py`:

```python
BUSY_STALE_SECS = 15 * 60  # jak okno staleness w overlay/kitt_state

def session_busy_fresh(session_id, max_age=BUSY_STALE_SECS):
    """True, jeśli znacznik busy tej sesji istnieje i jego timestamp jest
    świeższy niż max_age. Czyta zawartość pliku (int(time.time()) zapisany
    przez _set_session_marker). Fail-safe: brak pliku / błąd → False."""
```

Uwaga: znacznik zapisuje `int(time.time())` w treści pliku (`_set_session_marker`),
więc `session_busy_fresh` czyta zawartość (spójnie z tym, jak overlay liczy `age`),
z fallbackiem na `st_mtime`, gdy treść jest pusta/niepoprawna.

### Część B — nowy hook `ask_question_tts.py` (PreToolUse)

Rejestrowany na `PreToolUse` z matcherem `AskUserQuestion|ExitPlanMode`.

Działanie:
- silent no-op, gdy `load_config()` zwróci `None` (jak każdy hook),
- odczyt `tool_name` i `tool_input` z wejścia,
- **AskUserQuestion:** wyciągnij `tool_input["questions"]`; zbuduj krótką frazę z
  treści pytań (pole `question`). Jedno pytanie → sама treść; kilka → „mam kilka
  pytań, pierwsze: <treść pierwszego>". Przytnij do rozsądnej długości (np. ~140
  znaków / ~20 słów),
- **ExitPlanMode:** stała krótka fraza w języku konfiguracji, np. „Plan gotowy,
  zatwierdzić?",
- `sanitize_for_tts(text, language_code(config))`, `speak(text, priority=True)`,
  `set_session_attention(session_id, True)`,
- zdarzenie odpala się **natychmiast** przy wywołaniu narzędzia (nie po 60 s),
  więc realne pytanie jest ogłoszone od razu; późniejsze bezczynne `waiting` w
  trakcie tego czekania jest już wyciszone przez Część A (brak podwójnej mowy).

Frazy stałe (ExitPlanMode, prefiks „mam kilka pytań") idą przez katalog
`MESSAGES`-podobny per język (pl/en/de/fr), spójnie z `notification_tts.py`.

### Rejestracja — `hooks/hooks.json`

Dodać:

```json
"PreToolUse": [
  {
    "matcher": "AskUserQuestion|ExitPlanMode",
    "hooks": [
      { "type": "command",
        "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/ask_question_tts.py\"",
        "timeout": 5000 }
    ]
  }
]
```

Matcher zawęża wywołania do dwóch narzędzi, więc hook nie odpala się na każdym
tool-callu (inaczej niż PostToolUse `attention_clear.py`).

## Przepływ danych

1. UserPromptSubmit → `busy=True`, `attention=False`.
2. Agent pracuje / spawnuje subagentów → busy pozostaje True.
3. Bezczynność >60 s podczas pracy → Notification `waiting` → Część A widzi
   świeży busy → **cisza**.
4. Agent wywołuje `AskUserQuestion` → PreToolUse → Część B **mówi treść pytania**
   + attention.
5. (opcjonalnie) po 60 s Notification `waiting` → Część A wycisza (busy nadal
   True) → brak dubla.
6. Użytkownik odpowiada → PostToolUse `attention_clear` zdejmuje attention; tura
   trwa dalej.
7. Prośba o zgodę na narzędzie → Notification `permission` → **mów** (zawsze).
8. Koniec tury → Stop → `busy=False`. Późniejsze bezczynne `waiting` → brak
   busy → **mów** „Czekam" (realne czekanie).

## Obsługa błędów / edge cases

- **Twardy kill sesji** może zostawić nieskasowany busy → realne „Czekam"
  wyciszone maks. do 15 min (ograniczone `BUSY_STALE_SECS`). Akceptowalne.
- **Brak `session_id`** w wejściu → `session_busy_fresh` → False (fail-open:
  mowa zostaje włączona).
- **Pusty/niepoprawny `tool_input`** w Części B → hook nic nie mówi, exit 0.
- **Wersja Claude Code bez PreToolUse dla AskUserQuestion** → Część B nie zadziała;
  do potwierdzenia empirycznie (patrz de-risk).

## Odrzucona alternatywa

„Tylko realni subagenci w locie" — wykrywanie niezamkniętych wywołań `Task`
(tool_use bez tool_result) w transkrypcie. Węższe i dokładnie pod zgłoszony
scenariusz, ale kruche (parsowanie transkryptu) i nie łapie innej długiej pracy
jednego agenta. `busy` jest prostszy i pokrywa więcej przypadków.

## De-risk (do wykonania na starcie planu)

Raz włączyć `"debug": true` w configu i potwierdzić na realnej sesji:
1. fałszywe `waiting` podczas orkiestracji ma ustawiony świeży busy,
2. PreToolUse faktycznie odpala się dla `AskUserQuestion` (i jaki dokładnie jest
   kształt `tool_input`).
Jeśli (2) nie zachodzi — Część B przechodzi na inny mechanizm (np. rozpoznanie po
transkrypcie przy zdarzeniu Notification).

## Testy (pytest, `conftest` fejkuje `Popen` i przekierowuje `~/.claude`)

Część A (`notification_tts` / `session_busy_fresh`):
- `permission` → `speak` wywołany (bez zmian).
- `waiting` + świeży busy → `speak` **nie** wywołany, attention **nie** ustawiony.
- `waiting` + brak busy → `speak` wywołany + attention ustawiony.
- `waiting` + nieświeży busy (>`BUSY_STALE_SECS`) → `speak` wywołany.
- `session_busy_fresh`: brak pliku→False; świeży→True; stary→False.

Część B (`ask_question_tts`):
- AskUserQuestion z jednym pytaniem → `speak(priority=True)` z treścią pytania,
  attention ustawiony.
- AskUserQuestion z kilkoma pytaniami → fraza z pierwszym pytaniem + prefiks.
- ExitPlanMode → stała fraza w języku configu.
- brak configu → no-op.
- pusty `tool_input` → no-op, exit 0.

Lint: `uvx ruff check .`; testy: `uvx --with pytest pytest tests/ -q`.

## Aktualizacja dokumentacji

- `CLAUDE.md`: opis nowego hooka `ask_question_tts.py` (PreToolUse) oraz zmiany w
  `notification_tts.py` (filtr busy) i nowego helpera `session_busy_fresh`.
