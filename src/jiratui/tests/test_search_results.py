from typing import cast
from unittest.mock import AsyncMock, MagicMock, Mock, call, patch

from pydantic import SecretStr
import pytest
from textual.coordinate import Coordinate

from jiratui.api_controller.controller import APIController, APIControllerResponse
from jiratui.app import JiraApp
from jiratui.config import ApplicationConfiguration
from jiratui.models import (
    IssueStatus,
    IssueType,
    JiraField,
    JiraIssue,
    JiraIssueSearchResponse,
    SortSpec,
    WorkItemsSearchOrderBy,
)
from jiratui.utils.columns import DEFAULT_COLUMNS, resolve_columns
from jiratui.widgets.screen import MainScreen, WorkItemSearchResult
from jiratui.widgets.screens.goto import GotToScreen
from jiratui.widgets.search import (
    ConfirmDeleteItemScreen,
    IssuesSearchResultsTable,
    SearchResultsContainer,
)


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
        search_results_style_work_item_status=False,
        search_results_style_work_item_type=False,
        search_results_truncate_work_item_summary=None,
        enable_advanced_full_text_search=False,
        search_results_per_page=50,
        jql_expression_id_for_work_items_search=None,
        pre_defined_jql_expressions=None,
    )
    app = JiraApp(config_mock)
    app.api = APIController(config_mock)
    app._setup_logging = MagicMock()  # type:ignore[method-assign]
    return app


@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_click_next_page_search_results(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    app,
):
    async with app.run_test() as pilot:
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        main_screen.search_results_table.page = 1
        main_screen.search_results_table.token_by_page = {2: 'token_a'}
        main_screen.search_results_table.focus()
        # WHEN
        await pilot.press('alt+right')
        # THEN
        assert main_screen.search_results_table.page == 2
        search_issues_mock.assert_called_once_with('token_a', page=2)


@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_click_next_page_search_results_with_missing_token(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    app,
):
    async with app.run_test() as pilot:
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        main_screen.search_results_table.page = 0
        main_screen.search_results_table.token_by_page = {2: 'token_a'}
        main_screen.search_results_table.focus()
        # WHEN
        await pilot.press('alt+right')
        # THEN
        search_issues_mock.assert_not_called()
        assert main_screen.search_results_table.page == 0


@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_click_previous_page_search_results(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    app,
):
    async with app.run_test() as pilot:
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        main_screen.search_results_table.page = 2
        main_screen.search_results_table.token_by_page = {1: 'token_a'}
        main_screen.search_results_table.focus()
        # WHEN
        await pilot.press('alt+left')
        # THEN
        search_issues_mock.assert_called_once_with('token_a', page=1)
        assert main_screen.search_results_table.page == 1


@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_click_previous_page_search_results_with_missing_token(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    app,
):
    async with app.run_test() as pilot:
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        main_screen.search_results_table.page = 1
        main_screen.search_results_table.token_by_page = {2: 'token_a'}
        main_screen.search_results_table.focus()
        # WHEN
        await pilot.press('alt+left')
        # THEN
        search_issues_mock.assert_not_called()
        assert main_screen.search_results_table.page == 1


@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_click_filter_datatable_filtering_key_shows_input(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    app,
):
    app.config.search_results_page_filtering_enabled = True
    async with app.run_test() as pilot:
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        main_screen.search_results_table.focus()
        # WHEN
        await pilot.press('.')
        # THEN
        assert main_screen.search_results_filter_input.display is True
        assert main_screen.search_results_table.page == 1


@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_click_filter_datatable_filtering_key_feature_disabled(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    app,
):
    app.config.search_results_page_filtering_enabled = False
    async with app.run_test() as pilot:
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        main_screen.search_results_table.focus()
        # WHEN
        await pilot.press('.')
        # THEN
        assert main_screen.search_results_filter_input.display is False
        assert main_screen.search_results_table.page == 1


@patch.object(IssuesSearchResultsTable, 'get_initial_results_set')
@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_click_filter_datatable_filtering_key_hides_input(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    get_initial_results_set_mock: Mock,
    app,
):
    app.config.search_results_page_filtering_enabled = True
    async with app.run_test() as pilot:
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        main_screen.search_results_table.focus()
        # WHEN
        await pilot.press('.')
        # THEN
        assert main_screen.search_results_filter_input.display is True
        await pilot.press('escape')
        assert main_screen.search_results_filter_input.display is False
        get_initial_results_set_mock.assert_called_once()


@patch.object(IssuesSearchResultsTable, 'get_initial_results_set')
@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_datatable_filtering_yields_results(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    get_initial_results_set_mock: Mock,
    jira_issues: list[JiraIssue],
    app,
):
    app.config.search_results_page_filtering_enabled = True
    app.config.search_results_page_filtering_minimum_term_length = 3
    app.config.search_results_truncate_work_item_summary = 10
    app.config.search_results_style_work_item_status = False
    app.config.search_results_style_work_item_type = False
    get_initial_results_set_mock.side_effect = [
        JiraIssueSearchResponse(issues=jira_issues[0:]),
        JiraIssueSearchResponse(issues=jira_issues[0:]),
        JiraIssueSearchResponse(issues=jira_issues[0:]),
    ]
    async with app.run_test() as pilot:
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        main_screen.search_results_table.focus()
        # WHEN
        await pilot.press('.')
        await pilot.press('a')
        await pilot.press('b')
        await pilot.press('c')
        # THEN
        assert main_screen.search_results_filter_input.value == 'abc'
        assert main_screen.search_results_table.page == 1
        get_initial_results_set_mock.assert_has_calls([call(), call(), call()])
        assert main_screen.search_results_filter_input.total == 1
        assert main_screen.search_results_filter_input.border_subtitle == 'Found: 1'


@patch.object(IssuesSearchResultsTable, 'get_initial_results_set')
@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_datatable_filtering_yields_no_results(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    get_initial_results_set_mock: Mock,
    jira_issues: list[JiraIssue],
    app,
):
    app.config.search_results_page_filtering_enabled = True
    app.config.search_results_page_filtering_minimum_term_length = 3
    app.config.search_results_truncate_work_item_summary = 10
    app.config.search_results_style_work_item_status = False
    app.config.search_results_style_work_item_type = False
    get_initial_results_set_mock.side_effect = [
        JiraIssueSearchResponse(issues=jira_issues[0:]),
        JiraIssueSearchResponse(issues=jira_issues[0:]),
        JiraIssueSearchResponse(issues=jira_issues[0:]),
    ]
    async with app.run_test() as pilot:
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        main_screen.search_results_table.focus()
        # WHEN
        await pilot.press('.')
        await pilot.press('a')
        await pilot.press('b')
        await pilot.press('d')
        # THEN
        assert main_screen.search_results_filter_input.value == 'abd'
        assert main_screen.search_results_table.page == 1
        get_initial_results_set_mock.assert_has_calls([call(), call(), call()])
        assert main_screen.search_results_filter_input.total == 0
        assert main_screen.search_results_filter_input.border_subtitle == 'Found: 0'


@patch('jiratui.widgets.search.build_external_url_for_issue')
@patch.object(JiraApp, 'open_url')
@patch('jiratui.widgets.screen.MainScreen._search_work_items')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_open_issue_in_browser(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_work_items_mock: AsyncMock,
    open_url_mock: Mock,
    build_external_url_for_issue_mock: Mock,
    jira_issues: list[JiraIssue],
    app,
):
    app.config.search_results_truncate_work_item_summary = 10
    app.config.search_results_style_work_item_status = False
    app.config.search_results_style_work_item_type = False
    app.config.search_results_per_page = 10
    build_external_url_for_issue_mock.return_value = 'https://foo.bar/key-2'
    async with app.run_test() as pilot:
        # GIVEN
        search_work_items_mock.return_value = WorkItemSearchResult(
            total=2,
            response=JiraIssueSearchResponse(
                issues=jira_issues, next_page_token=None, is_last=None
            ),
        )
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        # WHEN
        await pilot.press('ctrl+r')
        await pilot.press('down')
        await pilot.press('down')
        await pilot.press('ctrl+o')
        # THEN
        assert main_screen.search_results_table.focus()
        assert main_screen.search_results_table.page == 1
        search_work_items_mock.assert_called_once()
        assert main_screen.search_results_table.search_results == JiraIssueSearchResponse(
            issues=jira_issues, next_page_token=None, is_last=None
        )
        assert main_screen.search_results_table.current_work_item_key == jira_issues[1].key
        open_url_mock.assert_called_once()
        assert main_screen.search_results_container.border_subtitle == 'Page 1 of 1 (total: 2)'


@patch('jiratui.widgets.screen.MainScreen.fetch_issue')
@patch('jiratui.widgets.screen.MainScreen._search_work_items')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_select_issue_in_search_results_datatable(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_work_items_mock: AsyncMock,
    fetch_issue_mock: AsyncMock,
    jira_issues: list[JiraIssue],
    app,
):
    app.config.search_results_truncate_work_item_summary = 10
    app.config.search_results_style_work_item_status = False
    app.config.search_results_style_work_item_type = False
    app.config.search_results_per_page = 10
    async with app.run_test() as pilot:
        # GIVEN
        search_work_items_mock.return_value = WorkItemSearchResult(
            total=2,
            response=JiraIssueSearchResponse(
                issues=jira_issues, next_page_token=None, is_last=None
            ),
        )
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        # WHEN
        await pilot.press('ctrl+r')
        await pilot.press('down')
        await pilot.press('enter')
        # THEN
        assert main_screen.search_results_table.focus()
        assert main_screen.search_results_table.page == 1
        search_work_items_mock.assert_called_once()
        assert main_screen.search_results_table.search_results == JiraIssueSearchResponse(
            issues=jira_issues, next_page_token=None, is_last=None
        )
        assert main_screen.search_results_table.current_work_item_key == jira_issues[1].key
        assert main_screen.search_results_container.border_subtitle == 'Page 1 of 1 (total: 2)'
        fetch_issue_mock.assert_called_once_with('key-2')


@patch('jiratui.widgets.screen.MainScreen._search_work_items')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_open_delete_issue_modal_screen(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_work_items_mock: AsyncMock,
    jira_issues: list[JiraIssue],
    app,
):
    app.config.search_results_truncate_work_item_summary = 10
    app.config.search_results_style_work_item_status = False
    app.config.search_results_style_work_item_type = False
    app.config.search_results_per_page = 10
    async with app.run_test() as pilot:
        # GIVEN
        search_work_items_mock.return_value = WorkItemSearchResult(
            total=2,
            response=JiraIssueSearchResponse(
                issues=jira_issues, next_page_token=None, is_last=None
            ),
        )
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        # WHEN
        await pilot.press('ctrl+r')
        await pilot.press('down')
        await pilot.press('down')
        await pilot.press('d')
        # THEN
        assert main_screen.search_results_table.focus()
        assert main_screen.search_results_table.page == 1
        search_work_items_mock.assert_called_once()
        assert main_screen.search_results_table.search_results == JiraIssueSearchResponse(
            issues=jira_issues, next_page_token=None, is_last=None
        )
        assert main_screen.search_results_table.current_work_item_key == jira_issues[1].key
        assert isinstance(app.screen, ConfirmDeleteItemScreen)


@patch.object(SearchResultsContainer, '_update_border_subtitle')
@patch('jiratui.widgets.screen.MainScreen._search_work_items')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_delete_issue_modal_screen_click_cancel(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_work_items_mock: AsyncMock,
    update_border_subtitle_mock: Mock,
    jira_issues: list[JiraIssue],
    app,
):
    app.config.search_results_truncate_work_item_summary = 10
    app.config.search_results_style_work_item_status = False
    app.config.search_results_style_work_item_type = False
    app.config.search_results_per_page = 10
    async with app.run_test() as pilot:
        # GIVEN
        search_work_items_mock.return_value = WorkItemSearchResult(
            total=2,
            response=JiraIssueSearchResponse(
                issues=jira_issues, next_page_token=None, is_last=None
            ),
        )
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        # WHEN
        await pilot.press('ctrl+r')
        await pilot.press('down')
        await pilot.press('down')
        await pilot.press('d')
        await pilot.press('tab')
        await pilot.press('enter')
        # THEN
        assert main_screen.search_results_table.focus()
        assert main_screen.search_results_table.page == 1
        search_work_items_mock.assert_called_once()
        assert main_screen.search_results_table.search_results == JiraIssueSearchResponse(
            issues=jira_issues, next_page_token=None, is_last=None
        )
        assert main_screen.search_results_table.current_work_item_key == jira_issues[1].key
        assert isinstance(app.screen, MainScreen)
        update_border_subtitle_mock.assert_called_once()


@patch.object(APIController, 'delete_work_item')
@patch.object(SearchResultsContainer, '_update_border_subtitle')
@patch('jiratui.widgets.screen.MainScreen._search_work_items')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_delete_issue_modal_screen_click_delete(
    fetch_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_work_items_mock: AsyncMock,
    update_border_subtitle_mock: Mock,
    delete_work_item_mock: AsyncMock,
    jira_issues: list[JiraIssue],
    app,
):
    app.config.search_results_truncate_work_item_summary = 10
    app.config.search_results_style_work_item_status = False
    app.config.search_results_style_work_item_type = False
    app.config.search_results_per_page = 10
    delete_work_item_mock.return_value = APIControllerResponse()
    async with app.run_test() as pilot:
        # GIVEN
        search_work_items_mock.return_value = WorkItemSearchResult(
            total=2,
            response=JiraIssueSearchResponse(
                issues=jira_issues, next_page_token=None, is_last=None
            ),
        )
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        # WHEN
        await pilot.press('ctrl+r')
        await pilot.press('down')
        await pilot.press('down')
        await pilot.press('d')
        await pilot.press('enter')
        # THEN
        assert main_screen.search_results_table.focus()
        assert main_screen.search_results_table.page == 1
        search_work_items_mock.assert_called_once()
        assert main_screen.search_results_table.search_results == JiraIssueSearchResponse(
            issues=jira_issues, next_page_token=None, is_last=None
        )
        assert main_screen.search_results_table.current_work_item_key != jira_issues[1].key
        assert isinstance(app.screen, MainScreen)
        delete_work_item_mock.assert_called_once_with(jira_issues[1].key)
        update_border_subtitle_mock.assert_has_calls([call(), call()])


@patch.object(APIController, 'delete_work_item')
@patch.object(SearchResultsContainer, '_update_border_subtitle')
@patch('jiratui.widgets.screen.MainScreen._search_work_items')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_delete_issue_modal_screen_click_delete_currently_selected_item(
    fetch_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_work_items_mock: AsyncMock,
    update_border_subtitle_mock: Mock,
    delete_work_item_mock: AsyncMock,
    jira_issues: list[JiraIssue],
    app,
):
    """Tests that deleting the currently select item clears the currently selected item key and the details' issue."""
    app.config.search_results_truncate_work_item_summary = 10
    app.config.search_results_style_work_item_status = False
    app.config.search_results_style_work_item_type = False
    app.config.search_results_per_page = 10
    delete_work_item_mock.return_value = APIControllerResponse()
    async with app.run_test() as pilot:
        # GIVEN
        search_work_items_mock.return_value = WorkItemSearchResult(
            total=2,
            response=JiraIssueSearchResponse(
                issues=jira_issues, next_page_token=None, is_last=None
            ),
        )
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        main_screen.current_loaded_work_item_key = jira_issues[1].key
        # WHEN
        await pilot.press('ctrl+r')
        await pilot.press('down')
        await pilot.press('down')
        await pilot.press('d')
        await pilot.press('enter')
        # THEN
        assert main_screen.search_results_table.focus()
        assert main_screen.search_results_table.page == 1
        search_work_items_mock.assert_called_once()
        assert main_screen.search_results_table.search_results == JiraIssueSearchResponse(
            issues=jira_issues, next_page_token=None, is_last=None
        )
        assert main_screen.search_results_table.current_work_item_key != jira_issues[1].key
        assert isinstance(app.screen, MainScreen)
        delete_work_item_mock.assert_called_once_with(jira_issues[1].key)
        update_border_subtitle_mock.assert_has_calls([call(), call()])
        assert main_screen.current_loaded_work_item_key is None
        assert main_screen.issue_details_widget.issue is None


@patch('jiratui.widgets.screen.MainScreen._search_work_items')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_open_goto_screen_with_goto_enabled(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_work_items_mock: AsyncMock,
    jira_issues: list[JiraIssue],
    app,
):
    app.config.search_results_truncate_work_item_summary = 10
    app.config.search_results_style_work_item_status = False
    app.config.search_results_style_work_item_type = False
    app.config.search_results_per_page = 10
    app.config.enable_goto = True
    async with app.run_test() as pilot:
        # GIVEN
        search_work_items_mock.return_value = WorkItemSearchResult(
            total=2,
            response=JiraIssueSearchResponse(
                issues=jira_issues, next_page_token=None, is_last=None
            ),
        )
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        # WHEN
        await pilot.press('ctrl+r')
        await pilot.press('down')
        await pilot.press('down')
        await pilot.press('f6')
        # THEN
        assert main_screen.search_results_table.has_focus
        assert isinstance(app.screen, GotToScreen)


@patch('jiratui.widgets.screen.MainScreen._search_work_items')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_open_goto_screen_with_goto_disabled(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_work_items_mock: AsyncMock,
    jira_issues: list[JiraIssue],
    app,
):
    app.config.search_results_truncate_work_item_summary = 10
    app.config.search_results_style_work_item_status = False
    app.config.search_results_style_work_item_type = False
    app.config.search_results_per_page = 10
    app.config.enable_goto = False
    async with app.run_test() as pilot:
        # GIVEN
        search_work_items_mock.return_value = WorkItemSearchResult(
            total=2,
            response=JiraIssueSearchResponse(
                issues=jira_issues, next_page_token=None, is_last=None
            ),
        )
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        # WHEN
        await pilot.press('ctrl+r')
        await pilot.press('down')
        await pilot.press('down')
        await pilot.press('f6')
        # THEN
        assert main_screen.search_results_table.has_focus
        assert isinstance(app.screen, MainScreen)


@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_search_results_table_renders_the_default_columns(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    app,
    jira_issues,
):
    async with app.run_test():
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        table = main_screen.search_results_table
        # WHEN
        table.search_results = JiraIssueSearchResponse(issues=jira_issues)
        # THEN
        assert [str(column.label) for column in table.columns.values()] == [
            '#',
            'Key',
            'Parent',
            'Status',
            'Type',
            'Summary',
        ]
        assert table.row_count == 2


@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_search_results_table_keeps_the_row_keys(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    app,
    jira_issues,
):
    # the widget splits the key of the row to work out the id and the key of the work item of the row
    async with app.run_test():
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        table = main_screen.search_results_table
        # WHEN
        table.search_results = JiraIssueSearchResponse(issues=jira_issues)
        # THEN
        assert [row.value for row in table.rows] == ['1#key-1', '2#key-2']


@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_search_results_table_renders_a_custom_field_column(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    app,
):
    async with app.run_test():
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        main_screen.active_columns = resolve_columns(
            ['key', 'customfield_10343'],
            jira_fields=[
                JiraField(
                    id='customfield_10343',
                    key='customfield_10343',
                    name='Dev Engineers',
                    custom=True,
                    schema={},
                )
            ],
        )
        table = main_screen.search_results_table
        issue = JiraIssue(
            id='1',
            key='key-1',
            summary='abcd',
            status=IssueStatus(name='Done', id='1'),
            issue_type=IssueType(id='1', name='Task'),
            raw_fields={
                'customfield_10343': [{'displayName': 'Naga Kiran K'}, {'displayName': 'Bart'}]
            },
        )
        # WHEN
        table.search_results = JiraIssueSearchResponse(issues=[issue])
        # THEN
        assert [str(column.label) for column in table.columns.values()] == ['Key', 'Dev Engineers']
        row = table.get_row_at(0)
        assert str(row[0]) == 'key-1'
        assert str(row[1]) == 'Naga Kiran K, Bart'


@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_search_results_table_renders_a_custom_field_without_a_value(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    app,
):
    async with app.run_test():
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        main_screen.active_columns = resolve_columns(['key', 'customfield_10343'])
        table = main_screen.search_results_table
        issue = JiraIssue(
            id='1',
            key='key-1',
            summary='abcd',
            status=IssueStatus(name='Done', id='1'),
            issue_type=IssueType(id='1', name='Task'),
            raw_fields={},
        )
        # WHEN
        table.search_results = JiraIssueSearchResponse(issues=[issue])
        # THEN
        assert str(table.get_row_at(0)[1]) == ''


@patch.object(APIController, 'search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_search_requests_the_fields_of_the_active_columns(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    app,
):
    # a column renders an empty value unless the field it displays is requested from the API
    async with app.run_test():
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        main_screen.active_columns = resolve_columns(['key', 'assignee', 'customfield_10343'])
        search_issues_mock.return_value = APIControllerResponse(
            result=JiraIssueSearchResponse(issues=[])
        )
        # WHEN
        await main_screen._search_work_items(calculate_total=False)
        # THEN
        requested_fields = search_issues_mock.call_args.kwargs['fields']
        assert 'assignee' in requested_fields
        assert 'customfield_10343' in requested_fields
        # the table always needs these, whether or not a column displays them
        for baseline_field in ('id', 'key', 'status', 'summary', 'issuetype', 'parent'):
            assert baseline_field in requested_fields


@patch.object(APIController, 'search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_search_with_the_default_columns_requests_the_baseline_fields(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    app,
):
    async with app.run_test():
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        search_issues_mock.return_value = APIControllerResponse(
            result=JiraIssueSearchResponse(issues=[])
        )
        # WHEN
        await main_screen._search_work_items(calculate_total=False)
        # THEN
        assert search_issues_mock.call_args.kwargs['fields'] == [
            'id',
            'key',
            'status',
            'summary',
            'issuetype',
            'parent',
        ]


@patch('jiratui.widgets.screen.MainScreen.action_search')
@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_applying_columns_re_runs_the_search(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    action_search_mock: AsyncMock,
    app,
):
    # the data of a column that was just added was never requested from the API, so the results must be fetched again
    async with app.run_test():
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        main_screen.search_results_table.page = 3
        main_screen.search_results_table.token_by_page = {2: 'token_a'}
        # WHEN
        main_screen._apply_columns(['key', 'assignee'])
        # THEN
        assert [column.id for column in main_screen.active_columns] == ['key', 'assignee']
        action_search_mock.assert_called_once()
        # the tokens of the pages of the previous results are no longer valid
        assert main_screen.search_results_table.page == 1
        assert main_screen.search_results_table.token_by_page == {}


@patch('jiratui.widgets.screen.MainScreen.action_search')
@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_cancelling_the_column_selection_keeps_the_columns(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    action_search_mock: AsyncMock,
    app,
):
    async with app.run_test():
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        columns_before = main_screen.active_columns
        # WHEN
        main_screen._apply_columns(None)
        # THEN
        assert main_screen.active_columns == columns_before
        action_search_mock.assert_not_called()


@patch('jiratui.widgets.screen.MainScreen.action_search')
@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_sort_by_a_column(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    action_search_mock: AsyncMock,
    app,
    jira_issues,
):
    async with app.run_test() as pilot:
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        table = main_screen.search_results_table
        table.search_results = JiraIssueSearchResponse(issues=jira_issues)
        table.focus()
        # the cursor is on the 'Key' column
        table.cursor_coordinate = Coordinate(0, 1)
        # WHEN
        await pilot.press('s')
        # THEN
        assert table.sort_spec == SortSpec(field='key', descending=False)
        assert table.sort_column_id == 'key'
        action_search_mock.assert_called_once()


@patch('jiratui.widgets.screen.MainScreen.action_search')
@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_sorting_by_the_same_column_reverses_the_direction(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    action_search_mock: AsyncMock,
    app,
    jira_issues,
):
    async with app.run_test() as pilot:
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        table = main_screen.search_results_table
        table.search_results = JiraIssueSearchResponse(issues=jira_issues)
        table.focus()
        table.cursor_coordinate = Coordinate(0, 1)
        # WHEN
        await pilot.press('s')
        await pilot.press('s')
        # THEN
        assert table.sort_spec == SortSpec(field='key', descending=True)


@patch('jiratui.widgets.screen.MainScreen.action_search')
@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_sorting_resets_the_pagination(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    action_search_mock: AsyncMock,
    app,
    jira_issues,
):
    # the tokens of the pages of the results sorted by the previous criteria are no longer valid
    async with app.run_test() as pilot:
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        table = main_screen.search_results_table
        table.search_results = JiraIssueSearchResponse(issues=jira_issues)
        table.page = 4
        table.token_by_page = {2: 'token_a'}
        table.focus()
        table.cursor_coordinate = Coordinate(0, 1)
        # WHEN
        await pilot.press('s')
        # THEN
        assert table.page == 1
        assert table.token_by_page == {}


@patch('jiratui.widgets.screen.MainScreen.action_search')
@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_a_column_that_cannot_be_sorted_is_not_sorted(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    action_search_mock: AsyncMock,
    app,
    jira_issues,
):
    async with app.run_test() as pilot:
        # GIVEN the cursor is on the '#' column, which displays the position of the item in the page
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        table = main_screen.search_results_table
        table.search_results = JiraIssueSearchResponse(issues=jira_issues)
        table.focus()
        table.cursor_coordinate = Coordinate(0, 0)
        # WHEN
        await pilot.press('s')
        # THEN
        assert table.sort_spec is None
        action_search_mock.assert_not_called()


@patch('jiratui.widgets.screen.MainScreen.action_search')
@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_the_header_of_the_sorted_column_displays_the_direction(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    action_search_mock: AsyncMock,
    app,
    jira_issues,
):
    # the table is rebuilt from scratch on every search, so the sorting must survive the rebuild
    async with app.run_test():
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        table = main_screen.search_results_table
        table.sort_spec = SortSpec(field='key', descending=True)
        table.sort_column_id = 'key'
        # WHEN
        table.search_results = JiraIssueSearchResponse(issues=jira_issues)
        # THEN
        assert [str(column.label) for column in table.columns.values()] == [
            '#',
            'Key ▼',
            'Parent',
            'Status',
            'Type',
            'Summary',
        ]


@patch('jiratui.widgets.screen.MainScreen.action_search')
@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_sorting_by_a_column_takes_precedence_over_the_order_by_widget(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    action_search_mock: AsyncMock,
    app,
):
    async with app.run_test():
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        main_screen.search_results_table.sort_spec = SortSpec(field='cf[10343]', descending=True)
        with patch.object(
            APIController,
            'search_issues',
            new=AsyncMock(
                return_value=APIControllerResponse(result=JiraIssueSearchResponse(issues=[]))
            ),
        ) as search_mock:
            # WHEN
            await main_screen._search_work_items(calculate_total=False)
            # THEN
            assert search_mock.call_args.kwargs['order_by'] == SortSpec(
                field='cf[10343]', descending=True
            )


@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_changing_the_order_by_widget_stops_sorting_by_a_column(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    app,
):
    # sorting by a column wins over the widget, so the widget would appear to be broken
    async with app.run_test() as pilot:
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        table = main_screen.search_results_table
        table.sort_spec = SortSpec(field='key')
        table.sort_column_id = 'key'
        # WHEN
        main_screen.order_by_widget.value = WorkItemsSearchOrderBy.PRIORITY_ASC.value
        await pilot.pause()
        # THEN
        assert table.sort_spec is None
        assert table.sort_column_id is None


@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_the_column_of_the_cursor_survives_a_rebuild_of_the_table(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    app,
    jira_issues,
):
    # sorting a column re-runs the search, which rebuilds the table; if the cursor moved back to the first column
    # then pressing the sort key again would sort a different column instead of reversing the sorting
    async with app.run_test():
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        table = main_screen.search_results_table
        table.search_results = JiraIssueSearchResponse(issues=jira_issues)
        table.cursor_coordinate = Coordinate(0, 3)
        # WHEN the results are rebuilt
        table.search_results = JiraIssueSearchResponse(issues=jira_issues)
        # THEN
        assert table.cursor_column == 3


@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_the_column_of_the_cursor_is_clamped_when_the_columns_change(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    app,
    jira_issues,
):
    async with app.run_test():
        # GIVEN
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        table = main_screen.search_results_table
        table.search_results = JiraIssueSearchResponse(issues=jira_issues)
        table.cursor_coordinate = Coordinate(0, 5)
        # WHEN the user removes columns
        main_screen.active_columns = resolve_columns(['key', 'summary'])
        table.search_results = JiraIssueSearchResponse(issues=jira_issues)
        # THEN
        assert table.cursor_column == 1


@patch.object(APIController, 'get_fields')
@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_columns_configured_by_name_are_resolved_on_startup(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    get_fields_mock: AsyncMock,
    app,
):
    # GIVEN a column configured with the name of a custom field, as displayed by the Jira UI
    app.config.search_results_columns = ['key', 'Fix-ETA[Date]']
    get_fields_mock.return_value = APIControllerResponse(
        success=True,
        result=[
            JiraField(
                id='customfield_10109',
                key='customfield_10109',
                name='Fix-ETA',
                custom=True,
                schema={},
            )
        ],
    )
    async with app.run_test():
        main_screen = cast('MainScreen', app.screen)  # type:ignore[name-defined] # noqa: F821
        # THEN the column is mapped to the id of the field, which is what makes it render a value
        assert [(column.id, column.label) for column in main_screen.active_columns] == [
            ('key', 'Key'),
            ('customfield_10109', 'Fix-ETA'),
        ]


@patch.object(APIController, 'get_fields')
@patch('jiratui.widgets.screen.MainScreen.search_issues')
@patch('jiratui.widgets.screen.MainScreen.fetch_statuses')
@patch('jiratui.widgets.screen.MainScreen.fetch_issue_types')
@patch('jiratui.widgets.screen.MainScreen.fetch_projects')
@pytest.mark.asyncio
async def test_built_in_columns_are_not_resolved_against_the_fields_of_the_instance(
    search_projects_mock: AsyncMock,
    fetch_issue_types_mock: AsyncMock,
    fetch_statuses_mock: AsyncMock,
    search_issues_mock: AsyncMock,
    get_fields_mock: AsyncMock,
    app,
):
    # GIVEN a configuration that only uses built-in columns
    app.config.search_results_columns = ['key', 'summary']
    async with app.run_test():
        # THEN the fields of the instance are not fetched
        get_fields_mock.assert_not_called()
