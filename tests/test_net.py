"""Tests for the network-play layer: the wire protocol round-trips
every action losslessly, and a host/join pair of NetworkSessions
actually connect and exchange messages over a real loopback socket —
mocking the socket here would only test the mock, not the framing and
threading this module exists to get right.
"""

import functools
import socket
import time
import unittest
from unittest import mock

from spokebound.model.pieces import Piece, Player
from spokebound.net import directory, protocol, session

_CONNECT_TIMEOUT = 2.0
_POLL_INTERVAL = 0.02


def _free_port() -> int:
    """Return a TCP port the OS says is free right now, for one test's
    own loopback connection. Asking the OS, rather than picking from a
    fixed range, means a fresh port every test (so a slow-closing socket
    from the last one can't make the next flaky) and never one inside a
    range Windows has reserved for Hyper-V, WSL or Docker, which bind()
    refuses with WinError 10013."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("0.0.0.0", 0))
        return probe.getsockname()[1]


def _wait_for(get_session, kind: str, timeout: float = _CONNECT_TIMEOUT):
    """Poll ``get_session()`` until an event of ``kind`` arrives, and
    return it. Fails the test (via TimeoutError) if it never does."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for event in get_session().poll():
            if event.kind == kind:
                return event
        time.sleep(_POLL_INTERVAL)
    raise TimeoutError(f"no {kind!r} event within {timeout}s")


class ProtocolRoundTripTests(unittest.TestCase):
    """Every message survives being turned into a dict and back."""

    def test_fleet_round_trips_every_piece_field(self) -> None:
        pieces = [
            Piece(Player.ORANGE, spokes=[1, 0, 2, 0, 3, 0, 4, 0], bounty=2, promoted=True, is_captain=False),
            Piece(Player.WHITE, spokes=[0] * 8, is_captain=True),
        ]
        restored = protocol.fleet_from(protocol.fleet(pieces))
        self.assertEqual(restored, pieces)

    def test_place_round_trips_a_square(self) -> None:
        square = (3, 5)
        self.assertEqual(protocol.place_from(protocol.place(square)), square)

    def test_move_round_trips_src_and_dst(self) -> None:
        src, dst = (8, 3), (7, 3)
        restored_src, restored_dst = protocol.move_from(protocol.move(src, dst))
        self.assertEqual((restored_src, restored_dst), (src, dst))

    def test_upgrade_adjust_round_trips_spoke_and_step(self) -> None:
        spoke, step = protocol.upgrade_adjust_from(protocol.upgrade_adjust(4, -1))
        self.assertEqual((spoke, step), (4, -1))

    def test_hello_carries_the_current_protocol_version(self) -> None:
        self.assertEqual(protocol.hello()["version"], protocol.PROTOCOL_VERSION)


class NetworkSessionTests(unittest.TestCase):
    """A real host/join pair over 127.0.0.1 — connection, messages in
    both directions, and disconnect all actually exercised rather than
    mocked, since that's exactly the behaviour this module has to get
    right."""

    def setUp(self) -> None:
        self._port = _free_port()
        self._sessions: list[session.NetworkSession] = []

    def tearDown(self) -> None:
        for sess in self._sessions:
            sess.close()

    def _connect_pair(self):
        host = session.NetworkSession.host(self._port)
        client = session.NetworkSession.join("127.0.0.1", self._port)
        self._sessions.extend([host, client])
        _wait_for(lambda: host, session.CONNECTED)
        _wait_for(lambda: client, session.CONNECTED)
        return host, client

    def test_join_connects_to_a_hosted_session(self) -> None:
        self._connect_pair()  # raises via _wait_for if it never connects

    def test_a_message_sent_by_the_host_arrives_at_the_client(self) -> None:
        host, client = self._connect_pair()
        host.send(protocol.place((2, 4)))
        event = _wait_for(lambda: client, session.MESSAGE)
        self.assertEqual(protocol.place_from(event.data), (2, 4))

    def test_a_message_sent_by_the_client_arrives_at_the_host(self) -> None:
        host, client = self._connect_pair()
        client.send(protocol.move((8, 3), (7, 3)))
        event = _wait_for(lambda: host, session.MESSAGE)
        self.assertEqual(protocol.move_from(event.data), ((8, 3), (7, 3)))

    def test_several_messages_in_a_row_all_arrive_in_order(self) -> None:
        host, client = self._connect_pair()
        for step in range(5):
            host.send(protocol.upgrade_adjust(step, 1))
        seen = []
        while len(seen) < 5:
            for event in _wait_for_all(client):
                seen.append(protocol.upgrade_adjust_from(event.data))
        self.assertEqual(seen, [(step, 1) for step in range(5)])

    def test_closing_the_host_notifies_the_client(self) -> None:
        host, client = self._connect_pair()
        host.close()
        _wait_for(lambda: client, session.DISCONNECTED)

    def test_join_reports_an_error_when_nothing_is_listening(self) -> None:
        client = session.NetworkSession.join("127.0.0.1", self._port)
        self._sessions.append(client)
        # A closed port isn't always refused instantly — some networks
        # (this one included) just silently drop it — so this has to
        # outlast NetworkSession's own connect timeout.
        _wait_for(lambda: client, session.ERROR, timeout=session._CONNECT_TIMEOUT_SECONDS + 2)

    def test_sending_before_a_connection_exists_does_not_raise(self) -> None:
        client = session.NetworkSession.join("127.0.0.1", self._port)
        self._sessions.append(client)
        client.send(protocol.hello())  # no connection yet — must not raise
        # Nothing is listening on this port, so the background connect
        # attempt is still in flight — wait for it to actually resolve
        # rather than leaving it to run on, orphaned, well past this
        # test's own end (tearDown's close() can't interrupt a
        # create_connection() call that hasn't produced a socket yet).
        _wait_for(lambda: client, session.ERROR, timeout=session._CONNECT_TIMEOUT_SECONDS + 2)


class RoomCodeTests(unittest.TestCase):
    """A real RoomHost/find_room pair over loopback — the LAN-discovery
    lookup a room code resolves through before NetworkSession's own
    connection ever starts. Mocking the socket here would only test
    the mock, not the framing this module exists to get right, same
    reasoning as NetworkSessionTests above."""

    def test_generate_room_code_has_the_expected_shape(self) -> None:
        code = directory.generate_room_code()
        self.assertEqual(len(code), directory.CODE_LENGTH)
        self.assertTrue(set(code) <= set(directory._CODE_ALPHABET))

    def test_generate_room_code_is_not_the_same_every_time(self) -> None:
        codes = {directory.generate_room_code() for _ in range(20)}
        self.assertGreater(len(codes), 1)

    # Each RoomHost below listens on an OS-assigned port (discovery_port=0)
    # rather than the real DISCOVERY_PORT, which can sit inside a range
    # Windows has reserved on whichever machine runs the tests.

    def test_find_room_locates_a_hosted_room_by_its_code(self) -> None:
        code = directory.generate_room_code()
        host = directory.RoomHost(code, game_port=54321, discovery_port=0)
        self.addCleanup(host.close)
        found = directory.find_room(code, timeout=2.0, discovery_port=host.discovery_port)
        self.assertIsNotNone(found)
        _, port = found
        self.assertEqual(port, 54321)

    def test_find_room_ignores_a_room_hosted_under_another_code(self) -> None:
        host = directory.RoomHost(directory.generate_room_code(), game_port=54322, discovery_port=0)
        self.addCleanup(host.close)
        # A code that's (almost certainly) not the one just hosted —
        # generated the same way, so a real collision is vanishingly
        # unlikely without needing to hand-pick a "wrong" value.
        other_code = directory.generate_room_code()
        found = directory.find_room(other_code, timeout=1.0, discovery_port=host.discovery_port)
        self.assertIsNone(found)

    def test_room_host_reports_the_port_the_os_assigned(self) -> None:
        host = directory.RoomHost(directory.generate_room_code(), game_port=54323, discovery_port=0)
        self.addCleanup(host.close)
        self.assertNotEqual(host.discovery_port, 0)

    def test_find_room_returns_none_when_nobody_is_hosting(self) -> None:
        found = directory.find_room(directory.generate_room_code(), timeout=1.0)
        self.assertIsNone(found)

    def test_join_by_room_code_connects_once_the_room_is_found(self) -> None:
        port = _free_port()
        code = directory.generate_room_code()
        room_host = directory.RoomHost(code, game_port=port, discovery_port=0)
        self.addCleanup(room_host.close)
        # The real lookup, pointed at this test's own discovery port.
        finder = mock.patch.object(
            session,
            "find_room",
            functools.partial(directory.find_room, discovery_port=room_host.discovery_port),
        )
        finder.start()
        self.addCleanup(finder.stop)
        host = session.NetworkSession.host(port)
        client = session.NetworkSession.join_by_room_code(code, 3.0)
        self.addCleanup(host.close)
        self.addCleanup(client.close)
        _wait_for(lambda: host, session.CONNECTED)
        _wait_for(lambda: client, session.CONNECTED)

    def test_join_by_room_code_errors_when_the_code_is_unknown(self) -> None:
        client = session.NetworkSession.join_by_room_code(
            directory.generate_room_code(), discovery_timeout=1.0
        )
        self.addCleanup(client.close)
        _wait_for(lambda: client, session.ERROR, timeout=2.0)


class AddressCodeTests(unittest.TestCase):
    """encode_address/decode_address — the room-code-shaped alternative
    used once a host's real address is known (see
    spokebound.net.address.public_ip), so a friend anywhere gets one
    thing to type same as a LAN friend's room code, rather than a raw
    IP:port string."""

    def test_round_trips_a_real_looking_address(self) -> None:
        code = directory.encode_address("198.51.100.23", 51820)
        self.assertEqual(directory.decode_address(code), ("198.51.100.23", 51820))

    def test_round_trips_the_extremes_of_each_field(self) -> None:
        for host, port in [("0.0.0.0", 0), ("255.255.255.255", 65535), ("192.168.1.1", 1)]:
            code = directory.encode_address(host, port)
            self.assertEqual(directory.decode_address(code), (host, port))

    def test_encoded_addresses_are_a_different_length_than_room_codes(self) -> None:
        code = directory.encode_address("198.51.100.23", 51820)
        self.assertEqual(len(code), directory.ADDRESS_CODE_LENGTH)
        self.assertNotEqual(directory.ADDRESS_CODE_LENGTH, directory.CODE_LENGTH)

    def test_a_real_room_code_never_decodes_as_an_address(self) -> None:
        # Wrong length (CODE_LENGTH, not ADDRESS_CODE_LENGTH) — this is
        # the property _start_join's dispatch between the two actually
        # relies on, see spokebound.ui.network_lobby_screen.
        self.assertIsNone(directory.decode_address(directory.generate_room_code()))

    def test_rejects_a_code_with_a_character_outside_the_alphabet(self) -> None:
        self.assertIsNone(directory.decode_address("IIIIIIIIII"))

    def test_rejects_the_wrong_length(self) -> None:
        self.assertIsNone(directory.decode_address("ABCDE"))
        self.assertIsNone(directory.decode_address("A" * 11))


def _wait_for_all(sess: session.NetworkSession, timeout: float = _CONNECT_TIMEOUT):
    """Poll until at least one event has arrived, then return every
    event queued at that point (there may be more than one)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = sess.poll()
        if events:
            return events
        time.sleep(_POLL_INTERVAL)
    raise TimeoutError(f"no events within {timeout}s")


if __name__ == "__main__":
    unittest.main()
