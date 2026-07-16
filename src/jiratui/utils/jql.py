"""This module provides the tools required to autocomplete a JQL expression.

The functions in this module work out *what* the user is typing at a given position of a JQL expression: the name of a
field, an operator, or the value of a field. This is what allows the app to offer the same suggestions that the Jira
web UI offers.

```{important}
This is a lexer, not a parser. It does not validate a JQL expression; it only needs to make sense of the expression
around the cursor, and it must cope with the expression being incomplete, because the user is in the middle of typing
it.
```
"""

import dataclasses
from dataclasses import dataclass
import enum
import re


class JQLTokenKind(enum.Enum):
    """The kind of a token of a JQL expression."""

    FIELD = 'field'
    """The name of a field. E.g.: `project`, `cf[10050]`, `"Dev Engineers"`."""
    OPERATOR = 'operator'
    """An operator. E.g.: `=`, `!=`, `in`, `was not`."""
    VALUE = 'value'
    """The value of a field. E.g.: `SB`, `"In Progress"`."""
    KEYWORD = 'keyword'
    """A word reserved by JQL. E.g.: `and`, `or`, `order by`."""
    PUNCTUATION = 'punctuation'
    """A character that separates other tokens. E.g.: `(`, `)`, `,`."""


class JQLContext(enum.Enum):
    """What the user is typing at a given position of a JQL expression."""

    FIELD = 'field'
    """The name of a field."""
    OPERATOR = 'operator'
    """An operator that applies to the field in scope."""
    VALUE = 'value'
    """A value of the field in scope."""
    KEYWORD = 'keyword'
    """A keyword; e.g. the direction of an `ORDER BY` clause."""
    NONE = 'none'
    """Nothing can be suggested at this position."""


WORD_OPERATORS: tuple[str, ...] = (
    'was not in',
    'was not',
    'was in',
    'not in',
    'is not',
    'changed',
    'was',
    'is',
    'in',
)
"""The operators made of words, longest first so that e.g. `was not in` is not read as `was`."""

SYMBOL_OPERATORS: tuple[str, ...] = ('!~', '!=', '>=', '<=', '~', '=', '>', '<')
"""The operators made of symbols, longest first so that e.g. `>=` is not read as `>`."""

LOGICAL_KEYWORDS: tuple[str, ...] = ('and', 'or', 'not')
"""The keywords that join the clauses of a JQL expression."""

ORDER_DIRECTION_KEYWORDS: tuple[str, ...] = ('asc', 'desc')
"""The keywords that define the direction of an `ORDER BY` clause."""

_TOKEN_PATTERN = re.compile(
    r"""
    (?P<whitespace>\s+)
    | (?P<quoted>"(?:\\.|[^"\\])*"?|'(?:\\.|[^'\\])*'?)
    | (?P<custom_field>cf\[\d+\])
    | (?P<punctuation>[(),])
    | (?P<symbol_operator>!~|!=|>=|<=|~|=|>|<)
    | (?P<word>[^\s(),"'=!<>~]+)
    """,
    re.VERBOSE | re.IGNORECASE,
)


@dataclass(frozen=True)
class JQLToken:
    """A token of a JQL expression."""

    kind: JQLTokenKind
    text: str
    """The text of the token, as typed by the user; including the quotes of a quoted value."""
    start: int
    """The position of the first character of the token within the expression."""
    end: int
    """The position after the last character of the token within the expression."""
    quoted: bool = False
    """Whether the text of the token is quoted."""

    @property
    def value(self) -> str:
        """The text of the token without the quotes."""

        if not self.quoted:
            return self.text
        text = self.text
        quote = text[0]
        text = text[1:]
        if text.endswith(quote):
            text = text[:-1]
        return text.replace(f'\\{quote}', quote)


@dataclass(frozen=True)
class JQLCursorContext:
    """What the user is typing at a given position of a JQL expression."""

    context: JQLContext
    """What can be suggested at the position."""
    prefix: str = ''
    """The text already typed by the user at the position. Suggestions should start with, or contain, this."""
    replace_start: int = 0
    """The position of the first character to replace when a suggestion is applied."""
    replace_end: int = 0
    """The position after the last character to replace when a suggestion is applied."""
    field: str | None = None
    """The field in scope; set when the context is an operator or a value."""
    operator: str | None = None
    """The operator in scope; set when the context is a value."""
    quoted: bool = False
    """Whether the cursor is inside a quoted value. A suggestion applied here must not be quoted again."""
    keywords: tuple[str, ...] = dataclasses.field(default_factory=tuple)
    """The keywords that can be suggested when the context is a keyword."""


def _is_word_operator_at(words: list[JQLToken], index: int) -> int:
    """Returns the number of tokens taken by a word operator starting at `index`; 0 if there is none."""

    for operator in WORD_OPERATORS:
        parts = operator.split(' ')
        if len(parts) > len(words) - index:
            continue
        candidate = [token.text.lower() for token in words[index : index + len(parts)]]
        if candidate == parts:
            return len(parts)
    return 0


def _raw_tokens(text: str) -> list[JQLToken]:
    """Splits an expression into tokens, without working out the role of each token."""

    tokens: list[JQLToken] = []
    for match in _TOKEN_PATTERN.finditer(text):
        if match.lastgroup == 'whitespace':
            continue
        token_text = match.group()
        if match.lastgroup == 'quoted':
            kind = JQLTokenKind.VALUE
            quoted = True
        elif match.lastgroup == 'punctuation':
            kind = JQLTokenKind.PUNCTUATION
            quoted = False
        elif match.lastgroup == 'symbol_operator':
            kind = JQLTokenKind.OPERATOR
            quoted = False
        else:
            kind = JQLTokenKind.FIELD
            quoted = False
        tokens.append(
            JQLToken(
                kind=kind, text=token_text, start=match.start(), end=match.end(), quoted=quoted
            )
        )
    return tokens


def tokenize(text: str) -> list[JQLToken]:
    """Splits a JQL expression into tokens.

    Args:
        text: a JQL expression. It does not need to be valid or complete.

    Returns:
        The tokens of the expression, in the order in which they appear.
    """

    raw = _raw_tokens(text)
    tokens: list[JQLToken] = []
    index = 0
    expects_field = True
    in_order_by = False

    while index < len(raw):
        token = raw[index]

        if token.kind is JQLTokenKind.PUNCTUATION:
            tokens.append(token)
            if token.text in ('(', ','):
                # a value of a list follows
                expects_field = expects_field and token.text == '('
            index += 1
            continue

        if token.kind is JQLTokenKind.OPERATOR:
            tokens.append(token)
            expects_field = False
            index += 1
            continue

        if not token.quoted:
            lowered = token.text.lower()
            # 'order by' spans two tokens
            if lowered == 'order' and index + 1 < len(raw) and raw[index + 1].text.lower() == 'by':
                tokens.append(
                    JQLToken(
                        kind=JQLTokenKind.KEYWORD,
                        text=text[token.start : raw[index + 1].end],
                        start=token.start,
                        end=raw[index + 1].end,
                    )
                )
                in_order_by = True
                expects_field = True
                index += 2
                continue
            if in_order_by and lowered in ORDER_DIRECTION_KEYWORDS:
                tokens.append(JQLToken(JQLTokenKind.KEYWORD, token.text, token.start, token.end))
                index += 1
                continue
            # an operator is looked for before a keyword: `not` starts the operator `not in`, but it is also a
            # keyword on its own
            if not in_order_by and not expects_field:
                if taken := _is_word_operator_at(raw, index):
                    tokens.append(
                        JQLToken(
                            kind=JQLTokenKind.OPERATOR,
                            text=text[token.start : raw[index + taken - 1].end],
                            start=token.start,
                            end=raw[index + taken - 1].end,
                        )
                    )
                    index += taken
                    continue
            if lowered in LOGICAL_KEYWORDS:
                tokens.append(JQLToken(JQLTokenKind.KEYWORD, token.text, token.start, token.end))
                expects_field = True
                index += 1
                continue

        if expects_field:
            tokens.append(
                JQLToken(
                    kind=JQLTokenKind.FIELD,
                    text=token.text,
                    start=token.start,
                    end=token.end,
                    quoted=token.quoted,
                )
            )
            # in an ORDER BY clause a field is followed by a direction or by another field
            expects_field = in_order_by
        else:
            tokens.append(
                JQLToken(
                    kind=JQLTokenKind.VALUE,
                    text=token.text,
                    start=token.start,
                    end=token.end,
                    quoted=token.quoted,
                )
            )
        index += 1

    return tokens


def _token_at_cursor(tokens: list[JQLToken], cursor: int) -> JQLToken | None:
    """The token that the user is typing at the given position.

    A cursor sitting at the end of a token continues that token, unless the token is punctuation or an operator: those
    are complete as soon as they are typed, so a cursor after them starts the next token; e.g. the cursor in
    `status in (|)` starts a value, it does not continue the `(`.
    """

    for token in tokens:
        if token.start < cursor < token.end:
            return token
        if cursor == token.end and token.kind not in (
            JQLTokenKind.PUNCTUATION,
            JQLTokenKind.OPERATOR,
        ):
            return token
    return None


def _tokens_before(tokens: list[JQLToken], cursor: int) -> list[JQLToken]:
    return [token for token in tokens if token.end <= cursor]


def _scope_of_value(tokens: list[JQLToken]) -> tuple[str | None, str | None]:
    """The field and the operator that a value being typed belongs to."""

    operator: str | None = None
    for token in reversed(tokens):
        if token.kind is JQLTokenKind.OPERATOR:
            operator = token.text.lower()
            continue
        if token.kind is JQLTokenKind.FIELD and operator is not None:
            return token.value, operator
        if token.kind is JQLTokenKind.KEYWORD and operator is None:
            return None, None
    return None, None


def context_at(text: str, cursor: int) -> JQLCursorContext:
    """Works out what the user is typing at a position of a JQL expression.

    Args:
        text: a JQL expression. It does not need to be valid or complete.
        cursor: the position of the cursor within the expression.

    Returns:
        An instance of `JQLCursorContext` describing what can be suggested at the position, and the span of the
        expression that a suggestion replaces.
    """

    cursor = max(0, min(cursor, len(text)))
    tokens = tokenize(text)
    current = _token_at_cursor(tokens, cursor)

    if current is not None:
        # the cursor is inside a token: the token is replaced by the suggestion
        before = [token for token in tokens if token.end <= current.start]
        prefix = current.value if current.quoted else current.text[: cursor - current.start]
        replace_start, replace_end = current.start, current.end
        if current.kind is JQLTokenKind.FIELD:
            if _is_order_by_direction_position(before):
                return JQLCursorContext(
                    context=JQLContext.KEYWORD,
                    prefix=prefix,
                    replace_start=replace_start,
                    replace_end=replace_end,
                    keywords=ORDER_DIRECTION_KEYWORDS + LOGICAL_KEYWORDS,
                )
            return JQLCursorContext(
                context=JQLContext.FIELD,
                prefix=prefix,
                replace_start=replace_start,
                replace_end=replace_end,
                quoted=current.quoted,
            )
        if current.kind is JQLTokenKind.OPERATOR:
            field_token = _last_field(before)
            return JQLCursorContext(
                context=JQLContext.OPERATOR,
                prefix=prefix,
                replace_start=replace_start,
                replace_end=replace_end,
                field=field_token.value if field_token else None,
            )
        if current.kind is JQLTokenKind.VALUE:
            scope_field, scope_operator = _scope_of_value(before)
            return JQLCursorContext(
                context=JQLContext.VALUE,
                prefix=prefix,
                replace_start=replace_start,
                replace_end=replace_end,
                field=scope_field,
                operator=scope_operator,
                quoted=current.quoted,
            )
        if current.kind is JQLTokenKind.KEYWORD:
            return JQLCursorContext(
                context=JQLContext.KEYWORD,
                prefix=prefix,
                replace_start=replace_start,
                replace_end=replace_end,
                keywords=LOGICAL_KEYWORDS + ORDER_DIRECTION_KEYWORDS,
            )
        return JQLCursorContext(context=JQLContext.NONE)

    # the cursor is not inside a token: the suggestion is inserted at the cursor
    before = _tokens_before(tokens, cursor)
    return _context_after(before, cursor)


def _last_field(tokens: list[JQLToken]) -> JQLToken | None:
    for token in reversed(tokens):
        if token.kind is JQLTokenKind.FIELD:
            return token
        if token.kind is JQLTokenKind.KEYWORD:
            return None
    return None


def _is_order_by_direction_position(tokens: list[JQLToken]) -> bool:
    """Whether a token following `tokens` is the direction of an `ORDER BY` clause."""

    seen_field = False
    for token in reversed(tokens):
        if token.kind is JQLTokenKind.KEYWORD:
            if token.text.lower().startswith('order'):
                return seen_field
            if token.text.lower() in ORDER_DIRECTION_KEYWORDS:
                seen_field = False
                continue
            return False
        if token.kind is JQLTokenKind.FIELD:
            if seen_field:
                return False
            seen_field = True
            continue
        if token.kind is JQLTokenKind.PUNCTUATION and token.text == ',':
            return False
        return False
    return False


def _context_after(tokens: list[JQLToken], cursor: int) -> JQLCursorContext:
    """The context of a cursor that sits after the given tokens, and not inside any of them."""

    empty = JQLCursorContext(
        context=JQLContext.FIELD, prefix='', replace_start=cursor, replace_end=cursor
    )
    if not tokens:
        # nothing has been typed yet: the expression starts with the name of a field
        return empty

    last = tokens[-1]

    if last.kind is JQLTokenKind.OPERATOR:
        scope_field, scope_operator = _scope_of_value(tokens)
        return JQLCursorContext(
            context=JQLContext.VALUE,
            replace_start=cursor,
            replace_end=cursor,
            field=scope_field,
            operator=scope_operator,
        )

    if last.kind is JQLTokenKind.PUNCTUATION:
        if last.text in ('(', ','):
            scope_field, scope_operator = _scope_of_value(tokens)
            if scope_field:
                # another value of a list of values; e.g.: status in (Open, |)
                return JQLCursorContext(
                    context=JQLContext.VALUE,
                    replace_start=cursor,
                    replace_end=cursor,
                    field=scope_field,
                    operator=scope_operator,
                )
            return empty
        # a closing parenthesis: a keyword joins the next clause
        return JQLCursorContext(
            context=JQLContext.KEYWORD,
            replace_start=cursor,
            replace_end=cursor,
            keywords=LOGICAL_KEYWORDS + ('order by',),
        )

    if last.kind is JQLTokenKind.KEYWORD:
        if last.text.lower() in ORDER_DIRECTION_KEYWORDS:
            return JQLCursorContext(
                context=JQLContext.NONE, replace_start=cursor, replace_end=cursor
            )
        # 'and', 'or', 'not' and 'order by' are all followed by the name of a field
        return empty

    if last.kind is JQLTokenKind.FIELD:
        if _is_order_by_direction_position(tokens):
            return JQLCursorContext(
                context=JQLContext.KEYWORD,
                replace_start=cursor,
                replace_end=cursor,
                keywords=ORDER_DIRECTION_KEYWORDS,
            )
        return JQLCursorContext(
            context=JQLContext.OPERATOR,
            replace_start=cursor,
            replace_end=cursor,
            field=last.value,
        )

    # the last token is a value: the clause is complete, so a keyword joins the next one
    return JQLCursorContext(
        context=JQLContext.KEYWORD,
        replace_start=cursor,
        replace_end=cursor,
        keywords=LOGICAL_KEYWORDS + ('order by',),
    )
