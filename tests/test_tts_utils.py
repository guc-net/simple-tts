"""Tests for tts_utils: config, language codes, tag extraction,
sanitizer, speak() dedup/priority, mute and quiet hours."""

import json
import time
from datetime import datetime

import pytest
import tts_utils
from tts_utils import (
    extract_tts_from_transcript,
    in_quiet_hours,
    language_code,
    load_config,
    sanitize_for_tts,
    speak,
)


class TestLoadConfig:
    def test_missing_file_returns_none(self, isolated_paths):
        assert load_config() is None

    def test_invalid_json_returns_none(self, isolated_paths):
        (isolated_paths / "config.json").write_text("{not json")
        assert load_config() is None

    def test_partial_config_merges_defaults(self, write_config):
        write_config(voice="Ewa")
        config = load_config()
        assert config["voice"] == "Ewa"
        assert config["rate"] == 220
        assert config["language"] == "Polish"


class TestLanguageCode:
    @pytest.mark.parametrize("language,expected", [
        ("Polish", "pl"),
        ("polish", "pl"),
        ("English", "en"),
        ("German", "de"),
        ("pl", "pl"),
        ("DE", "de"),
        ("Klingon", "en"),
    ])
    def test_resolution(self, language, expected):
        assert language_code({"language": language}) == expected

    def test_default_is_polish(self):
        assert language_code({}) == "pl"


class TestExtractFromTranscript:
    def _write_transcript(self, tmp_path, entries):
        path = tmp_path / "transcript.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in entries))
        return str(path)

    def test_extracts_tag_from_last_assistant_message(self, tmp_path):
        path = self._write_transcript(tmp_path, [
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Old <!-- TTS: stara wiadomość -->"}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Done <!-- TTS: zrobione -->"}]}},
        ])
        assert extract_tts_from_transcript(path) == "zrobione"

    def test_no_tag_returns_none(self, tmp_path):
        path = self._write_transcript(tmp_path, [
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "No tag here"}]}},
        ])
        assert extract_tts_from_transcript(path) is None

    def test_missing_file_returns_none(self, tmp_path):
        assert extract_tts_from_transcript(str(tmp_path / "nope.jsonl")) is None

    def test_skips_malformed_lines(self, tmp_path):
        path = tmp_path / "transcript.jsonl"
        path.write_text('not json\n' + json.dumps(
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "<!-- TTS: działa -->"}]}}))
        assert extract_tts_from_transcript(str(path)) == "działa"


class TestSanitizer:
    def test_longest_match_wins(self, isolated_paths):
        # 'deployed' must use its own entry, not 'deploy' + 'ed'
        assert sanitize_for_tts("deployed", "pl") == "deplojd"
        assert sanitize_for_tts("cached", "pl") == "keszowany"

    def test_multiword_phrase(self, isolated_paths):
        assert sanitize_for_tts("pull request", "pl") == "pul rekłest"

    def test_caps_get_spelled_out(self, isolated_paths):
        assert sanitize_for_tts("API", "pl") == "A P I"

    def test_case_insensitive_replacement(self, isolated_paths):
        assert sanitize_for_tts("Deployed", "pl") == "deplojd"

    def test_no_partial_word_replacement(self, isolated_paths):
        # 'cache' must not fire inside an unrelated longer word
        assert "kesz" not in sanitize_for_tts("cacheable", "pl")

    def test_user_overrides_win(self, isolated_paths):
        (isolated_paths / "phonetics.json").write_text(json.dumps({"docker": "dokerek"}))
        assert sanitize_for_tts("docker", "pl") == "dokerek"

    def test_unknown_language_only_spells_caps(self, isolated_paths):
        assert sanitize_for_tts("deployed JSON", "xx") == "deployed J S O N"

    def test_clock_time_spelled_to_words_pl(self, isolated_paths):
        # '14:02' must not reach `say` raw (it expands to 'czternasta i dwie minuty')
        assert sanitize_for_tts("Jest 14:02", "pl") == "Jest czternasta zero dwie"
        assert sanitize_for_tts("o 9:05", "pl") == "o dziewiąta zero pięć"
        assert sanitize_for_tts("14:00 lunch", "pl") == "czternasta lunch"
        assert sanitize_for_tts("23:59", "pl") == "dwudziesta trzecia pięćdziesiąt dziewięć"

    def test_clock_time_untouched_for_other_languages(self, isolated_paths):
        assert sanitize_for_tts("at 14:02", "xx") == "at 14:02"


class TestSpeak:
    def test_unconfigured_is_silent(self, isolated_paths, fake_say):
        speak("hello")
        assert fake_say == []

    def test_speaks_with_configured_voice_and_rate(self, write_config, fake_say):
        write_config(voice="Ewa", rate=200, engine="say")
        speak("dzień dobry")
        assert len(fake_say) == 1
        assert fake_say[0][1].endswith("edge_speak.py")
        payload = json.loads(fake_say.envs[0]["SIMPLE_TTS_PAYLOAD"])
        assert payload == {
            "engine": "say",
            "text": "dzień dobry",
            "say_voice": "Ewa",
            "say_rate": "200",
        }

    def test_edge_engine_spawns_helper_with_payload(self, write_config, fake_say):
        # Default engine is "edge": speak() spawns the edge_speak.py helper and
        # passes the synthesis details through the SIMPLE_TTS_PAYLOAD env var.
        write_config(voice="Krzysztof", language="Polish")  # engine defaults to edge
        speak("dzień dobry")
        assert len(fake_say) == 1
        assert fake_say[0][1].endswith("edge_speak.py")
        payload = json.loads(fake_say.envs[0]["SIMPLE_TTS_PAYLOAD"])
        assert payload["edge_voice"] == "pl-PL-MarekNeural"  # male voice
        assert payload["text"] == "dzień dobry"
        assert payload["say_voice"] == "Krzysztof"  # fallback voice preserved

    def _payload(self, fake_say, **cfg):
        write = self._write
        write(voice="Krzysztof", language="Polish", **cfg)
        speak("hej")
        return json.loads(fake_say.envs[0]["SIMPLE_TTS_PAYLOAD"])

    def test_howl_auto_plays_only_with_kitt_theme(self, write_config, fake_say):
        self._write = write_config
        # motyw KITT -> wyjec gra
        assert self._payload(fake_say, overlay_theme="kitt")["intro_sound"] == "kitt"

    def test_voice_profile_follows_theme(self, write_config, fake_say):
        self._write = write_config
        # kitt: wyjec + zniekształcenie
        p = self._payload(fake_say, overlay_theme="kitt")
        assert (p["intro_sound"], p["edge_pitch"]) == ("kitt", "-20Hz")

    def test_cylon_distorted_without_howl(self, write_config, fake_say):
        self._write = write_config
        # cylon: bez wyjca, ale zniekształcony
        p = self._payload(fake_say, overlay_theme="cylon")
        assert p["intro_sound"] == "none"
        assert p["edge_pitch"] == "-20Hz"

    def test_spark_plain_voice(self, write_config, fake_say):
        self._write = write_config
        # spark: zwykły głos — bez wyjca i bez zniekształcenia
        p = self._payload(fake_say, overlay_theme="spark")
        assert p["intro_sound"] == "none"
        assert p["edge_pitch"] == "+0Hz"

    def test_howl_off_silences_even_on_kitt(self, write_config, fake_say):
        self._write = write_config
        p = self._payload(fake_say, overlay_theme="kitt", voice_howl="off")
        assert p["intro_sound"] == "none"

    def test_howl_on_forces_it_on_other_themes(self, write_config, fake_say):
        self._write = write_config
        p = self._payload(fake_say, overlay_theme="spark", voice_howl="on")
        assert p["intro_sound"] == "kitt"

    def test_distortion_is_independent_of_howl(self, write_config, fake_say):
        self._write = write_config
        # wyłączone zniekształcenie -> pitch neutralny, niezależnie od wyjca
        p = self._payload(fake_say, overlay_theme="kitt", voice_distortion=False)
        assert p["edge_pitch"] == "+0Hz"
        assert p["intro_sound"] == "kitt"           # wyjec dalej gra

    def test_edge_engine_picks_female_voice_for_female_local_voice(self, write_config, fake_say):
        write_config(voice="Ewa", language="Polish")
        speak("gotowe")
        payload = json.loads(fake_say.envs[0]["SIMPLE_TTS_PAYLOAD"])
        assert payload["edge_voice"] == "pl-PL-ZofiaNeural"

    def test_edge_engine_falls_back_to_say_for_unmapped_language(self, write_config, fake_say):
        # A language whose code has no EDGE_VOICES entry uses the local `say`
        # engine ("xx" passes through language_code as a 2-letter code), still
        # routed through the edge_speak.py helper (payload engine="say").
        write_config(voice="Krzysztof", language="xx")
        speak("hello")
        assert fake_say[0][1].endswith("edge_speak.py")
        payload = json.loads(fake_say.envs[0]["SIMPLE_TTS_PAYLOAD"])
        assert payload["engine"] == "say"

    def test_records_pid_and_timestamp(self, write_config, fake_say, isolated_paths):
        write_config()
        speak("test")
        state = json.loads((isolated_paths / "state.json").read_text())
        assert state["pid"] == 12345
        assert state["ts"] == pytest.approx(time.time(), abs=5)

    def test_nonpriority_silent_while_recent_speech(self, write_config, fake_say,
                                                    isolated_paths):
        write_config()
        (isolated_paths / "state.json").write_text(
            json.dumps({"pid": 99999999, "ts": time.time()}))
        speak("powinno być cicho")
        assert fake_say == []

    def test_nonpriority_speaks_after_window(self, write_config, fake_say,
                                             isolated_paths, monkeypatch):
        write_config()
        monkeypatch.setattr(tts_utils, "_is_our_tts", lambda pid: False)
        (isolated_paths / "state.json").write_text(
            json.dumps({"pid": 99999999, "ts": time.time() - 10}))
        speak("już można mówić")
        assert len(fake_say) == 1

    def test_priority_kills_running_tts(self, write_config, fake_say,
                                        isolated_paths, monkeypatch):
        write_config()
        killed = []
        monkeypatch.setattr(tts_utils, "_is_our_tts", lambda pid: True)
        monkeypatch.setattr(tts_utils.os, "getpgid", lambda pid: pid)
        monkeypatch.setattr(tts_utils.os, "killpg",
                            lambda pgid, sig: killed.append((pgid, sig)))
        (isolated_paths / "state.json").write_text(
            json.dumps({"pid": 4242, "ts": time.time()}))
        speak("pilne", priority=True)
        assert (4242, 15) in killed  # SIGTERM == 15
        assert len(fake_say) == 1

    def test_nonpriority_enqueues_while_speaking(self, write_config, fake_say,
                                                  isolated_paths, monkeypatch):
        write_config()
        monkeypatch.setattr(tts_utils, "_is_our_tts", lambda pid: True)
        (isolated_paths / "state.json").write_text(
            json.dumps({"pid": 4242, "ts": time.time()}))
        speak("w kolejce")
        assert fake_say == []
        payload = tts_utils._queue_pop()
        assert payload is not None
        assert payload["text"] == sanitize_for_tts("w kolejce", "pl")

    def test_priority_clears_queue_before_speaking(self, write_config, fake_say,
                                                    isolated_paths, monkeypatch):
        write_config()
        monkeypatch.setattr(tts_utils, "_is_our_tts", lambda pid: True)
        monkeypatch.setattr(tts_utils.os, "getpgid", lambda pid: pid)
        monkeypatch.setattr(tts_utils.os, "killpg", lambda pgid, sig: None)
        tts_utils._queue_enqueue({"text": "stare"})
        (isolated_paths / "state.json").write_text(
            json.dumps({"pid": 4242, "ts": time.time()}))
        speak("nowe", priority=True)
        assert tts_utils._queue_pop() is None
        assert len(fake_say) == 1

    def test_failed_spawn_leaves_state_untouched(self, write_config, isolated_paths,
                                                   monkeypatch):
        write_config()
        assert not (isolated_paths / "state.json").exists()

        def boom(*args, **kwargs):
            raise OSError("boom")

        monkeypatch.setattr(tts_utils.subprocess, "Popen", boom)
        speak("cokolwiek")
        state_path = isolated_paths / "state.json"
        if state_path.exists():
            content = state_path.read_text().strip()
            assert content in ("", "{}")

    def test_empty_text_does_not_enqueue_or_spawn(self, write_config, fake_say,
                                                   isolated_paths, monkeypatch):
        write_config()
        monkeypatch.setattr(tts_utils, "_is_our_tts", lambda pid: True)
        (isolated_paths / "state.json").write_text(
            json.dumps({"pid": 4242, "ts": time.time()}))
        speak("")
        assert fake_say == []
        assert tts_utils._queue_pop() is None

    def test_say_payload_is_minimal(self, write_config, fake_say):
        write_config(voice="Ewa", rate=200, engine="say")
        speak("dzień dobry")
        payload = json.loads(fake_say.envs[0]["SIMPLE_TTS_PAYLOAD"])
        assert "intro_sound" not in payload
        assert "edge_pitch" not in payload


class TestMute:
    def test_enabled_false_is_silent(self, write_config, fake_say):
        write_config(enabled=False)
        speak("nic")
        assert fake_say == []

    def test_enabled_false_silences_priority_too(self, write_config, fake_say):
        write_config(enabled=False)
        speak("nic", priority=True)
        assert fake_say == []

    def test_enabled_true_speaks(self, write_config, fake_say):
        write_config(enabled=True)
        speak("mówię")
        assert len(fake_say) == 1

    def test_force_overrides_mute(self, write_config, fake_say):
        write_config(enabled=False)
        speak("test wymuszony", force=True)
        assert len(fake_say) == 1


class TestQuietHours:
    def _config(self, start, end):
        return {"quiet_hours": {"start": start, "end": end}}

    def test_inside_simple_window(self):
        assert in_quiet_hours(self._config("13:00", "15:00"),
                              now=datetime(2026, 6, 12, 14, 0))

    def test_outside_simple_window(self):
        assert not in_quiet_hours(self._config("13:00", "15:00"),
                                  now=datetime(2026, 6, 12, 16, 0))

    def test_overnight_window_late_evening(self):
        assert in_quiet_hours(self._config("22:00", "07:00"),
                              now=datetime(2026, 6, 12, 23, 30))

    def test_overnight_window_early_morning(self):
        assert in_quiet_hours(self._config("22:00", "07:00"),
                              now=datetime(2026, 6, 12, 6, 30))

    def test_overnight_window_daytime(self):
        assert not in_quiet_hours(self._config("22:00", "07:00"),
                                  now=datetime(2026, 6, 12, 12, 0))

    def test_start_boundary_is_quiet(self):
        assert in_quiet_hours(self._config("22:00", "07:00"),
                              now=datetime(2026, 6, 12, 22, 0))

    def test_end_boundary_is_loud(self):
        assert not in_quiet_hours(self._config("22:00", "07:00"),
                                  now=datetime(2026, 6, 12, 7, 0))

    def test_no_quiet_hours_configured(self):
        assert not in_quiet_hours({})

    def test_equal_start_end_means_disabled(self):
        assert not in_quiet_hours(self._config("08:00", "08:00"),
                                  now=datetime(2026, 6, 12, 8, 0))

    def test_malformed_value_means_disabled(self):
        assert not in_quiet_hours({"quiet_hours": "yes"})
        assert not in_quiet_hours(self._config("late", "early"))

    def test_speak_silent_during_quiet_hours(self, write_config, fake_say, monkeypatch):
        write_config(quiet_hours={"start": "22:00", "end": "07:00"})
        monkeypatch.setattr(tts_utils, "in_quiet_hours", lambda config: True)
        speak("cisza nocna")
        assert fake_say == []

    def test_force_overrides_quiet_hours(self, write_config, fake_say, monkeypatch):
        write_config(quiet_hours={"start": "22:00", "end": "07:00"})
        monkeypatch.setattr(tts_utils, "in_quiet_hours", lambda config: True)
        speak("test", force=True)
        assert len(fake_say) == 1
