"""This module finds the JQL expression inside a shell command line, so that a shell widget can complete it.

A shell widget (e.g. a zsh ZLE widget) only knows the whole command line and the position of the cursor within it; e.g.
`jiratui issues search --jql 'project = SB and sta|' -l 20`. This module works out which word of the command line
holds the expression, removes the shell quoting from it so that it can be completed as JQL, and writes the completed
expression back with the same quoting, so that the command line stays valid.
"""

from dataclasses import dataclass

DEFAULT_JQL_FLAGS: tuple[str, ...] = ('--jql', '-q')
"""The options whose value is a JQL expression."""

DEFAULT_JQL_COMMANDS: tuple[str, ...] = ('jqls',)
"""The commands whose positional arguments are a JQL expression."""

_COMMAND_SEPARATORS = frozenset(';|&\n')


@dataclass(frozen=True)
class ShellWord:
    """A word of a command line."""

    start: int
    """The position of the first character of the word, including any quote, within the command line."""
    end: int
    """The position after the last character of the word, including any closing quote."""
    raw: str
    """The word as written in the command line."""
    value: str
    """The word once the shell has removed its quoting."""
    offsets: tuple[int, ...]
    """`offsets[i]` is the number of characters of `value` produced by the first `i` characters of `raw`."""
    quote: str = ''
    """The quote that the word opens with; empty when the word does not start with a quote."""
    separator: bool = False
    """Whether the word is a command separator (`;`, `|`, `&` or a newline) rather than an argument."""


def _read_word(line: str, start: int) -> ShellWord:
    """Reads the word that starts at `start`; it ends at unquoted whitespace, a command separator or the end."""

    value: list[str] = []
    offsets: list[int] = [0]
    position = start
    length = len(line)
    quote_state = ''  # the quote that is open at the current position
    first_quote = line[start] if line[start] in ('"', "'") else ''

    while position < length:
        character = line[position]
        # how many characters of the line are consumed, and what they produce
        count, produced = 1, character
        if quote_state == "'":
            if character == "'":
                quote_state, produced = '', ''
        elif quote_state == '"':
            if character == '"':
                quote_state, produced = '', ''
            elif character == '\\' and position + 1 < length and line[position + 1] in '"\\$`':
                count, produced = 2, line[position + 1]
        else:
            if character in ' \t' or character in _COMMAND_SEPARATORS:
                break
            if character in ('"', "'"):
                quote_state, produced = character, ''
            elif character == '\\' and position + 1 < length:
                count, produced = 2, line[position + 1]
        # the characters of an escape sequence produce their value at its end, so a cursor in the middle of one maps
        # to the position before the value
        before = len(value)
        value.extend(produced)
        offsets.extend([before] * (count - 1) + [len(value)])
        position += count

    return ShellWord(
        start=start,
        end=position,
        raw=line[start:position],
        value=''.join(value),
        offsets=tuple(offsets),
        quote=first_quote,
    )


def split_words(line: str) -> list[ShellWord]:
    """Splits a command line into words the way a POSIX shell does, keeping track of the position of each of them.

    An unterminated quote extends its word to the end of the line, because that is what the user is typing.
    """

    words: list[ShellWord] = []
    position = 0
    length = len(line)
    while position < length:
        character = line[position]
        if character in ' \t':
            position += 1
            continue
        if character in _COMMAND_SEPARATORS:
            words.append(
                ShellWord(
                    start=position,
                    end=position + 1,
                    raw=character,
                    value=character,
                    offsets=(0, 1),
                    separator=True,
                )
            )
            position += 1
            continue

        word = _read_word(line, position)
        words.append(word)
        position = word.end
    return words


@dataclass(frozen=True)
class ShellJQLRegion:
    """The part of a command line that holds a JQL expression."""

    start: int
    """The position, within the command line, of the first character of the word that holds the expression."""
    end: int
    """The position after the last character of that word."""
    prefix: str
    """The text of the word that precedes the expression and is kept as-is; e.g. `--jql=`."""
    quote: str
    """The quote used to write the expression back: the one the user opened the expression with, `'` otherwise."""
    expression: str
    """The expression, without the shell quoting."""
    cursor: int
    """The position of the cursor within `expression`."""

    def replace(self, line: str, expression: str, cursor: int) -> tuple[str, int]:
        """Writes an expression back into the command line in place of this one.

        Args:
            line: the command line that this region was found in.
            expression: the new expression.
            cursor: the position of the cursor within the new expression.

        Returns:
            The new command line, and the position of the cursor within it.
        """

        word = f'{self.prefix}{quote(expression, self.quote)}'
        # the cursor goes where the text before it ends up once quoted; the closing quote is left after it
        before_cursor = f'{self.prefix}{quote(expression[:cursor], self.quote)[:-1]}'
        new_line = f'{line[: self.start]}{word}{line[self.end :]}'
        return new_line, self.start + len(before_cursor)


def quote(text: str, quote_character: str = "'") -> str:
    """Quotes a text for a POSIX shell, using the given quote."""

    if quote_character == '"':
        escaped = ''.join(f'\\{c}' if c in '"\\$`' else c for c in text)
        return f'"{escaped}"'
    return "'" + text.replace("'", "'\\''") + "'"


def find_jql_region(
    line: str,
    cursor: int,
    flags: tuple[str, ...] = DEFAULT_JQL_FLAGS,
    commands: tuple[str, ...] = DEFAULT_JQL_COMMANDS,
) -> ShellJQLRegion | None:
    """Finds the JQL expression that the cursor is in.

    The expression is the value of one of the `flags` (`--jql EXPR` or `--jql=EXPR`), or a positional argument of one
    of the `commands`. The cursor may also sit right after one of those, where the expression is yet to be typed.

    Args:
        line: the command line.
        cursor: the position of the cursor within the command line.
        flags: the options whose value is a JQL expression.
        commands: the commands whose positional arguments are a JQL expression.

    Returns:
        The region of the command line that holds the expression; `None` when the cursor is not in one.
    """

    cursor = max(0, min(cursor, len(line)))
    words = split_words(line)

    current_index: int | None = None
    for index, word in enumerate(words):
        if not word.separator and word.start <= cursor <= word.end:
            current_index = index
            break

    if current_index is None:
        # the cursor is between words: the expression is a word yet to be typed
        previous = [word for word in words if word.end <= cursor]
        if _is_jql_position(previous, flags, commands):
            return ShellJQLRegion(
                start=cursor, end=cursor, prefix='', quote="'", expression='', cursor=0
            )
        return None

    word = words[current_index]
    raw_offset = cursor - word.start

    for flag in flags:
        if flag.startswith('--') and word.raw.startswith(f'{flag}='):
            prefix = f'{flag}='
            if raw_offset < len(prefix):
                return None
            rest = split_words(word.raw[len(prefix) :])
            if not rest:
                return ShellJQLRegion(
                    start=word.start,
                    end=word.end,
                    prefix=prefix,
                    quote="'",
                    expression='',
                    cursor=0,
                )
            inner = rest[0]
            return ShellJQLRegion(
                start=word.start,
                end=word.end,
                prefix=prefix,
                quote=inner.quote or "'",
                expression=inner.value,
                cursor=inner.offsets[min(raw_offset - len(prefix), len(inner.offsets) - 1)],
            )

    if not _is_jql_position(words[:current_index], flags, commands):
        return None
    return ShellJQLRegion(
        start=word.start,
        end=word.end,
        prefix='',
        quote=word.quote or "'",
        expression=word.value,
        cursor=word.offsets[min(raw_offset, len(word.offsets) - 1)],
    )


def _is_jql_position(
    previous: list[ShellWord], flags: tuple[str, ...], commands: tuple[str, ...]
) -> bool:
    """Whether a word that follows `previous` is a JQL expression."""

    if not previous:
        return False
    if not previous[-1].separator and previous[-1].value in flags:
        return True
    # the command is the first word after the last separator
    command_words: list[ShellWord] = []
    for word in reversed(previous):
        if word.separator:
            break
        command_words.insert(0, word)
    if not command_words:
        return False
    command = command_words[0].value.rsplit('/', 1)[-1]
    if command not in commands:
        return False
    # a word that follows an option is the value of the option, not the expression
    return not previous[-1].value.startswith('-')
