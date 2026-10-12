# Rocket Math - formula node for Blender geometry & shader node editors.
#
# Type an equation, get a native Math / Vector Math node network inside a
# node group. A recursive-descent parser (no nesting limit, only "(") feeds an
# expression compiler that does common-subexpression elimination (CSE) so the
# generated network is minimal -- the whole point of the speed test.
#
# Install: Edit > Preferences > Add-ons > Install... pick this .py file, enable.
# Use: open a Geometry Nodes or Shader editor, press N, "Rocket Math" tab,
#      "Add Formula Node", then edit the Formula field.

bl_info = {
    "name": "Rocket Math",
    "author": "Rocket Science",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "Node Editor > Sidebar > Rocket Math",
    "description": "Typed formula node that compiles to native math nodes (with CSE).",
    "category": "Node",
}

import math

try:
    import bpy
except Exception:  # allows importing the module outside Blender for self-test
    bpy = None


# --------------------------------------------------------------------------- #
# AST
# --------------------------------------------------------------------------- #
class Num:
    __slots__ = ("v",)
    def __init__(self, v): self.v = float(v)

class Var:
    __slots__ = ("name",)
    def __init__(self, name): self.name = name

class BinOp:
    __slots__ = ("op", "left", "right")
    def __init__(self, op, left, right):
        self.op, self.left, self.right = op, left, right

class Call:
    __slots__ = ("fn", "args")
    def __init__(self, fn, args): self.fn, self.args = fn, args


class RocketError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Operation tables
# --------------------------------------------------------------------------- #
ORDER = ["x", "y", "z", "w", "v"]
VARS = set(ORDER)
CONSTS = {"pi": math.pi, "tau": math.tau, "e": math.e}

# name -> (operation, nargs, [(input_index, fixed_value), ...])  (ShaderNodeMath)
MATH_FUNCS = {
    "pow": ("POWER", 2, []),
    "log": ("LOGARITHM", 2, []),
    "ln": ("LOGARITHM", 1, [(1, math.e)]),
    "log2": ("LOGARITHM", 1, [(1, 2.0)]),
    "log10": ("LOGARITHM", 1, [(1, 10.0)]),
    "sqrt": ("SQRT", 1, []),
    "invsqrt": ("INVERSE_SQRT", 1, []),
    "exp": ("EXPONENT", 1, []),
    "sign": ("SIGN", 1, []),
    "round": ("ROUND", 1, []),
    "trunc": ("TRUNC", 1, []),
    "asin": ("ARCSINE", 1, []),
    "acos": ("ARCCOSINE", 1, []),
    "atan": ("ARCTANGENT", 1, []),
    "atan2": ("ARCTAN2", 2, []),
    "sinh": ("SINH", 1, []),
    "cosh": ("COSH", 1, []),
    "tanh": ("TANH", 1, []),
    "radians": ("RADIANS", 1, []),
    "degrees": ("DEGREES", 1, []),
    "lessthan": ("LESS_THAN", 2, []),
    "greaterthan": ("GREATER_THAN", 2, []),
    "compare": ("COMPARE", 3, []),
    "smoothmin": ("SMOOTH_MIN", 3, []),
    "smoothmax": ("SMOOTH_MAX", 3, []),
    "pingpong": ("PINGPONG", 2, []),
    "flooredmod": ("FLOORED_MODULO", 2, []),
}

# name -> (operation, input_index_map, return_type, arg_kinds)  (ShaderNodeVectorMath)
VEC_FUNCS = {
    "distance": ("DISTANCE", [0, 1], "FLOAT", ["V", "V"]),
    "length": ("LENGTH", [0], "FLOAT", ["V"]),
    "dot": ("DOT_PRODUCT", [0, 1], "FLOAT", ["V", "V"]),
    "cross": ("CROSS_PRODUCT", [0, 1], "VECTOR", ["V", "V"]),
    "normalize": ("NORMALIZE", [0], "VECTOR", ["V"]),
    "project": ("PROJECT", [0, 1], "VECTOR", ["V", "V"]),
    "reflect": ("REFLECT", [0, 1], "VECTOR", ["V", "V"]),
    "scale": ("SCALE", [0, 3], "VECTOR", ["V", "F"]),
    "faceforward": ("FACEFORWARD", [0, 1, 2], "VECTOR", ["V", "V", "V"]),
}

# polymorphic (componentwise) funcs: float op via ShaderNodeMath, vector via map.
POLY = {
    "abs": "ABSOLUTE", "min": "MINIMUM", "max": "MAXIMUM", "floor": "FLOOR",
    "ceil": "CEIL", "fract": "FRACT", "mod": "MODULO", "wrap": "WRAP",
    "snap": "SNAP", "sin": "SINE", "cos": "COSINE", "tan": "TANGENT",
}
POLY_NARGS = {
    "abs": 1, "min": 2, "max": 2, "floor": 1, "ceil": 1, "fract": 1,
    "mod": 2, "wrap": 3, "snap": 2, "sin": 1, "cos": 1, "tan": 1,
}
VEC_OP_MAP = {
    "ABSOLUTE": "ABSOLUTE", "MINIMUM": "MINIMUM", "MAXIMUM": "MAXIMUM",
    "FLOOR": "FLOOR", "CEIL": "CEIL", "FRACT": "FRACTION", "MODULO": "MODULO",
    "WRAP": "WRAP", "SNAP": "SNAP", "SINE": "SINE", "COSINE": "COSINE",
    "TANGENT": "TANGENT",
}

ALIASES = {
    "dist": "distance", "len": "length", "norm": "normalize",
    "rad": "radians", "deg": "degrees", "rsqrt": "invsqrt",
}
# infix words: "x dist y" -> distance(x, y)
INFIX_WORDS = {
    "dist": "distance", "distance": "distance", "dot": "dot", "cross": "cross",
    "angle": "angle", "project": "project", "reflect": "reflect", "mod": "mod",
    "atan2": "atan2", "snap": "snap",
}
COMMUTATIVE_FN = {"distance", "dot", "min", "max"}


def canonical(name):
    return ALIASES.get(name, name)


# --------------------------------------------------------------------------- #
# Tokenizer + parser
# --------------------------------------------------------------------------- #
def tokenize(s):
    toks = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c.isspace():
            i += 1
            continue
        if c.isdigit() or (c == "." and i + 1 < n and s[i + 1].isdigit()):
            j = i
            while j < n and (s[j].isdigit() or s[j] == "."):
                j += 1
            if j < n and s[j] in "eE":
                j += 1
                if j < n and s[j] in "+-":
                    j += 1
                while j < n and s[j].isdigit():
                    j += 1
            toks.append(("num", float(s[i:j])))
            i = j
            continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (s[j].isalnum() or s[j] == "_"):
                j += 1
            toks.append(("id", s[i:j].lower()))
            i = j
            continue
        if c in "+-*/^%(),":
            toks.append((c, c))
            i += 1
            continue
        raise RocketError("Unexpected character '%s'" % c)
    toks.append(("end", None))
    return toks


def _show(tok):
    return "end of formula" if tok[1] is None else "'%s'" % tok[1]


class _Parser:
    def __init__(self, toks):
        self.toks = toks
        self.pos = 0

    def cur(self):
        return self.toks[self.pos]

    def eat(self, kind=None):
        t = self.toks[self.pos]
        if kind is not None and t[0] != kind:
            raise RocketError("Expected '%s' but found %s" % (kind, _show(t)))
        self.pos += 1
        return t

    def parse(self):
        node = self.infix()
        if self.cur()[0] != "end":
            raise RocketError("Unexpected %s" % _show(self.cur()))
        return node

    def infix(self):
        left = self.add()
        while self.cur()[0] == "id" and self.cur()[1] in INFIX_WORDS:
            word = self.eat()[1]
            right = self.add()
            left = Call(INFIX_WORDS[word], [left, right])
        return left

    def add(self):
        left = self.mul()
        while self.cur()[0] in ("+", "-"):
            op = self.eat()[0]
            left = BinOp(op, left, self.mul())
        return left

    def mul(self):
        left = self.unary()
        while self.cur()[0] in ("*", "/", "%"):
            op = self.eat()[0]
            left = BinOp(op, left, self.unary())
        return left

    def unary(self):
        if self.cur()[0] == "-":
            self.eat()
            return BinOp("*", Num(-1.0), self.unary())
        if self.cur()[0] == "+":
            self.eat()
            return self.unary()
        return self.power()

    def power(self):
        base = self.primary()
        if self.cur()[0] == "^":
            self.eat()
            return BinOp("^", base, self.unary())
        return base

    def primary(self):
        t = self.cur()
        if t[0] == "(":
            self.eat("(")
            e = self.infix()
            self.eat(")")
            return e
        if t[0] == "num":
            self.eat()
            return Num(t[1])
        if t[0] == "id":
            name = self.eat()[1]
            if self.cur()[0] == "(":
                self.eat("(")
                args = []
                if self.cur()[0] != ")":
                    args.append(self.infix())
                    while self.cur()[0] == ",":
                        self.eat(",")
                        args.append(self.infix())
                self.eat(")")
                return Call(canonical(name), args)
            if name in CONSTS:
                return Num(CONSTS[name])
            if name in VARS:
                return Var(name)
            raise RocketError("Unknown name '%s' (variables are x, y, z, w, v)" % name)
        raise RocketError("Unexpected %s" % _show(t))


def parse(s):
    if not s or not s.strip():
        raise RocketError("Empty formula")
    return _Parser(tokenize(s)).parse()


def rewrite(n):
    """Expand composite macros (angle) into primitive calls."""
    if isinstance(n, Call):
        args = [rewrite(a) for a in n.args]
        if n.fn == "angle":
            if len(args) != 2:
                raise RocketError("angle expects 2 arguments")
            a, b = args
            return Call("acos", [Call("dot", [Call("normalize", [a]),
                                              Call("normalize", [b])])])
        return Call(n.fn, args)
    if isinstance(n, BinOp):
        return BinOp(n.op, rewrite(n.left), rewrite(n.right))
    return n


# --------------------------------------------------------------------------- #
# Type inference (FLOAT vs VECTOR)
# --------------------------------------------------------------------------- #
def etype(n, vt):
    if isinstance(n, Num):
        return "FLOAT"
    if isinstance(n, Var):
        return vt.get(n.name, "FLOAT")
    if isinstance(n, BinOp):
        if n.op == "^":
            return "FLOAT"
        lt, rt = etype(n.left, vt), etype(n.right, vt)
        return "VECTOR" if "VECTOR" in (lt, rt) else "FLOAT"
    if isinstance(n, Call):
        if n.fn in VEC_FUNCS:
            return VEC_FUNCS[n.fn][2]
        if n.fn in MATH_FUNCS:
            return "FLOAT"
        if n.fn in POLY:
            return "VECTOR" if any(etype(a, vt) == "VECTOR" for a in n.args) else "FLOAT"
        raise RocketError("Unknown function '%s'" % n.fn)
    raise RocketError("Bad node")


def _walk(n):
    yield n
    if isinstance(n, BinOp):
        yield from _walk(n.left)
        yield from _walk(n.right)
    elif isinstance(n, Call):
        for a in n.args:
            yield from _walk(a)


def infer_var_types(ast, overrides=None):
    used = {x.name for x in _walk(ast) if isinstance(x, Var)}
    vforce, fforce = set(), set()
    # Seed from connection-detected types (overrides win unless the formula
    # strictly demands the opposite, which surfaces as a clear conflict error).
    for v, t in (overrides or {}).items():
        if v in used:
            (vforce if t == "VECTOR" else fforce).add(v)

    def force_vec(node):
        if isinstance(node, Var):
            vforce.add(node.name)
        elif isinstance(node, BinOp) and node.op in ("+", "-", "%"):
            force_vec(node.left)
            force_vec(node.right)

    def force_float(node):
        if isinstance(node, Var):
            fforce.add(node.name)
        elif isinstance(node, BinOp) and node.op in ("+", "-", "*", "/", "%"):
            force_float(node.left)
            force_float(node.right)

    for node in _walk(ast):
        if isinstance(node, BinOp) and node.op == "^":
            force_float(node.left)
            force_float(node.right)
        elif isinstance(node, Call):
            if node.fn in MATH_FUNCS:
                for a in node.args:
                    force_float(a)
            elif node.fn in VEC_FUNCS:
                kinds = VEC_FUNCS[node.fn][3]
                for a, k in zip(node.args, kinds):
                    (force_vec if k == "V" else force_float)(a)

    changed = True
    while changed:
        changed = False
        vt = {v: ("VECTOR" if v in vforce else "FLOAT") for v in used}
        for node in _walk(ast):
            if isinstance(node, BinOp) and node.op in ("+", "-", "%"):
                if "VECTOR" in (etype(node.left, vt), etype(node.right, vt)):
                    for side in (node.left, node.right):
                        if isinstance(side, Var) and side.name not in vforce:
                            vforce.add(side.name)
                            changed = True

    conflict = vforce & fforce
    if conflict:
        raise RocketError("Variable '%s' used as both scalar and vector"
                          % sorted(conflict)[0])
    return {v: ("VECTOR" if v in vforce else "FLOAT") for v in used}


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
class CountingBuilder:
    """Backend that records node creation only -- used to verify CSE offline."""
    def __init__(self):
        self.nodes = []

    def node(self, kind, op):
        h = ("node", len(self.nodes), kind, op)
        self.nodes.append((kind, op))
        return h

    def set_default(self, n, idx, val):
        pass

    def link(self, src, n, idx):
        pass

    def out(self, n, idx):
        return ("out", n, idx)

    def value(self, v):
        self.nodes.append(("VALUE", None))
        return ("val", v)

    def place(self, n, depth):
        pass


class BlenderBuilder:
    KIND = {
        "MATH": "ShaderNodeMath",
        "VEC": "ShaderNodeVectorMath",
        "COMBINE": "ShaderNodeCombineXYZ",
        "VALUE": "ShaderNodeValue",
    }

    def __init__(self, tree):
        self.tree = tree
        self.ys = {}
        self.maxdepth = 0

    def node(self, kind, op):
        n = self.tree.nodes.new(self.KIND[kind])
        if op and kind in ("MATH", "VEC"):
            n.operation = op
        return n

    def set_default(self, n, idx, val):
        n.inputs[idx].default_value = val

    def link(self, src, n, idx):
        self.tree.links.new(src, n.inputs[idx])

    def out(self, n, idx):
        return n.outputs[idx]

    def value(self, v):
        n = self.node("VALUE", None)
        n.outputs[0].default_value = v
        self.place(n, 0)
        return n.outputs[0]

    def place(self, n, depth):
        self.maxdepth = max(self.maxdepth, depth)
        y = self.ys.get(depth, 0)
        n.location = (depth * 220.0, y)
        self.ys[depth] = y - 200.0


# --------------------------------------------------------------------------- #
# Compiler (AST -> builder, with CSE via memoised structural keys)
# --------------------------------------------------------------------------- #
def keyof(n):
    if isinstance(n, Num):
        return ("n", round(n.v, 9))
    if isinstance(n, Var):
        return ("var", n.name)
    if isinstance(n, BinOp):
        lk, rk = keyof(n.left), keyof(n.right)
        kids = tuple(sorted([lk, rk])) if n.op in ("+", "*") else (lk, rk)
        return ("b", n.op, kids)
    if isinstance(n, Call):
        ks = [keyof(a) for a in n.args]
        if n.fn in COMMUTATIVE_FN:
            ks = sorted(ks)
        return ("c", n.fn, tuple(ks))
    raise RocketError("Bad node")


class _Ctx:
    def __init__(self, b, var_sockets, var_types):
        self.b = b
        self.var_sockets = var_sockets
        self.var_types = var_types
        self.memo = {}


def _broadcast(ctx, sock):
    c = ctx.b.node("COMBINE", None)
    ctx.b.link(sock, c, 0)
    ctx.b.link(sock, c, 1)
    ctx.b.link(sock, c, 2)
    ctx.b.place(c, 1)
    return ctx.b.out(c, 0)


def _connect(ctx, node, idx, child, want, allow_broadcast=True, label=""):
    """Wire child into node.inputs[idx]; return child depth.

    allow_broadcast=False makes a scalar -> vector mismatch an error instead of
    silently expanding the scalar to (s, s, s). Used by the geometric vector
    functions (distance, dot, cross, ...) where broadcasting is meaningless.
    """
    who = label or "this operation"
    if isinstance(child, Num):
        if want == "VECTOR":
            if not allow_broadcast:
                raise RocketError("%s needs a vector input but got a number" % who)
            ctx.b.set_default(node, idx, (child.v, child.v, child.v))
        else:
            ctx.b.set_default(node, idx, child.v)
        return 0
    sock, ctype, depth = _emit(ctx, child)
    if want == "VECTOR" and ctype == "FLOAT":
        if not allow_broadcast:
            raise RocketError("%s needs a vector input but got a scalar" % who)
        sock = _broadcast(ctx, sock)
    elif want == "FLOAT" and ctype == "VECTOR":
        raise RocketError("%s expected a scalar but got a vector" % who)
    ctx.b.link(sock, node, idx)
    return depth


def _finish(ctx, node, outidx, rtype, depths):
    d = (max(depths) + 1) if depths else 1
    ctx.b.place(node, d)
    return (ctx.b.out(node, outidx), rtype, d)


def _emit(ctx, n):
    k = keyof(n)
    if k in ctx.memo:
        return ctx.memo[k]
    res = _emit_raw(ctx, n)
    ctx.memo[k] = res
    return res


def _emit_raw(ctx, n):
    if isinstance(n, Num):
        return (ctx.b.value(n.v), "FLOAT", 0)
    if isinstance(n, Var):
        if n.name not in ctx.var_sockets:
            raise RocketError("Variable '%s' is not available" % n.name)
        return (ctx.var_sockets[n.name], ctx.var_types[n.name], 0)
    if isinstance(n, BinOp):
        return _emit_binop(ctx, n)
    if isinstance(n, Call):
        return _emit_call(ctx, n)
    raise RocketError("Bad node")


def _emit_binop(ctx, n):
    L, R = n.left, n.right
    lt, rt = etype(L, ctx.var_types), etype(R, ctx.var_types)

    if n.op == "^":
        node = ctx.b.node("MATH", "POWER")
        d0 = _connect(ctx, node, 0, L, "FLOAT")
        d1 = _connect(ctx, node, 1, R, "FLOAT")
        return _finish(ctx, node, 0, "FLOAT", [d0, d1])

    vec = "VECTOR" in (lt, rt)

    if n.op in ("+", "-", "%"):
        name = {"+": "ADD", "-": "SUBTRACT", "%": "MODULO"}[n.op]
        if vec:
            node = ctx.b.node("VEC", name)
            d0 = _connect(ctx, node, 0, L, "VECTOR")
            d1 = _connect(ctx, node, 1, R, "VECTOR")
            return _finish(ctx, node, 0, "VECTOR", [d0, d1])
        node = ctx.b.node("MATH", name)
        d0 = _connect(ctx, node, 0, L, "FLOAT")
        d1 = _connect(ctx, node, 1, R, "FLOAT")
        return _finish(ctx, node, 0, "FLOAT", [d0, d1])

    if n.op == "*":
        if lt == "VECTOR" and rt == "VECTOR":
            node = ctx.b.node("VEC", "MULTIPLY")
            d0 = _connect(ctx, node, 0, L, "VECTOR")
            d1 = _connect(ctx, node, 1, R, "VECTOR")
            return _finish(ctx, node, 0, "VECTOR", [d0, d1])
        if lt == "VECTOR":  # vector * float -> scale
            node = ctx.b.node("VEC", "SCALE")
            d0 = _connect(ctx, node, 0, L, "VECTOR")
            d1 = _connect(ctx, node, 3, R, "FLOAT")
            return _finish(ctx, node, 0, "VECTOR", [d0, d1])
        if rt == "VECTOR":  # float * vector -> scale
            node = ctx.b.node("VEC", "SCALE")
            d0 = _connect(ctx, node, 0, R, "VECTOR")
            d1 = _connect(ctx, node, 3, L, "FLOAT")
            return _finish(ctx, node, 0, "VECTOR", [d0, d1])
        node = ctx.b.node("MATH", "MULTIPLY")
        d0 = _connect(ctx, node, 0, L, "FLOAT")
        d1 = _connect(ctx, node, 1, R, "FLOAT")
        return _finish(ctx, node, 0, "FLOAT", [d0, d1])

    if n.op == "/":
        if vec:
            node = ctx.b.node("VEC", "DIVIDE")
            d0 = _connect(ctx, node, 0, L, "VECTOR")
            d1 = _connect(ctx, node, 1, R, "VECTOR")
            return _finish(ctx, node, 0, "VECTOR", [d0, d1])
        node = ctx.b.node("MATH", "DIVIDE")
        d0 = _connect(ctx, node, 0, L, "FLOAT")
        d1 = _connect(ctx, node, 1, R, "FLOAT")
        return _finish(ctx, node, 0, "FLOAT", [d0, d1])

    raise RocketError("Unknown operator '%s'" % n.op)


def _emit_call(ctx, n):
    name = n.fn

    if name in VEC_FUNCS:
        op, inmap, ret, kinds = VEC_FUNCS[name]
        if len(n.args) != len(inmap):
            raise RocketError("'%s' expects %d argument(s)" % (name, len(inmap)))
        node = ctx.b.node("VEC", op)
        depths = []
        for a, idx, k in zip(n.args, inmap, kinds):
            if k == "V":
                depths.append(_connect(ctx, node, idx, a, "VECTOR",
                                       allow_broadcast=False, label="%s()" % name))
            else:
                depths.append(_connect(ctx, node, idx, a, "FLOAT"))
        return _finish(ctx, node, 1 if ret == "FLOAT" else 0, ret, depths)

    if name in MATH_FUNCS:
        op, nargs, fixed = MATH_FUNCS[name]
        if len(n.args) != nargs:
            raise RocketError("'%s' expects %d argument(s)" % (name, nargs))
        node = ctx.b.node("MATH", op)
        depths = [_connect(ctx, node, i, a, "FLOAT") for i, a in enumerate(n.args)]
        for idx, val in fixed:
            ctx.b.set_default(node, idx, val)
        return _finish(ctx, node, 0, "FLOAT", depths)

    if name in POLY:
        op, nargs = POLY[name], POLY_NARGS[name]
        if len(n.args) != nargs:
            raise RocketError("'%s' expects %d argument(s)" % (name, nargs))
        rtype = ("VECTOR" if any(etype(a, ctx.var_types) == "VECTOR" for a in n.args)
                 else "FLOAT")
        if rtype == "VECTOR":
            node = ctx.b.node("VEC", VEC_OP_MAP[op])
            want = "VECTOR"
        else:
            node = ctx.b.node("MATH", op)
            want = "FLOAT"
        depths = [_connect(ctx, node, i, a, want) for i, a in enumerate(n.args)]
        return _finish(ctx, node, 0, rtype, depths)

    raise RocketError("Unknown function '%s'" % name)


def compile_ast(ast, var_sockets, var_types, builder):
    ctx = _Ctx(builder, var_sockets, var_types)
    return _emit(ctx, ast)


def analyze(formula, overrides=None):
    """Parse + type-infer. Returns (ast, ordered_vars, var_types, result_type)."""
    ast = rewrite(parse(formula))
    var_types = infer_var_types(ast, overrides)
    rtype = etype(ast, var_types)
    ordered = [v for v in ORDER if v in var_types]
    return ast, ordered, var_types, rtype


def _used_vars(ast):
    return {n.name for n in _walk(ast) if isinstance(n, Var)}


def _encode_overrides(d):
    return ",".join("%s:%s" % (k, d[k]) for k in sorted(d))


def _decode_overrides(s):
    out = {}
    for part in (s or "").split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


# --------------------------------------------------------------------------- #
# Blender integration
# --------------------------------------------------------------------------- #
if bpy is not None:
    from bpy.app.handlers import persistent

    def _socket_type(t):
        return "NodeSocketVector" if t == "VECTOR" else "NodeSocketFloat"

    def _iface_sockets(iface):
        return [it for it in iface.items_tree
                if getattr(it, "item_type", "") == "SOCKET"]

    def _retype(iface, item, name, stype, in_out):
        """Change a socket's type in place; fall back to recreate if needed."""
        try:
            item.socket_type = stype
        except Exception:
            iface.remove(item)
            iface.new_socket(name, in_out=in_out, socket_type=stype)

    def _find_socket(iface, in_out, name):
        return next((s for s in _iface_sockets(iface)
                     if s.in_out == in_out and s.name == name), None)

    def _reconcile_interface(grp, available, in_types, rtype, with_formula):
        """Make the interface match (Formula?, X..available, Result) in place, so
        external links to the group node survive a rebuild. The String 'Formula'
        socket is the on-the-node text field (geometry nodes only)."""
        iface = grp.interface
        want_in = {v.upper(): _socket_type(in_types[v]) for v in available}

        for it in list(_iface_sockets(iface)):
            if it.in_out == "INPUT":
                if it.name == "Formula":
                    if not with_formula:
                        iface.remove(it)
                elif it.name not in want_in:
                    iface.remove(it)
            elif it.in_out == "OUTPUT" and it.name != "Result":
                iface.remove(it)

        if with_formula and _find_socket(iface, "INPUT", "Formula") is None:
            try:
                iface.new_socket("Formula", in_out="INPUT",
                                 socket_type="NodeSocketString")
            except Exception:
                pass  # some tree types may not support string sockets

        for v in available:
            name, stype = v.upper(), _socket_type(in_types[v])
            it = _find_socket(iface, "INPUT", name)
            if it is None:
                iface.new_socket(name, in_out="INPUT", socket_type=stype)
            elif it.socket_type != stype:
                _retype(iface, it, name, stype, "INPUT")

        rstype = _socket_type(rtype)
        out = _find_socket(iface, "OUTPUT", "Result")
        if out is None:
            iface.new_socket("Result", in_out="OUTPUT", socket_type=rstype)
        elif out.socket_type != rstype:
            _retype(iface, out, "Result", rstype, "OUTPUT")

    def build_tree(grp):
        """(Re)build the node group. Input sockets grow as you connect them; the
        formula is compiled against whatever is CONNECTED. A variable used in the
        formula whose input is not connected is an error."""
        is_geo = grp.bl_idname == "GeometryNodeTree"
        count = max(1, min(5, getattr(grp, "rocket_input_count", 1)))
        available = ORDER[:count]
        overrides = _decode_overrides(getattr(grp, "rocket_type_overrides", ""))
        in_types = {v: overrides.get(v, "FLOAT") for v in available}
        connected = set(overrides) & set(available)

        error = ""
        result_type = "FLOAT"
        ast = var_types = None
        formula = (grp.rocket_formula or "").strip()
        if formula:
            try:
                ast = rewrite(parse(formula))
                used = _used_vars(ast)
                missing = [v for v in ORDER if v in used and v not in connected]
                if missing:
                    raise RocketError("Input '%s' is used but not connected"
                                      % missing[0].upper())
                var_types = {v: in_types[v] for v in available}
                result_type = etype(ast, var_types)
            except RocketError as e:
                error, ast = str(e), None
            except Exception as e:  # noqa: BLE001 - never let an update crash Blender
                error, ast = "Parse error: %s" % e, None

        _reconcile_interface(grp, available, in_types, result_type, is_geo)

        grp.nodes.clear()
        gin = grp.nodes.new("NodeGroupInput")
        gout = grp.nodes.new("NodeGroupOutput")
        gin.location = (-260.0, 120.0)
        gout.location = (220.0, 0.0)

        if ast is not None and not error:
            var_sockets = {}
            for s in gin.outputs:
                for v in available:
                    if s.name == v.upper():
                        var_sockets[v] = s
            b = BlenderBuilder(grp)
            try:
                sock, _t, _d = compile_ast(ast, var_sockets, var_types, b)
                res_in = next((s for s in gout.inputs if s.name == "Result"), None)
                if res_in is not None:
                    grp.links.new(sock, res_in)
                gout.location = ((b.maxdepth + 1) * 220.0, 0.0)
            except RocketError as e:
                error = str(e)

        grp.rocket_error = error

    def _formula_update(self, context):
        build_tree(self)

    def _type_from_socket(sock):
        ft = sock.links[0].from_socket.type
        return "VECTOR" if ft in {"VECTOR", "RGBA"} else "FLOAT"

    def _sync_node(node, grp):
        """Drive a Rocket Math node from its instance: grow inputs as the last
        one gets connected, detect input types, read the on-node Formula field,
        and tint the node on error. Converges in one rebuild."""
        is_geo = grp.bl_idname == "GeometryNodeTree"
        overrides = {}
        highest = 0
        for i, var in enumerate(ORDER):
            sock = node.inputs.get(var.upper())
            if sock and sock.is_linked and sock.links:
                overrides[var] = _type_from_socket(sock)
                highest = i + 1
        count = max(1, min(5, highest + 1))   # always one empty trailing input
        enc = _encode_overrides(overrides)

        if is_geo:
            fsock = node.inputs.get("Formula")
            formula = fsock.default_value if fsock is not None else grp.rocket_formula
        elif node.bl_idname == ROCKET_ShaderNode.bl_idname:
            formula = node.formula
        else:
            formula = grp.rocket_formula   # legacy plain shader group node

        changed_co = (count != grp.rocket_input_count
                      or enc != grp.rocket_type_overrides)
        if changed_co:
            grp.rocket_input_count = count
            grp.rocket_type_overrides = enc
        if formula != grp.rocket_formula:
            grp.rocket_formula = formula   # update callback runs build_tree
        elif changed_co:
            build_tree(grp)

        want_red = bool(grp.rocket_error)
        if want_red and not node.use_custom_color:
            node.use_custom_color = True
            node.color = (0.45, 0.18, 0.18)
        elif not want_red and node.use_custom_color:
            node.use_custom_color = False

    def _sync_all():
        trees = list(bpy.data.node_groups)
        # Shader trees embedded in materials, worlds and lights. Blender 5.x
        # deprecates `use_nodes` (always on), so just check for a tree.
        for coll in (bpy.data.materials, bpy.data.worlds, bpy.data.lights):
            for idb in coll:
                if getattr(idb, "node_tree", None) is not None:
                    trees.append(idb.node_tree)
        for tree in trees:
            for node in tree.nodes:
                grp = getattr(node, "node_tree", None)
                if grp and getattr(grp, "rocket_is_formula", False):
                    _sync_node(node, grp)

    @persistent
    def _depsgraph_handler(scene, depsgraph=None):
        try:
            _sync_all()
        except Exception:
            pass  # never destabilise the depsgraph from a handler

    def _shader_formula_update(self, context):
        if self.node_tree is not None:
            _sync_node(self, self.node_tree)

    class ROCKET_ShaderNode(bpy.types.ShaderNodeCustomGroup):
        """Shader node groups cannot have String sockets, so the shader version
        of the formula node is a Python group node that draws its own text
        field and owns a hidden node group holding the generated network."""
        bl_idname = "RocketMathShaderNode"
        bl_label = "Formula"
        bl_icon = "DRIVER"

        formula: bpy.props.StringProperty(
            name="Formula", default="", update=_shader_formula_update)

        @classmethod
        def poll(cls, ntree):
            return ntree.bl_idname == "ShaderNodeTree"

        def init(self, context):
            grp = bpy.data.node_groups.new(".RocketMath", "ShaderNodeTree")
            grp.rocket_is_formula = True
            self.node_tree = grp
            build_tree(grp)
            self.width = 200.0

        def copy(self, node):
            # Each formula node owns its own group, so duplicates stay independent.
            if node.node_tree is not None:
                self.node_tree = node.node_tree.copy()

        def draw_buttons(self, context, layout):
            layout.prop(self, "formula", text="", icon="DRIVER")
            grp = self.node_tree
            if grp is not None and grp.rocket_error:
                layout.label(text=grp.rocket_error, icon="ERROR")

        def draw_buttons_ext(self, context, layout):
            layout.prop(self, "formula", text="Formula")

    class ROCKET_OT_add_formula(bpy.types.Operator):
        bl_idname = "node.rocket_add_formula"
        bl_label = "Add Formula Node"
        bl_description = "Add a Rocket Math formula node"
        bl_options = {"REGISTER", "UNDO"}

        @classmethod
        def poll(cls, context):
            sp = context.space_data
            return bool(sp and sp.type == "NODE_EDITOR" and sp.edit_tree is not None
                        and sp.edit_tree.is_editable
                        and sp.edit_tree.bl_idname in {"GeometryNodeTree", "ShaderNodeTree"})

        def invoke(self, context, event):
            # Like Blender's own Add menu: drop the node under the mouse and
            # let the user move it. Without this the node landed at the tree
            # origin, which in a material is usually hidden behind the
            # Principled BSDF or out of view, so adding looked like a no-op.
            sp = context.space_data
            if context.region and context.region.type == "WINDOW":
                sp.cursor_location_from_region(event.mouse_region_x,
                                               event.mouse_region_y)
            else:
                sp.cursor_location = sp.edit_tree.view_center
            result = self.execute(context)
            if "FINISHED" in result and context.region \
                    and context.region.type == "WINDOW":
                bpy.ops.node.translate_attach_remove_on_cancel("INVOKE_DEFAULT")
            return result

        def execute(self, context):
            sp = context.space_data
            tree = sp.edit_tree
            is_geo = tree.bl_idname == "GeometryNodeTree"
            group_node = "GeometryNodeGroup" if is_geo else ROCKET_ShaderNode.bl_idname
            try:
                node = tree.nodes.new(group_node)
            except RuntimeError as e:
                self.report({"ERROR"}, str(e))
                return {"CANCELLED"}

            if is_geo:
                grp = bpy.data.node_groups.new("RocketMath", tree.bl_idname)
                grp.rocket_is_formula = True
                node.node_tree = grp
                build_tree(grp)  # create the Formula field + first input + output
            # the shader node builds its own group in init()
            for n in tree.nodes:
                n.select = False
            node.select = True
            tree.nodes.active = node
            node.location = sp.cursor_location
            return {"FINISHED"}

    class ROCKET_OT_rebuild(bpy.types.Operator):
        bl_idname = "node.rocket_rebuild"
        bl_label = "Rebuild"
        bl_description = "Rebuild the node network from the formula"
        bl_options = {"REGISTER", "UNDO"}

        @classmethod
        def poll(cls, context):
            n = context.active_node
            return bool(n and getattr(n, "node_tree", None)
                        and getattr(n.node_tree, "rocket_is_formula", False))

        def execute(self, context):
            build_tree(context.active_node.node_tree)
            return {"FINISHED"}

    class ROCKET_PT_panel(bpy.types.Panel):
        bl_space_type = "NODE_EDITOR"
        bl_region_type = "UI"
        bl_category = "Rocket Math"
        bl_label = "Rocket Math"

        @classmethod
        def poll(cls, context):
            sp = context.space_data
            return sp and sp.type == "NODE_EDITOR"

        def draw(self, context):
            layout = self.layout
            layout.operator("node.rocket_add_formula", icon="ADD")
            node = context.active_node
            grp = getattr(node, "node_tree", None) if node else None
            if grp and getattr(grp, "rocket_is_formula", False):
                box = layout.box()
                box.label(text="Rocket Math", icon="DRIVER")
                fsock = node.inputs.get("Formula")
                if fsock is not None:
                    box.prop(fsock, "default_value", text="Formula")
                elif node.bl_idname == ROCKET_ShaderNode.bl_idname:
                    box.prop(node, "formula", text="Formula")
                else:
                    box.prop(grp, "rocket_formula", text="Formula")
                box.operator("node.rocket_rebuild", icon="FILE_REFRESH")
                if grp.rocket_error:
                    box.label(text=grp.rocket_error, icon="ERROR")
                else:
                    n_nodes = sum(1 for nd in grp.nodes
                                  if nd.bl_idname not in ("NodeGroupInput",
                                                          "NodeGroupOutput"))
                    box.label(text="Generated nodes: %d" % n_nodes)
                box.label(text="Inputs grow as you connect them.")

            sub = layout.box()
            sub.label(text="Syntax", icon="INFO")
            col = sub.column(align=True)
            col.label(text="Vars: x y z w v")
            col.label(text="Ops: + - * / ^ %")
            col.label(text="e.g. dist(x, y) * sin(z)")
            col.label(text="Full list: see README.md")

    class ROCKET_MT_add(bpy.types.Menu):
        bl_idname = "ROCKET_MT_add"
        bl_label = "Rocket Science"

        def draw(self, context):
            self.layout.operator_context = "INVOKE_REGION_WIN"
            self.layout.operator("node.rocket_add_formula",
                                 text="Formula", icon="DRIVER")

    def _add_menu(self, context):
        sp = context.space_data
        if sp and getattr(sp, "tree_type", "") in {"GeometryNodeTree", "ShaderNodeTree"}:
            self.layout.menu("ROCKET_MT_add", icon="DRIVER")

    _classes = (
        ROCKET_ShaderNode,
        ROCKET_OT_add_formula,
        ROCKET_OT_rebuild,
        ROCKET_MT_add,
        ROCKET_PT_panel,
    )

    def register():
        from bpy.props import StringProperty, BoolProperty, IntProperty
        bpy.types.NodeTree.rocket_is_formula = BoolProperty(default=False)
        bpy.types.NodeTree.rocket_formula = StringProperty(
            name="Formula", default="", update=_formula_update)
        bpy.types.NodeTree.rocket_input_count = IntProperty(
            name="Inputs", default=1, min=1, max=5)
        bpy.types.NodeTree.rocket_error = StringProperty(default="")
        bpy.types.NodeTree.rocket_type_overrides = StringProperty(default="")
        for c in _classes:
            bpy.utils.register_class(c)
        bpy.types.NODE_MT_add.append(_add_menu)
        if _depsgraph_handler not in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.append(_depsgraph_handler)

    def unregister():
        if _depsgraph_handler in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(_depsgraph_handler)
        bpy.types.NODE_MT_add.remove(_add_menu)
        for c in reversed(_classes):
            bpy.utils.unregister_class(c)
        del bpy.types.NodeTree.rocket_is_formula
        del bpy.types.NodeTree.rocket_formula
        del bpy.types.NodeTree.rocket_input_count
        del bpy.types.NodeTree.rocket_error
        del bpy.types.NodeTree.rocket_type_overrides

else:
    def register():
        pass

    def unregister():
        pass


# --------------------------------------------------------------------------- #
# Offline self-test (runs only outside Blender): verifies parsing + CSE.
# --------------------------------------------------------------------------- #
def _node_count(formula):
    ast, ordered, var_types, _rt = analyze(formula)
    b = CountingBuilder()
    compile_ast(ast, {v: ("in", v) for v in ordered}, var_types, b)
    return len(b.nodes), b.nodes


if __name__ == "__main__" and bpy is None:
    def check(formula, expect_max=None, note=""):
        cnt, nodes = _node_count(formula)
        ops = [o for k, o in nodes]
        print("  %-44s -> %2d nodes  %s" % (formula, cnt, note))
        if expect_max is not None:
            assert cnt <= expect_max, "expected <= %d, got %d" % (expect_max, cnt)
        return cnt

    print("Parsing / type tests:")
    for f in ["x + y", "sin(x) + cos(y)", "(((x)))", "x dist y",
              "distance(x, y)", "x * (y + z) ^ 2 - w / v",
              "angle(x, y)", "normalize(x) * length(y)"]:
        analyze(f)
        print("  ok:", f)

    print("\nCSE tests (shared subexpressions must collapse):")
    # distance(x,y) appears 3x but commutative+identical -> ONE vector node.
    naive = "distance(x,y) + distance(x,y)*sin(distance(x,y))"
    c1 = check(naive, note="(distance computed once)")
    # without CSE this would be 3 distance + ... ; assert distance node appears once
    _, nodes = _node_count(naive)
    dist_nodes = [o for k, o in nodes if o == "DISTANCE"]
    assert len(dist_nodes) == 1, "CSE failed: %d distance nodes" % len(dist_nodes)

    # commutative: x*y and y*x are the same node.
    _, nodes = _node_count("x*y + y*x")
    muls = [o for k, o in nodes if o == "MULTIPLY"]
    assert len(muls) == 1, "commutative CSE failed: %d multiplies" % len(muls)
    check("x*y + y*x", note="(x*y == y*x -> one multiply)")

    # deep nesting must not duplicate the shared inner term.
    deep = "sin(sin(sin(sin(sin(x))))) + sin(sin(sin(sin(sin(x)))))"
    _, nodes = _node_count(deep)
    sines = [o for k, o in nodes if o == "SINE"]
    assert len(sines) == 5, "nested CSE failed: %d sines" % len(sines)
    check(deep, note="(5 sines, second copy reused)")

    print("\nScalar/vector policy:")
    _node_count("distance(x, y)")      # x, y inferred as vectors -> ok
    print("  ok: distance(x, y) (vector inputs)")
    try:
        _node_count("dist(sin(x), y)")  # first arg is scalar -> must reject
        print("  FAIL: scalar into distance() accepted")
    except RocketError as e:
        print("  ok rejected scalar into distance(): %s" % e)

    print("\nError handling:")
    for bad in ["x +", "foo(x)", "(x", "x dist y dist"]:
        try:
            analyze(bad)
            print("  FAIL (no error):", bad)
        except RocketError as e:
            print("  ok rejected: %-18s -> %s" % (bad, e))

    print("\nAll self-tests passed.")
