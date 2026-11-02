"""
Headless tests for les_paul_carve.py.

Run with FreeCAD's command-line runner (no GUI needed):

    /Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd -c \
        "exec(open('/PATH/TO/test_les_paul_carve.py').read())"

Optional: pass the path to your .FCStd as the environment variable
CARVE_TEST_FCSTD to also run the real-body test, e.g.

    CARVE_TEST_FCSTD="$HOME/Desktop/CAD/Andy-50th/Andy 50th.FCStd" freecadcmd -c ...

The real-body test works on a COPY in a temp directory, never on your file.
Results are printed and also written to test_report.txt next to this script.
"""

import os
import sys
import shutil
import tempfile
import traceback

import FreeCAD as App
import Part

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import les_paul_carve as lpc  # noqa: E402

REPORT = []
FAILS = []


def log(msg):
    REPORT.append(msg)
    print(msg)


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    log("[%s] %s %s" % (status, name, detail))
    if not cond:
        FAILS.append(name)


def top_z_at(shape, x, y, zlo=-200, zhi=200):
    """Highest z of the solid at (x, y), found by intersecting a vertical line."""
    line = Part.makeLine(App.Vector(x, y, zlo), App.Vector(x, y, zhi))
    section = shape.common(line)
    if section.isNull() or not section.Vertexes:
        return None
    return max(v.Point.z for v in section.Vertexes)


def top_face_of(shape):
    """The planar face with normal +Z that has the largest ZMax."""
    best = None
    for f in shape.Faces:
        if isinstance(f.Surface, Part.Plane) and abs(f.Surface.Axis.z) > 0.999 and f.Surface.Axis.z > 0:
            if best is None or f.BoundBox.ZMax > best.BoundBox.ZMax:
                best = f
    return best


# ---------------------------------------------------------------------------
# Test 1: rectangle slab with an exact analytic answer
# ---------------------------------------------------------------------------
def expected_removal(d, dmax, p):
    """Independent restatement of the intended profile (rim, dip to first line, dome)."""
    if d < p.rim_width:
        return p.edge_removal + p.rim_dip * d / p.rim_width
    line = p.edge_removal + p.rim_dip
    crown_d = p.crown_fraction * dmax
    u = min((d - p.rim_width) / (crown_d - p.rim_width), 1.0) ** p.shoulder_bias
    k = p.profile_exponent
    return line - (line - p.peak_removal) * (u ** k / (u ** k + (1 - u) ** k))


def test_first_line_is_half_mm_below_rim():
    """First line (rim_width in) is rim_dip BELOW the outer rim, with the DEFAULT smoothing."""
    L, W, T = 300.0, 200.0, 30.0
    box = Part.makeBox(L, W, T)
    params = lpc.CarveParams()
    carved, _ = lpc.carve_top(top_face_of(box), box, params)
    y = W / 2
    z_rim = top_z_at(carved, 0.3, y)                  # essentially at the outer rim
    z_line = top_z_at(carved, params.rim_width, y)    # the first line
    drop = z_rim - z_line
    check("first line is ~0.5 mm BELOW the rim (+/-0.1 mm)", abs(drop - params.rim_dip) < 0.1,
          "drop=%.3f mm (target %.2f)" % (drop, params.rim_dip))
    z_mid = top_z_at(carved, params.rim_width / 2, y)
    check("rim band slopes down monotonically to the first line",
          z_rim >= z_mid >= z_line, "rim=%.3f mid=%.3f line=%.3f" % (z_rim, z_mid, z_line))
    z_inner = top_z_at(carved, params.rim_width + 25, y)
    check("dome rises above the first line beyond it", z_inner > z_line,
          "line=%.3f 25mm further in=%.3f" % (z_line, z_inner))


def test_front_stays_at_crown_height_with_no_lip():
    """The front is an open edge: the top stays at crown height right to it, no thin lip."""
    L, W, T = 500.0, 200.0, 40.0
    box = Part.makeBox(L, W, T)
    params = lpc.CarveParams()
    carved, info = lpc.carve_top(top_face_of(box), box, params)
    crown_z = T - params.peak_removal
    y = W / 2
    z_mid = top_z_at(carved, 440.0, y)
    z_edge = top_z_at(carved, L - 1.0, y)
    check("front: crown height held to the front edge",
          abs(z_mid - crown_z) < 0.1 and abs(z_edge - crown_z) < 0.1,
          "z at 440=%.3f, 1 mm from the front=%.3f, crown=%.3f" % (z_mid, z_edge, crown_z))
    flat = [top_z_at(carved, 470.0, y + dy) for dy in (-20, -10, 0, 10, 20)]
    check("front: flat across the strip (<0.05 mm)", max(flat) - min(flat) < 0.05)
    # Corner of the front: must not drop to the rim within a few mm.
    z_corner = top_z_at(carved, L - 3.0, 12.0)
    removal_corner = T - z_corner
    check("front: no thin lip at the front corner", removal_corner < params.edge_removal - 4,
          "removal 3 mm in from the corner edge=%.2f mm (rim=%.1f)" % (removal_corner, params.edge_removal))


def test_crown_is_a_flat_plateau():
    """The top inside the innermost line is flat, not a point or ridge (default smoothing)."""
    L, W, T = 200.0, 120.0, 30.0
    box = Part.makeBox(L, W, T)
    params = lpc.CarveParams()
    carved, _ = lpc.carve_top(top_face_of(box), box, params)
    z0 = top_z_at(carved, 100.0, 60.0)
    zs = [top_z_at(carved, 100.0, y) for y in (54.0, 57.0, 63.0, 66.0)]
    flat = max(abs(z - z0) for z in zs)
    check("crown: flat across the centre (<0.05 mm variation over 12 mm)", flat < 0.05,
          "max deviation=%.4f mm, crown z=%.3f (expected %.3f)" % (flat, z0, T - params.peak_removal))
    check("crown: at the full crown height", abs(z0 - (T - params.peak_removal)) < 0.05)
    z_out = top_z_at(carved, 100.0, 15.0)
    check("crown: falls away outside the innermost line", z_out < z0 - 0.5, "z at 45 mm off centre=%.3f" % z_out)


def test_rectangle_matches_analytic():
    L, W, T = 200.0, 120.0, 30.0
    box = Part.makeBox(L, W, T)  # top face at z = T
    top = top_face_of(box)
    params = lpc.CarveParams(edge_removal=9.5, peak_removal=1.6, neck_features=False,
                             profile_exponent=2.0, smoothing=0.0, grid_step=4.0)
    carved, info = lpc.carve_top(top, box, params)

    check("rect: result valid", carved.isValid())
    check("rect: single solid", len(carved.Solids) == 1, "solids=%d" % len(carved.Solids))
    check("rect: volume reduced", carved.Volume < box.Volume,
          "removed=%.1f mm^3" % (box.Volume - carved.Volume))
    # BoundBox is loose for BSpline faces, so compare optimal (tight) boxes.
    bb0, bb1 = box.optimalBoundingBox(), carved.optimalBoundingBox()
    log("rect: bbox before %s after %s" % (bb0, bb1))
    check("rect: XY bounding box unchanged",
          abs(bb0.XMin - bb1.XMin) < 1e-3 and abs(bb0.XMax - bb1.XMax) < 1e-3 and
          abs(bb0.YMin - bb1.YMin) < 1e-3 and abs(bb0.YMax - bb1.YMax) < 1e-3)
    check("rect: bottom unchanged", abs(bb0.ZMin - bb1.ZMin) < 1e-3)

    dmax = min(L, W) / 2.0  # widest interior point of a rectangle
    worst = 0.0
    # Sample across the middle (x = 100), where the plateau edge is parallel to the outline.
    for (x, y) in [(100.0, 2.0), (100.0, 8.0), (100.0, 14.0), (100.0, 20.0), (100.0, 30.0),
                   (100.0, 40.0), (100.0, 50.0), (100.0, 60.0), (100.0, 80.0), (100.0, 110.0)]:
        d = min(x, L - x, y, W - y)
        expected = T - expected_removal(d, dmax, params)
        actual = top_z_at(carved, x, y)
        if actual is None:
            worst = float("inf")
            continue
        worst = max(worst, abs(actual - expected))
    # The flat area's edge is located on the 4 mm grid, which limits agreement to ~0.25 mm.
    check("rect: top surface matches analytic profile (<0.4 mm)", worst < 0.4,
          "worst error=%.3f mm" % worst)

    # The plateau of a rectangle is centred on the rectangle, so its centre is the middle.
    cx, cy = info["crown_xy"]
    check("rect: crown plateau is centred", abs(cx - L / 2) < 6 and abs(cy - W / 2) < 6,
          "crown=%s" % (info["crown_xy"],))

def test_smoothing_keeps_shape_close():
    L, W, T = 200.0, 120.0, 30.0
    box = Part.makeBox(L, W, T)
    top = top_face_of(box)
    carved, _ = lpc.carve_top(top, box, lpc.CarveParams(smoothing=12.0))
    check("rect+smoothing: valid single solid", carved.isValid() and len(carved.Solids) == 1)
    edge = top_z_at(carved, 2.0, 60.0)
    centre = top_z_at(carved, 100.0, 60.0)
    check("rect+smoothing: edge lower than centre", edge is not None and centre is not None and edge < centre,
          "edge=%.2f centre=%.2f" % (edge, centre))


def test_rejects_non_horizontal_face():
    box = Part.makeBox(100, 50, 20)
    side = [f for f in box.Faces if isinstance(f.Surface, Part.Plane) and abs(f.Surface.Axis.z) < 0.001][0]
    try:
        lpc.carve_top(side, box)
        check("rejects vertical face", False, "no error raised")
    except ValueError:
        check("rejects vertical face", True)


# ---------------------------------------------------------------------------
# Test 2: the real Andy 50th guitar body (works on a temporary copy)
# ---------------------------------------------------------------------------
def _real_body_checks(label):
    src = os.environ.get("CARVE_TEST_FCSTD")
    if not src or not os.path.exists(src):
        log("[SKIP] real body test: set CARVE_TEST_FCSTD to your .FCStd path to run it")
        return
    tmpdir = tempfile.mkdtemp(prefix="carve_test_")
    copy = os.path.join(tmpdir, "copy.FCStd")
    shutil.copy(src, copy)
    doc = App.openDocument(copy)
    body = next(o for o in doc.Objects if getattr(o, "Label", "") == label)
    shape = body.Shape
    top = top_face_of(shape)
    check(label + ": found horizontal top face", top is not None)
    if top is None:
        return
    params = lpc.CarveParams()
    carved, info = lpc.carve_top(top, shape, params)
    bb0, bb1 = shape.optimalBoundingBox(), carved.optimalBoundingBox()
    log(label + ": body bbox %s" % (bb0,))
    log(label + ": removed %.0f mm^3 of %.0f mm^3; crown at (%.1f, %.1f); dmax=%.1f mm" % (
        info["removed_volume"], shape.Volume, info["crown_xy"][0], info["crown_xy"][1],
        info["max_interior_distance"]))
    check(label + ": result valid", carved.isValid())
    check(label + ": single solid", len(carved.Solids) == 1, "solids=%d" % len(carved.Solids))
    check(label + ": XY bbox unchanged",
          abs(bb0.XMin - bb1.XMin) < 0.01 and abs(bb0.XMax - bb1.XMax) < 0.01 and
          abs(bb0.YMin - bb1.YMin) < 0.01 and abs(bb0.YMax - bb1.YMax) < 0.01)
    check(label + ": top never higher than original", bb1.ZMax <= bb0.ZMax + 1e-3)
    check(label + ": volume reduced", carved.Volume < shape.Volume)

    # Measure only where there is material (routed pockets are open holes in the top face).
    # Lower bout near the perimeter: should drop by about edge_removal.
    z_edge = top_z_at(carved, 130.0, -160.5)  # ~1.5 mm inside the outline at the lower bout
    if z_edge is not None:
        drop_edge = bb0.ZMax - z_edge
        check(label + ": perimeter drop close to edge_removal (+/-1 mm)",
              abs(drop_edge - params.edge_removal) < 1.0, "drop=%.2f mm" % drop_edge)
    else:
        check(label + ": perimeter sample hits material", False)
    # Crown region: search the lower bout for material (routed pockets are open holes in the top).
    # The least-dropped material point should be well above the edge and close to peak_removal.
    drops = []
    for x in range(100, 201, 4):
        for y in range(-160, 161, 4):
            if not top.isInside(App.Vector(float(x), float(y), bb0.ZMax), 1e-6, True):
                continue
            z = top_z_at(carved, float(x), float(y))
            if z is not None:
                drops.append(bb0.ZMax - z)
    if drops:
        check(label + ": least drop on material in lower bout close to peak_removal (<4 mm above it)",
              min(drops) - params.peak_removal < 4.0, "min drop=%.2f mm" % min(drops))
        check(label + ": crown region is well above the edge", min(drops) < params.edge_removal - 3,
              "crown drop=%.2f, edge drop=%.2f" % (min(drops), params.edge_removal))
    else:
        check(label + ": lower bout has material", False)

    out_dir = os.environ.get("CARVE_TEST_OUT", tmpdir)
    os.makedirs(out_dir, exist_ok=True)
    out_step = os.path.join(out_dir, "carved_%s.step" % label.replace(" ", "").replace("-", ""))
    carved.exportStep(out_step)
    log(label + ": wrote %s" % out_step)
    shutil.rmtree(tmpdir, ignore_errors=True) if not os.environ.get("CARVE_TEST_OUT") else None
    App.closeDocument(doc.Name)


def test_real_body():
    """Body - Carve is the body that gets carved. Body - Main (the back, with cavities)
    is also carved here as a stress test for a top face with holes."""
    for label in ("Body - Carve", "Body - Main"):
        _real_body_checks(label)


def test_macro_path_on_body_carve():
    """Exercises the exact path the macro uses: sub-element name -> carve_subelement."""
    src = os.environ.get("CARVE_TEST_FCSTD")
    if not src or not os.path.exists(src):
        log("[SKIP] macro path test: set CARVE_TEST_FCSTD")
        return
    tmpdir = tempfile.mkdtemp(prefix="carve_macro_")
    copy = os.path.join(tmpdir, "copy.FCStd")
    shutil.copy(src, copy)
    doc = App.openDocument(copy)
    obj = next((o for o in doc.Objects if getattr(o, "Label", "") == "Body - Carve"), None)
    check("macro path: found 'Body - Carve'", obj is not None)
    if obj is not None:
        top = top_face_of(obj.Shape)
        idx = [i for i, f in enumerate(obj.Shape.Faces) if f.isSame(top)][0] + 1
        subname = "Face%d" % idx
        carved, info = lpc.carve_subelement(obj, subname, lpc.CarveParams())
        check("macro path: %s carved, valid single solid" % subname,
              carved.isValid() and len(carved.Solids) == 1, "removed=%.0f mm^3" % info["removed_volume"])
        import math
        params = lpc.CarveParams()
        crown_z = info["top_z"] - params.peak_removal
        # Waist (narrowest part, x ~ 280): flat across the centre at crown height, no ridge.
        zs = [top_z_at(carved, 280.0, y) for y in (-20, -10, 0, 10, 20)]
        check("real waist: flat across the centre (<0.05 mm)", max(zs) - min(zs) < 0.05,
              "variation=%.4f mm" % (max(zs) - min(zs)))
        check("real waist: at crown height", abs(zs[2] - crown_z) < 0.1,
              "z=%.3f crown=%.3f" % (zs[2], crown_z))
        # Front: the strip stays at crown height out toward the front.
        zf = [top_z_at(carved, 385.0, y) for y in (4, 10, 16)]
        check("real front: strip at crown height toward the front (+/-0.1 mm)",
              all(z is not None and abs(z - crown_z) < 0.1 for z in zf), "z=%s crown=%.3f" % (zf, crown_z))
        # No thin lip: 2 mm inside the outline around the horn tip and cutaway, the carve must
        # not have dropped to the rim.
        outer = max(top.Wires, key=lambda w: Part.Face(w).Area)
        pts = [p for p in outer.discretize(Distance=6.0) if p.x > 395.0]
        worst, n_checked = 0.0, 0
        for p in pts:
            for (nx, ny) in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                q = App.Vector(p.x + 2.0 * nx, p.y + 2.0 * ny, 0)
                if top.isInside(q, 1e-6, True):
                    z = top_z_at(carved, q.x, q.y)
                    if z is not None:
                        worst = max(worst, info["top_z"] - z)
                        n_checked += 1
                    break
        check("real front: no thin lip around the horn tip and cutaway",
              n_checked > 3 and worst < params.edge_removal - 3,
              "deepest removal 2 mm in from the front edge=%.2f mm over %d points (rim=%.1f)" % (
                  worst, n_checked, params.edge_removal))
        # Smooth edge: walk the outline along the front (x > 340) 2 mm apart, probe 1.5 mm inside
        # along the true inward normal, and require the height to change smoothly (no saw-tooth).
        P = [(p.x, p.y) for p in outer.discretize(Distance=2.0)]
        idx = [i for i, (x, y) in enumerate(P) if x > 340.0]
        runs, cur = [], [idx[0]]
        for a_, b_ in zip(idx[:-1], idx[1:]):
            if b_ == a_ + 1:
                cur.append(b_)
            else:
                runs.append(cur)
                cur = [b_]
        runs.append(cur)
        run = max(runs, key=len)
        zs_edge = []
        for i in run:
            j0, j1 = max(i - 1, 0), min(i + 1, len(P) - 1)
            tx, ty = P[j1][0] - P[j0][0], P[j1][1] - P[j0][1]
            norm = (tx * tx + ty * ty) ** 0.5 or 1.0
            nx, ny = -ty / norm, tx / norm
            if not top.isInside(App.Vector(P[i][0] + nx, P[i][1] + ny, 0), 1e-6, True):
                nx, ny = -nx, -ny
            z = top_z_at(carved, P[i][0] + 1.5 * nx, P[i][1] + 1.5 * ny)
            zs_edge.append(float("nan") if z is None else z)
        import numpy as _np
        zs_edge = _np.array(zs_edge)
        d2 = _np.abs(zs_edge[2:] - 2 * zs_edge[1:-1] + zs_edge[:-2])
        check("real front: edge height is smooth, no saw-tooth (max 2nd difference < 0.25 mm per 2 mm)",
              _np.nanmax(d2) < 0.25, "max=%.3f mm, rms=%.3f mm over %d points" % (
                  _np.nanmax(d2), _np.sqrt(_np.nanmean(d2 ** 2)), len(zs_edge)))
        try:
            lpc.carve_subelement(obj, "Edge1", lpc.CarveParams())
            check("macro path: non-face sub-element rejected", False, "no error raised")
        except ValueError:
            check("macro path: non-face sub-element rejected", True)
    App.closeDocument(doc.Name)
    shutil.rmtree(tmpdir, ignore_errors=True)


def run_all():
    tests = [test_rectangle_matches_analytic, test_crown_is_a_flat_plateau, test_front_stays_at_crown_height_with_no_lip, test_first_line_is_half_mm_below_rim, test_smoothing_keeps_shape_close,
             test_rejects_non_horizontal_face, test_real_body, test_macro_path_on_body_carve]
    for t in tests:
        log("--- %s" % t.__name__)
        try:
            t()
        except Exception:
            FAILS.append(t.__name__)
            log("[ERROR] %s\n%s" % (t.__name__, traceback.format_exc()))
    log("=== %s" % ("ALL PASSED" if not FAILS else "FAILURES: %s" % FAILS))
    with open(os.path.join(HERE, "test_report.txt"), "w") as fh:
        fh.write("\n".join(REPORT) + "\n")


run_all()
