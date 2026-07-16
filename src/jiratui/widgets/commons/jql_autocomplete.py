"""This module provides the widgets that autocomplete a JQL expression.

The widgets suggest the names of the fields, the operators that apply to a field, and the values of a field; the same
way the Jira web UI does.

```{important}
Only the values of a field require a call to the API. The names of the fields and the operators come from the JQL
reference data, which is fetched once per session; otherwise every keystroke would hit the network.
```
"""

import logging
from typing import Any, cast

from textual.document._document import Document
from textual.widgets import Input, TextArea
from textual_autocomplete import AutoComplete, DropdownItem, TargetState

from jiratui.api_controller.controller import APIController, APIControllerResponse
from jiratui.constants import LOGGER_NAME
from jiratui.models import JQLAutocompleteSuggestion, JQLFieldRef
from jiratui.utils.jql import JQLContext, JQLCursorContext, context_at
from jiratui.utils.session import ApplicationSession

logger = logging.getLogger(LOGGER_NAME)

MINIMUM_VALUE_QUERY_LENGTH = 1
"""The number of characters that the user needs to type before the values of a field are fetched from the API."""

MAXIMUM_SUGGESTIONS = 50
"""The number of suggestions displayed at once."""


def quote_if_needed(value: str) -> str:
    """Quotes a value of a JQL expression when it cannot be used as-is.

    Args:
        value: the value to use in the expression.

    Returns:
        The value, quoted if it contains a character that would make the expression invalid.
    """

    if not value:
        return value
    if value.endswith('()'):
        # a function; e.g.: currentUser()
        return value
    if any(character in value for character in ' ",()[]{}'):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


class JQLAutoCompleteMixin:
    """The logic shared by the widgets that autocomplete a JQL expression.

    The suggestions are fetched following the pattern used by the other autocomplete widgets of the app: the callback
    that provides the candidates is synchronous, so it returns the cached suggestions and schedules the fetch of the
    new ones; the fetch then asks the dropdown to re-evaluate itself.
    """

    def _init_jql(self, api_controller: APIController) -> None:
        self._api_controller = api_controller
        self._cached_suggestions: list[DropdownItem] = []
        self._last_query: tuple | None = None
        self._jql_context: JQLCursorContext | None = None
        self._reference_loaded = False

    @property
    def _jql_fields(self) -> list[JQLFieldRef]:
        return ApplicationSession().get('jql_fields') or []

    @property
    def _jql_functions(self) -> list[JQLFieldRef]:
        return ApplicationSession().get('jql_functions') or []

    async def _load_reference_data(self) -> None:
        """Loads the fields and functions that can be referenced in a JQL expression.

        The data is cached in the session because it does not change while the app is running.
        """

        session = ApplicationSession()
        if session.get('jql_fields') is not None:
            return
        response: APIControllerResponse = await self._api_controller.get_jql_autocomplete_data()
        if response.success and response.result:
            session.jql_fields = response.result.visible_field_names
            session.jql_functions = response.result.visible_function_names
        else:
            # the app degrades to suggesting only the values of the fields
            logger.debug('Unable to load the JQL autocomplete data')
            session.jql_fields = []
            session.jql_functions = []

    def _get_candidates(self, target_state: TargetState) -> list[DropdownItem]:
        context = context_at(target_state.text, target_state.cursor_position)
        self._jql_context = context
        if context.context is JQLContext.NONE:
            return []
        query = (context.context, context.prefix, context.field)
        if query != self._last_query:
            self._last_query = query
            self.call_later(self._fetch, context)  # type:ignore[attr-defined]
        return self._cached_suggestions

    def _field_suggestions(self, prefix: str) -> list[DropdownItem]:
        prefix = prefix.lower()
        items: list[DropdownItem] = []
        for jql_field in self._jql_fields:
            display = jql_field.display_name or jql_field.value
            if prefix and prefix not in display.lower() and prefix not in jql_field.value.lower():
                continue
            items.append(DropdownItem(main=jql_field.value, id=jql_field.value))
        return items[:MAXIMUM_SUGGESTIONS]

    def _operator_suggestions(self, context: JQLCursorContext) -> list[DropdownItem]:
        operators: list[str] = []
        for jql_field in self._jql_fields:
            if context.field and jql_field.value.lower() == context.field.lower():
                operators = list(jql_field.operators)
                break
            if context.field and (jql_field.display_name or '').lower() == context.field.lower():
                operators = list(jql_field.operators)
                break
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
        response: APIControllerResponse = (
            await self._api_controller.get_jql_autocomplete_suggestions(
                field_name=context.field, field_value=context.prefix
            )
        )
        if not response.success or not response.result:
            return []
        items: list[DropdownItem] = []
        suggestion: JQLAutocompleteSuggestion
        for suggestion in response.result:
            if not suggestion.value:
                continue
            items.append(
                DropdownItem(main=suggestion.display_name or suggestion.value, id=suggestion.value)
            )
        return items[:MAXIMUM_SUGGESTIONS]

    async def _fetch(self, context: JQLCursorContext) -> None:
        """Fetches the suggestions for a position of the expression and re-opens the dropdown."""

        try:
            await self._load_reference_data()
            if context.context is JQLContext.FIELD:
                self._cached_suggestions = self._field_suggestions(context.prefix)
            elif context.context is JQLContext.OPERATOR:
                self._cached_suggestions = self._operator_suggestions(context)
            elif context.context is JQLContext.KEYWORD:
                self._cached_suggestions = self._keyword_suggestions(context)
            elif context.context is JQLContext.VALUE:
                self._cached_suggestions = await self._value_suggestions(context)
            else:
                self._cached_suggestions = []
        except Exception as e:
            # a failure while the user types must never interrupt them
            logger.debug(f'Unable to fetch JQL suggestions: {e}', exc_info=True)
            self._cached_suggestions = []
        self._handle_target_update()  # type:ignore[attr-defined]

    def get_search_string(self, target_state: TargetState) -> str:
        """The text that the user has typed at the position of the cursor."""

        return context_at(target_state.text, target_state.cursor_position).prefix

    def _completion_text(self, value: str) -> str:
        """The text to insert in the expression for a selected suggestion."""

        context = self._jql_context
        option_id = self._selected_option_id() or value
        if context is None:
            return option_id
        if context.context is JQLContext.VALUE:
            # the value is already inside a pair of quotes, so it must not be quoted again
            return option_id if context.quoted else quote_if_needed(option_id)
        if context.context is JQLContext.FIELD:
            return option_id if context.quoted else quote_if_needed(option_id)
        return option_id

    def _selected_option_id(self) -> str | None:
        option_list = self.option_list  # type:ignore[attr-defined]
        if option_list.highlighted is None:
            return None
        return option_list.get_option_at_index(option_list.highlighted).id


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

    def apply_completion(self, value: str, state: TargetState) -> None:
        """Replaces the text that the user is typing with the selected suggestion."""

        context = context_at(state.text, state.cursor_position)
        self._jql_context = context
        text = self._completion_text(value)
        target: Input = self.target
        new_value = (
            f'{state.text[: context.replace_start]}{text}{state.text[context.replace_end :]}'
        )
        cursor = context.replace_start + len(text)
        if context.context in (JQLContext.FIELD, JQLContext.OPERATOR):
            # the next part of the clause follows, so the user does not need to type the space
            new_value = f'{new_value[:cursor]} {new_value[cursor:]}'
            cursor += 1
        target.value = new_value
        target.cursor_position = cursor


class JQLTextAreaAutoComplete(JQLAutoCompleteMixin, AutoComplete):
    """Autocompletes the JQL expression typed in a [TextArea](#textual.widgets.TextArea).

    ```{important}
    `AutoComplete` is written for an `Input`: it asserts that the target is an `Input`, and it reads the `value` and
    the `cursor_position` of the target, which a `TextArea` does not have. This class overrides the members that read
    the state of the target so that the same dropdown can be attached to the editor. The rest of the behaviour of
    `AutoComplete` works unchanged because a `TextArea` does provide the `selection` reactive, the `message_signal`
    and the `cursor_screen_offset` that it subscribes to.
    ```
    """

    def __init__(self, target: TextArea, api_controller: APIController, **kwargs: Any):
        """Initializes the widget.

        Args:
            target: the TextArea widget that holds the JQL expression.
            api_controller: the controller used to fetch the suggestions.
        """

        self._init_jql(api_controller)
        super().__init__(target=target, candidates=self._get_candidates, **kwargs)  # type:ignore[arg-type]

    @property
    def target(self) -> TextArea:  # type:ignore[override]
        """The TextArea that holds the expression."""

        if isinstance(self._target, TextArea):
            return self._target
        target = self.screen.query_one(cast(str, self._target))
        assert isinstance(target, TextArea)
        return target

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
        text = self._completion_text(value)
        if context.context in (JQLContext.FIELD, JQLContext.OPERATOR):
            # the next part of the clause follows, so the user does not need to type the space
            text = f'{text} '
        document = self._document
        self.target.replace(
            text,
            document.get_location_from_index(context.replace_start),
            document.get_location_from_index(context.replace_end),
        )
        self.target.move_cursor(document.get_location_from_index(context.replace_start + len(text)))
