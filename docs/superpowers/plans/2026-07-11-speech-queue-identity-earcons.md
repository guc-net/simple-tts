# simple-tts: kolejka mowy + tożsamość projektu + kategorie/earcony

## Context

Z analizy 5 możliwych usprawnień integracji z Claude Code użytkownik wybrał trzy:
- **F1 Kolejka mowy** — dziś `speak()` (hooks/tts_utils.py:404-424) **porzuca** komunikat non-priority,
  gdy cokolwiek gra lub skończyło <2 s temu; stan jest globalny, więc przy równoległych sesjach
  komunikaty Stop giną bezpowrotnie.
- **F2 Tożsamość sesji/projektu** — przy wielu pracujących sesjach nie wiadomo, która mówi;
  użytkownik chce **nazwę projektu na początku** komunikatu („Simple TTS: testy przeszły").
- **F3 Kategorie + earcony** — tag `<!-- TTS[ok|err|q]: -->` + krótki dźwięk przed mową,
  żeby charakter komunikatu (sukces/błąd/pytanie) był słyszalny zanim padną słowa.

Kolejność F1 → F2 → F3 (F1 restrukturyzuje `speak()`/payload, F2/F3 tylko dokładają pola).
Repo: `/Users/usterk/src/simple-tts`. Wymogi projektu: stdlib-only w hooks/, silent no-op bez
configu, TDD (pytest + fixtures `isolated_paths`/`write_config`/`fake_say` z tests/conftest.py), ruff.

## F1 — Globalna kolejka mowy

**Decyzje:**
- **Drenuje `edge_speak.py`** w tym samym procesie (jest detached liderem grupy → `pid` w state
  pozostaje ważny, overlay/`_is_our_tts` bez zmian, priority zabija killpg odtwarzanie + drain).
- **Engine=say też idzie przez helper**: `speak()` zawsze spawnuje `edge_speak.py`; nowe pole
  payloadu `"engine": "edge"|"say"` — dla say helper pomija cache/uvx i woła istniejące `_say(payload)`.
  (Bez tego say nie ma pętli drain; cała ścieżka say już jest w edge_speak.)
- **Jeden lock: istniejący flock na `STATE_PATH`** (`_locked_state`). Funkcje kolejki to prymitywy
  wołane wyłącznie pod nim — zamyka wyścig „helper widzi pustą kolejkę i wychodzi" vs „speak()
  widzi żywy pid i enqueue'uje". Bez drugiego locka (ryzyko deadlocka).
- **Kolejka**: `~/.claude/simple-tts-queue.d/`, wpis `<time_ns>-<pid>.json` z gotowym payloadem
  (po sanitize i prefiksach — drainer nie czyta configu). `QUEUE_TTL_SECS = 40` (stała), limit 8
  wpisów (przepełnienie wypycha najstarszy).
- **Nowa semantyka `speak()`** (payload budowany przed lockiem, potem jedna sekcja krytyczna):
  - priority: killpg + `_queue_clear()` + spawn + zapis stanu — wszystko pod lockiem,
  - non-priority + żywy pid: `_queue_enqueue(payload)` (zamiast porzucenia),
  - non-priority + martwy pid ale `ts < 2 s`: **nadal drop** (to dedup duplikatów, nie kolizja),
  - inaczej: spawn + zapis stanu pod lockiem; zapis stanu tylko po udanym spawn.
- **Pętla drain w edge_speak**: refaktor `main()` → `_speak_payload(payload)`; po odtworzeniu, pod
  `_locked_state`: `_queue_pop()` (czyści przeterminowane, unlink pod lockiem = brak podwójnego
  odtworzenia); pusto → zapis `{"ts": now}` **tylko gdy `state["pid"] == os.getpid()`** (żeby stary
  helper nie nadpisał stanu nowszego speak) i exit; wpis → odśwież ts, `sleep(0.4)`, odtwórz, powtórz.
  `edge_speak` importuje `tts_utils` (ten sam katalog, już na sys.path).

## F2 — Tożsamość projektu

- `speak(..., project=None)`; hooki mówiące (`stop_tts`, `notification_tts`, `ask_question_tts`)
  przekazują `os.path.basename(input.get('cwd') or '') or None`.
- Config `"announce_project": "auto"` w `DEFAULT_CONFIG` (`auto|on|off`); `auto` = prefiks tylko gdy
  nowa funkcja `fresh_busy_count()` (iteracja BUSY_DIR, świeżość jak `session_busy_fresh`) > 1.
- Format: separatory `-_.` → spacje, prefiks `f"{name}: {text}"` doklejony **przed**
  `sanitize_for_tts` (fonetyka obejmie nazwę). Prefiks projektu **wyklucza** prefiks imienia
  (`name_chance`) dla danego komunikatu.
- Inny klucz cache dla tekstu z prefiksem — akceptowalne (cache content-addressed, eviction rozmiarowa).

## F3 — Kategorie + earcony

- Regex wspólny: `<!--\s*TTS(?:\[(ok|err|q)\])?\s*:\s*(.+?)\s*-->`; brak kategorii → dzisiejsze
  zachowanie (kompatybilność wsteczna). Ekstrakcja w `stop_tts` zwraca `(category, text)`.
- `speak(..., category=None)` → pole payloadu `"earcon"` (pomijane przy braku lub `"earcons": false`
  — nowy klucz w `DEFAULT_CONFIG`, default true). Kategorię ustawia **tylko stop_tts** (notification/
  ask_question mają już mocniejszy sygnał — mowę priority).
- `edge_speak._speak_payload`: na początku `_play(sounds/earcon_<cat>.mp3)` (afplay ~0,3 s; brak
  pliku → cicho pomiń). Earcon poza cache mowy, niezależny od intro_sound/howl; dzięki F1 działa
  też dla engine=say.
- **Earcony**: 3 syntetyczne mp3 wygenerowane jednorazowo ffmpegiem (krok deweloperski, commit do
  `hooks/sounds/`): ok = dwuton wznoszący (880→1174 Hz), err = opadający (440→330), q = ton
  z glissando w górę; ~0,3 s, fade na końcu.
- `message_display.py`: regex jw.; w trybie `styled` kolor per kategoria (ok = obecna zieleń,
  err = ceglasta czerwień, q = bursztyn); `plain`/`hidden` bez zmian.
- `session_start.py`: instrukcja uczy formy `TTS[ok]/[err]/[q]` (jedno dodatkowe zdanie + przykład).

## Zadania (TDD, commit per zadanie, branch feature)

1. **T1**: prymitywy kolejki w `tts_utils` (`QUEUE_DIR`, `QUEUE_TTL_SECS`, `_queue_enqueue/_pop/_clear`)
   + `QUEUE_DIR` w `isolated_paths` (tests/conftest.py). Testy czysto plikowe.
2. **T2**: restrukturyzacja `speak()` (say przez helper, enqueue, priority-clear, spawn pod lockiem)
   + aktualizacja testów w test_tts_utils.py asertujących argv `['say', ...]`.
3. **T3**: `edge_speak`: `engine=say`, refaktor `_speak_payload`, pętla drain, guard pid przy exit-write.
4. **T4**: F2 (parametr `project`, `announce_project`, `fresh_busy_count`, 3 hooki).
5. **T5**: F3a — regex kategorii + `category` w speak/payload + stop_tts.
6. **T6**: F3b — earcony w edge_speak + wygenerowanie/commit 3 mp3.
7. **T7**: F3c — message_display (kolory) + session_start (instrukcja).
8. **T8**: CLAUDE.md (kolejka+drain, `announce_project`, `earcons`, format taga).

**Kluczowe pliki:** hooks/tts_utils.py, hooks/edge_speak.py, hooks/stop_tts.py,
hooks/notification_tts.py, hooks/ask_question_tts.py, hooks/message_display.py,
hooks/session_start.py, hooks/sounds/, tests/conftest.py, tests/test_tts_utils.py,
tests/test_edge_speak.py (+ nowe pliki testów), CLAUDE.md.

**Kluczowe testy (poza oczywistymi per zadanie):** enqueue przy żywym pid / drop przy ts<2 s
i martwym pid / priority czyści kolejkę / TTL i limit 8 / drain gra wpisy po kolei i nie gra
przeterminowanych / stary helper nie nadpisuje stanu nowego speak / `auto` z 0/1/2 świeżymi
markerami busy / prefiks tłumi imię / stary tag bez kategorii działa jak dziś / `[foo]` nie
matchuje / earcon pomijany bez pliku i przy `earcons:false` / plain-hidden display bez zmian.

## Ryzyka

- Wyścig enqueue-vs-exit drainera — chroniony wyłącznie wspólnym flockiem stanu (testy sekwencyjnie
  symulują protokół, bez realnej równoległości).
- Popen pod flockiem: trzymany ~ms; przy OSError stan nie może zostać z martwym pid (zapis po spawn).
- Zmiana ścieżki say-engine (helper zamiast gołego `say`) — jawnie odnotować w CLAUDE.md;
  speak_cli/MCP server dziedziczą automatycznie (idą przez `speak()`).

## Weryfikacja

- `uvx --with pytest pytest tests/ -q` (całość, conftest fejkuje Popen — nic nie mówi),
- `uvx ruff check .`,
- ręcznie: `python3 hooks/speak_cli.py "test"`; dwie szybkie komendy pod rząd →
  drugi komunikat mówiony po pierwszym (kolejka); `echo '{"cwd":"/x/proj",...}' | python3 hooks/stop_tts.py`
  z dwoma świeżymi markerami busy → prefiks; tag `<!-- TTS[err]: ... -->` → earcon błędu;
  `claude --plugin-dir .` na żywej sesji.
- Po akceptacji całości: merge do main, push (CI bump — commit `feat:` dla minor), aktualizacja
  pluginu lokalnie jak poprzednio.
