"""Peer-to-peer LAN/direct-IP play: one side hosts, the other joins.

There's no matchmaking or relay server — "inviting a friend" means
sharing your own address out of band (chat, a call) for them to type
into the Join screen. See :mod:`spokebound.net.session` for the
connection itself and :mod:`spokebound.net.protocol` for what goes
over it.
"""
