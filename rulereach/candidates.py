"""Shortest-first candidate strings for one lexer rule, from the real parse tree.

A rule can only win if some string matches its pattern, so the first question is
always "what does this pattern match?". The answer is taken from the parse tree
the standard library itself builds (``re._parser.parse``) rather than from a
hand-written model of the pattern syntax, and the strings are produced
shortest-first so that the first candidate which wins is the shortest one.

Two properties are tracked per rule, because the report's claims depend on them:

``exhaustive``
    the pattern's language is finite and every word in it was enumerated. If no
    candidate ever wins, that is a proof the rule cannot fire, not a guess.
``approximate``
    the pattern uses something this generator does not model (lookaround,
    backreference). Candidates may still win, but a miss proves nothing.
"""

import re
import re._constants as _C
import re._parser as _P

BACKSLASH = chr(92)

#: Characters tried when a pattern asks for a set or a complement, in the order
#: a lexer is most likely to care about. Keeping the list short keeps candidate
#: sets small; correctness never depends on it, because every candidate is
#: checked against the real lexer afterwards.
PREFS = ('a', '0', ' ', '_', 'A', '1', 'z', 'Z', '9', '.', '-', '/', '=', '"',
         "'", ':', ';', ',', '(', ')', '[', ']', '{', '}', '<', '>', '*', '+',
         '?', '!', '$', '%', '&', '|', '~', '^', '@', '#', '`', BACKSLASH,
         '\n', '\t', '\r')

SPACE_CHARS = ' \t\n\r\f\v'

MAX_OPTIONS = 6
MAX_BRANCHES = 32
MAX_DEPTH = 14
MAX_LEN = 32


class Info:
    """What the generator learned about one pattern while walking it."""

    def __init__(self):
        self.finite = True
        self.capped = False
        self.approximate = False
        self.unsupported = False
        self.anchors = set()

    @property
    def exhaustive(self):
        return (self.finite and not self.capped and not self.approximate
                and not self.unsupported)

    def as_dict(self):
        return {'finite': self.finite, 'capped': self.capped,
                'approximate': self.approximate, 'unsupported': self.unsupported,
                'exhaustive': self.exhaustive, 'anchors': sorted(self.anchors)}


def _name(op):
    return getattr(op, 'name', None) or repr(op)


def _category_has(cat, ch):
    name = _name(cat)
    word = ch.isascii() and (ch.isalnum() or ch == '_')
    digit = ch.isascii() and ch.isdigit()
    table = {
        'CATEGORY_DIGIT': digit,
        'CATEGORY_NOT_DIGIT': not digit,
        'CATEGORY_WORD': word,
        'CATEGORY_NOT_WORD': not word,
        'CATEGORY_SPACE': ch in SPACE_CHARS,
        'CATEGORY_NOT_SPACE': ch not in SPACE_CHARS,
        'CATEGORY_LINEBREAK': ch == '\n',
        'CATEGORY_NOT_LINEBREAK': ch != '\n',
    }
    return table.get(name)


def _item_has(item, ch):
    """Does one member of a character set contain ``ch``? None means unmodelled."""
    op, arg = item
    name = _name(op)
    if name == 'LITERAL':
        return chr(arg) == ch
    if name == 'NOT_LITERAL':
        return chr(arg) != ch
    if name == 'RANGE':
        return arg[0] <= ord(ch) <= arg[1]
    if name == 'CATEGORY':
        return _category_has(arg, ch)
    return None


def _set_size(items):
    """Number of characters in a positive set, or None when it is unbounded."""
    total = 0
    for op, arg in items:
        name = _name(op)
        if name == 'LITERAL':
            total += 1
        elif name == 'RANGE':
            total += arg[1] - arg[0] + 1
        else:
            return None
    return total


CATEGORY_REPS = {
    'CATEGORY_DIGIT': '0',
    'CATEGORY_NOT_DIGIT': 'a',
    'CATEGORY_WORD': 'a',
    'CATEGORY_NOT_WORD': '!',
    'CATEGORY_SPACE': ' ',
    'CATEGORY_NOT_SPACE': 'a',
    'CATEGORY_LINEBREAK': '\n',
    'CATEGORY_NOT_LINEBREAK': 'a',
}


def _members(items):
    """Representative characters of a positive set, plus whether that is all of them.

    Taking the characters from the set itself rather than from a global
    preference list matters: a rule keyed on ``[fF]`` has no candidate at all if
    only the preference list is consulted.
    """
    out = []
    exact = True
    for op, arg in items:
        name = _name(op)
        if name == 'LITERAL':
            out.append(chr(arg))
        elif name == 'RANGE':
            low, high = arg
            for code in range(low, min(high, low + 2) + 1):
                out.append(chr(code))
            if high > low + 2:
                exact = False
        elif name == 'CATEGORY':
            rep = CATEGORY_REPS.get(_name(arg))
            if rep is None:
                return None, False
            out.append(rep)
            exact = False
        else:
            return None, False
    return out, exact


def _pick_in(items, info):
    negate = bool(items) and _name(items[0][0]) == 'NEGATE'
    body = items[1:] if negate else items
    if negate:
        info.capped = True
        out = []
        for ch in PREFS:
            hit = False
            for item in body:
                got = _item_has(item, ch)
                if got is None:
                    info.unsupported = True
                    return []
                hit = hit or got
            if not hit:
                out.append(ch)
                if len(out) >= MAX_OPTIONS:
                    break
        return out
    members, exact = _members(body)
    if members is None:
        info.unsupported = True
        return []
    order = {ch: i for i, ch in enumerate(PREFS)}
    members = sorted(set(members), key=lambda ch: (order.get(ch, len(PREFS)), ch))
    if not exact or len(members) > MAX_OPTIONS:
        info.capped = True
    return members[:MAX_OPTIONS]


def _rank(strings, info):
    ranked = sorted({s for s in strings if len(s) <= MAX_LEN},
                    key=lambda s: (len(s), s))
    if len(ranked) > MAX_OPTIONS:
        info.capped = True
        ranked = ranked[:MAX_OPTIONS]
    return ranked


def _item_opts(item, info, depth):
    op, arg = item
    name = _name(op)
    if name == 'LITERAL':
        return [chr(arg)]
    if name == 'NOT_LITERAL':
        info.capped = True
        for ch in PREFS:
            if ord(ch) != arg:
                return [ch]
        return []
    if name == 'ANY':
        info.capped = True
        return ['a']
    if name == 'IN':
        return _pick_in(arg, info)
    if name == 'AT':
        info.anchors.add(_name(arg))
        return ['']
    if name in ('MAX_REPEAT', 'MIN_REPEAT', 'POSSESSIVE_REPEAT'):
        low, high, sub = arg
        base = _opts(sub, info, depth + 1)
        if base is None:
            return None
        if high is _C.MAXREPEAT:
            info.finite = False
            info.capped = True
        elif high > low:
            info.capped = True
        reps = [low] if high == low else [low, low + 1]
        out = set()
        for count in reps:
            for piece in base[:2]:
                out.add(piece * count)
        return _rank(out, info)
    if name == 'SUBPATTERN':
        return _opts(arg[-1], info, depth + 1)
    if name == 'ATOMIC_GROUP':
        return _opts(arg, info, depth + 1)
    if name == 'BRANCH':
        alts = arg[1]
        if len(alts) > MAX_BRANCHES:
            info.capped = True
            alts = alts[:MAX_BRANCHES]
        out = set()
        for alt in alts:
            got = _opts(alt, info, depth + 1)
            if got is None:
                return None
            out.update(got)
        return _rank(out, info)
    if name in ('ASSERT', 'ASSERT_NOT'):
        info.approximate = True
        return ['']
    return None


def _opts(seq, info, depth=0):
    if depth > MAX_DEPTH:
        info.capped = True
        return ['']
    out = ['']
    for item in seq:
        got = _item_opts(item, info, depth)
        if got is None:
            info.unsupported = True
            return None
        merged = set()
        for head in out:
            for tail in got:
                merged.add(head + tail)
        out = _rank(merged, info)
        if not out:
            return []
    return out


def candidates(pattern, flags=0):
    """Return ``(strings, Info)`` for one pattern, shortest string first."""
    info = Info()
    try:
        tree = _P.parse(pattern, flags)
    except (re.error, RecursionError, ValueError):
        info.unsupported = True
        return [], info
    try:
        out = _opts(tree, info)
    except RecursionError:
        info.unsupported = True
        return [], info
    if out is None:
        return [], info
    return out, info


def rule_candidates(lexer, state, index):
    """Candidate strings for the rule at ``(state, index)`` of a pygments lexer."""
    pattern = lexer._tokens[state][index][0].__self__
    return candidates(pattern.pattern, pattern.flags)


def _min_len(seq, depth=0):
    """Characters a subpattern must consume. None when it cannot be determined."""
    if depth > MAX_DEPTH:
        return None
    total = 0
    for op, arg in seq:
        name = _name(op)
        if name in ('LITERAL', 'NOT_LITERAL', 'ANY', 'IN', 'RANGE'):
            total += 1
        elif name in ('AT', 'ASSERT', 'ASSERT_NOT'):
            continue
        elif name in ('MAX_REPEAT', 'MIN_REPEAT', 'POSSESSIVE_REPEAT'):
            low, _high, sub = arg
            inner = _min_len(sub, depth + 1)
            if inner is None:
                return None
            total += low * inner
        elif name == 'SUBPATTERN':
            inner = _min_len(arg[-1], depth + 1)
            if inner is None:
                return None
            total += inner
        elif name == 'ATOMIC_GROUP':
            inner = _min_len(arg, depth + 1)
            if inner is None:
                return None
            total += inner
        elif name == 'BRANCH':
            best = None
            for alt in arg[1]:
                inner = _min_len(alt, depth + 1)
                if inner is None:
                    return None
                best = inner if best is None else min(best, inner)
            total += 0 if best is None else best
        else:
            return None
    return total


def min_length(pattern, flags=0):
    """Lower bound on the characters a pattern consumes when it matches.

    Used for the corpus floor: a rule whose pattern cannot match the empty
    string has to consume at least one character somewhere in the corpus, and
    within one input the consumed ranges of successive matches are disjoint.
    Returns 0 when the bound cannot be established, which keeps the floor valid.
    """
    try:
        tree = _P.parse(pattern, flags)
    except (re.error, RecursionError, ValueError):
        return 0
    try:
        out = _min_len(tree)
    except RecursionError:
        return 0
    return 0 if out is None else out


def rule_min_length(lexer, state, index):
    pattern = lexer._tokens[state][index][0].__self__
    return min_length(pattern.pattern, pattern.flags)
