"""This module provides the widgets that autocomplete a JQL expression.

The widgets suggest the names of the fields, the operators that apply to a field, and the values of a field; the same
way the Jira web UI does.

```{important}
Only the values of a field require a call to the API. The names of the fields and the operators come from the JQL
reference data, which is fetched once per session; otherwise every keystroke would hit the network.
```
"""

import asyncio
import logging
from typing import Any, cast

from textual import events
from textual.document._document import Document
from textual.timer import Timer
from textual.widgets import Input, TextArea
from textual_autocomplete import AutoComplete, DropdownItem, TargetState

from jiratui.api_controller.controller import APIController, APIControllerResponse
from jiratui.constants import LOGGER_NAME
from jiratui.models import JQLAutocompleteSuggestion, JQLFieldRef
from jiratui.utils.jql import (
    JQLContext,
    JQLCursorContext,
    context_at,
    operator_completion,
    quote_if_needed,
    strip_quotes,
)
from jiratui.utils.session import ApplicationSession

logger = logging.getLogger(LOGGER_NAME)

MINIMUM_VALUE_QUERY_LENGTH = 0
"""The number of characters that the user needs to type before the values of a field are fetched from the API.

The Jira web UI lists the values of a field as soon as the field is in scope, before anything is typed, and the API
answers with every value when no partial value is passed to it. The debounce below, and the exclusive worker that runs
the query, are what keep that from turning into a request per keystroke.
"""

MAXIMUM_SUGGESTIONS = 50
"""The number of suggestions displayed at once."""

VALUE_QUERY_DEBOUNCE_SECONDS = 0.3
"""How long the user has to stop typing before the values of a field are fetched from the API."""

SUGGESTIONS_WORKER_GROUP = 'jql-suggestions'
"""The group of the workers that fetch the values of a field. Only one of them runs at a time."""

REFERENCE_DATA_WORKER_GROUP = 'jql-reference-data'
"""The group of the workers that load the JQL reference data."""

SUGGESTION_NAVIGATION_KEYS = {'ctrl+n': 1, 'ctrl+p': -1}
"""The keys that move the highlight of the dropdown, and the direction in which each of them moves it.

The dropdown of `textual-autocomplete` recognises the arrow keys only; these are the readline keys that a terminal
user reaches for. They are claimed only while the dropdown is displayed, so that `ctrl+n` still creates a work item,
and `ctrl+p` still opens the command palette, when there are no suggestions on screen.
"""

_reference_data_lock = asyncio.Lock()
"""Serialises the load of the JQL reference data so that the widgets do not fetch it once each."""


def jql_value_aliases() -> dict[tuple[str, str], str]:
    """The readable values displayed to the user, mapped to the values that the API understands.

    An entry is added for every value suggested by the API; e.g. suggesting the user `Naga Kiran K -
    naga@example.com` for the field `Dev Engineers` records their account id, so that the expression can show the name
    and the search can send the id.

    **See Also**:
    - [resolve_values](#jiratui.utils.jql.resolve_values)
    """

    session = ApplicationSession()
    aliases: dict[tuple[str, str], str] | None = session.get('jql_value_aliases')
    if aliases is None:
        aliases = {}
        session.jql_value_aliases = aliases
    return aliases


class JQLAutoCompleteMixin:
    """The logic shared by the widgets that autocomplete a JQL expression.

    The names of the fields, the operators and the keywords are suggested from the reference data cached in the
    session, so they are resolved without leaving the event loop. The values of a field are the only suggestions that
    need the API: those are fetched by a worker, once the user stops typing, so that a query is not sent for every
    keystroke.
    """

    def _init_jql(self, api_controller: APIController) -> None:
        self._api_controller = api_controller
        self._cached_suggestions: list[DropdownItem] = []
        self._last_query: tuple | None = None
        self._jql_context: JQLCursorContext | None = None
        self._value_query_timer: Timer | None = None

    @property
    def _jql_fields(self) -> list[JQLFieldRef]:
        return ApplicationSession().get('jql_fields') or []

    @property
    def _jql_field_index(self) -> dict[str, JQLFieldRef]:
        """The fields of the reference data, keyed by the names that an expression may refer to them by.

        The API returns the name of a field the way it would be written in an expression, so a name that needs
        quoting arrives quoted; the tokenizer hands back the name of a field without its quotes, so the index is
        keyed by the unquoted name. The display name is indexed as well, because that is the name that the user
        recognises.
        """

        session = ApplicationSession()
        index: dict[str, JQLFieldRef] | None = session.get('jql_field_index')
        if index is None:
            index = {}
            for jql_field in self._jql_fields:
                index.setdefault(strip_quotes(jql_field.value).lower(), jql_field)
                if jql_field.display_name:
                    index.setdefault(jql_field.display_name.lower(), jql_field)
            session.jql_field_index = index
        return index

    def _field_ref(self, name: str | None) -> JQLFieldRef | None:
        """The entry of the reference data that a name refers to; `None` when the name is not a known field."""

        if not name:
            return None
        return self._jql_field_index.get(strip_quotes(name).lower())

    @property
    def _jql_functions(self) -> list[JQLFieldRef]:
        return ApplicationSession().get('jql_functions') or []

    @property
    def _reference_data_loaded(self) -> bool:
        return ApplicationSession().get('jql_fields') is not None

    async def _load_reference_data(self) -> None:
        """Loads the fields and functions that can be referenced in a JQL expression.

        The data is cached in the session because it does not change while the app is running.
        """

        if self._reference_data_loaded:
            return
        async with _reference_data_lock:
            session = ApplicationSession()
            if session.get('jql_fields') is not None:
                # another widget loaded the data while this one waited for the lock
                return
            response: APIControllerResponse = await self._api_controller.get_jql_autocomplete_data()
            if response.success and response.result:
                session.jql_fields = response.result.visible_field_names
                session.jql_functions = response.result.visible_function_names
                session.jql_field_index = None
            else:
                # the app degrades to suggesting only the values of the fields
                logger.debug('Unable to load the JQL autocomplete data')
                session.jql_fields = []
                session.jql_functions = []
                session.jql_field_index = None

    def _get_candidates(self, target_state: TargetState) -> list[DropdownItem]:
        context = context_at(target_state.text, target_state.cursor_position)
        self._jql_context = context
        if context.context is JQLContext.NONE:
            return []
        query = (context.context, context.prefix, context.field)
        if query != self._last_query:
            self._last_query = query
            if context.context is JQLContext.VALUE:
                # the values live in Jira, so the fetch waits until the user stops typing
                self._schedule_value_query(context)
            elif self._reference_data_loaded:
                self._cached_suggestions = self._local_suggestions(context)
            else:
                # the first suggestion of the session has to wait for the reference data
                self._start_reference_data_load(context)
        return self._cached_suggestions

    def _local_suggestions(self, context: JQLCursorContext) -> list[DropdownItem]:
        """The suggestions resolved from the data cached in the session, without calling the API."""

        if context.context is JQLContext.FIELD:
            return self._field_suggestions(context.prefix)
        if context.context is JQLContext.OPERATOR:
            return self._operator_suggestions(context)
        if context.context is JQLContext.KEYWORD:
            return self._keyword_suggestions(context)
        return []

    def _start_reference_data_load(self, context: JQLCursorContext) -> None:
        self.run_worker(  # type:ignore[attr-defined]
            self._fetch_reference_data(context),
            group=REFERENCE_DATA_WORKER_GROUP,
            exclusive=True,
        )

    async def _fetch_reference_data(self, context: JQLCursorContext) -> None:
        """Loads the reference data and then re-opens the dropdown with the suggestions it provides."""

        try:
            await self._load_reference_data()
            self._cached_suggestions = self._local_suggestions(context)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # a failure while the user types must never interrupt them
            logger.debug(f'Unable to load the JQL reference data: {e}', exc_info=True)
            self._cached_suggestions = []
        self._handle_target_update()  # type:ignore[attr-defined]

    def _schedule_value_query(self, context: JQLCursorContext) -> None:
        """Asks for the values of a field once the user has stopped typing for a moment.

        Every keystroke moves the deadline, so typing a name results in one query rather than one per character.
        """

        if self._value_query_timer is not None:
            self._value_query_timer.stop()
        self._value_query_timer = self.set_timer(  # type:ignore[attr-defined]
            VALUE_QUERY_DEBOUNCE_SECONDS, lambda: self._start_value_query(context)
        )

    def _start_value_query(self, context: JQLCursorContext) -> None:
        # the worker is exclusive, so a query that is still in flight is cancelled by this one; without that, a slow
        # response could arrive after a newer one and put stale suggestions back in the dropdown
        self.run_worker(  # type:ignore[attr-defined]
            self._fetch_values(context),
            group=SUGGESTIONS_WORKER_GROUP,
            exclusive=True,
        )

    async def _fetch_values(self, context: JQLCursorContext) -> None:
        """Fetches the values of a field and re-opens the dropdown with them."""

        try:
            self._cached_suggestions = await self._value_suggestions(context)
        except asyncio.CancelledError:
            # a newer query replaced this one; its suggestions are not wanted any more
            raise
        except Exception as e:
            # a failure while the user types must never interrupt them
            logger.debug(f'Unable to fetch JQL suggestions: {e}', exc_info=True)
            self._cached_suggestions = []
        self._handle_target_update()  # type:ignore[attr-defined]

    def _field_suggestions(self, prefix: str) -> list[DropdownItem]:
        prefix = prefix.lower()
        items: list[DropdownItem] = []
        for jql_field in self._jql_fields:
            # the API returns the name of a field the way it would be written in an expression, so a name that needs
            # quoting arrives quoted; the quotes are noise in the dropdown, but the expression needs them back
            name = strip_quotes(jql_field.value)
            display = jql_field.display_name or name
            if prefix and prefix not in display.lower() and prefix not in name.lower():
                continue
            items.append(DropdownItem(main=name, id=jql_field.value))
        return items[:MAXIMUM_SUGGESTIONS]

    def _operator_suggestions(self, context: JQLCursorContext) -> list[DropdownItem]:
        jql_field = self._field_ref(context.field)
        operators: list[str] = list(jql_field.operators) if jql_field else []
        prefix = context.prefix.lower()
        return [
            DropdownItem(main=operator, id=operator)
            for operator in operators
            if not prefix or operator.lower().startswith(prefix)
        ][:MAXIMUM_SUGGESTIONS]

    def _keyword_suggestions(self, context: JQLCursorContext) -> list[DropdownItem]:
        prefix = context.prefix.lower()
        keywords = list(context.keywords)
        keywords.extend(
            jql_function.value
            for jql_function in self._jql_functions
            if jql_function.value not in keywords
        )
        return [
            DropdownItem(main=keyword, id=keyword)
            for keyword in keywords
            if not prefix or keyword.lower().startswith(prefix)
        ][:MAXIMUM_SUGGESTIONS]

    async def _value_suggestions(self, context: JQLCursorContext) -> list[DropdownItem]:
        if not context.field or len(context.prefix) < MINIMUM_VALUE_QUERY_LENGTH:
            return []
        jql_field = self._field_ref(context.field)
        # the API rejects a field name that arrives quoted, and it answers for the id of a custom field, which is not
        # ambiguous the way a name shared by two fields is
        field_name = jql_field.cfid if jql_field and jql_field.cfid else strip_quotes(context.field)
        response: APIControllerResponse = (
            await self._api_controller.get_jql_autocomplete_suggestions(
                field_name=field_name, field_value=context.prefix
            )
        )
        if not response.success or not response.result:
            return []
        items: list[DropdownItem] = []
        suggestion: JQLAutocompleteSuggestion
        for suggestion in response.result:
            if not suggestion.value:
                continue
            # the API returns the value the way it would be written in an expression, so a value that needs quoting
            # arrives quoted; the alias holds the value on its own, because the expression quotes it when it needs to
            value = strip_quotes(suggestion.value)
            display = suggestion.display_name or value
            if display != value:
                # the expression shows the readable value; the search sends the one the API understands
                jql_value_aliases()[(context.field.lower(), display)] = value
            items.append(DropdownItem(main=display, id=display))
        return items[:MAXIMUM_SUGGESTIONS]

    def _handle_target_update(self) -> None:
        """Re-evaluates the dropdown after the state of the target changed.

        ```{important}
        `AutoComplete` keeps the dropdown on screen by constraining it against the size of the list of suggestions,
        but it does so in the same breath as replacing those suggestions, before the new ones have been laid out — so
        it constrains against the size of the *previous* list. When the new suggestions are wider, the dropdown is
        left overflowing the right edge of the screen and the end of every suggestion is cut off. Aligning it again
        once the list has been laid out is what puts it back on screen.
        ```
        """

        super()._handle_target_update()  # type:ignore[misc]
        self.call_after_refresh(self._align_to_target)  # type:ignore[attr-defined]

    def get_search_string(self, target_state: TargetState) -> str:
        """The text that the user has typed at the position of the cursor."""

        return context_at(target_state.text, target_state.cursor_position).prefix

    @property
    def is_open(self) -> bool:
        """Whether the dropdown is displaying suggestions."""

        return bool(self.display)  # type:ignore[attr-defined]

    def complete_highlighted(self) -> None:
        """Applies the suggestion that is currently highlighted in the dropdown.

        This is what a target widget calls when it claims the key that selects a suggestion before the dropdown gets a
        chance to see it.
        """

        option_list = self.option_list  # type:ignore[attr-defined]
        self._complete(option_index=option_list.highlighted or 0)  # type:ignore[attr-defined]

    def move_highlight(self, delta: int) -> bool:
        """Moves the highlight of the dropdown by `delta` suggestions, wrapping around at both ends.

        Returns:
            `True` when the dropdown moved its highlight, i.e. when it consumed the key; `False` when the key belongs
            to whoever else wants it.
        """

        if not self.is_open:
            return False
        option_list = self.option_list  # type:ignore[attr-defined]
        if not option_list.option_count:
            return False
        option_list.highlighted = (
            (option_list.highlighted or 0) + delta
        ) % option_list.option_count
        return True

    def _completion_text(self, value: str, text_after: str = '') -> tuple[str, int]:
        """The text to insert in the expression for a selected suggestion, and the cursor position within it."""

        context = self._jql_context
        option_id = self._selected_option_id() or value
        if context is None:
            return option_id, len(option_id)
        if context.context is JQLContext.FIELD:
            # the API returns the name of a field the way it would be written in an expression: quoted when it needs
            # quoting, and bare when it must not be quoted -- `development[builds].failing` is a field that Jira does
            # not resolve once it is quoted. So the name is written as it arrived, and the operator that follows it
            # gets the space that the user would otherwise type
            text = f'{option_id} '
            return text, len(text)
        if context.context is JQLContext.VALUE:
            # a quoted value is replaced along with its quotes, so the suggestion is quoted whether the user typed the
            # opening quote or not
            text = quote_if_needed(option_id)
            return text, len(text)
        if context.context is JQLContext.OPERATOR:
            return operator_completion(option_id, text_after)
        return option_id, len(option_id)

    def _selected_option_id(self) -> str | None:
        option_list = self.option_list  # type:ignore[attr-defined]
        if option_list.highlighted is None:
            return None
        return option_list.get_option_at_index(option_list.highlighted).id


class JQLDropdownKeysMixin:
    """Lets a widget that holds a JQL expression claim the keys of its dropdown before acting on them itself.

    ```{important}
    `AutoComplete` watches the keys of its target through the `message_signal`, which Textual publishes only *after*
    the target has handled the event and started to bubble it, so a handler on that signal cannot keep a key from
    reaching the bindings of the screen or of the app. The key has to be claimed here, in the target itself.
    ```
    """

    jql_autocomplete: 'JQLAutoCompleteMixin | None' = None
    """The dropdown attached to this widget; set by the dropdown itself."""

    def _claim_navigation_key(self, event: events.Key) -> bool:
        """Moves the highlight of the dropdown if the key belongs to it.

        Returns:
            `True` when the dropdown consumed the key, in which case the widget must not act on it.
        """

        delta = SUGGESTION_NAVIGATION_KEYS.get(event.key)
        if delta is None or self.jql_autocomplete is None:
            return False
        if not self.jql_autocomplete.move_highlight(delta):
            return False
        event.stop()
        event.prevent_default()
        return True

    def check_consume_key(self, key: str, character: str | None = None) -> bool:
        """Claims the keys that navigate the dropdown while it is displayed.

        ```{important}
        `ctrl+p` opens the command palette through a *priority* binding of the app, which Textual runs before the
        focused widget sees the key. Declaring the key as consumed is what takes that binding — and the `ctrl+n` of
        the main screen — out of the binding chain while the dropdown is open; without it the key never reaches
        `_claim_navigation_key`.
        ```
        """

        if key in SUGGESTION_NAVIGATION_KEYS and self.jql_autocomplete is not None:
            if self.jql_autocomplete.is_open:
                return True
        return super().check_consume_key(key, character)  # type:ignore[misc]


class JQLInputAutoComplete(JQLAutoCompleteMixin, AutoComplete):
    """Autocompletes the JQL expression typed in an [Input](#textual.widgets.Input)."""

    def __init__(self, target: Input, api_controller: APIController, **kwargs: Any):
        """Initializes the widget.

        Args:
            target: the Input widget that holds the JQL expression.
            api_controller: the controller used to fetch the suggestions.
        """

        self._init_jql(api_controller)
        super().__init__(target=target, candidates=self._get_candidates, **kwargs)  # type:ignore[arg-type]
        if isinstance(target, JQLDropdownKeysMixin):
            target.jql_autocomplete = self

    def apply_completion(self, value: str, state: TargetState) -> None:
        """Replaces the text that the user is typing with the selected suggestion."""

        context = context_at(state.text, state.cursor_position)
        self._jql_context = context
        text_after = state.text[context.replace_end :]
        text, offset = self._completion_text(value, text_after)
        target: Input = self.target
        target.value = f'{state.text[: context.replace_start]}{text}{text_after}'
        target.cursor_position = context.replace_start + offset


class JQLTextArea(JQLDropdownKeysMixin, TextArea):
    """A [TextArea](#textual.widgets.TextArea) that lets a dropdown claim the keys that navigate and select a
    suggestion.

    ```{important}
    A `TextArea` inserts a newline, or an indent, from within its own key handler. `AutoComplete` watches the keys of
    its target through the `message_signal`, which Textual publishes only *after* the target has handled the event, so
    by then the newline is already in the document and preventing the default achieves nothing. The key has to be
    claimed here, before the editor acts on it.
    ```
    """

    async def _on_key(self, event: events.Key) -> None:
        if self._claim_navigation_key(event):
            return
        autocomplete = self.jql_autocomplete
        if autocomplete is not None and autocomplete.is_open and event.key in ('enter', 'tab'):
            event.stop()
            event.prevent_default()
            autocomplete.complete_highlighted()
            return
        await super()._on_key(event)


class JQLTextAreaAutoComplete(JQLAutoCompleteMixin, AutoComplete):
    """Autocompletes the JQL expression typed in a [TextArea](#textual.widgets.TextArea).

    ```{important}
    `AutoComplete` is written for an `Input`: it asserts that the target is an `Input`, and it reads the `value` and
    the `cursor_position` of the target, which a `TextArea` does not have. This class overrides the members that read
    the state of the target so that the same dropdown can be attached to the editor.
    ```
    """

    def __init__(self, target: JQLTextArea, api_controller: APIController, **kwargs: Any):
        """Initializes the widget.

        Args:
            target: the editor that holds the JQL expression.
            api_controller: the controller used to fetch the suggestions.
        """

        self._init_jql(api_controller)
        super().__init__(target=target, candidates=self._get_candidates, **kwargs)  # type:ignore[arg-type]
        target.jql_autocomplete = self

    @property
    def target(self) -> JQLTextArea:  # type:ignore[override]
        """The editor that holds the expression."""

        if isinstance(self._target, JQLTextArea):
            return self._target
        target = self.screen.query_one(cast(str, self._target))
        assert isinstance(target, JQLTextArea)
        return target

    def _subscribe_to_target(self) -> None:
        """Watches the state of the editor.

        ```{important}
        `AutoComplete` re-evaluates the dropdown when the target posts `Input.Changed`, and a `TextArea` never posts
        that message; it only updates its `selection`, which the base class watches with a handler that rebuilds the
        suggestions without deciding whether to display them. So the editor watches `selection` with the handler that
        does both; otherwise the dropdown would hold the right suggestions and never appear.
        ```
        """

        target = self.target
        self.watch(target, 'has_focus', self._handle_focus_change)
        self.watch(target, 'selection', self._handle_target_update)

    @property
    def _document(self) -> Document:
        # the methods that convert between a location and an index are not declared by DocumentBase
        return cast(Document, self.target.document)

    def _get_target_state(self) -> TargetState:
        """The text of the editor and the position of the cursor within it.

        The position of the cursor of a `TextArea` is a (row, column) location; the tokenizer works on the flat text,
        so the location is converted into an index.
        """

        target = self.target
        return TargetState(
            text=target.text,
            cursor_position=self._document.get_index_from_location(target.selection.end),
        )

    def apply_completion(self, value: str, state: TargetState) -> None:
        """Replaces the text that the user is typing with the selected suggestion."""

        context = context_at(state.text, state.cursor_position)
        self._jql_context = context
        text, offset = self._completion_text(value, state.text[context.replace_end :])
        document = self._document
        self.target.replace(
            text,
            document.get_location_from_index(context.replace_start),
            document.get_location_from_index(context.replace_end),
        )
        self.target.move_cursor(document.get_location_from_index(context.replace_start + offset))
