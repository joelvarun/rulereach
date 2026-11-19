"""Smallest useful example: witness every rule of one lexer and print the corpus.

    python examples/quickstart.py css
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pygments.lexers import get_lexer_by_name

from rulereach import corpus, driver, explore, shadow


def main(argv):
    name = argv[1] if len(argv) > 1 else 'css'
    lexer = get_lexer_by_name(name)
    universe = driver.universe(lexer)
    print('%s lexer: %d rules declared, %d of them in reachable states'
          % (name, len(driver.rule_keys(lexer)), len(universe)))

    result = explore.explore(lexer)
    summary = result.summary()
    print('search: %d nodes, %d probes, %d of %d reachable states entered, %d rules witnessed'
          % (summary['nodes'], summary['probes'], summary['states_entered'],
             len(driver.reachable_states(lexer)), len(result.witness)))

    texts, info = corpus.build(lexer, result, objective='inputs')
    print('corpus: %d inputs, %d bytes, floor for any corpus is %d bytes'
          % (info['inputs'], info['bytes'], info['floor_bytes']))
    print()
    for text in sorted(texts, key=len, reverse=True)[:5]:
        print('  %-3d bytes  %r' % (len(text), text[:70]))
    print()

    covered = set()
    for text in texts:
        covered |= driver.covered(lexer, text)
    print('re-lexed the corpus: %d of %d rules fired' % (len(covered & set(universe)),
                                                        len(result.witness)))
    for row in shadow.census(lexer, result):
        if row['dead'] and row.get('proof'):
            print('rule %s cannot fire: pattern %s is taken by rule %s'
                  % (row['rule'], row['pattern'], row['taken_by'][0]['rule']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
