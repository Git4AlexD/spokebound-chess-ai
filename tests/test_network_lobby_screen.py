"""Tests for the Join box's dual room-code/address parsing (see the
module docstring on network_lobby_screen for why it accepts both)."""

import unittest

from spokebound.net.address import DEFAULT_PORT
from spokebound.ui.network_lobby_screen import (
    _looks_like_address, _parse_address)


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


if __name__ == "__main__":
    unittest.main()
