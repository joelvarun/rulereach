"""Trace-capable transcription of the pygments RegexLexer dispatch loop.

The matching is done by the very patterns pygments compiled: ``lexer._tokens``
holds ``re.Pattern.match`` bound methods, and this module calls them. Nothing
about regex semantics is reimplemented. What is added is visibility, which the
upstream generator does not expose: which rule won at every position, and what
the state stack looked like when it did.

``assert_equivalent`` checks the transcription token for token against
``RegexLexer.get_tokens_unprocessed``, so any drift from upstream behaviour is a
test failure rather than a silent modelling error.
"""

from pygments.lexer import RegexLexer
from pygments.token import Error, Whitespace, _TokenType


def rule_keys(lexer):
    """Every (state, index) pair in the lexer, in a stable order."""
    out = []
    for state in lexer._tokens:
        for index in range(len(lexer._tokens[state])):
            out.append((state, index))
    return out


def rule_pattern(lexer, state, index):
    """The compiled pattern object behind one rule."""
    return lexer._tokens[state][index][0].__self__


def apply_new_state(new_state, stack):
    """The state transition pygments performs, transcribed from pygments/lexer.py."""
    if isinstance(new_state, tuple):
        for state in new_state:
            if state == '#pop':
                if len(stack) > 1:
                    stack.pop()
            elif state == '#push':
                stack.append(stack[-1])
            else:
                stack.append(state)
    elif isinstance(new_state, int):
        if abs(new_state) >= len(stack):
            del stack[1:]
        else:
            del stack[new_state:]
    elif new_state == '#push':
        stack.append(stack[-1])
    else:
        raise ValueError('wrong state def: %r' % (new_state,))


def step(lexer, stack, text, pos):
    """One iteration of the dispatch loop.

    Returns ``(state, index, end, new_stack)`` for the rule that wins at ``pos``,
    or ``None`` when no rule in the top state matches there. ``stack`` is a list
    and is not modified; the returned stack is a fresh list.
    """
    state = stack[-1]
    for index, (rexmatch, action, new_state) in enumerate(lexer._tokens[state]):
        m = rexmatch(text, pos)
        if m:
            out = list(stack)
            if new_state is not None:
                apply_new_state(new_state, out)
            return state, index, m.end(), out
    return None


def run(lexer, text, stack=('root',), start=0, max_steps=4000000):
    """Lex ``text`` and return ``(tokens, fired, final_stack)``.

    ``tokens`` is what pygments would yield: a list of ``(pos, tokentype, value)``.
    ``fired`` is one ``(state, index, pos, end, stack_after)`` record per rule
    that won, where ``stack_after`` is the state stack the transition produced.
    """
    tokendefs = lexer._tokens
    statestack = list(stack)
    statetokens = tokendefs[statestack[-1]]
    pos = start
    tokens = []
    fired = []
    steps = 0
    while True:
        steps += 1
        if steps > max_steps:
            break
        for index, (rexmatch, action, new_state) in enumerate(statetokens):
            m = rexmatch(text, pos)
            if m:
                won = statestack[-1]
                if action is not None:
                    if type(action) is _TokenType:
                        tokens.append((pos, action, m.group()))
                    else:
                        tokens.extend(action(lexer, m))
                start_pos = pos
                pos = m.end()
                if new_state is not None:
                    apply_new_state(new_state, statestack)
                    statetokens = tokendefs[statestack[-1]]
                fired.append((won, index, start_pos, pos, tuple(statestack)))
                break
        else:
            try:
                if text[pos] == '\n':
                    statestack = ['root']
                    statetokens = tokendefs['root']
                    tokens.append((pos, Whitespace, '\n'))
                    pos += 1
                    continue
                tokens.append((pos, Error, text[pos]))
                pos += 1
            except IndexError:
                break
    return tokens, fired, tuple(statestack)


def covered(lexer, text):
    """The set of (state, index) rules that firing ``text`` exercises."""
    _, fired, _ = run(lexer, text)
    return {(state, index) for state, index, _, _, _ in fired}


def assert_equivalent(lexer, text):
    """Raise AssertionError unless the transcription matches pygments exactly.

    The comparison is against ``RegexLexer.get_tokens_unprocessed``, the loop
    this module transcribes. Some lexers override that method to relabel token
    types afterwards (``CFamilyLexer`` promotes a ``Name`` such as ``size_t`` to
    ``Keyword.Type``, for instance). That rewriting happens after the dispatch
    loop has already chosen a rule, so it changes token types without changing
    which rules fired, and it is deliberately outside this check.
    """
    mine, _, _ = run(lexer, text)
    theirs = list(RegexLexer.get_tokens_unprocessed(lexer, text))
    if mine != theirs:
        for i, (a, b) in enumerate(zip(mine, theirs)):
            if a != b:
                raise AssertionError('token %d differs: %r vs %r' % (i, a, b))
        raise AssertionError('token count differs: %d vs %d' % (len(mine), len(theirs)))
    return True


def state_targets(new_state, state):
    """State names a rule's transition can push, given it fires in ``state``."""
    if new_state is None:
        return ()
    if isinstance(new_state, int):
        return ()
    if new_state == '#push':
        return (state,)
    out = []
    for item in new_state:
        if item == '#pop':
            continue
        out.append(state if item == '#push' else item)
    return tuple(out)


def reachable_states(lexer, start='root'):
    """States that can actually sit on top of the stack.

    pygments materialises an ``include('x')`` by copying x's rules into the
    including state while also keeping ``x`` as an entry of ``_tokens``. Those
    template entries are never pushed, so their rule tuples can never fire; the
    copies inside the including state are what run. Restricting the rule
    universe to this closure keeps that bookkeeping artefact out of the numbers.
    """
    seen = {start}
    stack = [start]
    while stack:
        state = stack.pop()
        for rexmatch, action, new_state in lexer._tokens[state]:
            for target in state_targets(new_state, state):
                if target in lexer._tokens and target not in seen:
                    seen.add(target)
                    stack.append(target)
    return seen


def universe(lexer, start='root'):
    """Every (state, index) rule that sits in a reachable state."""
    out = []
    for state in sorted(reachable_states(lexer, start)):
        for index in range(len(lexer._tokens[state])):
            out.append((state, index))
    return out


def pending_stack(fired, default=('root',)):
    """State stack after the last match that consumed input.

    Most pygments states end in ``default('#pop')``, a zero-width rule. At the
    end of a string that rule, and any pop above it, fire in a cascade purely
    because the text ran out, so the stack after the final event describes the
    unwinding rather than the state the lexer was holding. Ignoring the trailing
    zero-width events gives the state that is actually waiting for more input.
    """
    for state, index, start, end, stack in reversed(fired):
        if end > start:
            return stack
    return tuple(default)
