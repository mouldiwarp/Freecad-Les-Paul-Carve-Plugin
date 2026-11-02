# Development

## Layout

```
les_paul_carve.py          carve geometry (no GUI). CarveParams, height_field, carve_top, carve_subelement
LesPaulCarveTop.FCMacro    FreeCAD macro: reads the selection, calls carve_subelement, adds the result
install.sh                 copies the macro and library into FreeCAD's macro folder
test_les_paul_carve.py     headless tests (run with FreeCAD's freecadcmd)
docs/                      design and development notes
```

The geometry lives in `les_paul_carve.py` and never imports the GUI. The macro is a thin
wrapper, so the geometry can be tested headless.

## Pipeline

1. `height_field(face, params)` samples a grid over the top face and builds the removal field:
   point-in-polygon for the inside, distance to the closed outline, blur of the signed distance,
   the rim, the shoulder, and the flat areas.
2. `carve_top(face, body, params)` fits one B-spline surface through the removal field, extrudes
   it down to make a solid, and intersects it with the body (`body.common(keep)`).
3. The macro adds the result as a new `Part::Feature`.

## Running the tests

```bash
FC=/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd
CARVE_TEST_FCSTD=/path/to/body.FCStd \
  "$FC" -c "exec(open('$PWD/test_les_paul_carve.py').read())"
```

- Look for `=== ALL PASSED` at the end.
- Each check prints `[PASS]` or `[FAIL]` and a number. Results are also saved to `test_report.txt`.
- The real-body tests need `CARVE_TEST_FCSTD`. They carve both `Body - Carve` and `Body - Main`,
  using a temporary copy of the file.

The tests check:
- a rectangle slab against the analytic profile
- the rim dip and the first line
- the flat crown and its falloff
- the open front (crown height held to the edge, no lip)
- the flat waist and central strip on the real body
- edge smoothness along the front, measured as the second difference of the height

Every test prints its measured value, so a change in numbers is visible even when a check still
passes.

## Changing the shape

1. Change the parameter in `CarveParams`, or the logic in `height_field`.
2. Run the tests. Check the failing numbers before loosening a tolerance.
3. Run `./install.sh` and restart FreeCAD.
4. Check the result in FreeCAD. The tests check numbers, not how the surface looks.

Useful checks when debugging:
- Render the removal field as contours, or shade the carved top from a few light angles.
- Walk the outline 2 mm in from the edge and read the removal along it. Look for stair-steps.

## Known pitfalls

- **Grid steps show up as ripples.** Anything computed from the grid cell by cell (a nearest-cell
  lookup, for example) will show as stair-steps. Compute distances analytically where the shape
  needs to be smooth.
- **Values outside the part matter.** The surface fit needs a continuous field across the edge.
  Setting values outside to a constant creates a cliff.
- **FreeCAD keeps imported modules.** After changing the library, restart FreeCAD. The macro reloads the
  library on every run, but a stale copy may still be loaded in an open session.
- **`BoundBox` is loose for B-spline faces.** Use `optimalBoundingBox()` when checking bounds.

## Contributing

Open an issue or a pull request. Keep the geometry in `les_paul_carve.py` free of GUI imports, and
add a test for any new behaviour.
