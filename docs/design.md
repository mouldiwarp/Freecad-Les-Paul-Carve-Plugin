# Design

This document describes what the carve does and why. For install and use, see the
[README](../README.md).

## Inputs and outputs

- **Input:** a flat, horizontal top face (normal +Z) of a solid body, plus the body it belongs to.
  The top face may have holes (pickup and control cavities). The holes are ignored.
- **Output:** a new solid. It is the original body with material removed from the top, so the
  top surface follows the carve. The bottom, sides and cavities are unchanged.

All lengths are in millimetres. The carve removes material downward from the top face.

## Orientation

The carve needs to know which way is the front of the instrument. `neck_direction` is the
direction from the tail toward the neck, in the top face's XY plane. The default is `(1, 0)`,
which matches a body whose neck points along +X.

Two axes are used:
- `S`: position along `neck_direction`, from tail to front.
- `Lt`: position across the body, perpendicular to `S`.

## The shape

The top is built from four parts, all expressed as "how much material to remove" at each point
(`removal`).

1. **Rim.** The outer edge is removed by `edge_removal` (14 mm). Moving inward from the edge, the
   removal falls linearly by `rim_dip` (0.5 mm) over `rim_width` (14 mm). That first contour
   ("the first line") is only a little lower than the rim.

2. **Shoulder.** From the first line the removal rises in an S-curve to the flat areas.
   - `profile_exponent` sets the S-curve sharpness.
   - `shoulder_bias` skews it, so the steepest part sits close to the edge and the rise eases
     into the top, as in the cross-section reference.

3. **Lower-bout crown.** Inside the innermost contour (where the distance from the edge reaches
   `crown_fraction` of the maximum), the top is flat at `peak_removal` (2 mm).

4. **Central strip.** A flat strip, `corridor_half_width` (28 mm) either side of the body centreline,
   runs from the lower-bout crown through the waist to the front. It is also flat at `peak_removal`.
   This matches the flat strip in the carve template.

The shoulder blends from the first line into whichever flat area is nearest. The blend uses the
exact distance to that area, so the shoulder has no stair-steps.

## The open front

The horn tip and cutaway are not treated as an edge. Distance from the edge is measured only from
the closed outline, which covers the sides and the tail. The front is the last `open_front_fraction`
(20%) of the body length. There the top stays at crown height right out to the edge, with no thin
lip. The neck angle is set by planing the front by hand for each build.

## Smoothing and accuracy

- The distance field is blurred (`smoothing`) to round the creases along the centreline. The blur is
  applied to the signed distance, so it does not bias the rim.
- The field is sampled on a grid (`grid_step`) and fitted with one B-spline surface. The surface
  passes through the grid points. Between them it follows the field closely.
- Outside the part, the field is evaluated with the same formula as inside. This avoids a cliff at
  the edge, which would otherwise ring along it.

## Why these numbers

The depths come from a cross-section reference: 14 mm of removal at the outer edge and 2 mm at the
flat crown, with an S-curve between. The 3/4" blank and 5/8" and 1/4" cap figures from an earlier
reference are the basis for the original depth estimates, but the cross-section values were
preferred.

The first-line dip and the 28 mm strip were taken from the carve template. The 88% crown fraction was
chosen by comparing the crown's size with the innermost contour of the isoline drawing.

All of these are parameters, so they can be adjusted without changing the code.

## Known limits

- The carve assumes the top face is the top of the blank. Other faces are not supported.
- The front must point along `neck_direction`.
- The field is a grid fit. It is accurate to about 0.1 mm on the test bodies, but it is not an exact
  analytic surface.
