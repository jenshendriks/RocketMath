# Benchmarking Rocket Math vs a hand-built formula node

The whole pitch is "fewer nodes, same result, faster eval." Here's how to turn
that into numbers you can post.

## Setup

1. **Make a heavy mesh.** `Add > Mesh > Grid`, then in the operator panel set
   *X*/*Y Subdivisions* high — e.g. `1000 × 1000` ≈ 1,000,000 vertices. (More
   verts = more field evaluations = a clearer gap.)
2. **Add a Geometry Nodes modifier** to it.
3. **Drive a visible result with the formula.** Simplest: a `Set Position` node,
   with its *Offset* fed by the Rocket Math node. Feed the Rocket Math inputs
   from `Position` (use `Separate XYZ` for scalar inputs, or the whole Position
   vector for vector inputs).
4. **Pick one non-trivial formula** with repeated sub-expressions, e.g.:
   ```
   sin(x*y) * cos(x*y) + (x*y)^2 - sqrt(abs(x*y))
   ```
   The repeated `x*y` is exactly what CSE collapses.

## Measure

1. In the Geometry Node editor header, open the **Overlays** dropdown and enable
   **Timings**. Each node now shows its evaluation time in ms.
2. Read the ms on the **Rocket Math** group node. Note the **Generated nodes**
   count from the sidebar's *Rocket Math* tab.
3. Let it run a few frames first (warm up), then read a few times and take a
   typical value — the number fluctuates frame to frame.

## Compare

Build the **same** formula with the other addon, on the **same** mesh, and read
its node timing and node count. Tabulate:

| Tool | Generated nodes | Eval time (ms) |
|---|---|---|
| Rocket Math | ? | ? |
| Hand-built node | ? | ? |

## Keep it fair

- Same mesh density and same formula for both.
- Same render engine / same frame.
- Compare the **node's own** timing, not whole-tree time (the rest of the tree
  is identical for both).
- Expect the biggest gap on formulas with repeated sub-expressions and on
  high vertex counts — that's where minimal-network + CSE pays off.
