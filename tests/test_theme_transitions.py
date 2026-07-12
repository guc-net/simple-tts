"""Testy płynności przejść między trybami motywów nakładki.

Kontrakt: zmiana trybu NIGDY nie powoduje skokowej zmiany obrazu — jasności
wjeżdżają po bramkach z easingiem, zmiany koloru to krosfejd albo stopniowa
wymiana treści (per segment / per kolumna), nigdy przebarwienie całości
w jednej klatce.
"""

import os
import sys

import pytest

pytest.importorskip("PIL")

OVERLAY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "overlay")
sys.path.insert(0, OVERLAY_DIR)

from themes import get_theme  # noqa: E402

W, H, SCALE = 520, 30, 2
SNAP = {"busy": 1, "age": 0.0}


def _mk(name):
    return get_theme(name, W, H, SCALE)


def _settle(t, mode, snap=SNAP, seconds=4.0, t0=100.0, level=0.0):
    """Ustabilizuj motyw w trybie; zwróć (now, stan op per idx)."""
    t.enter_mode(mode, snap)
    fps = t.fps(mode)
    now = t0
    ops = {i: spec["op"] for i, spec in enumerate(t.layers())}
    imgs = {i: spec["img"] for i, spec in enumerate(t.layers())}
    for _ in range(int(seconds * fps)):
        now += 1.0 / fps
        for idx, prop, val in t.step(1.0 / fps, now, level, snap):
            if prop == "op":
                ops[idx] = val
            elif prop == "img":
                imgs[idx] = val
    return now, ops, imgs


def _steps(t, mode, now, seconds, snap=SNAP, level=0.0, ops=None, imgs=None):
    """Krok po kroku w (już ustawionym) trybie; zwraca (now, ops, imgs,
    lista aktualizacji z PIERWSZEGO kroku)."""
    fps = t.fps(mode)
    first = None
    for _ in range(max(1, int(seconds * fps))):
        now += 1.0 / fps
        ups = t.step(1.0 / fps, now, level, snap)
        if first is None:
            first = ups
        for idx, prop, val in ups:
            if prop == "op" and ops is not None:
                ops[idx] = val
            elif prop == "img" and imgs is not None:
                imgs[idx] = val
    return now, first


# --- uwaga = tylko KOLOR (ruch wg aktywności); kolor wjeżdża po bramce --------

WAIT = {"busy": 1, "age": 0.0, "waiting": True}


@pytest.mark.parametrize("name", ["kitt", "cylon"])
def test_attn_color_ramps_in_when_waiting(name):
    t = _mk(name)
    now, ops, imgs = _settle(t, "think")          # ruch think, bez czekania
    now, first = _steps(t, "think", now, 0.0, snap=WAIT, ops=ops, imgs=imgs)
    for idx, prop, val in first:                   # pierwsza klatka: kolor wjeżdża
        if prop == "op" and idx in t.i_amber:
            assert val < 0.5, "kolor uwagi ma wjechać po bramce, nie wskoczyć"
    best, fps = 0.0, t.fps("think")
    for _ in range(int(2.0 * fps)):                # po ~2 s kolor jedzie z okiem
        now += 1.0 / fps
        for idx, prop, val in t.step(1.0 / fps, now, 0.0, WAIT):
            if prop == "op" and idx in t.i_amber:
                best = max(best, val)
    assert best > 0.6


# --- spark: uwaga przemalowuje oko (zielone -> kolor) i iskry ------------------

def test_spark_eye_recolors_when_waiting():
    t = _mk("spark")
    _n, ops, _i = _settle(t, "think", snap=WAIT, seconds=2.5)
    # zielone oko przygasa, kolorowa nakładka uwagi (i_alens0) się rozjaśnia
    assert ops.get(t.i_alens0, 0.0) > 0.4, "kolorowe oko uwagi ma wejść"
    assert ops.get(t.i_lens_g, 1.0) < 0.3, "zielone oko ma przygasnąć"
    assert not hasattr(t, "i_lens_a")


def test_spark_one_lens_blue_when_one_waiting():
    # 3 agentów pracuje, JEDNO zadanie czeka -> tylko JEDNA soczewka niebieska
    t = _mk("spark")
    snap = {"busy": 3, "age": 0.0, "waiting": True, "waiting_count": 1}
    _n, ops, _i = _settle(t, "think", snap=snap, seconds=3.0)
    blue = [i for i in range(t.i_alens0, t.i_alens0 + 3) if ops.get(i, 0.0) > 0.4]
    assert len(blue) == 1, f"jeden czekający -> jedna niebieska soczewka (jest {len(blue)})"


def test_spark_two_lenses_blue_when_two_waiting():
    t = _mk("spark")
    snap = {"busy": 3, "age": 0.0, "waiting": True, "waiting_count": 2}
    _n, ops, _i = _settle(t, "think", snap=snap, seconds=3.0)
    blue = [i for i in range(t.i_alens0, t.i_alens0 + 3) if ops.get(i, 0.0) > 0.4]
    assert len(blue) == 2, f"dwóch czekających -> dwie niebieskie soczewki (jest {len(blue)})"


def test_spark_non_waiting_lenses_stay_green():
    # przy jednym czekającym: soczewka 0 niebieska (zielona zgaszona),
    # pozostałe zostają zielone
    t = _mk("spark")
    snap = {"busy": 3, "age": 0.0, "waiting": True, "waiting_count": 1}
    _n, ops, _i = _settle(t, "think", snap=snap, seconds=3.0)
    assert ops.get(t.i_alens0 + 0, 0.0) > 0.4, "soczewka 0 ma być niebieska"
    assert ops.get(0, 0.0) < 0.3, "zielona soczewka 0 ma przygasnąć pod niebieską"
    assert ops.get(1, 0.0) > 0.4 and ops.get(2, 0.0) > 0.4, "soczewki 1,2 zostają zielone"
    assert ops.get(t.i_alens0 + 1, 0.0) < 0.1 and ops.get(t.i_alens0 + 2, 0.0) < 0.1, \
        "nakładki niebieskie 1,2 mają być zgaszone"


def test_spark_sparks_turn_blue_when_waiting():
    t = _mk("spark")
    wait3 = {"busy": 3, "age": 0.0, "waiting": True}
    _n, ops, imgs = _settle(t, "think", snap=wait3, seconds=3.0)
    par_idx = set(range(t.i_par0, t.i_par0 + t.n))
    att = sum(1 for i in par_idx if imgs.get(i, "").startswith("a"))
    assert att > 0, "iskry mają być niebieskie, gdy ktoś czeka"


def test_spark_shake_is_reactive_and_per_lens():
    t = _mk("spark")
    # idle: brak iskier -> wszystkie oczy stoją spokojnie
    _settle(t, "idle", snap={"busy": 1, "age": 0.0}, seconds=2.0)
    assert max(t.shake_amp) < 0.06, "w idle oczy mają stać spokojnie"
    # think z 2 agentami: iskry wpadają, oczy drżą — ale NIE identycznie
    snap = {"busy": 2, "age": 0.0}
    t.enter_mode("think", snap)
    now, peak_amp, peak_ang, desync = 100.0, 0.0, 0.0, 0.0
    for _ in range(int(4.0 * t.fps("think"))):
        now += 1.0 / t.fps("think")
        for idx, prop, val in t.step(1.0 / t.fps("think"), now, 0.0, snap):
            if prop == "xf" and idx == t.i_lens_g:
                peak_ang = max(peak_ang, abs(val[0]))
        peak_amp = max(peak_amp, max(t.shake_amp))
        desync = max(desync, abs(t.shake_amp[0] - t.shake_amp[1]))
    assert peak_amp > 0.3, "gdy iskry wpadają, oko ma się trząść"
    assert peak_ang > 0.03, "przy drżeniu oko ma się też przechylać"
    assert desync > 0.15, "dwa oczy mają trząść się OSOBNO, nie identycznie"


@pytest.mark.parametrize("name", ["kitt", "cylon"])
def test_attn_color_same_in_speak_and_think(name):
    # KITT i Cylon: jeden kolor uwagi (pomarańcz) — bez zmiany na żółto przy mowie
    t = _mk(name)
    assert t.ATTN_COLOR == t.ATTN_SPEAK, "jeden kolor uwagi, ten sam przy mowie"


def test_kitt_has_no_backing_background():
    t = _mk("kitt")
    assert "backing" not in t.sprites(), "KITT bez tła (tylko sunące światło)"
    assert _mk("cylon").sprites().get("backing") is not None, "Cylon zostaje z tłem"


@pytest.mark.parametrize("name", ["kitt", "cylon"])
def test_kitt_heads_grow_with_busy(name):
    # więcej agentów -> więcej „głów" w przejeździe -> szersza grupa diod
    def lit_glow(busy):
        t = _mk(name)
        snap = {"busy": busy, "age": 0.0}
        _n, ops, _i = _settle(t, "think", snap=snap, seconds=2.5)
        return sum(1 for i in t.i_glow if ops.get(i, 0.0) > 0.55)
    assert lit_glow(1) < lit_glow(4), "więcej agentów ma zapalać więcej głów"


def test_cylon_attn_color_follows_the_sweep():
    # kolor uwagi JEDZIE z okiem (nie miga naraz): część diod jasna, część ciemna
    t = _mk("cylon")
    _n, ops, _i = _settle(t, "think", snap=WAIT, seconds=3.0)
    lit = [i for i in t.i_amber if ops.get(i, 0.0) > 0.5]
    dark = [i for i in t.i_amber if ops.get(i, 0.0) < 0.15]
    assert lit and dark, "kolor uwagi ma jechać z okiem, nie zapalać się wszędzie"


def test_spark_no_sparks_while_speaking():
    t = _mk("spark")
    now, ops, imgs = _settle(t, "speak", level=0.6, seconds=3.0)
    par_idx = set(range(t.i_par0, t.i_par0 + t.n))
    lit = [i for i in par_idx if ops.get(i, 0.0) > 0.02]
    assert not lit, "podczas mowy iskry nie latają (zostaje samo oko)"


def test_spark_no_sparks_when_idle():
    t = _mk("spark")
    now, ops, imgs = _settle(t, "idle", snap={"busy": 1, "age": 0.0}, seconds=3.0)
    par_idx = set(range(t.i_par0, t.i_par0 + t.n))
    lit = [i for i in par_idx if ops.get(i, 0.0) > 0.02]
    assert not lit, "w idle nie ma latających iskier"


def test_spark_more_agents_more_sparks():
    def lit_count(busy):
        t = _mk("spark")
        _n, ops, _i = _settle(t, "think", snap={"busy": busy, "age": 0.0},
                              seconds=3.0)
        par = range(t.i_par0, t.i_par0 + t.n)
        return sum(1 for i in par if ops.get(i, 0.0) > 0.02)
    c1, c3, c5 = lit_count(1), lit_count(3), lit_count(5)
    assert c1 < c3 < c5, f"więcej agentów -> więcej iskier ({c1} < {c3} < {c5})"


def test_spark_lens_count_follows_busy():
    lens_idx = lambda t: list(range(t.i_alens0))          # noqa: E731
    for busy, want in ((1, 1), (2, 2), (3, 3), (5, 5)):
        t = _mk("spark")
        _n, ops, _i = _settle(t, "think", snap={"busy": busy, "age": 0.0},
                              seconds=3.0)
        lit = [i for i in lens_idx(t) if ops.get(i, 0.0) > 0.4]
        assert len(lit) == want, f"{busy} agentów -> {want} soczewek (jest {len(lit)})"


def test_spark_merges_and_rotates_when_speaking():
    t = _mk("spark")
    _n, ops, _i = _settle(t, "speak", snap={"busy": 3, "age": 0.0},
                          level=0.5, seconds=3.5)
    lit = [i for i in range(t.i_alens0) if ops.get(i, 0.0) > 0.4]
    assert len(lit) == 1, "przy mowie soczewki scalają się w jedną"
    assert t.rphase > 0.9, "po scaleniu oko się obraca"
    assert all(abs(t.lens_x[i] - t.cx) < 1.0 for i in range(t.i_alens0))


def _time_until(t, predicate, mode, snap, level, t0=300.0, max_s=3.0):
    """Sekundy do spełnienia predicate(t) w danym trybie (max_s gdy nie zajdzie)."""
    fps, now = t.fps(mode), t0
    for _ in range(int(max_s * fps)):
        now += 1.0 / fps
        t.step(1.0 / fps, now, level, snap)
        if predicate(t):
            return now - t0
    return max_s


def test_spark_speak_rotation_faster_than_return():
    # busy=1 -> soczewki scalone od startu, więc rphase zależy TYLKO od tau
    # rotacji (odseparowane od merge). Przejście PRACA->MOWA ma być wyraźnie
    # szybsze niż powrót MOWA->praca (mowa startuje od razu, oko musi zdążyć się
    # obrócić); powrót zostaje bez zmian. Każdy kierunek mierzony od świeżej,
    # ustabilizowanej instancji, więc rphase startuje z czystego 0 lub 1.
    snap = {"busy": 1, "age": 0.0}
    tf = _mk("spark")
    _settle(tf, "think", snap=snap, seconds=3.0)               # rphase ~0
    tf.enter_mode("speak", snap)
    t_fwd = _time_until(tf, lambda th: th.rphase > 0.9, "speak", snap, 0.5)
    tb = _mk("spark")
    _settle(tb, "speak", snap=snap, level=0.5, seconds=3.0)    # rphase ~1
    tb.enter_mode("think", snap)
    t_back = _time_until(tb, lambda th: th.rphase < 0.1, "think", snap, 0.0)
    assert t_fwd < 0.85 * t_back, \
        f"przejscie do mowy ma byc wyraznie szybsze ({t_fwd} < 0.85*{t_back})"


def test_spark_rotation_waits_for_merge():
    t = _mk("spark")
    _settle(t, "think", snap={"busy": 3, "age": 0.0}, seconds=3.0)   # rozdzielone
    snap = {"busy": 3, "age": 0.0}
    t.enter_mode("speak", snap)
    fps, now, saw = t.fps("speak"), 200.0, False
    for _ in range(int(0.25 * fps)):
        now += 1.0 / fps
        t.step(1.0 / fps, now, 0.4, snap)
        spread = max(abs(t.lens_x[i] - t.cx) for i in range(t.i_alens0))
        if spread > 3.0:                            # jeszcze rozjechane
            assert t.rphase < 0.2, "obrót ma czekać, aż soczewki się scalą"
            saw = True
    assert saw, "test miał uchwycić moment scalania"
