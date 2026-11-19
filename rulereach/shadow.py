"""Why a rule never fires: which earlier rule takes its input instead.

A rule in a first-match list is dead when every string its pattern accepts is
taken by a rule above it. This module answers that question with evidence: it
replays each candidate string at the states the search actually reached and
reports which rule won. For a pattern whose language is finite and was
enumerated in full, "every candidate lost" is a proof rather than a sample.
"""

from . import candidates as _candidates
from . import driver


def contexts(result, state, limit=8):
    """Cheapest explored nodes whose active state is ``state``."""
    nodes = [node for node in result.dist if node[0][-1] == state]
    nodes.sort(key=lambda node: (result.dist[node], len(result.prefix[node])))
    return nodes[:limit]


def explain(lexer, result, rule, limit=8):
    """Report the rule that wins each candidate string of ``rule``."""
    state, index = rule
    strings, info = _candidates.rule_candidates(lexer, state, index)
    nodes = contexts(result, state, limit=limit)
    losses = []
    winners = {}
    for text in strings:
        for node in nodes:
            prefix = result.prefix[node]
            events = driver.run(lexer, prefix + text)[1]
            winner = None
            for fired_state, fired_index, start, _end, _stack in events:
                if start >= len(prefix):
                    winner = (fired_state, fired_index)
                    break
            if winner == rule:
                return {'rule': rule, 'dead': False, 'witness': prefix + text}
            if winner is not None:
                winners[winner] = winners.get(winner, 0) + 1
                losses.append({'candidate': text, 'taken_by': winner})
    ranked = sorted(winners.items(), key=lambda item: -item[1])
    return {
        'rule': rule,
        'dead': True,
        'proof': bool(info.exhaustive),
        'states_tried': len(nodes),
        'candidates_tried': len(strings),
        'taken_by': [{'rule': list(key), 'count': count} for key, count in ranked[:3]],
        'pattern': driver.rule_pattern(lexer, state, index).pattern[:160],
        'examples': losses[:4],
    }


def census(lexer, result, limit=8):
    """Explain every rule the search could not witness."""
    return [explain(lexer, result, rule, limit=limit) for rule in result.unreached]
