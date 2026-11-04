"""Tests for the Join box's dual room-code/address parsing (see the
module docstring on network_lobby_screen for why it accepts both)."""

import unittest
from unittest import mock

from spokebound.net.address import DEFAULT_PORT
from spokebound.ui import network_lobby_screen as lobby
from spokebound.ui.network_lobby_screen import _looks_like_address, _parse_address
from tests.tk_support import new_tk_root


class LooksLikeAddressTests(unittest.TestCase):
    def test_a_room_code_does_not_look_like_an_address(self) -> None:
        self.assertFalse(_looks_like_address("K7XQP"))

    def test_an_address_carrying_code_does_not_look_like_an_address(
            self) -> None:
        # Handled by decode_address in _start_join instead — a
        # directory.encode_address code has no '.' or ':' in it either,
        # same as a plain room code, so it takes the same path through
        # here and only diverges after.
        self.assertFalse(_looks_like_address("DP8ENF4JJ6"))

    def test_a_bare_ip_looks_like_an_address(self) -> None:
        self.assertTrue(_looks_like_address("203.0.113.10"))

    def test_an_ip_with_a_port_looks_like_an_address(self) -> None:
        self.assertTrue(_looks_like_address("203.0.113.10:51820"))

    def test_a_hostname_looks_like_an_address(self) -> None:
        self.assertTrue(_looks_like_address("my-host.example.com"))


class ParseAddressTests(unittest.TestCase):
    def test_a_bare_host_defaults_to_the_default_port(self) -> None:
        self.assertEqual(_parse_address("203.0.113.10"),
                         ("203.0.113.10", DEFAULT_PORT))

    def test_a_host_with_a_port_uses_that_port(self) -> None:
        self.assertEqual(_parse_address("203.0.113.10:12345"),
                         ("203.0.113.10", 12345))


class HostingTests(unittest.TestCase):
    """The Host screen, with every socket patched out."""

    def setUp(self) -> None:
        self._root = new_tk_root()
        self.addCleanup(self._root.destroy)

    def test_hosting_still_opens_when_the_discovery_port_is_unavailable(
            self) -> None:
        # What bind() raises on Windows for a port inside a range
        # Hyper-V, WSL or Docker has reserved (WinError 10013).
        reserved = PermissionError(13, "An attempt was made to access a "
                                       "socket in a way forbidden by its "
                                       "access permissions")
        with (mock.patch.object(lobby, "RoomHost", side_effect=reserved),
              mock.patch.object(lobby, "NetworkSession") as sessions,
              mock.patch.object(lobby.relay, "address", return_value=None),
              mock.patch.object(lobby, "_KNOWN_PUBLIC_IP", "203.0.113.10")):
            sessions.host.return_value.poll.return_value = []
            screen = lobby.NetworkLobbyScreen(self._root, mock.Mock(),
                                              mock.Mock())
            screen._show_host()
        sessions.host.assert_called_once_with(DEFAULT_PORT)
        self.assertIsNone(screen._room_host)
        # The address code still gives a friend a way in.
        self.assertIsNotNone(screen._address_code)


if __name__ == "__main__":
    unittest.main()
