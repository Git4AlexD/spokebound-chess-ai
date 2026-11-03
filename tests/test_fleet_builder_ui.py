"""Tests for the fixed-size/shrink-to-fit button machinery and the
shared fleet-building widgets built on top of it: fit_text,
theme.make_fixed_button, FleetEditor, preset_column, and the custom-fleet
screen's own save/load/delete wiring."""

import tempfile
import tkinter as tk
import tkinter.font as tkfont
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from spokebound.model import custom_fleets
from spokebound.model.pieces import Player
from spokebound.model.spending import FleetBuilder
from spokebound.ui import fit_text, theme
from spokebound.ui.fleet_editor import FleetEditor
from spokebound.ui.preset_column import build_preset_column
from tests.tk_support import new_tk_root


class FitTextTests(unittest.TestCase):
    def setUp(self) -> None:
        self._root = new_tk_root()
        self.addCleanup(self._root.destroy)

    def test_short_text_keeps_the_base_size(self) -> None:
        size = fit_text.fit_font_size(self._root, "Hi", "Helvetica", 12,
                                      max_width=200)
        self.assertEqual(size, 12)

    def test_long_text_shrinks_to_fit(self) -> None:
        long_text = "A Very Long Preset Fleet Name Indeed" * 2
        size = fit_text.fit_font_size(self._root, long_text, "Helvetica",
                                      12, max_width=100)
        self.assertLess(size, 12)

    def test_never_shrinks_below_the_floor(self) -> None:
        long_text = "An Extremely Unreasonably Long Custom Fleet Name" * 5
        size = fit_text.fit_font_size(self._root, long_text, "Helvetica",
                                      12, max_width=20, min_size=7)
        self.assertEqual(size, 7)

    def test_bold_text_is_measured_as_bold(self) -> None:
        text = "Spokebound"
        size = fit_text.fit_font_size(self._root, text, "Helvetica", 40,
                                      max_width=300, weight="bold")
        measured = tkfont.Font(root=self._root, family="Helvetica",
                               size=size, weight="bold").measure(text)
        self.assertLessEqual(measured, 300)


class MakeFixedButtonTests(unittest.TestCase):
    def setUp(self) -> None:
        self._root = new_tk_root()
        self.addCleanup(self._root.destroy)

    def test_holder_is_pinned_to_the_requested_size(self) -> None:
        holder = theme.make_fixed_button(self._root, "Short", lambda: None,
                                         width=140, height=36)
        self.assertEqual(int(holder.cget("width")), 140)
        self.assertEqual(int(holder.cget("height")), 36)

    def test_a_very_long_label_keeps_the_same_size(self) -> None:
        holder = theme.make_fixed_button(
            self._root, "An Extremely Unreasonably Long Custom Fleet Name",
            lambda: None, width=140, height=36)
        self.assertEqual(int(holder.cget("width")), 140)
        self.assertEqual(int(holder.cget("height")), 36)

    def test_clicking_runs_the_command(self) -> None:
        calls = []
        holder = theme.make_fixed_button(self._root, "Go",
                                         lambda: calls.append(1),
                                         width=140, height=36)
        button = holder.winfo_children()[0]
        with patch("spokebound.ui.theme.sound.play_button_click"):
            button.invoke()
        self.assertEqual(calls, [1])


class NameDialogTests(unittest.TestCase):
    """The themed replacement for tkinter.simpledialog.askstring.

    wait_window() (called at the end of its own __init__, to block the
    caller the same way askstring does) is stubbed out for these tests
    — otherwise construction alone would hang forever, since nothing
    autonomously closes the dialog in a plain unittest.
    """

    def setUp(self) -> None:
        self._root = new_tk_root()
        self.addCleanup(self._root.destroy)

    def _dialog(self, initial: str = ""):
        from spokebound.ui.name_dialog import NameDialog

        with patch.object(NameDialog, "wait_window", lambda self: None):
            return NameDialog(self._root, "Save Fleet", "Name this fleet:",
                             initial)

    def test_starts_with_the_initial_value(self) -> None:
        dialog = self._dialog(initial="Old Name")
        self.assertEqual(dialog._name_var.get(), "Old Name")
        dialog.destroy()

    def test_confirming_sets_result_to_the_typed_name(self) -> None:
        dialog = self._dialog()
        dialog._name_var.set("My Fleet")
        dialog._confirm()
        self.assertEqual(dialog.result, "My Fleet")

    def test_confirming_strips_surrounding_whitespace(self) -> None:
        dialog = self._dialog()
        dialog._name_var.set("  My Fleet  ")
        dialog._confirm()
        self.assertEqual(dialog.result, "My Fleet")

    def test_confirming_blank_leaves_result_none(self) -> None:
        dialog = self._dialog()
        dialog._name_var.set("   ")
        dialog._confirm()
        self.assertIsNone(dialog.result)

    def test_cancelling_leaves_result_none_even_with_text_typed(self) -> None:
        dialog = self._dialog()
        dialog._name_var.set("My Fleet")
        dialog._cancel()
        self.assertIsNone(dialog.result)

    def test_confirming_closes_the_window(self) -> None:
        dialog = self._dialog()
        dialog._confirm()
        self.assertFalse(dialog.winfo_exists())

    def test_the_entry_confirms_on_return_and_cancels_on_escape(self) -> None:
        dialog = self._dialog()
        entry = next(w for w in dialog.winfo_children()
                    if isinstance(w, tk.Entry))
        self.assertTrue(entry.bind("<Return>"))
        self.assertTrue(entry.bind("<Escape>"))
        dialog.destroy()


class FleetEditorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._root = new_tk_root()
        self.addCleanup(self._root.destroy)

    def _editor(self, on_change=None):
        builder = FleetBuilder(Player.ORANGE)
        return FleetEditor(self._root, builder, thumb_size=60,
                          editor_size=160, pady=4, on_change=on_change)

    def test_starts_invalid_with_every_piece_at_zero(self) -> None:
        editor = self._editor()
        self.assertFalse(editor.is_valid())

    def test_loading_a_preset_makes_it_valid_and_fires_on_change(self) -> None:
        from spokebound.model.presets import PRESETS

        calls = []
        editor = self._editor(on_change=lambda: calls.append(1))
        editor.load_preset(PRESETS["Vanguard"])
        self.assertTrue(editor.is_valid())
        self.assertEqual(calls, [1])
        self.assertEqual([p.cost for p in editor.pieces],
                         [sum((0, 1, 2, 4)[lvl] for lvl in spokes)
                         for spokes in PRESETS["Vanguard"]])

    def test_on_change_is_not_fired_by_construction_itself(self) -> None:
        calls = []
        self._editor(on_change=lambda: calls.append(1))
        self.assertEqual(calls, [])

    def test_an_accepted_adjust_fires_on_change(self) -> None:
        calls = []
        editor = self._editor(on_change=lambda: calls.append(1))
        accepted = editor._adjust(0, 1)  # spend 1 pt on spoke 0
        self.assertTrue(accepted)
        self.assertEqual(calls, [1])

    def test_a_refused_adjust_does_not_fire_on_change(self) -> None:
        calls = []
        editor = self._editor(on_change=lambda: calls.append(1))
        accepted = editor._adjust(0, -1)  # can't go below level 0
        self.assertFalse(accepted)
        self.assertEqual(calls, [])


class PresetColumnTests(unittest.TestCase):
    def setUp(self) -> None:
        self._root = new_tk_root()
        self.addCleanup(self._root.destroy)

    def test_empty_entries_show_the_placeholder_text(self) -> None:
        column = build_preset_column(self._root, "Your Custom Fleets", [],
                                     140, 32, 4,
                                     empty_text="No Custom Fleets Built Yet")
        texts = [w.cget("text") for w in column.winfo_children()
                if isinstance(w, tk.Label)]
        self.assertIn("No Custom Fleets Built Yet", texts)

    def test_entries_without_delete_are_a_single_button_each(self) -> None:
        column = build_preset_column(
            self._root, "Presets", [("Rush", lambda: None)], 140, 32, 4)
        # heading label + one fixed-button holder
        self.assertEqual(len(column.winfo_children()), 2)

    def test_entries_with_delete_add_a_second_button(self) -> None:
        calls = []
        column = build_preset_column(
            self._root, "Yours", [("Rush", lambda: None)], 140, 32, 4,
            on_delete=lambda name: calls.append(name))
        row = column.winfo_children()[1]
        self.assertEqual(len(row.winfo_children()), 2)

    def test_delete_button_calls_on_delete_with_the_entrys_name(self) -> None:
        calls = []
        column = build_preset_column(
            self._root, "Yours", [("Rush", lambda: None)], 140, 32, 4,
            on_delete=lambda name: calls.append(name))
        row = column.winfo_children()[1]
        delete_holder = row.winfo_children()[1]
        delete_button = delete_holder.winfo_children()[0]
        with patch("spokebound.ui.theme.sound.play_button_click"):
            delete_button.invoke()
        self.assertEqual(calls, ["Rush"])


class CustomFleetScreenTests(unittest.TestCase):
    def setUp(self) -> None:
        self._root = new_tk_root()
        self.addCleanup(self._root.destroy)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Path(tmp.name) / "custom_fleets.json"
        patcher = patch.object(custom_fleets, "_STORE", store)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _screen(self):
        from spokebound.ui.custom_fleet_screen import CustomFleetScreen

        return CustomFleetScreen(self._root, lambda: None)

    def test_save_is_disabled_until_the_fleet_is_valid(self) -> None:
        screen = self._screen()
        self.assertIn("disabled", screen._save_button.state())

    def test_saving_without_a_name_does_not_persist_anything(self) -> None:
        from spokebound.model.presets import PRESETS

        screen = self._screen()
        screen._load(PRESETS["Rush"])
        dialog = MagicMock(result=None)
        with patch("spokebound.ui.custom_fleet_screen.NameDialog",
                  return_value=dialog):
            screen._save()
        self.assertEqual(custom_fleets.load_all(), {})

    def test_saving_with_a_name_persists_the_built_fleet(self) -> None:
        from spokebound.model.presets import PRESETS

        screen = self._screen()
        screen._load(PRESETS["Rush"])
        dialog = MagicMock(result="My Fleet")
        with patch("spokebound.ui.custom_fleet_screen.NameDialog",
                  return_value=dialog):
            screen._save()
        self.assertEqual(custom_fleets.load_all(), {"My Fleet": PRESETS["Rush"]})

    def test_saving_an_invalid_fleet_does_not_prompt_or_persist(self) -> None:
        screen = self._screen()  # still all-zero, invalid
        with patch("spokebound.ui.custom_fleet_screen.NameDialog") as dialog:
            screen._save()
        dialog.assert_not_called()
        self.assertEqual(custom_fleets.load_all(), {})

    def test_delete_removes_a_saved_fleet(self) -> None:
        custom_fleets.save("My Fleet", [[1, 0, 0, 0, 0, 0, 0, 0]] * 6)
        screen = self._screen()
        screen._delete("My Fleet")
        self.assertEqual(custom_fleets.load_all(), {})


if __name__ == "__main__":
    unittest.main()
