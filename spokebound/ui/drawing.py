"""Drawing pieces as eight-spoke stars on a Tk canvas.

Spoke 0 points up the screen and indices run clockwise, matching
:data:`spokebound.model.pieces.DIRECTION_NAMES`.
"""

import colorsys
import math
import tkinter as tk
from collections.abc import Callable

from spokebound.config import UNLIMITED
from spokebound.model.pieces import SPOKE_COUNT, Piece
from spokebound.ui import theme

# Spoke length as a fraction of the star's radius, per range level. Level 0
# keeps a short stub so every piece still reads as a star.
LEVEL_LENGTHS = (0.2, 0.55, 0.8, 1.0)
DEGREES_PER_SPOKE = 360 / SPOKE_COUNT

# A non-Captain spoke's marker is a single tapered "exhaust" blade, base
# to its own range ring — length alone says the level, not a count of
# shapes (see _draw_regular_star). It starts, right at the hub, as
# exactly the body's own hull colour, and only warms further along its
# own length (see _heat_gradient/EXHAUST_HEAT_STOP), in EXHAUST_BANDS
# flat steps — Tk can't paint a true gradient fill, so a blade is
# really several short, separately-coloured trapezoids stacked end to
# end (see _tapered_quad) — fine enough that the steps blend together
# at the sizes a piece is actually drawn at. Base/tip widths are
# fractions of the piece's own radius.
EXHAUST_BASE_WIDTH_FRACTION = 0.085
EXHAUST_TIP_WIDTH_FRACTION = 0.032
EXHAUST_BANDS = 9
# How far a spoke's own tip sits along the *one shared* heat fade (see
# _heat_gradient) every piece's exhaust and cockpit both run along —
# proportional to its own range level out of the longest level there
# is, so a level-1 tip is always only a little warmed and only an
# unlimited spoke's tip ever reaches theme.HEAT_HOT in full, using the
# SAME fixed fade at every level (never renormalised to 0..1 per spoke)
# so a given level's own colour is consistent wherever it appears on
# the board.
EXHAUST_HEAT_STOP = {level: level / UNLIMITED for level in range(UNLIMITED + 1)}
# The small marker capping each blade's tip, and its highlight dot —
# both fractions of the piece's own radius. No bloom/glow — just the
# same heat colour as the blade's own tip band, in a small flat circle.
EXHAUST_TIP_MARKER_FRACTION = 0.05
EXHAUST_TIP_HIGHLIGHT_FRACTION = 0.4

# The Captain's own hexagon markers (see _draw_captain_star) are a
# separate, fixed look from the exhaust above — this is their own size,
# unrelated to the fractions above and never changed alongside them.
CAPTAIN_HEX_SIZE_FRACTION = 0.20

# A non-Captain piece's hub is drawn as SPOKE_COUNT faceted wedges (see
# _draw_hull), not one flat colour — each shaded lighter or darker by
# _hull_shade depending on where it sits relative to one fixed light
# source, the same for every piece, so the hub reads as a lit, panelled
# hull rather than a flat cutout; the seams between adjacent wedges,
# catching the light slightly differently, read as the panel lines.
# HULL_LIGHT_DIRECTION points from a piece's own centre toward the
# light (up and to the left); HULL_WEDGE_INSET pulls each wedge's outer
# two corners in from the hub's own true edge by this fraction, so the
# faceting is purely a cosmetic overlay drawn after the hub's own
# silhouette and outline, never able to poke past it.
HULL_LIGHT_DIRECTION = (-0.7071, -0.7071)
HULL_LIGHT_STRENGTH = 0.30
HULL_SHADOW_STRENGTH = 0.30
HULL_WEDGE_INSET = 0.92

# The decorative sun drawn around the board's single centre goal square
# (see draw_sun) — the same tapered, banded prong construction as a
# piece's own exhaust, just reusing SPOKE_COUNT's 8 directions and run
# in reverse: hot core, cooling outward, rather than a reach to show.
SUN_PRONG_BASE_WIDTH_FRACTION = 0.16
SUN_PRONG_TIP_WIDTH_FRACTION = 0.045
SUN_CORE_FRACTION = 0.22
SUN_BANDS = 6

Point = tuple[float, float]


def spoke_point(centre: Point, radius: float, spoke: int, fraction: float,
                rotated: bool = False) -> Point:
    """Return the point ``fraction`` of the way out along ``spoke``.

    ``rotated`` turns the star 180 degrees, used for White's pieces so each
    spike points the way the piece actually moves on the board.
    """
    degrees = _spoke_degrees(spoke, rotated)
    angle = math.radians(degrees)
    length = radius * fraction
    return (centre[0] + length * math.cos(angle),
            centre[1] + length * math.sin(angle))


def _spoke_degrees(spoke: int, rotated: bool = False) -> float:
    """Return a spoke's screen-space angle (Tk's convention: 0 is right,
    positive is clockwise)."""
    return -90 + DEGREES_PER_SPOKE * spoke + (180 if rotated else 0)


def _point_at(x: float, y: float, r: float, degrees: float) -> Point:
    """Return the point ``r`` away from (x, y) at ``degrees``."""
    angle = math.radians(degrees)
    return (x + r * math.cos(angle), y + r * math.sin(angle))


def spoke_at(centre: Point, x: float, y: float) -> int:
    """Return the spoke nearest the direction from ``centre`` to (x, y)."""
    degrees = math.degrees(math.atan2(y - centre[1], x - centre[0])) + 90
    return round(degrees / DEGREES_PER_SPOKE) % SPOKE_COUNT


def level_at(centre: Point, radius: float, x: float, y: float) -> int:
    """Return the range level whose ring is nearest to (x, y).

    Lets a click set a spoke straight to the level under the pointer
    (including back down to 0), rather than only stepping it by one.
    """
    fraction = math.hypot(x - centre[0], y - centre[1]) / radius
    return min(range(len(LEVEL_LENGTHS)),
               key=lambda level: abs(LEVEL_LENGTHS[level] - fraction))


def _hexagon(tip: Point, size: float, angle: float) -> list[float]:
    """Six straight edges, one vertex pointing outward along the spoke."""
    coords: list[float] = []
    for i in range(6):
        coords.extend(_point_at(tip[0], tip[1], size, angle + 60 * i))
    return coords


# How many straight edges approximate a curve for _ellipse below — enough
# that _draw_silhouette's own outline (itself built from straight-edge
# maths, see _scaled_polygon) reads as smoothly curved rather than
# faceted at the sizes a piece is actually drawn at.
_CIRCLE_SIDES = 20


def _ellipse(centre: Point, half_length: float, half_width: float,
            angle: float) -> list[float]:
    """A many-sided oval, its long axis (``half_length``) pointing
    outward along the spoke at ``angle`` and its short axis
    (``half_width``) across it — a circle when the two are equal."""
    coords: list[float] = []
    rad = math.radians(angle)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    for i in range(_CIRCLE_SIDES):
        t = math.radians(360 * i / _CIRCLE_SIDES)
        local_x, local_y = half_length * math.cos(t), half_width * math.sin(t)
        coords.extend((centre[0] + local_x * cos_a - local_y * sin_a,
                      centre[1] + local_x * sin_a + local_y * cos_a))
    return coords


def _tapered_quad(p0: Point, half0: float, p1: Point, half1: float,
                  perp_degrees: float) -> list[float]:
    """A quad running from ``p0`` to ``p1``, ``half0``/``half1`` wide
    across the perpendicular (``perp_degrees``) at each end — one band
    of a thermal exhaust blade or sun prong (see _draw_regular_star and
    draw_sun), which stack several of these end to end to fake a
    gradient Tk can't fill directly."""
    rad = math.radians(perp_degrees)
    px, py = math.cos(rad), math.sin(rad)
    a = (p0[0] + px * half0, p0[1] + py * half0)
    b = (p0[0] - px * half0, p0[1] - py * half0)
    c = (p1[0] - px * half1, p1[1] - py * half1)
    d = (p1[0] + px * half1, p1[1] + py * half1)
    return [coord for point in (a, b, c, d) for coord in point]


def _scaled_polygon(points: list[float], factor: float) -> list[float]:
    """Return ``points`` scaled by ``factor`` around its own centre — a
    clean dilation for a *regular* polygon (a roughly circular shape:
    the hub, an ellipse marker, a hexagon), with no stroke or join
    rendering involved. See :func:`_regular_dilator`."""
    xs, ys = points[0::2], points[1::2]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    return [coord for x, y in zip(xs, ys)
           for coord in (cx + (x - cx) * factor, cy + (y - cy) * factor)]


Dilator = Callable[[float], list[float]]


def _regular_dilator(points: list[float]) -> Dilator:
    """Return a dilator (see _draw_silhouette) for a roughly-regular,
    roughly-circular polygon — scaling the whole shape by a factor
    around its own centre, by however much its own apothem (the
    distance from its centre to an edge's own midpoint, not a vertex —
    a vertex already sits further out than an edge does, so scaling by
    a vertex-based factor would stretch corners out much more than
    edges) says is needed to widen every edge by ``extra``.

    This ONLY suits a shape that's roughly as wide as it is tall: the
    single scale factor it computes widens every direction from the
    centre alike, so on an elongated shape (a long, thin exhaust blade)
    it would inflate the far (long-axis) ends by many times ``extra``
    just to widen the near (short-axis) sides by ``extra`` — see
    _blade_dilator for the shape that actually needs.
    """
    xs, ys = points[0::2], points[1::2]
    mx, my = (xs[0] + xs[1]) / 2, (ys[0] + ys[1]) / 2
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    apothem = math.hypot(mx - cx, my - cy)

    def dilate(extra: float) -> list[float]:
        return points if not extra else _scaled_polygon(points, 1 + extra / apothem)

    return dilate


def _blade_dilator(p0: Point, half0: float, p1: Point, half1: float,
                   along_degrees: float, perp_degrees: float) -> Dilator:
    """Return a dilator (see _draw_silhouette) for one tapered-quad
    band of an exhaust blade or sun prong: widens ``half0``/``half1`` by
    ``extra`` on both sides AND pushes ``p0``/``p1`` outward along the
    blade's own axis (``along_degrees``) by ``extra`` — the correct,
    even dilation of a long thin shape by a constant pixel amount,
    unlike _regular_dilator's single scale-about-centre factor (which
    is exactly how an earlier version of this ended up with huge,
    blurry, disconnected borders: a factor big enough to widen a band's
    short axis by a couple of pixels flings its own far tip outward by
    many times that instead, once that same factor is applied to a
    point already tens of pixels from the centre along the long axis).
    """
    arad = math.radians(along_degrees)
    ax, ay = math.cos(arad), math.sin(arad)

    def dilate(extra: float) -> list[float]:
        if not extra:
            return _tapered_quad(p0, half0, p1, half1, perp_degrees)
        p0e = (p0[0] - ax * extra, p0[1] - ay * extra)
        p1e = (p1[0] + ax * extra, p1[1] + ay * extra)
        return _tapered_quad(p0e, half0 + extra, p1e, half1 + extra,
                             perp_degrees)

    return dilate


def _draw_silhouette(canvas: tk.Canvas, shapes: list[tuple[Dilator, str]],
                     outline: str, border: float) -> None:
    """Draw ``shapes`` — each a (dilator, own fill colour) pair, see
    :func:`_regular_dilator`/:func:`_blade_dilator` — as one solid
    silhouette with a single outer outline, even though its pieces are
    filled in different colours (a hub plus a thermal gradient's
    several bands, say) and aren't all the same kind of shape.

    Every shape is first drawn again, dilated outward by ``border``, as
    a plain fill in the outline colour — no stroke, so there's no join
    rendering to go wrong at a shared edge. Each shape is then filled
    again at very slightly past its true size, in its own fill colour,
    with no outline of its own. Both passes draw every shape in turn,
    so a shape's enlarged copy, drawn before any fill, ends up behind
    every fill including its own — the fill colours paint over all of
    it except the sliver that sticks out past the true shapes, leaving
    only the outermost boundary of the combined shape showing as the
    outline, and no seam where two differently-coloured shapes meet in
    the interior.

    The fill pass is only barely enlarged, far less than the outline
    pass — just enough that two adjacent fill shapes overlap by a
    guaranteed pixel or so of their own, rather than only meeting at
    their true (sub-pixel) boundary. Two separately-filled shapes that
    only just touch can still leave a stray pixel of gap between them
    once Tk rounds each one to the pixel grid on its own; the slight
    extra overlap here is what actually closes that, not the dilator's
    own maths, which only governs the width of the outline itself.
    """
    for dilate, _fill in shapes:
        canvas.create_polygon(*dilate(border), fill=outline, outline="")
    for dilate, fill in shapes:
        canvas.create_polygon(*dilate(min(1.0, border / 2)), fill=fill,
                              outline="")


def _hull_shade(colour: str, point: Point, centre: Point,
                radius: float) -> str:
    """Lighten or darken ``colour`` by how closely ``point`` (relative
    to ``centre``) sits toward HULL_LIGHT_DIRECTION or away from it —
    the near-light side of a piece reads brighter, the far side darker,
    as if one fixed light were falling across the whole hull (see
    _draw_hull)."""
    lx, ly = HULL_LIGHT_DIRECTION
    dx = (point[0] - centre[0]) / radius
    dy = (point[1] - centre[1]) / radius
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return colour
    alignment = max(-1.0, min(1.0, (dx * lx + dy * ly) / length))
    if alignment >= 0:
        return theme.mix_hex(colour, "#FFFFFF", alignment * HULL_LIGHT_STRENGTH)
    return theme.mix_hex(colour, "#000000", -alignment * HULL_SHADOW_STRENGTH)


def _draw_hull(canvas: tk.Canvas, centre: Point, radius: float, fill: str,
              rotated: bool) -> None:
    """Draw the hub's faceted lighting overlay: one triangular wedge per
    spoke direction, from the centre out to two adjacent hub vertices
    (pulled in by HULL_WEDGE_INSET so they sit safely inside the hub's
    own already-drawn outline), each shaded by _hull_shade from its own
    centroid. Purely cosmetic — drawn after _draw_silhouette, with no
    outline or dilation of its own, since it never needs to affect the
    piece's real silhouette, only how the hub already inside it reads.
    """
    hub_radius = radius * LEVEL_LENGTHS[0]
    vertices = [spoke_point(centre, hub_radius, spoke, HULL_WEDGE_INSET,
                           rotated)
               for spoke in range(SPOKE_COUNT)]
    for i, vertex in enumerate(vertices):
        next_vertex = vertices[(i + 1) % SPOKE_COUNT]
        centroid = ((centre[0] + vertex[0] + next_vertex[0]) / 3,
                   (centre[1] + vertex[1] + next_vertex[1]) / 3)
        wedge_colour = _hull_shade(fill, centroid, centre, radius)
        canvas.create_polygon(centre[0], centre[1], *vertex, *next_vertex,
                              fill=wedge_colour, outline="")


def _hex_to_unit_rgb(colour: str) -> tuple[float, float, float]:
    return tuple(int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))


def _unit_rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02X}"
                         for c in rgb)


def _heat_gradient(fill: str, t: float) -> str:
    """Blend ``fill`` toward theme.HEAT_HOT (plain white) — pure
    ``fill`` (that piece's own hull colour) at ``t=0``, pure white at
    ``t=1``. Done by desaturating and brightening ``fill`` in HSV, its
    own hue held fixed throughout, rather than by a plain RGB blend
    toward a literal white pixel: white has no hue of its own to mix
    in, so there's never some other, unrelated colour to pass through
    partway (the risk a blend toward any *other* fixed colour runs —
    see the note on theme.HEAT_HOT). ``t`` is usually
    :func:`_physical_heat` of some point along a blade, never
    re-normalised per spoke — so a given ``t`` always lands on the same
    point of the same fade everywhere it's used."""
    hue, saturation, value = colorsys.rgb_to_hsv(*_hex_to_unit_rgb(fill))
    saturation *= 1 - t
    value += (1 - value) * t
    return _unit_rgb_to_hex(colorsys.hsv_to_rgb(hue, saturation, value))


def _physical_heat(frac: float) -> float:
    """Return how far along the shared heat ramp (_heat_gradient) a
    point sits, purely from its own physical distance out from the hub
    (as a fraction of the piece's radius) — piecewise-linear between
    LEVEL_LENGTHS's own knots, (LEVEL_LENGTHS[level], EXHAUST_HEAT_STOP
    [level]) for each level, the same for every spoke regardless of its
    own level. A level-1 spoke's blade only ever covers the first knot
    segment, unchanged; a level-2 spoke's blade covers that same first
    segment — pixel for pixel the same colours a level-1 spoke already
    shows there — and then keeps warming, from exactly where that left
    off, over the segment beyond it; unlimited keeps going again from
    there. So a longer spoke's gradient only ever continues a shorter
    one's, never re-paces or restarts it, and there's always at least a
    sliver of the piece's own hull colour showing at every root.
    Clamped to never read below LEVEL_LENGTHS[0] — a blade's own
    geometry reaches in past the hub's edge, to the piece's centre, to
    guarantee it fully covers the hub there (see _draw_regular_star),
    but its *colour* should still read as exactly the hub's own hull
    colour throughout that inset stretch, not extrapolate past it."""
    frac = max(LEVEL_LENGTHS[0], frac)
    for i in range(len(LEVEL_LENGTHS) - 1):
        lo_frac, hi_frac = LEVEL_LENGTHS[i], LEVEL_LENGTHS[i + 1]
        if frac <= hi_frac or i == len(LEVEL_LENGTHS) - 2:
            lo_heat, hi_heat = EXHAUST_HEAT_STOP[i], EXHAUST_HEAT_STOP[i + 1]
            span = hi_frac - lo_frac
            local_t = 0.0 if span <= 0 else (frac - lo_frac) / span
            return lo_heat + (hi_heat - lo_heat) * local_t
    return 1.0


def _draw_field(canvas: tk.Canvas, centre: Point, radius: float) -> None:
    """Draw the piece's fixed HUD overlay: three solid range rings (one
    square, two squares, the whole board) and a dashed ray out to each of
    the eight board directions — the same colour and the same halo-backed
    treatment on every piece, on either side, so these read as the
    board's own reference frame rather than anything team-coloured (see
    theme.PIECE_RING/PIECE_DIRECTION_GUIDE). Fixed to the board
    orientation even when the piece itself is rotated.
    """
    x, y = centre
    for fraction in LEVEL_LENGTHS[1:]:
        r = radius * fraction
        canvas.create_oval(x - r, y - r, x + r, y + r,
                           outline=theme.HIGHLIGHT_SHADOW, width=3)
        canvas.create_oval(x - r, y - r, x + r, y + r,
                           outline=theme.PIECE_RING, width=1)

    for spoke in range(SPOKE_COUNT):
        end = spoke_point(centre, radius, spoke, 0.94)
        # No backing halo here, unlike the rings above: a halo behind a
        # dashed line is itself either solid (and fills every gap with
        # shadow) or dashed on its own schedule (and almost never lands
        # exactly behind the ray's own dashes), so either way some
        # shadow ends up showing in a gap that should be transparent.
        # Plain thin dashes read fine on their own.
        canvas.create_line(*centre, *end, fill=theme.PIECE_DIRECTION_GUIDE,
                           width=1, dash=(2, 4))
        dot = max(0.6, radius * 0.025)
        canvas.create_oval(end[0] - dot, end[1] - dot, end[0] + dot,
                           end[1] + dot, fill=theme.PIECE_DIRECTION_GUIDE,
                           outline="")


def draw_star(canvas: tk.Canvas, centre: Point, radius: float, piece: Piece,
              rotated: bool = False, lost: bool = False,
              sun_direction: Point | None = None) -> None:
    """Draw ``piece`` as a star whose spikes show its range.

    The Captain (always range level 1 on every spoke — see
    spokebound.model.pieces.make_captain) keeps its own long-standing
    look: a hexagon at each tip in the side's own accent colour,
    outlined like the body, plus the Captain's own rings — see
    :func:`_draw_captain_star`. Every other piece is drawn as a single
    silhouette in the side's own colour, each spoke's own tapered
    thermal exhaust blade reaching out to its range ring — see
    :func:`_draw_regular_star`. ``lost`` greys the piece out and crosses
    it off either way. ``sun_direction`` is the direction, in this same
    pixel space, from the board's own centre square toward this piece
    (see board_view.BoardView.redraw) — it steers which side of a
    non-Captain piece's cockpit catches the light; left ``None`` (any
    context with no real board position, e.g. a fleet thumbnail) it
    falls back to a fixed "lit from above" default.
    """
    fill, outline = (theme.LOST_PIECE_COLOURS if lost
                     else theme.PIECE_COLOURS[piece.owner])
    _draw_field(canvas, centre, radius)
    if piece.is_captain:
        _draw_captain_star(canvas, centre, radius, piece, rotated, fill,
                           outline)
    else:
        _draw_regular_star(canvas, centre, radius, piece, rotated, fill,
                           outline, sun_direction)

    if piece.bounty:
        badge = (centre[0] + radius * 0.9, centre[1] - radius * 0.9)
        draw_badge(canvas, badge, radius * 0.18, str(piece.bounty))

    if lost:
        x, y = centre
        r = radius * 0.8
        canvas.create_line(x - r, y - r, x + r, y + r, fill=outline, width=2)
        canvas.create_line(x - r, y + r, x + r, y - r, fill=outline, width=2)


def _draw_regular_star(canvas: tk.Canvas, centre: Point, radius: float,
                       piece: Piece, rotated: bool, fill: str,
                       outline: str,
                       sun_direction: Point | None = None) -> None:
    """Draw a non-Captain piece as one silhouette: the hub plus every
    active spoke's own tapered thermal exhaust blade, base to its own
    range ring, with a single ``outline`` around the combined shape
    (see :func:`_draw_silhouette`). A spoke's level is read from how far
    its blade reaches — not from any marker count — and each blade
    starts, right at the hub, as the body's own ``fill`` and warms along
    its own length up to however hot that level's tip runs (see
    _heat_gradient/EXHAUST_HEAT_STOP), capped with a small marker in
    that same tip colour — no glow, just the flat colour. The hub itself
    gets a faceted, lit-hull overlay on top (see _draw_hull), separate
    from the exhaust's own colouring.
    """
    # The floor matters more than the ratio here: a board piece can be
    # drawn at well under half the spoke editor's own radius, and a
    # purely proportional border gets lost against the field overlay
    # at that size.
    border = max(1.5, radius * 0.045)
    # A small hub the same size on every piece (the level-0 stub's own
    # reach), not a body reaching out to each spoke's own range — that
    # would draw a filled wedge between any two long spokes, fusing them
    # into one blob instead of leaving each spoke's own blade to read as
    # its own separate arm.
    hub_points = [c for spoke in range(SPOKE_COUNT)
                 for c in spoke_point(centre, radius, spoke, LEVEL_LENGTHS[0],
                                      rotated)]
    shapes: list[tuple[Dilator, str]] = [(_regular_dilator(hub_points), fill)]
    # _draw_silhouette's own outline dilates every shape outward by
    # `border`, so a blade whose true tip sits exactly on its range ring
    # would have its *outline* overshoot the ring by that much. Pulling
    # the tip in by the same amount keeps the drawn outline right at
    # the ring, never past it.
    edge_inset = border / radius
    tip_markers: list[tuple[Point, str]] = []
    for spoke, level in enumerate(piece.spokes):
        if level == 0:
            continue
        angle = _spoke_degrees(spoke, rotated)
        perp = angle + 90
        base_frac, tip_frac = LEVEL_LENGTHS[0], LEVEL_LENGTHS[level] - edge_inset
        for band in range(EXHAUST_BANDS):
            t0, t1 = band / EXHAUST_BANDS, (band + 1) / EXHAUST_BANDS
            frac0 = base_frac + (tip_frac - base_frac) * t0
            frac1 = base_frac + (tip_frac - base_frac) * t1
            # The very first band's own near end reaches all the way
            # back to the piece's own centre, well past the hub's edge
            # (base_frac) — pure overlap, same width and (via
            # _physical_heat's own clamp) same hull colour as the hub
            # itself right there, so it fully covers the hub in this
            # direction rather than relying on its own wide base lining
            # up exactly with the hub's own much narrower vertex there,
            # which is what used to leave a sliver of the hub's own
            # outline peeking through once a direction had a blade.
            p0 = spoke_point(centre, radius, spoke, 0.0 if band == 0 else
                             frac0, rotated)
            p1 = spoke_point(centre, radius, spoke, frac1, rotated)
            half0 = radius * (EXHAUST_BASE_WIDTH_FRACTION -
                             (EXHAUST_BASE_WIDTH_FRACTION -
                              EXHAUST_TIP_WIDTH_FRACTION) * t0)
            half1 = radius * (EXHAUST_BASE_WIDTH_FRACTION -
                             (EXHAUST_BASE_WIDTH_FRACTION -
                              EXHAUST_TIP_WIDTH_FRACTION) * t1)
            # Coloured by this band's own PHYSICAL position (see
            # _physical_heat), not by how far along this one blade it
            # happens to sit — so a longer spoke's gradient continues a
            # shorter one's rather than restarting or re-pacing it.
            band_colour = _heat_gradient(fill, _physical_heat((frac0 + frac1) / 2))
            shapes.append((_blade_dilator(p0, half0, p1, half1, angle, perp),
                          band_colour))
        tip_markers.append((spoke_point(centre, radius, spoke, tip_frac,
                                        rotated),
                            _heat_gradient(fill, _physical_heat(tip_frac))))

    _draw_silhouette(canvas, shapes, outline, border)
    _draw_hull(canvas, centre, radius, fill, rotated)
    for tip, tip_colour in tip_markers:
        r = radius * EXHAUST_TIP_MARKER_FRACTION
        canvas.create_oval(tip[0] - r, tip[1] - r, tip[0] + r, tip[1] + r,
                           fill=tip_colour, outline=theme.HIGHLIGHT_SHADOW,
                           width=1)
        hr = r * EXHAUST_TIP_HIGHLIGHT_FRACTION
        hx, hy = tip[0] - r * 0.3, tip[1] - r * 0.3
        canvas.create_oval(hx - hr, hy - hr, hx + hr, hy + hr,
                           fill="#FFFFFF", outline="")
    _draw_cockpit(canvas, centre, radius, sun_direction)


def _draw_cockpit(canvas: tk.Canvas, centre: Point, radius: float,
                  sun_direction: Point | None = None) -> None:
    """Draw a small glassy cockpit at a piece's own centre, in the same
    fixed, neutral grey (theme.COCKPIT_FILL/COCKPIT_HIGHLIGHT) regardless
    of which side owns the piece or how far it can reach — a plain
    cockpit window, not a status indicator. Oval, wider than tall, with
    a lighter highlight oval standing in for a glassy reflection, since
    plain Tk shapes can't blend a real one. The highlight sits on
    whichever side faces ``sun_direction`` — the direction from the
    board's own centre square to this piece — so every piece's shading
    agrees on where the board's one light source is; with no real
    position to go on (``None``), it falls back to a fixed "lit from
    above".
    """
    cockpit_fill = theme.COCKPIT_FILL
    highlight = theme.COCKPIT_HIGHLIGHT
    x, y = centre
    w, h = radius * 0.17, radius * 0.11
    canvas.create_oval(x - w, y - h, x + w, y + h, fill=cockpit_fill,
                       outline=theme.HIGHLIGHT_SHADOW, width=1)
    hw, hh = w * 0.42, h * 0.38
    if sun_direction is not None and any(sun_direction):
        mag = math.hypot(*sun_direction)
        ux, uy = sun_direction[0] / mag, sun_direction[1] / mag
    else:
        ux, uy = 0.0, -1.0
    # The highlight sits toward the sun, i.e. the opposite of the
    # direction from the sun to this piece — the near side catches
    # the light, the far side falls in its own shadow.
    hx, hy = x - ux * w * 0.5, y - uy * h * 0.55
    canvas.create_oval(hx - hw, hy - hh, hx + hw, hy + hh, fill=highlight,
                       outline="")


def _draw_captain_star(canvas: tk.Canvas, centre: Point, radius: float,
                       piece: Piece, rotated: bool, fill: str,
                       outline: str) -> None:
    """Draw the Captain exactly as every other piece used to be drawn:
    each spoke's own hexagon marker outlined individually (in the side's
    own PIECE_MARKER_COLOURS, not the body colour), tucked half behind
    the body so only its outward half shows, plus a small hexagon core
    and the Captain's own rings. Every Captain spoke is range level 1
    (see spokebound.model.pieces.make_captain), so this never needs to
    handle any other level.
    """
    marker_colour = theme.PIECE_MARKER_COLOURS[piece.owner][1]
    pullback = CAPTAIN_HEX_SIZE_FRACTION
    for spoke, level in enumerate(piece.spokes):
        if level != 1:
            continue
        angle = _spoke_degrees(spoke, rotated)
        anchor = spoke_point(centre, radius, spoke,
                             LEVEL_LENGTHS[1] - pullback, rotated)
        canvas.create_polygon(*_hexagon(anchor,
                                        radius * CAPTAIN_HEX_SIZE_FRACTION,
                                        angle),
                              fill=marker_colour, outline=outline, width=1,
                              joinstyle=tk.MITER)

    body = [c for spoke, level in enumerate(piece.spokes)
            for c in spoke_point(centre, radius, spoke,
                                 LEVEL_LENGTHS[level] - (
                                     pullback if level == 1 else 0),
                                 rotated)]
    canvas.create_polygon(*body, fill=fill, outline=outline, width=2,
                          joinstyle=tk.MITER)

    canvas.create_polygon(*_hexagon(centre, radius * 0.08, 0),
                          fill=marker_colour, outline=outline, width=1,
                          joinstyle=tk.MITER)
    _draw_captain_rings(canvas, centre, radius, outline)


def _draw_captain_rings(canvas: tk.Canvas, centre: Point, radius: float,
                        colour: str) -> None:
    """Mark the Captain with concentric rings inside its body."""
    body_radius = radius * LEVEL_LENGTHS[1]
    x, y = centre
    for fraction in (0.62, 0.32):
        r = body_radius * fraction
        canvas.create_oval(x - r, y - r, x + r, y + r,
                           outline=theme.HIGHLIGHT, width=4)
        canvas.create_oval(x - r, y - r, x + r, y + r, outline=colour,
                           width=2)



def draw_badge(canvas: tk.Canvas, centre: Point, size: float,
               text: str) -> None:
    """Draw a small dark disc with ``text`` in it, for bounty values."""
    x, y = centre
    canvas.create_oval(x - size, y - size, x + size, y + size,
                       fill=theme.BADGE_FILL, outline="")
    font = (theme.FONT_FAMILY, max(7, int(size)), "bold")
    canvas.create_text(x, y, text=text, fill=theme.BADGE_TEXT, font=font)


def draw_sun(canvas: tk.Canvas, centre: Point, radius: float) -> None:
    """Draw the decorative sun around the board's single centre goal
    square: the same tapered, banded exhaust construction a piece's own
    spoke uses (see _draw_regular_star), run in reverse — white-hot at
    the core, cooling outward along each of SPOKE_COUNT prongs, since
    it's a fixed star rather than a reach to show. Independent of
    either side's own colours and of board rotation.
    """
    border = max(1.5, radius * 0.05)
    core_radius = radius * SUN_CORE_FRACTION
    shapes: list[tuple[Dilator, str]] = [
        (_regular_dilator(_ellipse(centre, core_radius, core_radius, 0)),
         theme.SUN_CORE)
    ]
    for spoke in range(SPOKE_COUNT):
        angle = _spoke_degrees(spoke)
        perp = angle + 90
        for band in range(SUN_BANDS):
            t0, t1 = band / SUN_BANDS, (band + 1) / SUN_BANDS
            frac0 = SUN_CORE_FRACTION + (1.0 - SUN_CORE_FRACTION) * t0
            frac1 = SUN_CORE_FRACTION + (1.0 - SUN_CORE_FRACTION) * t1
            half0 = radius * (SUN_PRONG_BASE_WIDTH_FRACTION -
                             (SUN_PRONG_BASE_WIDTH_FRACTION -
                              SUN_PRONG_TIP_WIDTH_FRACTION) * t0)
            half1 = radius * (SUN_PRONG_BASE_WIDTH_FRACTION -
                             (SUN_PRONG_BASE_WIDTH_FRACTION -
                              SUN_PRONG_TIP_WIDTH_FRACTION) * t1)
            p0 = spoke_point(centre, radius, spoke, frac0)
            p1 = spoke_point(centre, radius, spoke, frac1)
            colour = theme.mix_hex(theme.SUN_CORE, theme.SUN_TIP,
                                   (t0 + t1) / 2)
            shapes.append((_blade_dilator(p0, half0, p1, half1, angle, perp),
                          colour))
    _draw_silhouette(canvas, shapes, theme.SUN_OUTLINE, border)


def draw_guides(canvas: tk.Canvas, centre: Point, radius: float,
                colour: str = theme.GUIDE) -> None:
    """Draw faint spoke lines and range rings behind an editable star —
    this chart itself, not the piece optionally drawn on top of it
    (see SpokeEditor.redraw), so it's the one thing always visible
    here even with no piece selected. ``colour`` lets a caller retint
    it (see the Piece Upgrade terminal's own green CRT look) without
    touching the piece's own colours."""
    for spoke in range(SPOKE_COUNT):
        end = spoke_point(centre, radius, spoke, 1.0)
        canvas.create_line(*centre, *end, fill=colour, dash=(1, 6))
    for fraction in LEVEL_LENGTHS[1:]:
        r = radius * fraction
        canvas.create_oval(centre[0] - r, centre[1] - r,
                           centre[0] + r, centre[1] + r, outline=colour)
