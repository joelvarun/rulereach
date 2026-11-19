"""Turning witnesses into a corpus: greedy chains, then an exact minimum cover.

Two separate things happen here and only one of them is a heuristic.

The chains are built greedily: walk the transition graph and keep appending the
edge that covers the most still-uncovered rules per byte. That produces long
inputs which share one prefix across many rules, and is where most of the saving
against one-input-per-rule comes from.

Choosing which of the resulting inputs to ship is then solved exactly. Every
candidate input is a real string whose coverage was measured by running the
lexer on it, so picking a minimum-byte subset that still covers every rule is a
weighted set cover over observed data, and HiGHS solves it to a proven zero gap.
Two bounds are reported next to the answer: the LP relaxation of that cover, and
an unconditional floor that holds for any corpus whatsoever.
"""

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp

from . import candidates as _candidates
from . import driver
from . import explore as _explore


def floor_bytes(lexer, rules):
    """Bytes any corpus must contain to fire every rule in ``rules``.

    A rule whose pattern cannot match the empty string consumes at least one
    character when it fires, and inside a single input the consumed ranges of
    successive matches are disjoint, so the floor is the sum of those minimum
    lengths. Patterns whose minimum cannot be established contribute zero, which
    keeps the bound valid rather than optimistic.
    """
    return sum(_candidates.rule_min_length(lexer, state, index)
               for state, index in rules)


def chains(lexer, result, targets, max_len=4000, separators=('', '\n'),
           max_chains=12):
    """Long inputs built by concatenating witnesses, keeping only what verifies.

    A witness was found starting from a clean ``root`` state, so appending it to
    an input that has already moved the lexer elsewhere does not have to work.
    Each append is therefore lexed and kept only if the rule it was meant to
    cover actually fires in the combined text, which makes the resulting inputs
    correct by construction rather than by argument.
    """
    target_set = set(targets)
    remaining = set(targets)
    out = []
    while remaining and len(out) < max_chains:
        text = ''
        covered = set()
        order = sorted(remaining, key=lambda rule: (len(result.witness[rule][1]), rule))
        for rule in order:
            if rule in covered:
                continue
            witness = result.witness[rule][1]
            for separator in separators:
                candidate = text + separator + witness
                if len(candidate) > max_len:
                    break
                got = driver.covered(lexer, candidate) & target_set
                if rule in got:
                    text, covered = candidate, got
                    break
        if not text or not (covered & remaining):
            break
        out.append(text)
        remaining -= covered
    return out


def walk_chains(lexer, result, targets, max_len=4000, max_chains=12):
    """Long inputs taken from the transition graph itself.

    At each step the edge covering the most still-wanted rules per byte is
    appended. Only edges whose head was expanded during the search are followed,
    so the walk stays inside the part of the graph that has outgoing edges
    instead of dead-ending after two steps. The finished text is lexed and its
    real coverage is what counts.
    """
    by_tail = {}
    for tail, text, head, cost, rules in result.edges:
        by_tail.setdefault(tail, []).append((text, head, cost, rules))
    start = (_explore.START_STACK, None)
    target_set = set(targets)
    remaining = set(targets)
    out = []
    while remaining and len(out) < max_chains:
        node = start
        text = ''
        guess = set(remaining)
        while len(text) < max_len:
            best = None
            for cand, head, cost, rules in by_tail.get(node, ()):
                if head not in by_tail:
                    continue
                gain = len(rules & guess)
                if not gain:
                    continue
                score = gain / (cost + 0.5)
                if best is None or score > best[0]:
                    best = (score, cand, head, rules)
            if best is None:
                break
            text += best[1]
            node = best[2]
            guess -= best[3]
        if not text:
            break
        got = driver.covered(lexer, text) & target_set
        if not (got & remaining):
            break
        out.append(text)
        remaining -= got
    return out


def build_pool(lexer, result, targets, **kwargs):
    """Candidate inputs (chains first, then per-rule witnesses) and what they cover."""
    items = []
    seen = set()
    rest = {k: v for k, v in kwargs.items() if k != 'max_len'}
    for builder in (walk_chains, chains):
        for cap in (120, 600, 4000):
            for text in builder(lexer, result, targets, max_len=cap, **rest):
                if text not in seen:
                    seen.add(text)
                    items.append(text)
    for rule in sorted(targets):
        text = result.witness[rule][1]
        if text not in seen:
            seen.add(text)
            items.append(text)
    target_set = set(targets)
    coverage = [driver.covered(lexer, text) & target_set for text in items]
    return items, coverage


def exact_cover(items, coverage, targets, objective='bytes'):
    """Minimum subset of ``items`` covering every rule in ``targets``.

    ``objective='bytes'`` minimises total corpus size. ``objective='inputs'``
    minimises how many separate inputs are needed and then, among the solutions
    of that size, the smallest total bytes. Both are solved to a proven zero
    gap by HiGHS. Returns ``(chosen indices, info)``.
    """
    targets = sorted(targets)
    n = len(items)
    cost = np.array([float(len(text)) for text in items])
    rows = np.zeros((len(targets), n))
    for row, rule in enumerate(targets):
        for col in range(n):
            if rule in coverage[col]:
                rows[row, col] = 1.0
    missing = [targets[row] for row in range(len(targets)) if rows[row].sum() == 0]
    if missing:
        raise ValueError('no candidate input covers %d rule(s)' % len(missing))
    constraint = LinearConstraint(rows, lb=1.0, ub=np.inf)
    constraints = [constraint]
    weights = cost
    if objective == 'inputs':
        count = milp(c=np.ones(n), constraints=constraints,
                     integrality=np.ones(n), bounds=Bounds(0, 1))
        if not count.success:
            raise RuntimeError('cover solve failed: %s' % count.message)
        limit = int(round(count.fun))
        constraints = constraints + [LinearConstraint(np.ones((1, n)), lb=0,
                                                      ub=float(limit))]
    res = milp(c=weights, constraints=constraints, integrality=np.ones(n),
               bounds=Bounds(0, 1))
    if not res.success:
        raise RuntimeError('cover solve failed: %s' % res.message)
    chosen = [j for j in range(n) if res.x[j] > 0.5]
    relaxed = linprog(c=cost, A_ub=-rows, b_ub=-np.ones(len(targets)),
                      bounds=(0, 1))
    info = {
        'pool': n,
        'milp_bytes': float(res.fun),
        'milp_gap': float(getattr(res, 'mip_gap', 0.0) or 0.0),
        'lp_relaxation_bytes': float(relaxed.fun) if relaxed.success else None,
    }
    return chosen, info


def build(lexer, result, targets=None, objective='bytes', **kwargs):
    """End to end: pool, exact cover, verification, bounds."""
    if targets is None:
        targets = sorted(result.witness)
    targets = sorted(set(targets))
    items, coverage = build_pool(lexer, result, targets, **kwargs)
    chosen, info = exact_cover(items, coverage, targets, objective=objective)
    corpus = [items[j] for j in chosen]
    verified = set()
    for text in corpus:
        verified |= driver.covered(lexer, text)
    for text in corpus:
        driver.assert_equivalent(lexer, text)
    out = {
        'inputs': len(corpus),
        'bytes': sum(len(text) for text in corpus),
        'covered': len(verified & set(targets)),
        'targets': len(targets),
        'verified_complete': verified >= set(targets),
        'unshared_bytes': sum(len(result.witness[rule][1]) for rule in targets),
        'floor_bytes': floor_bytes(lexer, targets),
    }
    out.update(info)
    return corpus, out
