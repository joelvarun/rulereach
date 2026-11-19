"""Tests. The important ones check the clever paths against brute force."""

import itertools
import os
import sys

import pytest
from pygments.lexers import get_lexer_by_name

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rulereach import baseline, candidates, corpus, driver, explore

SMALL = 'ini'
PANEL = ['ini', 'toml', 'css', 'python']


def lexer(name):
    return get_lexer_by_name(name)


def test_driver_matches_pygments_on_real_files():
    index = baseline.build_index(['.py', '.h'])
    for name, ext in (('python', '.py'), ('c', '.h')):
        lex = lexer(name)
        checked = 0
        for path in index[ext][:6]:
            text = baseline.read_text(path, limit=40000)
            if text:
                driver.assert_equivalent(lex, text)
                checked += len(text)
        assert checked > 10000


def test_pending_stack_ignores_the_end_of_input_unwind():
    lex = lexer('python')
    _tokens, fired, final = driver.run(lex, 'def ')
    assert final == ('root',)
    assert driver.pending_stack(fired) == ('root', 'funcname')


def test_reachable_states_cover_everything_that_fires():
    for name in PANEL:
        lex = lexer(name)
        result = explore.explore(lex)
        assert set(result.witness) <= set(driver.universe(lex))


def test_candidates_match_their_own_pattern():
    for name in PANEL:
        lex = lexer(name)
        for state, index in driver.universe(lex):
            strings, info = candidates.rule_candidates(lex, state, index)
            if info.approximate or info.unsupported or info.anchors:
                continue
            pattern = driver.rule_pattern(lex, state, index)
            for text in strings:
                assert pattern.match(text) is not None, (name, state, index, text)


def test_min_length_never_exceeds_a_real_match():
    for name in PANEL:
        lex = lexer(name)
        for state, index in driver.universe(lex):
            pattern = driver.rule_pattern(lex, state, index)
            bound = candidates.rule_min_length(lex, state, index)
            strings, _info = candidates.rule_candidates(lex, state, index)
            for text in strings:
                match = pattern.match(text)
                if match is not None:
                    assert match.end() - match.start() >= bound


def test_every_witness_fires_its_rule():
    for name in PANEL:
        lex = lexer(name)
        result = explore.explore(lex)
        for rule, (_cost, text) in result.witness.items():
            assert rule in driver.covered(lex, text), (name, rule, text)


def test_corpus_is_complete_and_verified():
    for name in PANEL:
        lex = lexer(name)
        result = explore.explore(lex)
        texts, info = corpus.build(lex, result)
        assert info['verified_complete']
        assert info['covered'] == info['targets']
        assert info['bytes'] == sum(len(text) for text in texts)
        assert info['bytes'] >= info['floor_bytes']
        assert info['milp_gap'] == pytest.approx(0.0, abs=1e-6)


def test_exact_cover_matches_brute_force():
    lex = lexer(SMALL)
    result = explore.explore(lex)
    targets = sorted(result.witness)
    items, coverage = corpus.build_pool(lex, result, targets)
    assert len(items) <= 20, 'brute force needs a small pool'
    best = None
    for size in range(1, len(items) + 1):
        for pick in itertools.combinations(range(len(items)), size):
            hit = set()
            for index in pick:
                hit |= coverage[index]
            if hit >= set(targets):
                total = sum(len(items[index]) for index in pick)
                if best is None or total < best:
                    best = total
    chosen, info = corpus.exact_cover(items, coverage, targets)
    assert info['milp_bytes'] == pytest.approx(best)


def test_witnesses_are_not_beaten_by_brute_force():
    """No string up to three characters fires a rule sooner than our witness."""
    lex = lexer(SMALL)
    result = explore.explore(lex)
    alphabet = baseline.alphabet(lex)[:26]
    shortest = {}
    for size in (1, 2, 3):
        for combo in itertools.product(alphabet, repeat=size):
            text = ''.join(combo)
            for rule in driver.covered(lex, text):
                if rule not in shortest:
                    shortest[rule] = size
    for rule, size in shortest.items():
        assert rule in result.witness, (rule, size)
        assert len(result.witness[rule][1]) <= size, (rule, result.witness[rule], size)
