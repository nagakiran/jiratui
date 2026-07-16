from unittest.mock import AsyncMock, MagicMock, Mock, patch

from pydantic import SecretStr
import pytest
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
from jiratui.utils.session import ApplicationSession
from jiratui.widgets.commons.jql_autocomplete import quote_if_needed
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
    await pilot.pause()
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
async def test_applying_a_value_inserts_the_value_and_not_the_display_name(
    app, reference_data_mock, suggestions_mock
):
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
            assert editor.text == '"Dev Engineers" in (nagakiran@juniper.net'


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
