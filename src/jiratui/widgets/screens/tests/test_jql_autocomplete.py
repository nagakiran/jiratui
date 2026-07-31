from unittest.mock import AsyncMock, MagicMock, Mock, patch

from pydantic import SecretStr
import pytest
from textual.command import CommandPalette
from textual.widgets import TextArea

from jiratui.api_controller.controller import APIController, APIControllerResponse
from jiratui.app import JiraApp
from jiratui.config import ApplicationConfiguration
from jiratui.models import (
    JQLAutocompleteData,
    JQLAutocompleteSuggestion,
    JQLFieldRef,
    WorkItemsSearchOrderBy,
)
from jiratui.utils.columns import DEFAULT_COLUMNS
from jiratui.utils.jql import quote_if_needed
from jiratui.utils.session import ApplicationSession
from jiratui.widgets.commons.jql_autocomplete import (
    VALUE_QUERY_DEBOUNCE_SECONDS,
    JQLInputAutoComplete,
    jql_value_aliases,
)
from jiratui.widgets.screen import MainScreen
from jiratui.widgets.screens.jql import JQLEditorScreen

REFERENCE_DATA = JQLAutocompleteData(
    visible_field_names=[
        JQLFieldRef(
            value='project', display_name='project', operators=['=', '!=', 'in'], orderable=True
        ),
        JQLFieldRef(
            value='"Dev Engineers"',
            display_name='Dev Engineers',
            operators=['=', 'in'],
            cfid='customfield_10343',
        ),
    ],
    visible_function_names=[JQLFieldRef(value='currentUser()')],
)

SUGGESTIONS = [
    JQLAutocompleteSuggestion(
        value='nagakiran@juniper.net', display_name='Naga Kiran K - nagakiran@juniper.net'
    ),
    JQLAutocompleteSuggestion(
        value='hnagaraja@juniper.net', display_name='Hegde, Nagaraja - hnagaraja@juniper.net'
    ),
]


@pytest.fixture()
def app() -> JiraApp:
    config_mock = Mock(spec=ApplicationConfiguration)
    config_mock.configure_mock(
        jira_api_base_url='foo.bar',
        jira_api_username='foo',
        jira_api_token=SecretStr('bar'),
        jira_api_version=3,
        use_bearer_authentication=False,
        cloud=True,
        ignore_users_without_email=True,
        default_project_key_or_id=None,
        active_sprint_on_startup=False,
        jira_account_id=None,
        tui_title=None,
        tui_custom_title=None,
        tui_title_include_jira_server_title=False,
        on_start_up_only_fetch_projects=False,
        log_file='',
        log_level='ERROR',
        theme=None,
        search_results_page_filtering_enabled=False,
        ssl=None,
        search_results_default_order=WorkItemsSearchOrderBy.CREATED_DESC,
        search_on_startup=False,
        show_keybinding_hints=False,
        enable_recent_history=False,
        enable_goto=False,
        search_results_columns=list(DEFAULT_COLUMNS),
        search_results_column_widths=None,
        pre_defined_jql_expressions=None,
    )
    app = JiraApp(config_mock)
    app.api = APIController(config_mock)
    app._setup_logging = MagicMock()  # type:ignore[method-assign]
    return app


@pytest.fixture(autouse=True)
def clear_session():
    ApplicationSession().clear()
    yield
    ApplicationSession().clear()


@pytest.fixture()
def suggestions_mock() -> AsyncMock:
    return AsyncMock(return_value=APIControllerResponse(result=SUGGESTIONS))


@pytest.fixture()
def reference_data_mock() -> AsyncMock:
    return AsyncMock(return_value=APIControllerResponse(result=REFERENCE_DATA))


async def open_editor(app, pilot, text: str, cursor: tuple[int, int] | None = None):
    await app.push_screen(JQLEditorScreen(''))
    await pilot.pause()
    screen = app.screen
    editor = screen.query_one('#jql-editor', expect_type=TextArea)
    editor.focus()
    await pilot.pause()
    editor.text = text
    editor.move_cursor(cursor if cursor else (0, len(text)))
    await pilot.pause()
    # the values of a field are only fetched once the user stops typing
    await pilot.pause(VALUE_QUERY_DEBOUNCE_SECONDS + 0.1)
    return screen, editor, screen.autocomplete


def dropdown_options(autocomplete) -> list[str]:
    option_list = autocomplete.option_list
    return [
        str(option_list.get_option_at_index(index).prompt)
        for index in range(option_list.option_count)
    ]


@pytest.mark.parametrize(
    'value, expected',
    [
        pytest.param('SB', 'SB', id='no-quotes-needed'),
        pytest.param('In Progress', '"In Progress"', id='contains-a-space'),
        pytest.param('a,b', '"a,b"', id='contains-a-comma'),
        pytest.param('currentUser()', 'currentUser()', id='a-function-is-not-quoted'),
        pytest.param('say "hi"', '"say \\"hi\\""', id='escapes-quotes'),
        pytest.param('', '', id='empty'),
    ],
)
def test_quote_if_needed(value, expected):
    assert quote_if_needed(value) == expected


@pytest.mark.asyncio
async def test_field_names_are_suggested_without_calling_the_api(
    app, reference_data_mock, suggestions_mock
):
    # the names of the fields come from the reference data; hitting the API on every keystroke would be too slow
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, _, autocomplete = await open_editor(app, pilot, 'pro')
            assert dropdown_options(autocomplete) == ['project']
            suggestions_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_operators_of_a_field_are_suggested_without_calling_the_api(
    app, reference_data_mock, suggestions_mock
):
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, _, autocomplete = await open_editor(app, pilot, 'project ')
            assert dropdown_options(autocomplete) == ['=', '!=', 'in']
            suggestions_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_values_of_a_field_are_fetched_from_the_api(
    app, reference_data_mock, suggestions_mock
):
    # this is the expression of the Jira web UI: "Dev Engineers" in (naga
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, _, autocomplete = await open_editor(app, pilot, '"Dev Engineers" in (naga')
            assert dropdown_options(autocomplete) == [
                'Naga Kiran K - nagakiran@juniper.net',
                'Hegde, Nagaraja - hnagaraja@juniper.net',
            ]
            assert suggestions_mock.await_args.kwargs == {
                'field_name': 'Dev Engineers',
                'field_value': 'naga',
            }


@pytest.mark.asyncio
async def test_applying_a_value_inserts_the_display_name_and_records_its_alias(
    app, reference_data_mock, suggestions_mock
):
    # the expression shows the value the way the user recognises it; `resolve_values` puts back the value that the
    # API issued when the search runs
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, editor, autocomplete = await open_editor(app, pilot, '"Dev Engineers" in (naga')
            # WHEN
            autocomplete.option_list.highlighted = 0
            autocomplete.apply_completion(
                'Naga Kiran K - nagakiran@juniper.net', autocomplete._get_target_state()
            )
            await pilot.pause()
            # THEN
            assert editor.text == '"Dev Engineers" in ("Naga Kiran K - nagakiran@juniper.net"'
            assert jql_value_aliases() == {
                ('dev engineers', 'Naga Kiran K - nagakiran@juniper.net'): 'nagakiran@juniper.net',
                (
                    'dev engineers',
                    'Hegde, Nagaraja - hnagaraja@juniper.net',
                ): 'hnagaraja@juniper.net',
            }


@pytest.mark.asyncio
async def test_applying_a_field_appends_a_space(app, reference_data_mock, suggestions_mock):
    # the operator follows the field, so the user does not need to type the space
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, editor, autocomplete = await open_editor(app, pilot, 'pro')
            autocomplete.option_list.highlighted = 0
            autocomplete.apply_completion('project', autocomplete._get_target_state())
            await pilot.pause()
            assert editor.text == 'project '


@pytest.mark.asyncio
async def test_applying_the_in_operator_opens_a_list(app, reference_data_mock, suggestions_mock):
    # `in` takes a list, and JQL only accepts a list between parentheses; the cursor is left inside them so that the
    # values can be typed straight away
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, editor, autocomplete = await open_editor(app, pilot, 'project ')
            # WHEN the 'in' operator is applied
            autocomplete.option_list.highlighted = 2
            autocomplete.apply_completion('in', autocomplete._get_target_state())
            await pilot.pause()
            # THEN
            assert editor.text == 'project in ()'
            assert editor.cursor_location == (0, 12)


@pytest.mark.asyncio
async def test_applying_an_equality_operator_only_appends_a_space(
    app, reference_data_mock, suggestions_mock
):
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, editor, autocomplete = await open_editor(app, pilot, 'project ')
            autocomplete.option_list.highlighted = 0
            autocomplete.apply_completion('=', autocomplete._get_target_state())
            await pilot.pause()
            assert editor.text == 'project = '
            assert editor.cursor_location == (0, 10)


@pytest.mark.asyncio
async def test_applying_the_in_operator_does_not_repeat_an_existing_list(
    app, reference_data_mock, suggestions_mock
):
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, editor, autocomplete = await open_editor(app, pilot, 'project (MNHA)', cursor=(0, 8))
            autocomplete.option_list.highlighted = 2
            autocomplete.apply_completion('in', autocomplete._get_target_state())
            await pilot.pause()
            assert editor.text == 'project in (MNHA)'


@pytest.mark.asyncio
async def test_applying_a_value_inside_a_quoted_value_keeps_the_quotes(
    app, reference_data_mock, suggestions_mock
):
    # the quotes typed by the user are part of the text that the suggestion replaces, so the suggestion has to bring
    # them back; without them the expression is not valid JQL
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, editor, autocomplete = await open_editor(app, pilot, '"Dev Engineers" in ("naga')
            autocomplete.option_list.highlighted = 0
            autocomplete.apply_completion(
                'Naga Kiran K - nagakiran@juniper.net', autocomplete._get_target_state()
            )
            await pilot.pause()
            assert editor.text == '"Dev Engineers" in ("Naga Kiran K - nagakiran@juniper.net"'


@pytest.mark.asyncio
async def test_a_value_that_the_api_returns_quoted_is_not_recorded_as_an_alias(
    app, reference_data_mock
):
    # the API returns the value the way it would be written in an expression; recording the quotes would make the
    # search send `status != "\"Dev Complete\""`, which matches no status at all
    suggestions_mock = AsyncMock(
        return_value=APIControllerResponse(
            result=[
                JQLAutocompleteSuggestion(value='"Dev Complete"', display_name='Dev Complete'),
            ]
        )
    )
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, editor, autocomplete = await open_editor(app, pilot, 'project = "Dev')
            assert dropdown_options(autocomplete) == ['Dev Complete']
            # WHEN
            autocomplete.option_list.highlighted = 0
            autocomplete.apply_completion('Dev Complete', autocomplete._get_target_state())
            await pilot.pause()
            # THEN the value stands on its own in the expression, and nothing has to be resolved at search time
            assert editor.text == 'project = "Dev Complete"'
            assert jql_value_aliases() == {}


@pytest.mark.asyncio
async def test_the_reference_data_is_fetched_once(app, reference_data_mock, suggestions_mock):
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, editor, _ = await open_editor(app, pilot, 'pro')
            editor.text = 'proj'
            editor.move_cursor((0, 4))
            await pilot.pause()
            await pilot.pause()
            assert reference_data_mock.await_count == 1


@pytest.mark.asyncio
async def test_the_editor_works_when_the_reference_data_cannot_be_fetched(app, suggestions_mock):
    # a failure while the user types must never interrupt them
    failing = AsyncMock(return_value=APIControllerResponse(success=False, error='boom'))
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=failing),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, _, autocomplete = await open_editor(app, pilot, 'pro')
            # no field can be suggested, but the editor is still usable
            assert dropdown_options(autocomplete) == []


@pytest.mark.asyncio
async def test_the_values_are_still_suggested_when_the_reference_data_cannot_be_fetched(
    app, suggestions_mock
):
    failing = AsyncMock(return_value=APIControllerResponse(success=False, error='boom'))
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=failing),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, _, autocomplete = await open_editor(app, pilot, 'project = na')
            assert dropdown_options(autocomplete) == [
                'Naga Kiran K - nagakiran@juniper.net',
                'Hegde, Nagaraja - hnagaraja@juniper.net',
            ]


@pytest.mark.asyncio
async def test_an_api_error_does_not_break_the_editor(app, reference_data_mock):
    exploding = AsyncMock(side_effect=ValueError('boom'))
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=exploding),
    ):
        async with app.run_test() as pilot:
            _, _, autocomplete = await open_editor(app, pilot, 'project = na')
            assert dropdown_options(autocomplete) == []


@pytest.mark.asyncio
async def test_escape_with_the_dropdown_open_does_not_close_the_editor(
    app, reference_data_mock, suggestions_mock
):
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            screen, _, autocomplete = await open_editor(app, pilot, 'pro')
            assert autocomplete.display is True
            # WHEN
            await pilot.press('escape')
            await pilot.pause()
            # THEN
            assert app.screen is screen


@pytest.mark.asyncio
async def test_escape_with_the_dropdown_closed_closes_the_editor(
    app, reference_data_mock, suggestions_mock
):
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            dismissed_with: list = []
            await app.push_screen(JQLEditorScreen('project = SB'), callback=dismissed_with.append)
            await pilot.pause()
            # WHEN
            await pilot.press('escape')
            await pilot.pause()
            # THEN
            assert dismissed_with == ['project = SB']


@pytest.mark.asyncio
async def test_the_target_state_of_a_multiline_expression(
    app, reference_data_mock, suggestions_mock
):
    # the cursor of a TextArea is a (row, column) location; the tokenizer works on the flat text
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, _, autocomplete = await open_editor(
                app, pilot, 'project = SB\nand assi', cursor=(1, 8)
            )
            state = autocomplete._get_target_state()
            assert state.text == 'project = SB\nand assi'
            # 'project = SB' is 12 characters, so the second row starts at 13 and the cursor at (1, 8) is at 21
            assert state.cursor_position == 21


@pytest.mark.asyncio
async def test_enter_with_the_dropdown_open_applies_the_suggestion_and_inserts_no_newline(
    app, reference_data_mock, suggestions_mock
):
    # a TextArea inserts the newline from its own key handler, before the dropdown is told about the key
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, editor, autocomplete = await open_editor(app, pilot, 'pro')
            assert autocomplete.display is True
            # WHEN
            await pilot.press('enter')
            await pilot.pause()
            # THEN
            assert editor.text == 'project '
            assert '\n' not in editor.text


@pytest.mark.asyncio
async def test_tab_with_the_dropdown_open_applies_the_suggestion_and_inserts_no_indent(
    app, reference_data_mock, suggestions_mock
):
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, editor, autocomplete = await open_editor(app, pilot, 'pro')
            assert autocomplete.display is True
            # WHEN
            await pilot.press('tab')
            await pilot.pause()
            # THEN
            assert editor.text == 'project '


@pytest.mark.asyncio
async def test_enter_with_the_dropdown_closed_inserts_a_newline(
    app, reference_data_mock, suggestions_mock
):
    # the editor is still an editor: the key is only claimed while the dropdown is open
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, editor, autocomplete = await open_editor(app, pilot, 'project = SB ')
            assert autocomplete.display is False
            # WHEN
            await pilot.press('enter')
            await pilot.pause()
            # THEN
            assert editor.text == 'project = SB \n'


@pytest.mark.asyncio
async def test_ctrl_n_and_ctrl_p_move_the_highlight_of_the_dropdown(
    app, reference_data_mock, suggestions_mock
):
    # the dropdown of `textual-autocomplete` recognises the arrow keys only; these are the readline keys
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, editor, autocomplete = await open_editor(app, pilot, '"Dev Engineers" in (naga')
            option_list = autocomplete.option_list
            assert option_list.option_count == 2
            option_list.highlighted = 0
            # WHEN
            await pilot.press('ctrl+n')
            await pilot.pause()
            # THEN
            assert option_list.highlighted == 1
            # WHEN the end of the list is passed
            await pilot.press('ctrl+n')
            await pilot.pause()
            # THEN it wraps around
            assert option_list.highlighted == 0
            # WHEN
            await pilot.press('ctrl+p')
            await pilot.pause()
            # THEN it wraps around the other way
            assert option_list.highlighted == 1
            # and neither key reached the editor
            assert editor.text == '"Dev Engineers" in (naga'


@pytest.mark.asyncio
async def test_ctrl_n_then_enter_applies_the_suggestion_that_was_highlighted(
    app, reference_data_mock, suggestions_mock
):
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, editor, autocomplete = await open_editor(app, pilot, '"Dev Engineers" in (naga')
            autocomplete.option_list.highlighted = 0
            second_suggestion = dropdown_options(autocomplete)[1]
            # WHEN
            await pilot.press('ctrl+n')
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            # THEN
            assert editor.text == f'"Dev Engineers" in ("{second_suggestion}"'


@pytest.mark.asyncio
async def test_ctrl_n_with_the_dropdown_closed_leaves_the_expression_alone(
    app, reference_data_mock, suggestions_mock
):
    # the keys are only claimed while there are suggestions on screen
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            screen, editor, autocomplete = await open_editor(app, pilot, 'project = SB ')
            assert autocomplete.display is False
            # WHEN
            await pilot.press('ctrl+n')
            await pilot.pause()
            # THEN the editor is left alone and the key is not claimed
            assert editor.text == 'project = SB '
            assert app.screen is screen
            # WHEN
            await pilot.press('ctrl+p')
            await pilot.pause()
            # THEN it still opens the command palette
            assert CommandPalette.is_open(app)


@pytest.mark.asyncio
async def test_the_values_of_a_field_are_fetched_once_the_user_stops_typing(
    app, reference_data_mock, suggestions_mock
):
    # without the debounce every keystroke sends a query, and the responses arrive while the user is still typing
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            _, editor, autocomplete = await open_editor(app, pilot, '"Dev Engineers" in (n')
            suggestions_mock.reset_mock()
            # WHEN the user types the rest of the name without stopping
            for text in (
                '"Dev Engineers" in (na',
                '"Dev Engineers" in (nag',
                '"Dev Engineers" in (naga',
            ):
                editor.text = text
                editor.move_cursor((0, len(text)))
                await pilot.pause()
            # THEN nothing has been asked for yet
            suggestions_mock.assert_not_awaited()
            # WHEN the user stops typing
            await pilot.pause(VALUE_QUERY_DEBOUNCE_SECONDS + 0.1)
            # THEN only the last prefix is queried
            assert suggestions_mock.await_count == 1
            assert suggestions_mock.await_args.kwargs == {
                'field_name': 'Dev Engineers',
                'field_value': 'naga',
            }


@pytest.mark.asyncio
async def test_a_single_character_does_not_query_the_values_of_a_field(
    app, reference_data_mock, suggestions_mock
):
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test() as pilot:
            await open_editor(app, pilot, '"Dev Engineers" in (n')
            suggestions_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_dropdown_of_the_search_bar_is_not_cut_off_by_the_edge_of_the_screen(
    app, reference_data_mock, suggestions_mock
):
    # the JQL input sits on the right of the search bar, so a dropdown aligned to the cursor runs past the edge of
    # the screen unless it is pushed back; when it is not, the end of every suggestion is cut off
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
    ):
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            jql_input = app.screen.query_one('#input_search_term')
            autocomplete = app.screen.query_one(JQLInputAutoComplete)
            jql_input.focus()
            await pilot.pause()
            jql_input.value = '"Dev Engineers" in (naga'
            jql_input.cursor_position = len(jql_input.value)
            await pilot.pause()
            await pilot.pause(VALUE_QUERY_DEBOUNCE_SECONDS + 0.1)
            await pilot.pause()
            # GIVEN the dropdown is showing a suggestion wider than the room left of the screen edge
            assert autocomplete.display is True
            region = autocomplete.option_list.region
            assert region.width >= len('Naga Kiran K - nagakiran@juniper.net')
            # THEN it still fits on the screen
            screen_width = app.screen.scrollable_content_region.width
            assert region.x >= 0
            assert region.x + region.width <= screen_width


@pytest.mark.asyncio
async def test_the_dropdown_of_the_search_bar_is_navigated_with_ctrl_n_and_ctrl_p(
    app, reference_data_mock, suggestions_mock
):
    # `ctrl+n` creates a work item and `ctrl+p` opens the command palette; the dropdown only takes them while it is
    # showing suggestions
    with (
        patch.object(APIController, 'get_jql_autocomplete_data', new=reference_data_mock),
        patch.object(APIController, 'get_jql_autocomplete_suggestions', new=suggestions_mock),
        patch.object(MainScreen, 'action_create_work_item') as create_work_item,
    ):
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen = app.screen
            jql_input = screen.query_one('#input_search_term')
            autocomplete = screen.query_one(JQLInputAutoComplete)
            jql_input.focus()
            await pilot.pause()
            jql_input.value = '"Dev Engineers" in (naga'
            jql_input.cursor_position = len(jql_input.value)
            await pilot.pause()
            await pilot.pause(VALUE_QUERY_DEBOUNCE_SECONDS + 0.1)
            # GIVEN the dropdown is showing suggestions
            assert autocomplete.display is True
            autocomplete.option_list.highlighted = 0
            # WHEN
            await pilot.press('ctrl+n')
            await pilot.pause()
            # THEN the highlight moved, and neither the create-work-item form nor the command palette was opened
            assert autocomplete.option_list.highlighted == 1
            create_work_item.assert_not_called()
            assert app.screen is screen
            # WHEN
            await pilot.press('ctrl+p')
            await pilot.pause()
            # THEN
            assert autocomplete.option_list.highlighted == 0
            assert app.screen is screen
            # WHEN the dropdown is hidden
            autocomplete.action_hide()
            await pilot.pause()
            await pilot.press('ctrl+n')
            await pilot.pause()
            # THEN the key goes back to creating a work item
            create_work_item.assert_called_once()
