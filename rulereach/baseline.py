"""Baselines: what real files on this machine actually exercise.

The point of comparison for a synthesized corpus is not a strawman but the code
people really lex. Files are found with the lexer's own ``filenames`` globs, so
the Python lexer is measured against real Python files, the CSS lexer against
real stylesheets, and so on. A uniform-random baseline of matched size is also
reported, because "just throw bytes at it" is the other obvious approach.
"""

import glob
import json
import os
import random

from . import candidates as _candidates
from . import driver

#: Directories searched for real input files. Targeted rather than broad: a
#: blind walk of Program Files costs minutes on Windows and finds no more
#: languages than these do.
def default_roots():
    stdlib = os.path.dirname(os.__file__)
    local = os.environ.get('LOCALAPPDATA', '')
    windir = os.environ.get('SystemRoot', 'C:/Windows')
    roots = [
        stdlib,
        os.path.join(stdlib, 'site-packages'),
        os.path.join(os.path.dirname(stdlib), 'Include'),
        os.path.join(windir, 'System32', 'WindowsPowerShell', 'v1.0'),
        os.path.join(windir, 'INF'),
        os.path.join(windir, 'System32'),
    ]
    for pattern in (os.path.join(local, 'Programs', 'Microsoft VS Code', 'resources', 'app'),
                    os.path.join(local, 'Programs', 'Microsoft VS Code', '*', 'resources', 'app')):
        roots.extend(sorted(glob.glob(pattern)))
    return tuple(r for r in roots if r and os.path.isdir(r))


SKIP_DIRS = {'__pycache__', '.git', 'node_modules', '.pytest_cache', 'WinSxS',
             'Installer', 'servicing', 'assembly', 'DriverStore', 'LogFiles',
             'CatRoot', 'config', 'spool', 'Speech_OneCore'}

MAX_FILE_BYTES = 400_000


def build_index(extensions, roots=None, cache='docs/file_index.json',
                per_ext=160, max_dirs=2500):
    """One filesystem pass collecting real files by extension, cached to JSON.

    Windows makes directory walking the slowest part of the whole run, so this
    happens once per machine and is reused.
    """
    extensions = {e.lower() for e in extensions}
    roots = tuple(roots or default_roots())
    if cache and os.path.exists(cache):
        with open(cache, encoding='utf-8') as handle:
            saved = json.load(handle)
        if saved.get('roots') == list(roots) and extensions <= set(saved.get('files', {})):
            return {e: saved['files'][e] for e in extensions}
    found = {e: [] for e in extensions}
    for root in roots:
        dirs_seen = 0
        for base, subdirs, names in os.walk(root):
            dirs_seen += 1
            if dirs_seen > max_dirs:
                break
            subdirs[:] = [d for d in subdirs if d not in SKIP_DIRS]
            for name in names:
                ext = os.path.splitext(name)[1].lower()
                if ext not in extensions or len(found[ext]) >= per_ext:
                    continue
                path = os.path.join(base, name)
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                if 0 < size <= MAX_FILE_BYTES:
                    found[ext].append(path)
    if cache:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        files = {}
        if os.path.exists(cache):
            with open(cache, encoding='utf-8') as handle:
                files = json.load(handle).get('files', {})
        files.update(found)
        with open(cache, 'w', encoding='utf-8') as handle:
            json.dump({'roots': list(roots), 'files': files}, handle, indent=1)
    return found


def lexer_extensions(lexer):
    """Extensions from the lexer's own filename globs."""
    out = []
    for glob in getattr(lexer, 'filenames', ()):
        if glob.startswith('*.') and '*' not in glob[2:] and '[' not in glob:
            out.append(os.path.splitext(glob)[1].lower())
    return out


def find_files(lexer, index=None, limit_files=120, limit_bytes=4_000_000):
    """Real local files for this lexer, taken from the cached index."""
    exts = lexer_extensions(lexer)
    if not exts:
        return []
    index = index if index is not None else build_index(exts)
    out = []
    total = 0
    for ext in exts:
        for path in index.get(ext, ()):
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            out.append(path)
            total += size
            if len(out) >= limit_files or total >= limit_bytes:
                return out
    return out


#: Directories searched for real input files. Picked because they hold large
#: amounts of ordinary, machine-local source in many languages.
DEFAULT_ROOTS = (
    os.path.join(os.path.dirname(os.__file__)),
    os.path.join(os.path.dirname(os.__file__), 'site-packages'),
    os.path.join(os.path.dirname(os.path.dirname(os.__file__)), 'Include'),
    os.environ.get('LOCALAPPDATA', ''),
    os.environ.get('ProgramFiles', ''),
    os.environ.get('SystemRoot', ''),
)

SKIP_DIRS = {'__pycache__', '.git', 'node_modules', '.pytest_cache',
             'WinSxS', 'Installer', 'servicing', 'assembly'}


def read_text(path, limit=400_000):
    try:
        with open(path, encoding='utf-8', errors='replace') as handle:
            return handle.read(limit)
    except OSError:
        return ''


def corpus_curve(lexer, paths, targets):
    """Cumulative (bytes, rules covered) over real files, plus the final set."""
    targets = set(targets)
    covered = set()
    points = [(0, 0)]
    total = 0
    used = 0
    for path in paths:
        text = read_text(path)
        if not text:
            continue
        used += 1
        total += len(text)
        covered |= driver.covered(lexer, text) & targets
        points.append((total, len(covered)))
    return {'points': points, 'bytes': total, 'files': used,
            'covered': len(covered), 'covered_rules': covered}


def alphabet(lexer):
    """Characters that appear in the lexer's own candidate strings."""
    chars = set()
    for state in lexer._tokens:
        for index in range(len(lexer._tokens[state])):
            strings, _info = _candidates.rule_candidates(lexer, state, index)
            for text in strings:
                chars.update(text)
    chars.update(' \n\tabc01_"()[]{}=;:,.-/*#')
    return ''.join(sorted(chars))


def random_baseline(lexer, targets, nbytes, seed=20261119, chunk=200):
    """Coverage of uniform-random text of the same size as the real answer."""
    targets = set(targets)
    rng = random.Random(seed)
    letters = alphabet(lexer)
    covered = set()
    spent = 0
    while spent < nbytes:
        size = min(chunk, nbytes - spent)
        text = ''.join(rng.choice(letters) for _ in range(size))
        covered |= driver.covered(lexer, text) & targets
        spent += size
    return {'bytes': spent, 'covered': len(covered)}
