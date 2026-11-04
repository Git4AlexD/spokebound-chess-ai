"""Tests for spokebound.ui.sound: the mapping from a game event to a
sound stays right, playback never raises, and disabling it (as these
tests do for every other suite touching the UI) truly plays nothing."""

import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from spokebound.ui import sound
from tests.tk_support import new_tk_root, retry_tcl_init

EFFECT_FILES = {
    sound.play_move: "move.wav",
    sound.play_capture: "capture.wav",
    sound.play_button_click: "button_click.wav",
    sound.play_unit_click: "unit_click.wav",
    sound.play_reject: "reject.wav",
    sound.play_win: "win.wav",
    sound.play_loss: "loss.wav",
}


class SoundAssetTests(unittest.TestCase):
    def test_every_effect_file_exists_on_disk(self) -> None:
        for filename in EFFECT_FILES.values():
            with self.subTest(filename=filename):
                self.assertTrue((sound.ASSETS / filename).is_file())

    def test_the_menu_music_file_exists_on_disk(self) -> None:
        self.assertTrue(sound._MUSIC_FILE.is_file())

    def test_the_keep_alive_silence_file_exists_on_disk(self) -> None:
        self.assertTrue(sound._KEEPALIVE_FILE.is_file())


class SoundEffectPlaybackTests(unittest.TestCase):
    """The one-shot effects — everything but the background music, which
    plays through a separate channel (see MusicPlaybackTests)."""

    def setUp(self) -> None:
        self._winsound = MagicMock()
        self._winsound.SND_FILENAME = 1
        self._winsound.SND_ASYNC = 2
        patcher = patch.object(sound, "winsound", self._winsound)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_each_effect_plays_its_own_file_asynchronously(self) -> None:
        for play, filename in EFFECT_FILES.items():
            with self.subTest(filename=filename):
                self._winsound.reset_mock()
                play()
                path, flags = self._winsound.PlaySound.call_args[0]
                self.assertTrue(path.endswith(filename))
                self.assertTrue(flags & self._winsound.SND_ASYNC)

    def test_muted_effects_never_touch_winsound(self) -> None:
        with patch.object(sound, "_effects_enabled", False):
            sound.play_move()
        self._winsound.PlaySound.assert_not_called()

    def test_a_playback_error_is_swallowed_not_raised(self) -> None:
        self._winsound.PlaySound.side_effect = RuntimeError("no device")
        sound.play_move()  # must not raise


class MusicPlaybackTests(unittest.TestCase):
    """The background music plays through Windows' MCI (via ctypes)
    rather than winsound — its own channel, so a button click or a move
    sound (still on winsound) never interrupts it. See the module
    docstring in spokebound.ui.sound for why."""

    def setUp(self) -> None:
        self._winmm = MagicMock()
        patcher = patch.object(sound, "_winmm", self._winmm)
        patcher.start()
        self.addCleanup(patcher.stop)
        # play_menu_music is idempotent based on this flag, so every
        # test starts from "not already playing" regardless of what an
        # earlier test in this class left it as.
        flag_patcher = patch.object(sound, "_music_playing", False)
        flag_patcher.start()
        self.addCleanup(flag_patcher.stop)

    def _commands(self) -> list[str]:
        return [call.args[0] for call in self._winmm.mciSendStringW.call_args_list]

    def test_starting_the_music_opens_and_plays_it_looping(self) -> None:
        sound.play_menu_music()
        commands = self._commands()
        self.assertTrue(any("open" in c and "menu_music.mp3" in c for c in commands))
        self.assertTrue(any(c.startswith("play") and "repeat" in c for c in commands))

    def test_stop_closes_the_music_channel(self) -> None:
        sound.play_menu_music()
        self._winmm.reset_mock()
        sound.stop()
        commands = self._commands()
        self.assertTrue(any(c.startswith("close") for c in commands))

    def test_playing_menu_music_twice_does_not_restart_it(self) -> None:
        # Any pre-game navigation (opening the tutorial, backing out of
        # a build) can call this again; it must never interrupt an
        # already-running loop.
        sound.play_menu_music()
        self._winmm.reset_mock()
        sound.play_menu_music()
        self._winmm.mciSendStringW.assert_not_called()

    def test_stop_lets_the_music_be_started_again(self) -> None:
        sound.play_menu_music()
        sound.stop()
        self._winmm.reset_mock()
        sound.play_menu_music()
        self._winmm.mciSendStringW.assert_called()

    def test_muted_still_opens_and_plays_the_channel_then_pauses_it(self) -> None:
        # Not "never touch MCI while muted" (the old behaviour) — that
        # left the channel never actually created, so unmuting later had
        # nothing to resume (see MuteTests.
        # test_unmuting_after_starting_muted_actually_resumes). The
        # channel exists either way; muted just means it starts paused.
        with patch.object(sound, "_music_enabled", False):
            sound.play_menu_music()
        commands = self._commands()
        self.assertTrue(any("open" in c and "menu_music.mp3" in c for c in commands))
        self.assertTrue(any(c.startswith("play") and "repeat" in c for c in commands))
        self.assertTrue(any(c.startswith("pause") for c in commands))

    def test_stop_always_closes_the_channel_even_while_muted(self) -> None:
        # Muted just means silent, not "stop tracking whether the loop
        # should be running" — a mid-mute transition into deploy still
        # has to actually release the channel.
        with patch.object(sound, "_music_enabled", False):
            sound.stop()
        self._winmm.mciSendStringW.assert_called_once_with(f"close {sound._MUSIC_ALIAS}", None, 0, None)

    def test_a_playback_error_is_swallowed_not_raised(self) -> None:
        self._winmm.mciSendStringW.side_effect = OSError("no device")
        sound.play_menu_music()  # must not raise
        sound.stop()  # must not raise either

    def test_a_winsound_effect_does_not_touch_the_music_channel(self) -> None:
        # The whole point of the separate channel: firing an ordinary
        # effect must never issue an MCI command of its own.
        winsound_patcher = patch.object(sound, "winsound", MagicMock())
        winsound_patcher.start()
        self.addCleanup(winsound_patcher.stop)
        sound.play_menu_music()
        self._winmm.reset_mock()
        sound.play_move()
        sound.play_button_click()
        self._winmm.mciSendStringW.assert_not_called()


class KeepAliveTests(unittest.TestCase):
    """A silent track loops on its own MCI channel so the audio output
    never goes idle and swallows the next effect — see
    sound.keep_output_awake."""

    def setUp(self) -> None:
        self._winmm = MagicMock()
        patcher = patch.object(sound, "_winmm", self._winmm)
        patcher.start()
        self.addCleanup(patcher.stop)
        for flag in ("_keepalive_playing", "_music_playing"):
            flag_patcher = patch.object(sound, flag, False)
            flag_patcher.start()
            self.addCleanup(flag_patcher.stop)

    def _commands(self) -> list[str]:
        return [call.args[0] for call in self._winmm.mciSendStringW.call_args_list]

    def test_loops_the_silent_track_on_its_own_channel(self) -> None:
        sound.keep_output_awake()
        commands = self._commands()
        self.assertTrue(
            any(c.startswith("open") and "silence.wav" in c and sound._KEEPALIVE_ALIAS in c for c in commands)
        )
        self.assertIn(f"play {sound._KEEPALIVE_ALIAS} repeat", commands)
        self.assertFalse(any(sound._MUSIC_ALIAS in c for c in commands))

    def test_starting_it_twice_does_not_restart_it(self) -> None:
        sound.keep_output_awake()
        self._winmm.reset_mock()
        sound.keep_output_awake()
        self._winmm.mciSendStringW.assert_not_called()

    def test_stopping_the_music_leaves_it_running(self) -> None:
        sound.keep_output_awake()
        sound.play_menu_music()
        self._winmm.reset_mock()
        sound.stop()
        self.assertFalse(any(sound._KEEPALIVE_ALIAS in c for c in self._commands()))

    def test_a_playback_error_is_swallowed_not_raised(self) -> None:
        self._winmm.mciSendStringW.side_effect = OSError("no device")
        sound.keep_output_awake()  # must not raise


class MuteTests(unittest.TestCase):
    """set_music_muted/is_music_muted and set_effects_muted/
    is_effects_muted: independent switches, each the settings dialog's
    two buttons call one of."""

    def setUp(self) -> None:
        self._winmm = MagicMock()
        patcher = patch.object(sound, "_winmm", self._winmm)
        patcher.start()
        self.addCleanup(patcher.stop)
        self._winsound = MagicMock()
        winsound_patcher = patch.object(sound, "winsound", self._winsound)
        winsound_patcher.start()
        self.addCleanup(winsound_patcher.stop)
        flag_patcher = patch.object(sound, "_music_playing", False)
        flag_patcher.start()
        self.addCleanup(flag_patcher.stop)
        # The mute functions flip real module flags directly; restore
        # both regardless of what a test leaves them as.
        self.addCleanup(setattr, sound, "_music_enabled", sound._music_enabled)
        self.addCleanup(setattr, sound, "_effects_enabled", sound._effects_enabled)

    def test_starts_unmuted(self) -> None:
        self.assertFalse(sound.is_music_muted())
        self.assertFalse(sound.is_effects_muted())

    def test_muting_music_reports_as_muted(self) -> None:
        sound.set_music_muted(True)
        self.assertTrue(sound.is_music_muted())

    def test_muting_music_pauses_a_playing_channel(self) -> None:
        sound.play_menu_music()
        self._winmm.reset_mock()
        sound.set_music_muted(True)
        self._winmm.mciSendStringW.assert_called_once_with(f"pause {sound._MUSIC_ALIAS}", None, 0, None)

    def test_unmuting_music_resumes_a_playing_channel(self) -> None:
        sound.play_menu_music()
        sound.set_music_muted(True)
        self._winmm.reset_mock()
        sound.set_music_muted(False)
        self._winmm.mciSendStringW.assert_called_once_with(f"resume {sound._MUSIC_ALIAS}", None, 0, None)

    def test_unmuting_music_with_none_playing_does_not_resume(self) -> None:
        # Nothing to resume if the loop was never started (or already
        # stopped) — must not issue a resume against a closed channel.
        sound.set_music_muted(True)
        self._winmm.reset_mock()
        sound.set_music_muted(False)
        self._winmm.mciSendStringW.assert_not_called()

    def test_unmuting_after_starting_muted_actually_resumes(self) -> None:
        # The exact bug this fixes: starting the menu loop while muted
        # used to skip opening the channel at all (see _mci, removed),
        # so unmuting afterwards tried — and silently failed — to
        # resume a channel that had never actually been created,
        # leaving the music permanently silent for the rest of the
        # session no matter how many times it was un-muted.
        with patch.object(sound, "_music_enabled", False):
            sound.play_menu_music()
        self._winmm.reset_mock()
        sound.set_music_muted(False)
        self._winmm.mciSendStringW.assert_called_once_with(f"resume {sound._MUSIC_ALIAS}", None, 0, None)

    def test_muting_effects_reports_as_muted(self) -> None:
        sound.set_effects_muted(True)
        self.assertTrue(sound.is_effects_muted())

    def test_muting_effects_silences_them(self) -> None:
        sound.set_effects_muted(True)
        sound.play_move()
        self._winsound.PlaySound.assert_not_called()

    def test_unmuting_effects_restores_them(self) -> None:
        sound.set_effects_muted(True)
        sound.set_effects_muted(False)
        sound.play_move()
        self._winsound.PlaySound.assert_called_once()

    def test_muting_effects_does_not_touch_the_music_channel(self) -> None:
        sound.play_menu_music()
        self._winmm.reset_mock()
        sound.set_effects_muted(True)
        self._winmm.mciSendStringW.assert_not_called()

    def test_muting_music_does_not_touch_effects(self) -> None:
        sound.set_music_muted(True)
        sound.play_move()
        self._winsound.PlaySound.assert_called_once()


class MakeButtonSoundTests(unittest.TestCase):
    """theme.make_button wires every button to the click sound in one
    place, rather than each of its many call sites remembering to."""

    def setUp(self) -> None:
        self._root = new_tk_root()
        self.addCleanup(self._root.destroy)

    def test_clicking_a_made_button_plays_the_click_and_runs_the_command(self) -> None:
        from spokebound.ui import theme

        calls = []
        button = theme.make_button(self._root, "Go", lambda: calls.append("command"))
        with patch.object(sound, "play_button_click") as play:
            button.invoke()
        play.assert_called_once()
        self.assertEqual(calls, ["command"])


class SpokeEditorSoundTests(unittest.TestCase):
    """The same widget backs both the build screen and the in-game Piece
    Upgrade card, so this one place covers spending a point either way."""

    def setUp(self) -> None:
        self._root = new_tk_root()
        self.addCleanup(self._root.destroy)

    def test_an_accepted_spoke_change_plays_the_unit_click(self) -> None:
        from spokebound.model.pieces import Piece, Player
        from spokebound.ui import drawing
        from spokebound.ui.drawing import LEVEL_LENGTHS
        from spokebound.ui.spoke_editor import SpokeEditor

        editor = SpokeEditor(self._root, lambda spoke, step: True, size=200)
        editor.show(Piece(Player.ORANGE))
        x, y = drawing.spoke_point(editor._centre, editor._radius, 0, LEVEL_LENGTHS[1])
        with patch.object(sound, "play_unit_click") as click, patch.object(sound, "play_reject") as reject:
            editor._click(type("Event", (), {"x": x, "y": y})())
        click.assert_called_once()
        reject.assert_not_called()

    def test_a_refused_spoke_change_plays_the_reject_buzz(self) -> None:
        from spokebound.model.pieces import Piece, Player
        from spokebound.ui import drawing
        from spokebound.ui.drawing import LEVEL_LENGTHS
        from spokebound.ui.spoke_editor import SpokeEditor

        editor = SpokeEditor(self._root, lambda spoke, step: False, size=200)
        editor.show(Piece(Player.ORANGE))
        x, y = drawing.spoke_point(editor._centre, editor._radius, 0, LEVEL_LENGTHS[1])
        with patch.object(sound, "play_unit_click") as click, patch.object(sound, "play_reject") as reject:
            editor._click(type("Event", (), {"x": x, "y": y})())
        reject.assert_called_once()
        click.assert_not_called()


class DeployScreenSoundTests(unittest.TestCase):
    def setUp(self) -> None:
        self._root = new_tk_root()
        self.addCleanup(self._root.destroy)

    def _screen(self):
        from spokebound.config import FLEET_SIZE
        from spokebound.model.pieces import Piece, Player
        from spokebound.ui.deploy_screen import DeployScreen

        orange = [Piece(Player.ORANGE, spokes=[1, 0, 0, 0, 0, 0, 0, 0]) for _ in range(FLEET_SIZE)]
        white = [Piece(Player.WHITE, spokes=[1, 0, 0, 0, 0, 0, 0, 0]) for _ in range(FLEET_SIZE)]
        return DeployScreen(self._root, orange, white, lambda *a: None, lambda: None)

    def test_placing_a_piece_plays_the_button_click(self) -> None:
        screen = self._screen()
        square = screen._deployment.legal_squares()[0]
        with patch.object(sound, "play_button_click") as click:
            screen._on_square(square)
        click.assert_called_once()

    def test_clicking_an_illegal_square_plays_the_reject_buzz(self) -> None:
        screen = self._screen()
        illegal = (3, 3)  # the centre square: never a sanctuary square
        assert illegal not in screen._deployment.legal_squares()
        with patch.object(sound, "play_reject") as reject, patch.object(sound, "play_button_click") as click:
            screen._on_square(illegal)
        reject.assert_called_once()
        click.assert_not_called()


class AIMenuScreenSoundTests(unittest.TestCase):
    """Dragging the difficulty slider clicks like a button, not a unit
    edit — one click per level actually crossed, none for the initial
    default the screen opens on."""

    def setUp(self) -> None:
        self._root = new_tk_root()
        self.addCleanup(self._root.destroy)

    def test_building_the_screen_plays_no_click(self) -> None:
        from spokebound.ui.ai_menu_screen import AIMenuScreen

        with patch.object(sound, "play_button_click") as click:
            AIMenuScreen(self._root, lambda level: None, lambda: None)
        click.assert_not_called()

    def test_changing_level_plays_one_click(self) -> None:
        from spokebound.ui.ai_menu_screen import AIMenuScreen

        menu = AIMenuScreen(self._root, lambda level: None, lambda: None)
        with (
            patch.object(sound, "play_button_click") as click,
            patch.object(sound, "play_unit_click") as unit_click,
        ):
            menu._on_slide(menu._last_level + 1)
        click.assert_called_once()
        unit_click.assert_not_called()

    def test_resettling_on_the_same_level_plays_no_click(self) -> None:
        from spokebound.ui.ai_menu_screen import AIMenuScreen

        menu = AIMenuScreen(self._root, lambda level: None, lambda: None)
        with patch.object(sound, "play_button_click") as click:
            menu._on_slide(menu._last_level)
        click.assert_not_called()


class AppMusicLifecycleTests(unittest.TestCase):
    """The welcome menu's music should span every pre-game screen and
    stop once the placing-pieces phase begins — see spokebound.ui.app."""

    def setUp(self) -> None:
        from spokebound.ui.app import SpokeboundApp

        with patch.object(sound, "play_menu_music"), patch.object(sound, "keep_output_awake") as keep_awake:
            self._app = retry_tcl_init(SpokeboundApp)
        self._keep_awake = keep_awake
        self.addCleanup(self._app.destroy)

    def test_launching_keeps_the_audio_output_awake(self) -> None:
        self._keep_awake.assert_called_once()

    def test_show_welcome_starts_the_music(self) -> None:
        with patch.object(sound, "play_menu_music") as play:
            self._app.show_welcome()
        play.assert_called_once()

    def test_play_again_restarts_the_music(self) -> None:
        self._app._ai_player = None
        with patch.object(sound, "play_menu_music") as play:
            self._app._play_again()
        play.assert_called_once()

    def test_starting_deployment_stops_the_music(self) -> None:
        from spokebound.model.pieces import Piece, Player

        self._app._fleets = {
            Player.ORANGE: [Piece(Player.ORANGE, spokes=[1, 0, 0, 0, 0, 0, 0, 0])],
            Player.WHITE: [Piece(Player.WHITE, spokes=[1, 0, 0, 0, 0, 0, 0, 0])],
        }
        with patch.object(sound, "stop") as stop:
            self._app._start_deploy()
        stop.assert_called_once()

    def test_finishing_deployment_does_not_stop_the_music_again(self) -> None:
        # It already stopped when deployment began; actual play
        # beginning (the same DeployScreen instance, handed off in
        # place — see its own module docstring) has no reason to touch
        # it again.
        from spokebound.model.pieces import Piece, Player

        self._app._fleets = {
            Player.ORANGE: [Piece(Player.ORANGE, spokes=[1, 0, 0, 0, 0, 0, 0, 0])],
            Player.WHITE: [Piece(Player.WHITE, spokes=[1, 0, 0, 0, 0, 0, 0, 0])],
        }
        self._app._start_deploy()
        screen = self._app._screen
        with patch.object(sound, "stop") as stop:
            while not screen._deployment.is_done:
                screen._place(screen._deployment.legal_squares()[0])
        stop.assert_not_called()


def _button_texts(dialog) -> list[str]:
    """The label text inside each fixed-size button holder in the
    dialog's button row, in pack order (music, then effects)."""
    texts = []
    for holder in dialog._buttons_row.winfo_children():
        button = holder.winfo_children()[0]
        texts.append(button.cget("text"))
    return texts


class SettingsDialogTests(unittest.TestCase):
    """The gear icon's popup: a thin face on the real
    sound.set_music_muted/set_effects_muted (MuteTests covers the
    muting logic itself in isolation) — checked here against a mocked
    MCI channel, so no real audio calls happen, but the module's actual
    mute state does change."""

    def setUp(self) -> None:
        self._root = new_tk_root()
        self.addCleanup(self._root.destroy)
        patcher = patch.object(sound, "_winmm", MagicMock())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(setattr, sound, "_music_enabled", sound._music_enabled)
        self.addCleanup(setattr, sound, "_effects_enabled", sound._effects_enabled)
        sound._music_enabled = True
        sound._effects_enabled = True

    def test_opens_showing_two_mute_buttons(self) -> None:
        from spokebound.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self._root)
        texts = _button_texts(dialog)
        self.assertEqual(len(texts), 2)
        self.assertEqual(texts, ["Mute Music", "Mute Sound"])
        dialog.destroy()

    def test_toggling_music_only_relabels_the_music_button(self) -> None:
        from spokebound.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self._root)
        dialog._toggle_music()
        self.assertTrue(sound.is_music_muted())
        self.assertFalse(sound.is_effects_muted())
        self.assertEqual(_button_texts(dialog), ["Unmute Music", "Mute Sound"])
        dialog.destroy()

    def test_toggling_effects_only_relabels_the_effects_button(self) -> None:
        from spokebound.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self._root)
        dialog._toggle_effects()
        self.assertFalse(sound.is_music_muted())
        self.assertTrue(sound.is_effects_muted())
        self.assertEqual(_button_texts(dialog), ["Mute Music", "Unmute Sound"])
        dialog.destroy()

    def test_every_rebuild_keeps_the_same_fixed_size(self) -> None:
        from spokebound.ui.settings_dialog import BUTTON_HEIGHT, BUTTON_WIDTH, SettingsDialog

        dialog = SettingsDialog(self._root)
        for holder in dialog._buttons_row.winfo_children():
            self.assertEqual(int(holder.cget("width")), BUTTON_WIDTH)
            self.assertEqual(int(holder.cget("height")), BUTTON_HEIGHT)
        dialog._toggle_music()
        dialog._toggle_effects()
        for holder in dialog._buttons_row.winfo_children():
            self.assertEqual(int(holder.cget("width")), BUTTON_WIDTH)
            self.assertEqual(int(holder.cget("height")), BUTTON_HEIGHT)
        dialog.destroy()


class SettingsGearTests(unittest.TestCase):
    """add_gear is what every screen (not just the welcome menu) puts in
    its own top-right corner — see spokebound.ui.settings_gear."""

    def setUp(self) -> None:
        self._root = new_tk_root()
        self.addCleanup(self._root.destroy)

    def test_the_gear_opens_the_settings_dialog(self) -> None:
        from spokebound.ui.settings_gear import add_gear

        frame = tk.Frame(self._root)
        gear = add_gear(frame)
        with patch("spokebound.ui.settings_gear.SettingsDialog") as dialog:
            gear.invoke()
        dialog.assert_called_once_with(frame)


if __name__ == "__main__":
    unittest.main()
