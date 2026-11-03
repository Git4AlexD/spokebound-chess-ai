"""Regression tests for the network-play screen handoff in app.py — a
real two-app, real-socket integration test. The bug this guards
against (see test_second_fleet_submitter_reaches_deploy_screen) only
ever showed up in the actual reentrant call chain between two live
NetworkSessions and app.py's own screen-switching, never in a
unit-level check of either piece alone, so mocking either one here
would only test the mock.
"""

import time
import tkinter as tk
import unittest

from spokebound.model.pieces import Piece, Player
from spokebound.model.presets import PRESETS
from spokebound.net.session import NetworkSession
from spokebound.ui.app import SpokeboundApp
from tests.tk_support import retry_tcl_init

_PORT_BASE = 58900


def _make_app() -> SpokeboundApp:
    """Return a SpokeboundApp built without its normal __init__ side
    effects (maximizing the window, starting menu music) — this test
    only needs its screen-switching logic, not a real visible window."""
    def build() -> SpokeboundApp:
        app = SpokeboundApp.__new__(SpokeboundApp)
        tk.Tk.__init__(app)
        app._screen = None
        app._fleets = {}
        app._ai_player = None
        app._ai_difficulty = None
        app._session = None
        app._local_player = None
        app._remote_player = None
        return app
    return retry_tcl_init(build)


def _pieces(preset_name: str, owner: Player) -> list[Piece]:
    return [Piece(owner, spokes=list(spokes))
           for spokes in PRESETS[preset_name]]


class NetworkFleetHandoffTests(unittest.TestCase):
    """Both sides of a network match must actually reach the deploy
    screen once fleets are exchanged — regardless of which one submits
    first."""

    def setUp(self) -> None:
        self._port = _PORT_BASE + self._testMethodName.__hash__() % 500
        self.host = _make_app()
        self.join = _make_app()
        self.addCleanup(self.host.destroy)
        self.addCleanup(self.join.destroy)

    def _pump(self, cycles: int = 40, delay: float = 0.02) -> None:
        """Run both apps' event loops forward, giving background
        network threads real wall-clock time to deliver messages."""
        for _ in range(cycles):
            self.host.update()
            self.join.update()
            time.sleep(delay)

    def _connect(self) -> None:
        host_session = NetworkSession.host(self._port)
        join_session = NetworkSession.join("127.0.0.1", self._port)
        self._pump()
        self.host._network_connected(host_session, True)
        self.join._network_connected(join_session, False)
        self._pump()

    def test_second_fleet_submitter_reaches_deploy_screen(self) -> None:
        """The second side to submit its fleet already has the first
        side's fleet message queued, so processing it happens on the
        very first, synchronous poll inside NetworkWaitScreen's own
        __init__ — which used to reenter app._show() and clobber its
        own, already-correct DeployScreen back off screen with a
        NetworkWaitScreen stuck waiting on a message already
        consumed."""
        self._connect()
        self.join._network_fleet_done(_pieces("Balanced", Player.WHITE))
        self._pump()
        self.host._network_fleet_done(_pieces("Balanced", Player.ORANGE))
        self._pump()

        self.assertEqual(type(self.host._screen).__name__, "DeployScreen")
        self.assertEqual(type(self.join._screen).__name__, "DeployScreen")

    def test_first_fleet_submitter_also_reaches_deploy_screen(self) -> None:
        """The same handoff with host and join's roles in it swapped —
        submit order, not host/join identity, is what used to matter."""
        self._connect()
        self.host._network_fleet_done(_pieces("Balanced", Player.ORANGE))
        self._pump()
        self.join._network_fleet_done(_pieces("Balanced", Player.WHITE))
        self._pump()

        self.assertEqual(type(self.host._screen).__name__, "DeployScreen")
        self.assertEqual(type(self.join._screen).__name__, "DeployScreen")

    def test_a_placement_made_right_after_connecting_reaches_the_peer(
            self) -> None:
        """Once both are on the deploy screen, a placement sent the
        instant deployment starts — before the peer's own first poll
        would otherwise have run — must still update the peer's board
        and hand the turn over correctly (the same reentrancy hazard
        DeployScreen's own first poll has, see its __init__)."""
        self._connect()
        self.join._network_fleet_done(_pieces("Balanced", Player.WHITE))
        self._pump()
        self.host._network_fleet_done(_pieces("Balanced", Player.ORANGE))
        self._pump()

        host_screen = self.host._screen
        join_screen = self.join._screen
        square = host_screen._deployment.legal_squares()[0]
        host_screen._on_square(square)
        self._pump()

        self.assertIsNotNone(join_screen._deployment.board.get(square))
        self.assertIs(join_screen._deployment.current, Player.WHITE)


if __name__ == "__main__":
    unittest.main()
