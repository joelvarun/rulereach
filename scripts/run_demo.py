"""Run rulereach over every lexer in the panel and write docs/metrics.json.

Usage:
    python scripts/run_demo.py            # full panel
    python scripts/run_demo.py python css # just these lexers
"""

import json
import os
import platform
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygments
from pygments.lexer import ExtendedRegexLexer, RegexLexer
from pygments.lexers import get_lexer_by_name

from rulereach import baseline, corpus, driver, explore, shadow

PANEL = ['python', 'c', 'css', 'javascript', 'typescript', 'html', 'xml',
         'ini', 'toml', 'markdown', 'powershell', 'batch']

INDEX_EXTENSIONS = ['.py', '.c', '.h', '.css', '.js', '.ts', '.html', '.htm',
                    '.xml', '.ini', '.inf', '.cfg', '.toml', '.md', '.ps1',
                    '.psm1', '.bat', '.cmd', '.json', '.yaml', '.rst']


def usable(lexer):
    """Plain RegexLexer lexers only: the extended kind needs a lexer context."""
    return (isinstance(lexer, RegexLexer)
            and not isinstance(lexer, ExtendedRegexLexer)
            and hasattr(lexer, '_tokens'))


def unreached_report(lexer, result):
    """Why each rule with no witness has none, with a few concrete examples."""
    buckets = {'exhaustive_candidates': 0, 'approximate_pattern': 0, 'other': 0}
    examples = []
    for rule in result.unreached:
        info = result.info.get(rule, {})
        if info.get('exhaustive'):
            kind = 'exhaustive_candidates'
        elif info.get('approximate') or info.get('unsupported'):
            kind = 'approximate_pattern'
        else:
            kind = 'other'
        buckets[kind] += 1
        if len(examples) < 6:
            examples.append({
                'state': rule[0],
                'index': rule[1],
                'pattern': driver.rule_pattern(lexer, *rule).pattern[:120],
                'kind': kind,
            })
    return buckets, examples


def thin(points, keep=60):
    if len(points) <= keep:
        return points
    step = len(points) / float(keep)
    return [points[min(len(points) - 1, int(i * step))] for i in range(keep)]


def run_one(name, index):
    lexer = get_lexer_by_name(name)
    if not usable(lexer):
        return None
    started = time.time()
    universe = driver.universe(lexer)
    result = explore.explore(lexer)
    search_time = time.time() - started

    smallest, small_info = corpus.build(lexer, result, objective='bytes')
    fewest, few_info = corpus.build(lexer, result, objective='inputs')

    paths = baseline.find_files(lexer, index=index)
    real = baseline.corpus_curve(lexer, paths, universe)
    random_hit = baseline.random_baseline(lexer, universe, small_info['bytes'])

    checked = 0
    for path in paths[:20]:
        text = baseline.read_text(path, limit=60000)
        if text:
            driver.assert_equivalent(lexer, text)
            checked += len(text)

    buckets, examples = unreached_report(lexer, result)
    census = shadow.census(lexer, result)
    proved_dead = [row for row in census if row['dead'] and row.get('proof')]
    only_synth = sorted(set(result.witness) - real['covered_rules'])
    record = {
        'lexer': name,
        'states_declared': len(lexer._tokens),
        'states_reachable': len(driver.reachable_states(lexer)),
        'rules_declared': len(driver.rule_keys(lexer)),
        'rules_universe': len(universe),
        'rules_witnessed': len(result.witness),
        'search': result.summary(),
        'search_seconds': round(search_time, 2),
        'smallest': small_info,
        'fewest': few_info,
        'real_corpus': {k: real[k] for k in ('files', 'bytes', 'covered')},
        'real_corpus_curve': thin(real['points']),
        'random_corpus': random_hit,
        'unreached': buckets,
        'unreached_examples': examples,
        'proved_dead': len(proved_dead),
        'proved_dead_detail': proved_dead[:4],
        'rules_only_synthesis_reaches': len(only_synth),
        'equivalence_bytes_checked': checked,
        'seconds': round(time.time() - started, 2),
    }
    return record, smallest, fewest


def main(argv):
    names = argv[1:] or PANEL
    index = baseline.build_index(INDEX_EXTENSIONS)
    records = []
    corpora = {}
    for name in names:
        got = run_one(name, index)
        if got is None:
            print('%-12s skipped (not a plain RegexLexer)' % name)
            continue
        record, smallest, fewest = got
        records.append(record)
        corpora[name] = {'smallest': smallest, 'fewest': fewest}
        print('%-12s universe %4d  witnessed %4d  corpus %5db/%3d  real %8db/%4d  random %4d  %5.1fs' % (
            name, record['rules_universe'], record['rules_witnessed'],
            record['smallest']['bytes'], record['smallest']['inputs'],
            record['real_corpus']['bytes'], record['real_corpus']['covered'],
            record['random_corpus']['covered'], record['seconds']))

    totals = {
        'lexers': len(records),
        'rules_universe': sum(r['rules_universe'] for r in records),
        'rules_witnessed': sum(r['rules_witnessed'] for r in records),
        'rules_real_corpus': sum(r['real_corpus']['covered'] for r in records),
        'rules_random_corpus': sum(r['random_corpus']['covered'] for r in records),
        'corpus_bytes': sum(r['smallest']['bytes'] for r in records),
        'corpus_inputs': sum(r['smallest']['inputs'] for r in records),
        'fewest_inputs': sum(r['fewest']['inputs'] for r in records),
        'fewest_inputs_bytes': sum(r['fewest']['bytes'] for r in records),
        'floor_bytes': sum(r['smallest']['floor_bytes'] for r in records),
        'unshared_bytes': sum(r['smallest']['unshared_bytes'] for r in records),
        'real_corpus_bytes': sum(r['real_corpus']['bytes'] for r in records),
        'real_corpus_files': sum(r['real_corpus']['files'] for r in records),
        'equivalence_bytes_checked': sum(r['equivalence_bytes_checked'] for r in records),
        'rules_only_synthesis_reaches': sum(r['rules_only_synthesis_reaches'] for r in records),
        'rules_declared': sum(r['rules_declared'] for r in records),
        'proved_dead': sum(r['proved_dead'] for r in records),
    }
    out = {
        'generated': time.strftime('%Y-%m-%d %H:%M:%S'),
        'environment': {
            'python': sys.version.split()[0],
            'pygments': pygments.__version__,
            'platform': platform.platform(),
        },
        'totals': totals,
        'lexers': records,
    }
    os.makedirs('docs', exist_ok=True)
    with open('docs/metrics.json', 'w', encoding='utf-8') as handle:
        json.dump(out, handle, indent=1)
    with open('docs/corpora.json', 'w', encoding='utf-8') as handle:
        json.dump(corpora, handle, indent=1)
    print()
    print('totals: %d lexers, %d of %d rules witnessed in %d bytes (%d inputs)' % (
        totals['lexers'], totals['rules_witnessed'], totals['rules_universe'],
        totals['corpus_bytes'], totals['corpus_inputs']))
    print('        real local files: %d bytes over %d files reach %d rules' % (
        totals['real_corpus_bytes'], totals['real_corpus_files'],
        totals['rules_real_corpus']))
    print('        floor for any corpus: %d bytes' % totals['floor_bytes'])
    print('        rules proved unreachable: %d' % totals['proved_dead'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
