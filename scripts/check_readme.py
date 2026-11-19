"""Check that every number in README.md still matches docs/metrics.json.

Run after any re-run of the demo. It parses the per lexer table and the headline
sentences out of the README and compares them with the measured data, so a stale
number in the prose fails loudly instead of sitting there.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def number(text):
    return int(text.replace(',', '').strip())


def main():
    with open('docs/metrics.json', encoding='utf-8') as handle:
        data = json.load(handle)
    readme = open('README.md', encoding='utf-8').read()
    records = {r['lexer']: r for r in data['lexers']}
    totals = data['totals']
    problems = []

    rows = re.findall(r'^\| ([a-z]+) \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \| '
                      r'([\d,]+) \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \|$',
                      readme, flags=re.M)
    if len(rows) != len(records):
        problems.append('table has %d rows, metrics has %d lexers'
                        % (len(rows), len(records)))
    for row in rows:
        name = row[0]
        record = records.get(name)
        if record is None:
            problems.append('table row for unknown lexer %s' % name)
            continue
        expected = [record['rules_universe'], record['real_corpus']['files'],
                    record['real_corpus']['bytes'], record['real_corpus']['covered'],
                    record['smallest']['bytes'], record['rules_witnessed'],
                    record['proved_dead']]
        got = [number(cell) for cell in row[1:]]
        if got != expected:
            problems.append('%s row says %s, metrics say %s' % (name, got, expected))

    headline = [
        (totals['real_corpus_files'], 'files'),
        (totals['real_corpus_bytes'], 'bytes of real files'),
        (totals['rules_real_corpus'], 'rules reached by real files'),
        (totals['rules_witnessed'], 'rules witnessed'),
        (totals['rules_universe'], 'reachable rules'),
        (totals['corpus_bytes'], 'corpus bytes'),
        (totals['rules_random_corpus'], 'rules from random text'),
        (totals['floor_bytes'], 'floor bytes'),
        (totals['proved_dead'], 'proved unreachable'),
        (totals['rules_only_synthesis_reaches'], 'rules only synthesis reaches'),
        (totals['equivalence_bytes_checked'], 'bytes checked for equivalence'),
        (totals['fewest_inputs'], 'fewest inputs'),
        (totals['fewest_inputs_bytes'], 'fewest inputs bytes'),
    ]
    for value, label in headline:
        if '{:,}'.format(value) not in readme and str(value) not in readme:
            problems.append('README never mentions %s (%d)' % (label, value))

    for problem in problems:
        print('MISMATCH:', problem)
    print('%d checks, %d problems' % (len(rows) * 7 + len(headline), len(problems)))
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
