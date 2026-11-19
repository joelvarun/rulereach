"""Draw docs/before_after.png from docs/metrics.json.

Left panel: how much of each lexer's reachable rule set three corpora reach.
Right panel: coverage against corpus size for the Python lexer, log scale,
which is where the three orders of magnitude show up.
"""

import json
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

SURFACE = '#fcfcfb'
INK = '#0b0b0b'
INK_SOFT = '#52514e'
GRID = '#d9d8d4'
REAL = '#2a78d6'
SYNTH = '#eb6834'
RANDOM = '#1baf7a'


def load(path='docs/metrics.json'):
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def panel_coverage(ax, records):
    records = sorted(records, key=lambda r: r['rules_universe'])
    names = [r['lexer'] for r in records]
    span = range(len(records))
    height = 0.26

    def pct(value, total):
        return 100.0 * value / total if total else 0.0

    real = [pct(r['real_corpus']['covered'], r['rules_universe']) for r in records]
    rand = [pct(r['random_corpus']['covered'], r['rules_universe']) for r in records]
    synth = [pct(r['rules_witnessed'], r['rules_universe']) for r in records]

    ax.barh([i + height for i in span], synth, height=height, color=SYNTH,
            label='rulereach corpus', zorder=3)
    ax.barh(list(span), real, height=height, color=REAL,
            label='real files on this machine', zorder=3)
    ax.barh([i - height for i in span], rand, height=height, color=RANDOM,
            label='random text, same size as rulereach', zorder=3)

    for i, (a, b, c) in enumerate(zip(synth, real, rand)):
        ax.text(a + 1.2, i + height, '%.0f%%' % a, va='center', fontsize=8, color=INK)
        ax.text(b + 1.2, i, '%.0f%%' % b, va='center', fontsize=8, color=INK_SOFT)
        ax.text(c + 1.2, i - height, '%.0f%%' % c, va='center', fontsize=8, color=INK_SOFT)

    ax.set_yticks(list(span))
    ax.set_yticklabels(names, fontsize=9, color=INK)
    ax.set_xlim(0, 118)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel('reachable lexer rules exercised (percent)', fontsize=9, color=INK_SOFT)
    ax.set_title('Rule coverage per lexer', fontsize=11, color=INK, loc='left')
    ax.xaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ('top', 'right', 'left'):
        ax.spines[side].set_visible(False)
    ax.spines['bottom'].set_color(GRID)
    ax.tick_params(colors=INK_SOFT, length=0)
    ax.legend(fontsize=8, frameon=False, loc='upper center',
              bbox_to_anchor=(0.5, -0.10), ncol=3)


def panel_curve(ax, record):
    points = [p for p in record['real_corpus_curve'] if p[0] >= 200]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    floor = record['smallest']['floor_bytes']
    universe = record['rules_universe']

    ax.plot(xs, ys, color=REAL, linewidth=2.0, zorder=3,
            label='real %s files, cumulative' % record['lexer'])
    ax.plot([xs[-1]], [ys[-1]], marker='o', markersize=8, color=REAL,
            markeredgecolor=SURFACE, markeredgewidth=2, zorder=4)
    ax.annotate('%d files, %.1f MB\n%d of %d rules'
                % (record['real_corpus']['files'], xs[-1] / 1e6, ys[-1], universe),
                xy=(xs[-1], ys[-1]), xytext=(-8, 12), textcoords='offset points',
                fontsize=8, color=REAL, ha='right')

    synth_x = record['smallest']['bytes']
    synth_y = record['rules_witnessed']
    ax.plot([synth_x], [synth_y], marker='o', markersize=10, color=SYNTH,
            markeredgecolor=SURFACE, markeredgewidth=2, zorder=5,
            label='rulereach corpus')
    ax.annotate('%d bytes\n%d of %d rules' % (synth_x, synth_y, universe),
                xy=(synth_x, synth_y), xytext=(10, -6), textcoords='offset points',
                fontsize=8, color=INK)

    rand_x = record['random_corpus']['bytes']
    rand_y = record['random_corpus']['covered']
    ax.plot([rand_x], [rand_y], marker='o', markersize=8, color=RANDOM,
            markeredgecolor=SURFACE, markeredgewidth=2, zorder=5,
            label='random text, same size')
    ax.annotate('random text, %d rules' % rand_y, xy=(rand_x, rand_y),
                xytext=(14, -14), textcoords='offset points', fontsize=8,
                color=INK_SOFT)

    ax.axvline(floor, color=INK_SOFT, linewidth=1.0, linestyle=(0, (4, 3)), zorder=2)
    ax.annotate('floor for any\ncorpus: %d bytes' % floor,
                xy=(floor, universe * 0.45), xytext=(9, 0),
                textcoords='offset points', fontsize=8, color=INK_SOFT, ha='left')

    ax.set_xscale('log')
    ax.set_xlim(min(floor, min(xs)) * 0.35, max(xs) * 3.0)
    ax.set_ylim(0, universe * 1.12)
    ax.set_xlabel('corpus size in bytes (log scale)', fontsize=9, color=INK_SOFT)
    ax.set_ylabel('rules exercised', fontsize=9, color=INK_SOFT)
    ax.set_title('%s lexer: coverage against corpus size' % record['lexer'],
                 fontsize=11, color=INK, loc='left')
    ax.grid(True, color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    for side in ('bottom', 'left'):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_SOFT, length=0)
    ax.legend(fontsize=8, frameon=False, loc='lower right')


def main(argv):
    data = load(argv[1] if len(argv) > 1 else 'docs/metrics.json')
    records = data['lexers']
    headline = max(records, key=lambda r: r['rules_universe'])
    fig, axes = plt.subplots(1, 2, figsize=(12.6, 5.8), facecolor=SURFACE)
    for ax in axes:
        ax.set_facecolor(SURFACE)
    panel_coverage(axes[0], records)
    panel_curve(axes[1], headline)
    totals = data['totals']
    fig.suptitle(
        'Exercising a syntax lexer: %s bytes of real files reach %d of %d rules, '
        '%s synthesized bytes reach %d'
        % ('{:,}'.format(totals['real_corpus_bytes']), totals['rules_real_corpus'],
           totals['rules_universe'], '{:,}'.format(totals['corpus_bytes']),
           totals['rules_witnessed']),
        fontsize=12, color=INK, y=0.985)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    os.makedirs('docs', exist_ok=True)
    fig.savefig('docs/before_after.png', dpi=150, facecolor=SURFACE)
    print('wrote docs/before_after.png')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
