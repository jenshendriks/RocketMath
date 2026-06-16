# Rocket Math

A formula node for Blender's **Geometry Nodes** and **Shader** editors. Type an
equation, get a clean, minimal network of native Math / Vector Math nodes —
only the nodes your formula actually needs.

Unlike fixed "switchboard" formula nodes that pre-build every possible operation
and gate them with a text field, Rocket Math **compiles** your formula on the
spot and reuses shared sub-expressions (common-subexpression elimination), so
the generated graph stays small and fast.

## Install

1. `Edit > Preferences > Add-ons > Install…`
2. Pick `rocket_math.py` and enable it.
3. In a Geometry Nodes or Shader editor: **Shift+A → Rocket Science → Formula**
   (or the **Add Formula Node** button in the sidebar's *Rocket Math* tab).

In **Geometry Nodes**, type your formula directly in the **Formula** field on
the node body. (In the Shader editor the field lives in the sidebar's *Rocket
Math* tab instead.) The network rebuilds as you edit.

## Inputs

Inputs **grow as you connect them**. The node starts with one input (`x`); plug
something into it and the next (`y`) appears, and so on up to five
(`x` `y` `z` `w` `v`). There's always one spare empty input at the end.

- Each input's type (**float** or **vector**) is auto-detected from whatever you
  plug into it.
- The formula is just math over the connected inputs. If the formula uses an
  input that **isn't connected**, the node turns **red** and reports the error
  (e.g. *"Input 'Y' is used but not connected"*).

Constants: `pi` `tau` `e`.

## Operators

| Operator | Meaning |
|---|---|
| `+` `-` `*` `/` | add, subtract, multiply, divide |
| `^` | power |
| `%` | modulo |
| `-x` | negate |
| `( … )` | grouping — **unlimited** nesting |

## Functions

### Scalar math
`pow(a,b)` · `log(a,base)` · `ln(a)` · `log2(a)` · `log10(a)` · `sqrt(a)` ·
`invsqrt(a)` · `exp(a)` · `sign(a)` · `round(a)` · `trunc(a)` ·
`asin(a)` · `acos(a)` · `atan(a)` · `atan2(a,b)` ·
`sinh(a)` · `cosh(a)` · `tanh(a)` · `radians(a)` · `degrees(a)` ·
`lessthan(a,b)` · `greaterthan(a,b)` · `compare(a,b,epsilon)` ·
`smoothmin(a,b,dist)` · `smoothmax(a,b,dist)` · `pingpong(a,scale)` ·
`flooredmod(a,b)`

### Scalar **or** vector (componentwise)
`abs(a)` · `min(a,b)` · `max(a,b)` · `floor(a)` · `ceil(a)` · `fract(a)` ·
`mod(a,b)` · `wrap(a,max,min)` · `snap(a,step)` · `sin(a)` · `cos(a)` · `tan(a)`

### Vector only
`distance(a,b)` · `length(a)` · `dot(a,b)` · `cross(a,b)` · `normalize(a)` ·
`project(a,b)` · `reflect(a,b)` · `scale(a,f)` · `faceforward(a,b,c)` ·
`angle(a,b)` *(composite: acos of the dot of the normalized vectors)*

These require vector inputs — passing a scalar is a clear error, not a silent
broadcast.

### Aliases
`dist`=`distance`, `len`=`length`, `norm`=`normalize`, `rad`=`radians`,
`deg`=`degrees`, `rsqrt`=`invsqrt`

### Infix forms
For readability, these two-argument ops can be written between their operands:

```
x dist y        ==  distance(x, y)
x dot y         ==  dot(x, y)
x cross y       ==  cross(x, y)
x angle y       ==  angle(x, y)
x project y     ==  project(x, y)
x reflect y     ==  reflect(x, y)
x mod y         ==  mod(x, y)
x atan2 y       ==  atan2(x, y)
x snap y        ==  snap(x, y)
```

## Examples

```
sin(x) + cos(y) * z
(x + y) * (x + y)              # the x+y add is built ONCE and reused
dist(x, y) * w                 # connect vectors to X and Y; W can stay scalar
normalize(x) * length(y)
smoothmin(x, y, 0.5)
abs(sin(x * pi)) ^ 2
```

## Notes / limitations

- Computation always runs as native nodes (the only thing that evaluates in
  these editors). Rocket Math's win is generating the *minimal* such network.
- Vector ops (`distance`, `dot`, …) need vector inputs: until you connect a
  vector, that input is a float and the formula will report a clear error.
- Self-test of the parser/compiler/CSE: `python3 rocket_math.py` (runs outside
  Blender).
