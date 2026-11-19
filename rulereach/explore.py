"""Shortest witness search over a lexer's own state space.

The search is a Dijkstra over nodes of the form ``(state stack, previous
character)``, which is what a pygments rule can actually see: the stack decides
which rule list is active, and the character to the left decides whether an
anchor or a word boundary can hold. Edges are produced by appending a candidate
string and asking the real lexer what happened, so an edge is only ever added
once the implementation has demonstrated it.

The result is, for every rule, the shortest text found that makes that rule fire,
plus the transition graph the corpus builder then shares work across.
"""

import heapq

from . import candidates as _candidates
from . import driver

START_STACK = ('root',)

#: Single characters appended at every node regardless of the active rules.
#: Lexers often leave a state on a character no rule in that state mentions.
FILLER = (' ', '\n', 'a', '0', '_', '"', "'", '#', '=', '(', ')', '[', ']',
          '{', '}', '<', '>', ';', ':', ',', '.', '-', '/', '*', '!', '$',
          '%', '&', '|', chr(92), chr(9))


class Result:
    """Everything the search learned about one lexer."""

    def __init__(self, lexer):
        self.lexer = lexer
        self.rules = driver.universe(lexer)
        self.rule_set = set(self.rules)
        self.dist = {}
        self.prefix = {}
        self.edges = []
        self.witness = {}
        self.complete = False
        self.nodes_expanded = 0
        self.probes = 0
        self.info = {}

    @property
    def reached(self):
        return set(self.witness)

    @property
    def unreached(self):
        return [r for r in self.rules if r not in self.witness]

    def witness_text(self, rule):
        return self.witness[rule][1]

    def summary(self):
        exhaustive_misses = [r for r in self.unreached
                             if self.info.get(r, {}).get('exhaustive')]
        return {
            'rules': len(self.rules),
            'reached': len(self.witness),
            'unreached': len(self.unreached),
            'unreached_with_exhaustive_candidates': len(exhaustive_misses),
            'states': len({s for s, _ in self.rules}),
            'states_entered': len({node[0][-1] for node in self.dist}),
            'nodes': len(self.dist),
            'nodes_expanded': self.nodes_expanded,
            'edges': len(self.edges),
            'probes': self.probes,
            'search_complete': self.complete,
            'witness_bytes_total': sum(len(t) for _, t in self.witness.values()),
            'witness_bytes_max': max([len(t) for _, t in self.witness.values()] or [0]),
        }


def _candidate_table(lexer, result):
    """Candidate strings per state, deduplicated, shortest first."""
    table = {}
    for state in lexer._tokens:
        pool = []
        for index in range(len(lexer._tokens[state])):
            strings, info = _candidates.rule_candidates(lexer, state, index)
            result.info[(state, index)] = info.as_dict()
            pool.extend(strings)
        pool.extend(FILLER)
        seen = []
        marker = set()
        for text in sorted({p for p in pool if p}, key=lambda s: (len(s), s)):
            if text not in marker:
                marker.add(text)
                seen.append(text)
        table[state] = seen
    return table


def explore(lexer, max_nodes=2500, per_stack=4, per_top=30, max_depth=4,
            max_prefix=48, max_probes=8000000):
    """Dijkstra over the lexer's state space. Returns a :class:`Result`.

    Every probe lexes the whole candidate text from position zero with the real
    lexer, so the rules recorded for an edge are observed facts about the
    implementation rather than a prediction. The ``(stack, previous character)``
    node abstraction therefore only affects how much of the state space the
    search reaches, never whether a reported witness is real.

    ``per_stack`` bounds how many distinct previous characters are explored for
    the same state stack, which spends the node budget on new states instead of
    on many spellings of one state.
    """
    result = Result(lexer)
    table = _candidate_table(lexer, result)
    start = (START_STACK, None)
    result.dist[start] = 0
    result.prefix[start] = ''
    queue = [(0, 0, start)]
    order = 0
    stack_seen = {START_STACK: 1}
    top_seen = {START_STACK[-1]: 1}
    while queue:
        cost, _, node = heapq.heappop(queue)
        if cost > result.dist.get(node, -1):
            continue
        if result.nodes_expanded >= max_nodes:
            break
        result.nodes_expanded += 1
        stack, prev = node
        base = result.prefix[node]
        if len(base) >= max_prefix:
            continue
        for text in table.get(stack[-1], ()):
            result.probes += 1
            if result.probes > max_probes:
                break
            full = base + text
            if len(full) > max_prefix:
                continue
            tokens, fired, final = driver.run(lexer, full)
            if not fired:
                continue
            final = driver.pending_stack(fired)
            head_node = (final, text[-1] if text else prev)
            rules = frozenset((state, index) for state, index, _, _, _ in fired)
            result.edges.append((node, text, head_node, len(text), rules))
            total = cost + len(text)
            for rule in rules:
                known = result.witness.get(rule)
                if known is None or len(full) < known[0]:
                    result.witness[rule] = (len(full), full)
            if total >= result.dist.get(head_node, float('inf')):
                continue
            if head_node not in result.dist:
                if len(final) > max_depth:
                    continue
                if stack_seen.get(final, 0) >= per_stack:
                    continue
                if top_seen.get(final[-1], 0) >= per_top:
                    continue
                top_seen[final[-1]] = top_seen.get(final[-1], 0) + 1
                stack_seen[final] = stack_seen.get(final, 0) + 1
            result.dist[head_node] = total
            result.prefix[head_node] = full
            order += 1
            heapq.heappush(queue, (total, order, head_node))
    result.complete = not queue
    return result
