"""This module completes JQL expressions outside of the TUI; e.g. from a shell, from fzf or from an editor.

It produces the same suggestions as the dropdown of the JQL editor of the app (see
`jiratui.widgets.commons.jql_autocomplete`), but every call is a separate process, so nothing can be kept in a session:
the reference data (the fields, their operators and the functions) is cached on disk instead, and so are the readable
values of a field (e.g. the name of a user) mapped to the values that the API understands (e.g. their account id).

```{important}
This module must not import Textual, nor the API controller at import time: it runs on every keystroke that asks for a
completion, and importing the app costs about a second.
```
"""

from collections.abc import Iterable
import dataclasses
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import html
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, Any

from jiratui.constants import LOGGER_NAME
from jiratui.files import get_cache_directory
from jiratui.models import JQLFieldRef
from jiratui.utils.jql import (
    JQLContext,
    JQLCursorContext,
    JQLTokenKind,
    context_at,
    operator_completion,
    quote_if_needed,
    strip_quotes,
    tokenize,
)

if TYPE_CHECKING:
    from jiratui.api_controller.controller import APIController

logger = logging.getLogger(LOGGER_NAME)

CACHE_FILE_NAME = 'jql_autocomplete.json'
"""The name of the file, within the cache directory, that holds the JQL reference data."""

DEFAULT_CACHE_TTL = timedelta(hours=24)
"""How long the reference data is used before it is fetched again."""

MAXIMUM_SUGGESTIONS = 200
"""The number of suggestions returned at once. Higher than the dropdown of the app because fzf filters them."""


def get_cache_file() -> Path:
    """The file that holds the JQL reference data."""

    return get_cache_directory() / CACHE_FILE_NAME


@dataclass
class JQLReferenceCache:
    """The JQL reference data of a Jira instance, kept on disk between processes."""

    base_url: str | None = None
    """The Jira instance that the data belongs to; the data of another instance is never used."""
    fetched_at: datetime | None = None
    """When the fields and the functions were fetched."""
    fields: list[JQLFieldRef] = field(default_factory=list)
    """The fields that can be referenced in an expression."""
    functions: list[JQLFieldRef] = field(default_factory=list)
    """The functions that can be referenced in an expression."""
    aliases: dict[str, dict[str, str]] = field(default_factory=dict)
    """The readable values of a field mapped to the values that the API understands, keyed by the lowercase name of
    the field; e.g. `{'assignee': {'Jane Doe - jane@example.com': '5c01...'}}`."""
    path: Path | None = None
    """The file that the data was read from, and is written back to."""

    @classmethod
    def load(cls, path: Path | None = None, base_url: str | None = None) -> 'JQLReferenceCache':
        """Reads the cache.

        Args:
            path: the file to read; the file in the cache directory by default.
            base_url: the Jira instance in use. A cache written for another instance is discarded.

        Returns:
            The cache; empty when the file does not exist, cannot be read or belongs to another instance.
        """

        path = path or get_cache_file()
        empty = cls(base_url=base_url, path=path)
        try:
            document: Any = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return empty
        except (OSError, ValueError) as e:
            logger.debug(f'Unable to read the JQL reference data from {path}: {e}')
            return empty
        if not isinstance(document, dict):
            return empty
        if base_url and document.get('base_url') != base_url:
            return empty
        fetched_at: datetime | None = None
        if raw_fetched_at := document.get('fetched_at'):
            try:
                fetched_at = datetime.fromisoformat(raw_fetched_at)
            except (TypeError, ValueError):
                fetched_at = None
        aliases = document.get('aliases')
        return cls(
            base_url=document.get('base_url'),
            fetched_at=fetched_at,
            fields=_field_refs(document.get('fields')),
            functions=_field_refs(document.get('functions')),
            aliases=(
                {
                    str(name): {str(k): str(v) for k, v in values.items()}
                    for name, values in aliases.items()
                    if isinstance(values, dict)
                }
                if isinstance(aliases, dict)
                else {}
            ),
            path=path,
        )

    def save(self) -> None:
        """Writes the cache back to its file, atomically, so that a concurrent reader never sees half of it."""

        path = self.path or get_cache_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            'base_url': self.base_url,
            'fetched_at': self.fetched_at.isoformat() if self.fetched_at else None,
            'fields': [dataclasses.asdict(ref) for ref in self.fields],
            'functions': [dataclasses.asdict(ref) for ref in self.functions],
            'aliases': self.aliases,
        }
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent, prefix=f'.{path.name}-', suffix='.tmp'
        )
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as temporary_file:
                json.dump(document, temporary_file)
            os.replace(temporary_name, path)
        except BaseException:
            try:
                os.remove(temporary_name)
            except OSError:
                pass
            raise

    def is_stale(self, ttl: timedelta = DEFAULT_CACHE_TTL) -> bool:
        """Whether the fields and the functions have to be fetched again."""

        if self.fetched_at is None or not self.fields:
            return True
        fetched_at = self.fetched_at
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
        return datetime.now(UTC) - fetched_at > ttl

    def field_ref(self, name: str | None) -> JQLFieldRef | None:
        """The field that a name refers to, by the name used in an expression or by its display name."""

        if not name:
            return None
        key = strip_quotes(name).lower()
        for ref in self.fields:
            if strip_quotes(ref.value).lower() == key:
                return ref
        for ref in self.fields:
            if ref.display_name and ref.display_name.lower() == key:
                return ref
        return None

    def add_alias(self, field_name: str, display: str, value: str) -> None:
        """Records that the readable value `display` of a field is sent to the API as `value`."""

        self.aliases.setdefault(strip_quotes(field_name).lower(), {})[display] = value

    def alias_mapping(self) -> dict[tuple[str, str], str]:
        """The aliases in the shape that [resolve_values](#jiratui.utils.jql.resolve_values) expects."""

        return {
            (name, display): value
            for name, values in self.aliases.items()
            for display, value in values.items()
        }

    async def refresh(self, controller: 'APIController') -> bool:
        """Fetches the fields and the functions again.

        Returns:
            Whether the data was fetched; the data in the cache is left untouched when it was not.
        """

        response = await controller.get_jql_autocomplete_data()
        if not response.success or not response.result:
            logger.debug(f'Unable to fetch the JQL reference data: {response.error}')
            return False
        self.fields = list(response.result.visible_field_names)
        self.functions = list(response.result.visible_function_names)
        self.fetched_at = datetime.now(UTC)
        return True


_FIELD_REF_ATTRIBUTES = frozenset(f.name for f in dataclasses.fields(JQLFieldRef))


def _field_refs(items: Any) -> list[JQLFieldRef]:
    refs: list[JQLFieldRef] = []
    if not isinstance(items, list):
        return refs
    for item in items:
        if not isinstance(item, dict) or not item.get('value'):
            continue
        try:
            refs.append(
                JQLFieldRef(**{k: v for k, v in item.items() if k in _FIELD_REF_ATTRIBUTES})
            )
        except Exception:
            continue
    return refs


@dataclass(frozen=True)
class Candidate:
    """A suggestion for the text at the position of the cursor."""

    display: str
    """The text displayed to the user, and the text that the user picks."""
    insert: str
    """The text that replaces the span of the expression being completed."""
    cursor_offset: int
    """The position of the cursor within `insert` once the suggestion is applied."""
    kind: str
    """What the suggestion is: `field`, `operator`, `value`, `function` or `keyword`."""
    detail: str = ''
    """Additional information to display next to the suggestion; e.g. the display name of a field."""


@dataclass(frozen=True)
class Completion:
    """The suggestions for a position of an expression."""

    text: str
    """The expression."""
    context: JQLCursorContext
    """What is being typed at the position."""
    candidates: list[Candidate]

    def apply(self, candidate: Candidate) -> tuple[str, int]:
        """Applies a suggestion to the expression.

        Returns:
            The new expression, and the position of the cursor within it.
        """

        start, end = self.context.replace_start, self.context.replace_end
        if self.context.context is JQLContext.NONE:
            start = end = len(self.text)
        text = f'{self.text[:start]}{candidate.insert}{self.text[end:]}'
        return text, start + candidate.cursor_offset

    def find(self, choice: str) -> Candidate | None:
        """The candidate that the user picked by its display text, or by the text that it inserts."""

        choice = choice.strip()
        for candidate in self.candidates:
            if candidate.display == choice:
                return candidate
        for candidate in self.candidates:
            if candidate.insert.strip() == choice:
                return candidate
        return None


def _is_in_order_by(text: str, position: int) -> bool:
    for token in tokenize(text[:position]):
        if (
            token.kind is JQLTokenKind.KEYWORD
            and ' '.join(token.text.lower().split()) == 'order by'
        ):
            return True
    return False


def _matches(prefix: str, *names: str | None) -> bool:
    if not prefix:
        return True
    prefix = prefix.lower()
    return any(name and prefix in name.lower() for name in names)


def field_candidates(
    cache: JQLReferenceCache, context: JQLCursorContext, order_by: bool = False
) -> list[Candidate]:
    """The fields whose name, or display name, contains what the user has typed."""

    candidates: list[Candidate] = []
    seen: set[str] = set()
    for ref in cache.fields:
        if order_by and not ref.orderable:
            continue
        name = strip_quotes(ref.value)
        if name in seen or not _matches(context.prefix, name, ref.display_name):
            continue
        seen.add(name)
        # the API returns the name the way it is written in an expression; quoted only when it has to be
        insert = f'{ref.value} '
        display_name = html.unescape(ref.display_name) if ref.display_name else ''
        detail = display_name if display_name and display_name != name else ''
        if ref.cfid and ref.cfid not in detail:
            detail = f'{detail} {ref.cfid}'.strip()
        candidates.append(
            Candidate(
                display=name, insert=insert, cursor_offset=len(insert), kind='field', detail=detail
            )
        )
    # the fields whose name starts with what was typed come first
    prefix = context.prefix.lower()
    candidates.sort(key=lambda c: (not c.display.lower().startswith(prefix), c.display.lower()))
    return candidates[:MAXIMUM_SUGGESTIONS]


def operator_candidates(
    cache: JQLReferenceCache, context: JQLCursorContext, text_after: str = ''
) -> list[Candidate]:
    """The operators that the field in scope supports."""

    ref = cache.field_ref(context.field)
    operators = list(ref.operators) if ref else []
    prefix = context.prefix.lower()
    candidates: list[Candidate] = []
    for operator in operators:
        if prefix and not operator.lower().startswith(prefix):
            continue
        insert, offset = operator_completion(operator, text_after)
        candidates.append(
            Candidate(display=operator, insert=insert, cursor_offset=offset, kind='operator')
        )
    return candidates


def keyword_candidates(context: JQLCursorContext) -> list[Candidate]:
    """The keywords that can follow what has been typed; e.g. `and`, `or`, `order by`."""

    prefix = context.prefix.lower()
    candidates: list[Candidate] = []
    for keyword in context.keywords:
        if prefix and not keyword.lower().startswith(prefix):
            continue
        insert = f'{keyword} '
        candidates.append(
            Candidate(display=keyword, insert=insert, cursor_offset=len(insert), kind='keyword')
        )
    return candidates


def function_candidates(
    cache: JQLReferenceCache, context: JQLCursorContext, exclude: Iterable[str] = ()
) -> list[Candidate]:
    """The functions whose result can be compared against the field in scope; e.g. `currentUser()` for `assignee`."""

    ref = cache.field_ref(context.field)
    field_types = set(ref.types) if ref else set()
    excluded = {value.lower() for value in exclude}
    candidates: list[Candidate] = []
    for function in cache.functions:
        if field_types and function.types and not field_types.intersection(function.types):
            continue
        if function.value.lower() in excluded or not _matches(
            context.prefix, function.value, function.display_name
        ):
            continue
        candidates.append(
            Candidate(
                display=function.value,
                insert=function.value,
                cursor_offset=len(function.value),
                kind='function',
            )
        )
    return candidates


async def value_candidates(
    cache: JQLReferenceCache, context: JQLCursorContext, controller: 'APIController'
) -> list[Candidate]:
    """The values of the field in scope, as suggested by the API, followed by the functions that apply to it.

    A value whose readable form differs from the one the API understands (e.g. the name of a user and their account id)
    is suggested by its readable form and recorded as an alias, so that the expression stays readable and the search
    sends what the API understands.
    """

    if not context.field:
        return []
    ref = cache.field_ref(context.field)
    # the API rejects a field name that arrives quoted, and it answers for the id of a custom field, which is not
    # ambiguous the way a name shared by two fields is
    field_name = ref.cfid if ref and ref.cfid else strip_quotes(context.field)
    response = await controller.get_jql_autocomplete_suggestions(
        field_name=field_name, field_value=context.prefix or None
    )
    candidates: list[Candidate] = []
    seen: set[str] = set()
    if response.success and response.result:
        for suggestion in response.result:
            if not suggestion.value:
                continue
            value = strip_quotes(suggestion.value)
            display = suggestion.display_name or value
            if display in seen:
                continue
            seen.add(display)
            if display != value:
                cache.add_alias(context.field, display, value)
            insert = quote_if_needed(display)
            candidates.append(
                Candidate(display=display, insert=insert, cursor_offset=len(insert), kind='value')
            )
    candidates.extend(function_candidates(cache, context, exclude=seen))
    return candidates[:MAXIMUM_SUGGESTIONS]


async def complete(
    text: str,
    cursor: int | None,
    cache: JQLReferenceCache,
    controller: 'APIController | None' = None,
) -> Completion:
    """Works out the suggestions for a position of an expression.

    Args:
        text: the expression; it does not need to be valid or complete.
        cursor: the position of the cursor; the end of the expression when `None`.
        cache: the reference data. It is refreshed with `controller` when it is stale.
        controller: used to fetch the values of a field, and the reference data when it is stale. Without it only the
            fields, the operators and the keywords are suggested.

    Returns:
        The suggestions.
    """

    cursor = len(text) if cursor is None else max(0, min(cursor, len(text)))
    context = context_at(text, cursor)
    candidates: list[Candidate] = []
    if context.context is JQLContext.VALUE:
        if controller is not None:
            candidates = await value_candidates(cache, context, controller)
        else:
            candidates = function_candidates(cache, context)
    elif context.context is JQLContext.FIELD:
        candidates = field_candidates(
            cache, context, order_by=_is_in_order_by(text, context.replace_start)
        )
    elif context.context is JQLContext.OPERATOR:
        candidates = operator_candidates(cache, context, text[context.replace_end :])
    elif context.context is JQLContext.KEYWORD:
        candidates = keyword_candidates(context)
    return Completion(text=text, context=context, candidates=candidates)


def apply_choice(
    text: str, cursor: int | None, choice: str, cache: JQLReferenceCache
) -> tuple[str, int]:
    """Applies a suggestion picked by its display text, without asking the API for the suggestions again.

    This is what a picker that runs as a separate process calls once the user has picked a suggestion printed by
    [complete](#jiratui.utils.jql_completion.complete).

    Args:
        text: the expression.
        cursor: the position of the cursor; the end of the expression when `None`.
        choice: the display text of the suggestion.
        cache: the reference data; used to write the name of a field the way an expression expects it.

    Returns:
        The new expression, and the position of the cursor within it.
    """

    cursor = len(text) if cursor is None else max(0, min(cursor, len(text)))
    context = context_at(text, cursor)
    choice = choice.strip()
    if context.context is JQLContext.FIELD:
        ref = cache.field_ref(choice)
        insert = f'{ref.value if ref else quote_if_needed(choice)} '
        offset = len(insert)
    elif context.context is JQLContext.OPERATOR:
        insert, offset = operator_completion(choice, text[context.replace_end :])
    elif context.context is JQLContext.VALUE:
        insert = quote_if_needed(choice)
        offset = len(insert)
    else:
        insert = f'{choice} '
        offset = len(insert)
    completion = Completion(text=text, context=context, candidates=[])
    return completion.apply(Candidate(display=choice, insert=insert, cursor_offset=offset, kind=''))


def needs_api(text: str, cursor: int | None) -> bool:
    """Whether completing at a position requires the API, regardless of the state of the cache."""

    cursor = len(text) if cursor is None else cursor
    return context_at(text, cursor).context is JQLContext.VALUE
