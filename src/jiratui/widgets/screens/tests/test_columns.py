from unittest.mock import MagicMock, Mock

from pydantic import SecretStr
import pytest

from jiratui.api_controller.controller import APIController
from jiratui.app import JiraApp
from jiratui.config import ApplicationConfiguration
from jiratui.models import WorkItemsSearchOrderBy
from jiratui.utils.columns import BUILTIN_COLUMNS, DEFAULT_COLUMNS, resolve_columns
from jiratui.widgets.screens.columns import ColumnSelectionScreen


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
    )
    app = JiraApp(config_mock)
    app.api = APIController(config_mock)
    app._setup_logging = MagicMock()  # type:ignore[method-assign]
    return app


def build_screen(
    selected: list[str] | None = None, default: list[str] | None = None
) -> ColumnSelectionScreen:
    return ColumnSelectionScreen(
        available_columns=list(BUILTIN_COLUMNS.values()),
        selected_column_ids=selected if selected is not None else list(DEFAULT_COLUMNS),
        default_column_ids=default,
    )


@pytest.mark.asyncio
async def test_screen_lists_the_selected_columns_first(app):
    async with app.run_test() as pilot:
        # GIVEN
        screen = build_screen(selected=['key', 'summary'])
        await app.push_screen(screen)
        await pilot.pause()
        # THEN
        options = screen.option_list
        assert str(options.get_option_at_index(0).prompt) == '[x] Key'
        assert str(options.get_option_at_index(1).prompt) == '[x] Summary'
        # the rest of the columns are not selected
        assert all(
            str(options.get_option_at_index(index).prompt).startswith('[ ]')
            for index in range(2, options.option_count)
        )


@pytest.mark.asyncio
async def test_toggle_adds_a_column(app):
    async with app.run_test() as pilot:
        # GIVEN
        screen = build_screen(selected=['key'])
        await app.push_screen(screen)
        await pilot.pause()
        screen._highlight('assignee')
        # WHEN
        await pilot.press('space')
        # THEN
        assert screen.selected_column_ids == ['key', 'assignee']


@pytest.mark.asyncio
async def test_toggle_removes_a_column(app):
    async with app.run_test() as pilot:
        # GIVEN
        screen = build_screen(selected=['key', 'assignee'])
        await app.push_screen(screen)
        await pilot.pause()
        screen._highlight('assignee')
        # WHEN
        await pilot.press('space')
        # THEN
        assert screen.selected_column_ids == ['key']


@pytest.mark.asyncio
async def test_move_a_column_up(app):
    async with app.run_test() as pilot:
        # GIVEN
        screen = build_screen(selected=['key', 'summary'])
        await app.push_screen(screen)
        await pilot.pause()
        screen._highlight('summary')
        # WHEN
        await pilot.press('shift+up')
        # THEN
        assert screen.selected_column_ids == ['summary', 'key']


@pytest.mark.asyncio
async def test_move_a_column_down(app):
    async with app.run_test() as pilot:
        # GIVEN
        screen = build_screen(selected=['key', 'summary'])
        await app.push_screen(screen)
        await pilot.pause()
        screen._highlight('key')
        # WHEN
        await pilot.press('shift+down')
        # THEN
        assert screen.selected_column_ids == ['key', 'summary'][::-1]


@pytest.mark.asyncio
async def test_moving_the_first_column_up_does_nothing(app):
    async with app.run_test() as pilot:
        # GIVEN
        screen = build_screen(selected=['key', 'summary'])
        await app.push_screen(screen)
        await pilot.pause()
        screen._highlight('key')
        # WHEN
        await pilot.press('shift+up')
        # THEN
        assert screen.selected_column_ids == ['key', 'summary']


@pytest.mark.asyncio
async def test_moving_the_last_column_down_does_nothing(app):
    async with app.run_test() as pilot:
        # GIVEN
        screen = build_screen(selected=['key', 'summary'])
        await app.push_screen(screen)
        await pilot.pause()
        screen._highlight('summary')
        # WHEN
        await pilot.press('shift+down')
        # THEN
        assert screen.selected_column_ids == ['key', 'summary']


@pytest.mark.asyncio
async def test_a_column_that_is_not_displayed_cannot_be_re_ordered(app):
    async with app.run_test() as pilot:
        # GIVEN
        screen = build_screen(selected=['key'])
        await app.push_screen(screen)
        await pilot.pause()
        screen._highlight('assignee')
        # WHEN
        await pilot.press('shift+up')
        # THEN
        assert screen.selected_column_ids == ['key']


@pytest.mark.asyncio
async def test_filter_narrows_the_columns(app):
    async with app.run_test() as pilot:
        # GIVEN
        screen = build_screen(selected=['key'])
        await app.push_screen(screen)
        await pilot.pause()
        # WHEN
        screen.filter_input.value = 'assign'
        await pilot.pause()
        # THEN
        options = screen.option_list
        assert options.option_count == 1
        assert str(options.get_option_at_index(0).prompt) == '[ ] Assignee'


@pytest.mark.asyncio
async def test_filter_matches_the_id_of_a_field(app):
    async with app.run_test() as pilot:
        # GIVEN
        screen = build_screen(selected=[])
        await app.push_screen(screen)
        await pilot.pause()
        # WHEN
        screen.filter_input.value = 'resolutiondate'
        await pilot.pause()
        # THEN
        assert screen.option_list.option_count == 1


@pytest.mark.asyncio
async def test_apply_dismisses_with_the_selected_columns(app):
    async with app.run_test() as pilot:
        # GIVEN
        dismissed_with: list = []
        screen = build_screen(selected=['key', 'summary'])
        await app.push_screen(screen, callback=dismissed_with.append)
        await pilot.pause()
        # WHEN
        await pilot.press('enter')
        await pilot.pause()
        # THEN
        assert dismissed_with == [['key', 'summary']]


@pytest.mark.asyncio
async def test_cancel_dismisses_without_a_selection(app):
    async with app.run_test() as pilot:
        # GIVEN
        dismissed_with: list = []
        screen = build_screen(selected=['key'])
        await app.push_screen(screen, callback=dismissed_with.append)
        await pilot.pause()
        # WHEN
        await pilot.press('escape')
        await pilot.pause()
        # THEN
        assert dismissed_with == [None]


@pytest.mark.asyncio
async def test_apply_without_columns_does_not_dismiss(app):
    # a table without columns would display nothing
    async with app.run_test() as pilot:
        # GIVEN
        screen = build_screen(selected=[])
        await app.push_screen(screen)
        await pilot.pause()
        # WHEN
        await pilot.press('enter')
        await pilot.pause()
        # THEN
        assert app.screen is screen


@pytest.mark.asyncio
async def test_reset_restores_the_configured_columns(app):
    async with app.run_test() as pilot:
        # GIVEN
        screen = build_screen(selected=['key', 'assignee'], default=list(DEFAULT_COLUMNS))
        await app.push_screen(screen)
        await pilot.pause()
        # WHEN
        await pilot.press('ctrl+r')
        # THEN
        assert screen.selected_column_ids == list(DEFAULT_COLUMNS)


@pytest.mark.asyncio
async def test_screen_ignores_a_selected_column_that_is_not_available(app):
    async with app.run_test() as pilot:
        # GIVEN a column of a field that the Jira instance no longer exposes
        screen = ColumnSelectionScreen(
            available_columns=resolve_columns(['key']),
            selected_column_ids=['key', 'customfield_10343'],
        )
        await app.push_screen(screen)
        await pilot.pause()
        # THEN
        assert screen.selected_column_ids == ['key']
