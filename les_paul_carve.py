"""
Les Paul style top carve for FreeCAD 1.x.

Given a body and its horizontal top face, this removes material from the top to
form a carved maple cap:

  * an outer rim, then a "first line" a little lower than the rim,
  * a shoulder that rises from the first line to a FLAT crown,
  * the flat crown in the lower bout (inside the innermost line),
  * a flat central corridor (the innermost "U" of the carve template) that carries the
    crown height from the lower bout, through the waist, all the way to the front,
  * an OPEN front: the horn tip and cutaway are not treated as an edge the top rolls off
    toward. The top stays at crown height right to the front edge, so the neck angle can be
    planed in by hand. The rim and shoulder are measured from the sides and tail only.

The shoulder interpolates between the first line and the nearest flat area, so the
flat areas blend smoothly into the sides.

All lengths are millimetres. Orientation: the neck is toward +X by default
(CarveParams.neck_direction); change that if your body is modelled differently.

Public API
    carve_top(top_face, body_shape, params=None) -> (Part.Shape, dict)
    carve_subelement(obj, "Face2", params=None)  -> (Part.Shape, dict)
"""

from dataclasses import dataclass
from typing import Tuple

import numpy as np
import FreeCAD as App
import Part


@dataclass
class CarveParams:
    # ---- Depths, measured down from the top face (the top of the maple blank).
    # Removed at the outer rim (mm).
    edge_removal: float = 14.0
    # Removed at the flat crown (mm).
    peak_removal: float = 2.0
    # ---- Outer rim: the first line sits rim_width mm in from the edge and is rim_dip mm
    # LOWER than the rim. The shoulder then rises from that line.
    rim_width: float = 14.0
    rim_dip: float = 0.5
    # ---- Lower-bout crown: the flat top starts where the distance from the edge reaches
    # this fraction of the maximum interior distance (the innermost line).
    crown_fraction: float = 0.88
    # Shape of the rise from the first line to the flat areas. 1.0 = straight ramp,
    # 2.0 = S-curve: flat at the first line, steepest mid-shoulder, flat on top.
    profile_exponent: float = 2.0
    # Skews the S-curve. 1.0 = symmetric. Below 1 the rise is steepest early (close to the
    # edge) and eases gradually into the flat top, as in the cross-section reference.
    shoulder_bias: float = 0.7
    # ---- Waist and front
    # Turn off to get only the lower-bout dome with the rim all the way round.
    neck_features: bool = True
    # Direction from the tail toward the neck/front, in the XY plane of the top face.
    neck_direction: Tuple[float, float] = (1.0, 0.0)
    # Half width of the flat central corridor (the innermost "U") that runs from the
    # lower-bout crown through the waist to the front (mm).
    corridor_half_width: float = 28.0
    # Fraction of the body length, measured back from the front, where the outline is an
    # OPEN edge (horn tip and cutaway): the top does not roll off toward it.
    open_front_fraction: float = 0.20
    # ---- Numerics
    # Gaussian smoothing (mm). Rounds creases along the centreline.
    smoothing: float = 8.0
    # Sampling spacing of the height field grid (mm). Smaller is slower but finer.
    grid_step: float = 4.0
    # Spacing used to sample the outline for distance calculations (mm).
    perimeter_step: float = 0.5


def _outer_wire(face):
    """The largest wire of the face is its outer boundary; the others are holes."""
    return max(face.Wires, key=lambda w: Part.Face(w).Area)


def _gauss_blur(a, sigma_cells):
    """Separable Gaussian blur with edge padding. sigma is in grid cells."""
    if sigma_cells <= 0:
        return a
    r = int(np.ceil(3 * sigma_cells))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma_cells) ** 2)
    k /= k.sum()

    def conv_axis(arr, axis):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r, r)
        padded = np.pad(arr, pad, mode="edge")
        return np.apply_along_axis(lambda v: np.convolve(v, k, mode="valid"), axis, padded)

    return conv_axis(conv_axis(a, 0), 1)


def _inside_mask(X, Y, poly):
    """Even-odd point-in-polygon test, vectorised over the grid."""
    inside = np.zeros(X.shape, dtype=bool)
    x1, y1 = poly[:, 0], poly[:, 1]
    x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
    with np.errstate(divide="ignore", invalid="ignore"):
        for i in range(len(poly)):
            crosses = (y1[i] > Y) != (y2[i] > Y)
            if not crosses.any():
                continue
            x_at = x1[i] + (Y - y1[i]) * (x2[i] - x1[i]) / (y2[i] - y1[i])
            inside ^= crosses & (X < x_at)
    return inside


def _min_distance(P, targets, chunk=500):
    """Distance from each point in P (N,2) to the nearest of targets (M,2)."""
    d = np.empty(len(P))
    for s in range(0, len(P), chunk):
        diff = P[s:s + chunk, None, :] - targets[None, :, :]
        d[s:s + chunk] = np.sqrt((diff ** 2).sum(-1)).min(axis=1)
    return d


def _min_distance_arg(P, targets, chunk=1000):
    """Like _min_distance, but also returns the index of the nearest target."""
    d = np.empty(len(P))
    idx = np.empty(len(P), dtype=int)
    for s in range(0, len(P), chunk):
        diff = P[s:s + chunk, None, :] - targets[None, :, :]
        dist = np.sqrt((diff ** 2).sum(-1))
        idx[s:s + chunk] = dist.argmin(axis=1)
        d[s:s + chunk] = dist[np.arange(len(dist)), idx[s:s + chunk]]
    return d, idx


def _s_curve(t, k):
    """S-shaped 0..1 ramp, flat at both ends when k > 1 (k = 1 is a straight line)."""
    t = np.asarray(t, dtype=float)
    a, b = t ** k, (1.0 - t) ** k
    with np.errstate(invalid="ignore", divide="ignore"):
        out = a / (a + b)
    return np.where(np.isnan(out), 1.0, out)


def _check_horizontal(face):
    normal = face.Surface.Axis if isinstance(face.Surface, Part.Plane) else None
    if normal is None or abs(normal.z) < 0.999:
        raise ValueError(
            "The selected face must be a horizontal (flat, +/-Z) face, "
            "such as the top of the body."
        )


def carve_subelement(obj, subname, params=None):
    """
    Carve obj using a face given by its selection sub-name (e.g. "Face2").

    The face is taken from obj.Shape itself, so it always shares the body's
    coordinate frame. Returns (carved_shape, info).
    """
    shape = obj.Shape
    face = shape.getElement(subname)
    if face.ShapeType != "Face":
        raise ValueError("Selected element %s is not a face." % subname)
    return carve_top(face, shape, params)


def height_field(top_face, params=None):
    """
    Compute the carve on a grid. Returns a dict with the grid (xs, ys), the removal field
    (mm below the top face), and diagnostics. carve_top builds the solid from this.
    """
    params = params or CarveParams()
    _check_horizontal(top_face)

    outer = _outer_wire(top_face)
    poly = np.array([[p.x, p.y] for p in outer.discretize(Distance=params.perimeter_step)])
    if np.allclose(poly[0], poly[-1]):
        poly = poly[:-1]

    bb = outer.BoundBox
    step = params.grid_step
    margin = max(2 * step, 3 * params.smoothing + step)  # keep the blur's edge padding off the part
    xs = np.arange(bb.XMin - margin, bb.XMax + margin + step, step)
    ys = np.arange(bb.YMin - margin, bb.YMax + margin + step, step)
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    P = np.column_stack([X.ravel(), Y.ravel()])
    inside = _inside_mask(X, Y, poly)

    # Axes: S runs from the tail toward the front, Lt across the body.
    ax = np.array(params.neck_direction, dtype=float)
    ax /= np.linalg.norm(ax)
    lat = np.array([-ax[1], ax[0]])
    S = X * ax[0] + Y * ax[1]
    Lt = X * lat[0] + Y * lat[1]
    ps, pl = poly @ ax, poly @ lat
    s_min, s_max = float(ps.min()), float(ps.max())
    l0 = 0.5 * (float(pl.min()) + float(pl.max()))      # body centreline

    # ---- Distance from the edge, measured only from the CLOSED part of the outline.
    # The open front (horn tip and cutaway) is left out so the top does not drop toward it.
    s_open = s_max - params.open_front_fraction * (s_max - s_min)
    kept = (ps <= s_open) if params.neck_features else np.ones(len(poly), dtype=bool)
    d_all, nearest = _min_distance_arg(P, poly)
    d_kept = _min_distance(P, poly[kept], chunk=1000)
    nearest_is_open = ~kept[nearest].reshape(X.shape)
    d_all = d_all.reshape(X.shape)
    d = d_kept.reshape(X.shape)
    # Outside the closed edge the signed distance goes negative; outside the OPEN front it
    # keeps counting up, so the field continues smoothly past the open edge.
    outside_open = ~inside & nearest_is_open
    d = _gauss_blur(np.where(inside | outside_open, d, -d), params.smoothing / step)
    d = np.maximum(d, 0.0)   # evaluated on every node (also outside the part) so the fit has no cliff

    rim_w = max(params.rim_width, 1e-6)
    line_removal = params.edge_removal + params.rim_dip
    # The crown size comes from the closed part of the body only, never from the open front.
    closed_zone = inside & (S <= s_open) if params.neck_features else inside
    dmax = float(d[closed_zone].max())
    crown_d = max(params.crown_fraction * dmax, rim_w + 1e-3)

    # ---- Flat areas ("plateaus")
    crown = closed_zone & (d >= crown_d)                 # lower-bout crown, inside the innermost line
    plateau = crown.copy()
    s_crown = float(S[crown].mean()) if crown.any() else s_min
    if params.neck_features and crown.any():
        # Flat corridor from the lower-bout crown all the way to the front.
        corridor = (inside & (d >= rim_w) & (np.abs(Lt - l0) <= params.corridor_half_width)
                    & (S >= s_crown))
        plateau |= corridor

    # ---- Shoulder: interpolate between the first line (t = 0) and the nearest flat area (t = 1)
    # The distance to the flat areas is computed analytically (continuous), not from grid cells,
    # so the shoulder has no stair-steps.
    #   * lower-bout crown: its edge is an offset of the outline, so the distance is crown_d - d
    #   * central strip:    distance to the rectangle |Lt - l0| <= half width, S >= s_crown
    dp = np.maximum(crown_d - d, 0.0)
    if params.neck_features and crown.any():
        dx = np.maximum(s_crown - S, 0.0)
        dy = np.maximum(np.abs(Lt - l0) - params.corridor_half_width, 0.0)
        dp = np.minimum(dp, np.hypot(dx, dy))
    num = np.clip(d - rim_w, 0.0, None)
    den = num + dp
    with np.errstate(invalid="ignore", divide="ignore"):
        t = np.where(den > 1e-9, num / den, 1.0)
    t = np.clip(_gauss_blur(t, 0.25 * params.smoothing / step), 0.0, 1.0)
    t = np.where(dp <= 0.0, 1.0, t)

    rim = params.edge_removal + params.rim_dip * np.clip(d / rim_w, 0.0, 1.0)
    shoulder = line_removal - (line_removal - params.peak_removal) * _s_curve(t ** params.shoulder_bias, params.profile_exponent)
    removal = np.where(d < rim_w, rim, shoulder)

    return {"xs": xs, "ys": ys, "X": X, "Y": Y, "inside": inside, "removal": removal,
            "d": d, "dmax": dmax, "crown": crown, "plateau": plateau, "s_open": s_open}


def carve_top(top_face, body_shape, params=None):
    """
    Carve the top of body_shape.

    top_face    : a planar, horizontal Part.Face on the body's top (the upper-most face).
    body_shape  : Part.Shape of the body that owns top_face.
    params      : CarveParams (defaults used if None).

    Returns (carved_shape, info). info holds diagnostics such as crown position.
    """
    params = params or CarveParams()
    field = height_field(top_face, params)
    xs, ys, X, Y = field["xs"], field["ys"], field["X"], field["Y"]
    inside, removal, crown = field["inside"], field["removal"], field["crown"]
    top_z = _outer_wire(top_face).BoundBox.ZMax

    # Build the height field as a B-spline surface through the grid.
    pts = [[App.Vector(float(xs[i]), float(ys[j]), float(top_z - removal[i, j]))
            for j in range(len(ys))] for i in range(len(xs))]
    surf = Part.BSplineSurface()
    surf.interpolate(pts)
    sheet = Part.Face(surf)

    # Extrude the sheet straight down to make a solid "keep" region under the carve.
    z_bottom = body_shape.BoundBox.ZMin - 5.0
    depth = top_z - z_bottom + params.edge_removal + 5.0
    keep = sheet.extrude(App.Vector(0, 0, -depth))
    if not keep.isValid():
        raise RuntimeError("Carve tool solid is invalid; try a larger grid_step.")

    carved = body_shape.common(keep)
    if carved.isNull() or not carved.isValid():
        raise RuntimeError("Boolean carve failed; the result is not a valid shape.")

    # Crown position = centre of the lower-bout flat top.
    sel = crown if crown.any() else inside
    info = {
        "top_z": top_z,
        "max_interior_distance": field["dmax"],
        "removed_volume": body_shape.Volume - carved.Volume,
        "solids": len(carved.Solids),
        "crown_xy": (float(X[sel].mean()), float(Y[sel].mean())),
        "open_front_from": field["s_open"],
    }
    return carved, info
