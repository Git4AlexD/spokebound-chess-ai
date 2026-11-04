"""Tests for spokebound.model.custom_fleets: plain JSON persistence,
isolated from the real data file via a temp path."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from spokebound.model import custom_fleets

FLEET = [[1, 0, 0, 0, 0, 0, 0, 0]] * 6


class CustomFleetsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        store = Path(self._tmp.name) / "custom_fleets.json"
        patcher = patch.object(custom_fleets, "_STORE", store)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_load_all_is_empty_before_anything_is_saved(self) -> None:
        self.assertEqual(custom_fleets.load_all(), {})

    def test_save_then_load_all_round_trips(self) -> None:
        custom_fleets.save("Rushers", FLEET)
        self.assertEqual(custom_fleets.load_all(), {"Rushers": FLEET})

    def test_save_creates_the_data_directory(self) -> None:
        nested = custom_fleets._STORE.parent / "nested" / "custom_fleets.json"
        with patch.object(custom_fleets, "_STORE", nested):
            self.assertFalse(nested.parent.exists())
            custom_fleets.save("Rushers", FLEET)
            self.assertTrue(nested.is_file())

    def test_saving_twice_under_the_same_name_overwrites(self) -> None:
        custom_fleets.save("Rushers", FLEET)
        other = [[2, 0, 0, 0, 0, 0, 0, 0]] * 6
        custom_fleets.save("Rushers", other)
        self.assertEqual(custom_fleets.load_all(), {"Rushers": other})

    def test_multiple_fleets_coexist(self) -> None:
        custom_fleets.save("Rushers", FLEET)
        custom_fleets.save("Turtles", [[0, 1, 0, 0, 0, 0, 0, 0]] * 6)
        self.assertEqual(set(custom_fleets.load_all()), {"Rushers", "Turtles"})

    def test_delete_removes_a_saved_fleet(self) -> None:
        custom_fleets.save("Rushers", FLEET)
        custom_fleets.delete("Rushers")
        self.assertEqual(custom_fleets.load_all(), {})

    def test_deleting_an_unknown_name_does_nothing(self) -> None:
        custom_fleets.save("Rushers", FLEET)
        custom_fleets.delete("Nonexistent")  # must not raise
        self.assertEqual(custom_fleets.load_all(), {"Rushers": FLEET})

    def test_a_corrupt_store_reads_back_as_empty(self) -> None:
        custom_fleets._STORE.parent.mkdir(parents=True, exist_ok=True)
        custom_fleets._STORE.write_text("not valid json{")
        self.assertEqual(custom_fleets.load_all(), {})


class DefaultStoreLocationTests(unittest.TestCase):
    """Where custom_fleets.json lives depends on whether this is a
    packaged executable — a plain source run keeps its data next to the
    project, but a PyInstaller build extracts to a temp folder that's
    deleted on exit, so it needs a real, persistent location instead."""

    def test_unfrozen_uses_the_project_data_folder(self) -> None:
        with patch.object(custom_fleets.sys, "frozen", False, create=True):
            store = custom_fleets._default_store()
        self.assertEqual(store.name, "custom_fleets.json")
        self.assertEqual(store.parent.name, "data")

    def test_frozen_uses_appdata_not_the_temp_bundle(self) -> None:
        with (
            patch.object(custom_fleets.sys, "frozen", True, create=True),
            patch.dict("os.environ", {"APPDATA": r"C:\Users\Test\AppData\Roaming"}),
        ):
            store = custom_fleets._default_store()
        self.assertEqual(store, Path(r"C:\Users\Test\AppData\Roaming") / "Spokebound" / "custom_fleets.json")


if __name__ == "__main__":
    unittest.main()
