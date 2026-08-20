"""This module contains widgets for implementing work item search functionality."""

from typing import cast

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, ItemGrid, Vertical
from textual.coordinate import Coordinate
from textual.message import Message
from textual.reactive import Reactive, reactive
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Rule, Static
from textual.widgets._data_table import RowDoesNotExist

from jiratui.api_controller.controller import APIControllerResponse
from jiratui.config import CONFIGURATION
from jiratui.models import JiraIssue, JiraIssueSearchResponse, SortSpec
from jiratui.utils.column_values import render_field_value
from jiratui.utils.columns import (
    INDEX_COLUMN_ID,
    STATUS_COLUMN_ID,
    SUMMARY_COLUMN_ID,
    WORK_ITEM_TYPE_COLUMN_ID,
    ColumnSpec,
    column_ids_from_config,
    fixed_width_of,
    resolve_columns,
    sortable_field_for,
)
from jiratui.utils.session import ApplicationSession
from jiratui.utils.styling import get_style_for_work_item_status, get_style_for_work_item_type
from jiratui.utils.urls import build_external_url_for_issue
from jiratui.widgets.messages import SearchWorkItem
from jiratui.widgets.screens.goto import GotToScreen


class ConfirmDeleteItemScreen(ModalScreen[bool]):
    """A modal screen that allows users to confirm deleting an item."""

    BINDINGS = [('escape', 'app.pop_screen', 'Close Screen')]

    def __init__(self, work_item_key: str):
        super().__init__()
        self._work_item_key = work_item_key

    def compose(self) -> ComposeResult:
        vertical = Vertical()
        vertical.border_title = f'Delete Work Item {self._work_item_key}'
        with vertical:
            yield Static(
                Text(
                    f'Warning: if the work item {self._work_item_key} has subtasks, deleting it will also delete all its subtasks!',
                    style='italic orange',
                )
            )
            yield Rule()
            with ItemGrid(classes='delete-work-item-grid-buttons'):
                yield Button('Delete', variant='success', id='delete-work-item-button')
                yield Button('Cancel', variant='error', id='delete-work-item-button-cancel')

    @on(Button.Pressed, '#delete-work-item-button')
    def delete_item(self) -> None:
        if self._work_item_key:
            self.dismiss(True)

    @on(Button.Pressed, '#delete-work-item-button-cancel')
    def cancel_deleting_item(self) -> None:
        self.dismiss(False)


class DataTableSearchInput(Input):
    """An input field that allows users to perform searches in the currently active search results page.

    The feature to search within search results pages is controlled by these settings:

    - `search_results_page_filtering_enabled`
    - `search_results_page_filtering_minimum_term_length`
    """

    BINDINGS = [Binding('escape', 'hide', 'Hide search input', show=False)]

    total: Reactive[int | None] = reactive(None)
    """Keeps track of the total number of records after filtering them based on the input value."""

    def __init__(
        self,
        placeholder: str | None = None,
        border_title: str | None = None,
        hide: bool | None = True,
    ):
        super().__init__(id='searchable-datatable-input-field')
        self.placeholder = placeholder or 'Type to filter items in the current page...'
        self.border_title = border_title or 'Filter'
        self.styles.display = 'none' if hide else 'block'

    def action_hide(self) -> None:
        # hide the input widget
        self.styles.display = 'none'
        screen = cast('MainScreen', self.screen)  # type:ignore[name-defined] # noqa: F821
        # reset the results to the initial result set
        screen.search_results_table.search_results = (
            screen.search_results_table.get_initial_results_set()
        )
        # give focus back to the data table
        screen.search_results_table.focus()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Check if an action may run."""
        if action == 'hide' and not CONFIGURATION.get().search_results_page_filtering_enabled:
            return False
        return True

    def watch_total(self, value: int | None = None) -> None:
        if value is not None:
            self.border_subtitle = f'Found: {value}'
        else:
            self.border_subtitle = None

    @on(Input.Changed)
    async def on_input_changed(self, event: Input.Changed) -> None:
        screen = cast('MainScreen', self.screen)  # type:ignore[name-defined] # noqa: F821
        cleaned = event.value.strip() if event.value else None
        if not cleaned or (
            len(cleaned) < CONFIGURATION.get().search_results_page_filtering_minimum_term_length
        ):
            screen.search_results_table.search_results = (
                screen.search_results_table.get_initial_results_set()
            )
            self.total = 0
        else:
            cleaned = cleaned.lower()
            if (initial_results_set := screen.search_results_table.get_initial_results_set()) and (
                issues := initial_results_set.issues
            ):
                filtered: list[JiraIssue] = [
                    record
                    for record in issues
                    if (
                        cleaned in record.summary.lower()
                        or cleaned in record.key.lower()
                        or cleaned in record.parent_key
                    )
                ]
                screen.search_results_table.search_results = JiraIssueSearchResponse(
                    issues=filtered
                )
                self.total = len(filtered)


class IssuesSearchResultsTable(DataTable):
    """The widget that displays the results of a search.

    This widget provides a reactive attribute, `search_results`, that contains the issues that the table will
    display.

    The widget can post a message of type [IssuesSearchResultsTable.WorkItemDeleted](#jiratui.widgets.search.IssuesSearchResultsTable.WorkItemDeleted)
    when the user deletes an item from the table.

    ```{important}
    Deleting an item will delete the item from Jira. After a successful deletion the datatable will remove the row
    related to the item that was deleted. In addition, the widget will send the message
    [IssuesSearchResultsTable.WorkItemDeleted](#jiratui.widgets.search.IssuesSearchResultsTable.WorkItemDeleted) to
    notify other widgets so they can update the relevant widgets.
    ```

    **See Also**:
    - [Use Case: Open Go-To Screen](#use-case-search-results-goto-screen)
    - [Use Case: Search and Fetch using Go-To Screen](#use-case-search-and-fetch-item-goto-screen)
    """

    search_results: Reactive[JiraIssueSearchResponse | None] = reactive(None, always_update=True)

    BINDINGS = [
        Binding(
            key='.',
            action='filter',
            description='Filter',
            tooltip='Filter the results of the current page',
        ),
        Binding('escape', 'hide', 'Hide search input', show=False),
        Binding(
            key='alt+left',
            action='previous_issues_page',
            description='\uf060',
            show=True,
            key_display='alt+left',
            tooltip='Previous page',
        ),
        Binding(
            key='alt+right',
            action='next_issues_page',
            description='\uf061',
            show=True,
            key_display='alt+right',
            tooltip='Next page',
        ),
        Binding(
            key='ctrl+o',
            action='open_issue_in_browser',
            description='Browse',
            show=True,
            key_display='^o',
            tooltip='Open item in the browser',
        ),
        Binding(
            key='d',
            action='delete_work_item',
            description='\uf014',
            show=True,
            key_display='d',
            tooltip='Delete the work item currently highlighted',
        ),
        Binding(
            key='f6',
            action='open_go_to_screen',
            description='Related',
            show=True,
            key_display='f6',
            tooltip='View related work items',
        ),
        Binding(
            key='s',
            action='sort_by_column',
            description='Sort',
            show=True,
            key_display='s',
            tooltip='Sort the results by the current column',
        ),
    ]

    SMALLEST_MAXIMUM_WIDTH_FOR_SUMMARY_COLUMN = 30

    class WorkItemDeleted(Message):
        def __init__(self, work_item_key: str) -> None:
            self._work_item_key = work_item_key
            super().__init__()

        @property
        def work_item_key(self) -> str:
            return self._work_item_key

    def __init__(self):
        super().__init__(id='search_results', cursor_type='row')
        # stores the next page's token by page number
        # e.g.: {2: 'token-a', 3: 'token-b'}
        # to fetch the results page
        #   2: we need to use the token 'token-a'
        #   3: we need to use the token 'token-b'
        self.token_by_page: dict[int, str] = {}
        self.page = 1
        self.current_work_item_key: str | None = None
        self.current_work_item_id: str | None = None
        self._initial_results_set: JiraIssueSearchResponse | None = None
        self.sort_spec: SortSpec | None = None
        """The criteria used to sort the results. This is set when the user sorts by a column, and it takes precedence
        over the "Order By" widget. The rows are sorted by Jira, not by this table, so that the sorting applies to
        every page of the results and not only to the page currently displayed."""
        self.sort_column_id: str | None = None
        """The id of the column that the results are sorted by. Kept so the header of the column can display the
        direction of the sorting after the table is rebuilt."""

    @property
    def current_work_item(self) -> JiraIssue | None:
        """The work item that the cursor is on.

        The table stores the key of the work item, not the work item itself, so it is looked up among the results
        currently displayed. This is the only reliable source of the full summary of the item: the summary rendered in
        the row is truncated, and the column that displays it may not be one of the columns chosen by the user.

        Returns:
            The work item that the cursor is on; or `None` when the results do not contain it.
        """

        if not self.current_work_item_key or not self.search_results:
            return None
        for issue in self.search_results.issues or []:
            if issue.key == self.current_work_item_key:
                return issue
        return None

    def set_initial_results_set(self, data: JiraIssueSearchResponse | None = None):
        self._initial_results_set = data

    def get_initial_results_set(self) -> JiraIssueSearchResponse | None:
        return self._initial_results_set

    def watch_search_results(self, response: JiraIssueSearchResponse | None = None) -> None:
        """Watches the content of a reactive attribute that contains the details of the work item selected by the user.

        Args:
            response: an instance of `JiraIssueSearchResponse` with the work item selected by the user.

        Returns:
            None
        """
        if response is None:
            return

        # clearing the table moves the cursor back to the first column; the column that the user was on is restored
        # once the rows are rebuilt, so that e.g. sorting by a column again reverses the sorting of that same column
        previous_cursor_column = self.cursor_column

        # clear the existing data
        self.clear(columns=True)

        columns = self.active_columns

        maximum_summary_column_width = max(
            self.SMALLEST_MAXIMUM_WIDTH_FOR_SUMMARY_COLUMN,
            self.parent.container_size.width - fixed_width_of(columns),  # type:ignore[attr-defined]
        )

        # update next search tokens
        if response.next_page_token:
            # there is a token to fetch the next page
            self.token_by_page[self.page + 1] = response.next_page_token

        # set the columns
        self.add_columns(*[self._build_header(column) for column in columns])
        # build the rows
        for index, issue in enumerate(response.issues):
            self.add_row(
                *[
                    self._build_cell(column, issue, index, maximum_summary_column_width)
                    for column in columns
                ],
                key=f'{issue.id}#{issue.key}',
            )

        if response.issues and previous_cursor_column:
            self.cursor_coordinate = Coordinate(
                self.cursor_coordinate.row, min(previous_cursor_column, len(columns) - 1)
            )

    @property
    def active_columns(self) -> list[ColumnSpec]:
        """The columns currently displayed by the table.

        The columns are owned by the screen because they determine the fields that the screen requests from the API
        when it searches for work items.
        """

        columns = getattr(self.screen, 'active_columns', None)
        if not columns:
            return resolve_columns(column_ids_from_config(CONFIGURATION.get()))
        return columns

    def _build_header(self, column: ColumnSpec) -> str:
        """Builds the label of the header of a column.

        The label of the column that the results are sorted by displays the direction of the sorting.

        Args:
            column: the column.

        Returns:
            The label to display in the header of the column.
        """

        if self.sort_spec and column.id == self.sort_column_id:
            return f'{column.label} {"▼" if self.sort_spec.descending else "▲"}'
        return column.label

    def _build_cell(
        self, column: ColumnSpec, issue: JiraIssue, index: int, maximum_summary_column_width: int
    ):
        """Builds the value of a cell of the table.

        Args:
            column: the column that the cell belongs to.
            issue: the work item that the row of the cell displays.
            index: the position of the work item within the current page of results.
            maximum_summary_column_width: the width available for the summary of a work item.

        Returns:
            The value to display in the cell.
        """

        if column.id == INDEX_COLUMN_ID:
            return index + 1
        if column.id == SUMMARY_COLUMN_ID:
            return Text(
                issue.cleaned_summary(
                    CONFIGURATION.get().search_results_truncate_work_item_summary
                    or maximum_summary_column_width
                )
            )
        if column.id == STATUS_COLUMN_ID:
            style_status = ''
            if CONFIGURATION.get().search_results_style_work_item_status:
                style_status = get_style_for_work_item_status(issue.status.name.lower())
            return Text(issue.status.name, style=style_status)
        if column.id == WORK_ITEM_TYPE_COLUMN_ID:
            style_work_type = ''
            if CONFIGURATION.get().search_results_style_work_item_type:
                style_work_type = get_style_for_work_item_type(issue.issue_type.name.lower())
            return Text(issue.work_item_type_name, style=style_work_type)
        if column.getter:
            return Text(str(column.getter(issue) or ''))
        # the column displays a field that is not modelled by JiraIssue; e.g.: a custom field
        return Text(render_field_value((issue.raw_fields or {}).get(column.id)))

    def _jql_fields(self) -> list:
        return ApplicationSession().get('jql_fields') or []

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Sorts the results by the column whose header the user clicked."""

        event.stop()
        self._sort_by_column_at(event.column_index)

    def action_sort_by_column(self) -> None:
        """Sorts the results by the column that the cursor is on.

        Pressing this again on the same column reverses the direction of the sorting.
        """

        self._sort_by_column_at(self.cursor_column)

    def _sort_by_column_at(self, column_index: int) -> None:
        columns = self.active_columns
        if column_index < 0 or column_index >= len(columns):
            return
        column = columns[column_index]
        field = sortable_field_for(column, self._jql_fields())
        if not field:
            self.notify(
                f'The results cannot be sorted by "{column.label}".',
                title='Sort Results',
                severity='warning',
            )
            return

        if self.sort_column_id == column.id and self.sort_spec:
            self.sort_spec = self.sort_spec.toggled()
        else:
            self.sort_spec = SortSpec(field=field)
        self.sort_column_id = column.id
        # the results are sorted by Jira, so the search needs to run again; the tokens of the pages of the results
        # sorted by the previous criteria are no longer valid
        self.page = 1
        self.token_by_page = {}
        screen = cast('MainScreen', self.screen)  # type:ignore[name-defined] # noqa: F821
        self.run_worker(screen.action_search(), exclusive=True)

    def clear_sorting(self) -> None:
        """Stops sorting the results by a column.

        This is used when the user chooses a different criteria using the "Order By" widget, which would otherwise
        appear to have no effect.
        """

        self.sort_spec = None
        self.sort_column_id = None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Fetches the details of the currently-selected item."""
        if event.row_key:
            screen = cast('MainScreen', self.screen)  # type:ignore[name-defined] # noqa: F821
            # bring the details pane back into view if the user hid it; no-op when already visible
            screen.show_details_pane()
            self.current_work_item_id, self.current_work_item_key = event.row_key.value.split('#')
            # use exclusive=True to make sure that if the user selects another work item before the worker finishes
            # retrieving the data of the previously selected the correct data is fetched
            # the exclusive flag tells Textual to cancel all previous workers before starting the new one.
            self.run_worker(screen.fetch_issue(self.current_work_item_key), exclusive=True)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Stores the key of the currently-selected item."""
        if event.row_key:
            self.current_work_item_id, self.current_work_item_key = event.row_key.value.split('#')

    def action_open_issue_in_browser(self) -> None:
        """Opens the currently-selected item in the default browser."""
        if self.current_work_item_key:
            self.notify('Opening Work Item in the browser...')
            self.app.open_url(build_external_url_for_issue(self.current_work_item_key))

    def action_delete_work_item(self) -> None:
        """Deletes the currently-selected item."""

        if self.current_work_item_key:
            self.run_worker(
                self._open_work_item_deletion_screen(self.current_work_item_key), exclusive=True
            )

    async def _open_work_item_deletion_screen(self, work_item_key: str) -> None:
        """Opens a modal screen to let the user decided whether to delete the work item or not.

        Args:
            work_item_key: key of the work item to delete.

        Returns:
            None
        """

        await self.app.push_screen(
            ConfirmDeleteItemScreen(work_item_key), callback=self._delete_work_item
        )

    async def _delete_work_item(self, delete_item: bool = False) -> None:
        """Deletes the currently-selected item.

        Args:
            delete_item: if `True` the user confirmed deleting the item in the modal screen; otherwise the user
            canceled the operation.

        Returns:
            None.
        """

        if delete_item and self.current_work_item_key:
            response: APIControllerResponse = await self.app.api.delete_work_item(  # type:ignore[attr-defined]
                self.current_work_item_key
            )
            if response.success:
                try:
                    self.remove_row(f'{self.current_work_item_id}#{self.current_work_item_key}')
                except RowDoesNotExist:
                    pass
                else:
                    # post the message to the parent container can update the pagination legend
                    self.post_message(self.WorkItemDeleted(self.current_work_item_key))
                    # force the table to highlight another item to avoid RowDoesNotExist exceptions with the next delete
                    # attempt
                    self.action_cursor_up()
                    self.action_cursor_down()
                self.notify(f'Deleted {self.current_work_item_key}', title='Delete Work Item')
            else:
                self.notify(
                    f'Failed to delete the item {self.current_work_item_key}.',
                    title='Delete Work Item',
                    severity='error',
                )
                if response.error:
                    self.notify(
                        response.error,
                        title='Delete Work Item',
                        severity='error',
                    )

    def action_filter(self) -> None:
        if not CONFIGURATION.get().search_results_page_filtering_enabled:
            return
        screen = cast('MainScreen', self.screen)  # type:ignore[name-defined] # noqa: F821
        widget = screen.search_results_filter_input
        widget.styles.display = 'block'
        widget.focus(True)
        widget.total = 0
        widget.value = ''
        self.refresh_bindings()

    def action_hide(self) -> None:
        if not CONFIGURATION.get().search_results_page_filtering_enabled:
            return
        screen = cast('MainScreen', self.screen)  # type:ignore[name-defined] # noqa: F821
        # hide the input widget
        screen.search_results_filter_input.styles.display = 'none'
        # reset the results to the initial result set
        self.search_results = self.get_initial_results_set()
        # give focus back to the data table
        self.focus()
        self.refresh_bindings()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Check if an action may run."""

        if action == 'filter' and not CONFIGURATION.get().search_results_page_filtering_enabled:
            return False
        if action == 'hide' and not CONFIGURATION.get().search_results_page_filtering_enabled:
            return False
        if action == 'previous_issues_page':
            if self.page > 1:
                return True
            return False
        if action == 'next_issues_page':
            if self.token_by_page.get(self.page + 1):
                return True
            if self.page > 0:
                return True
            return False
        return True

    async def action_previous_issues_page(self):
        if self.page > 1:
            next_page_token = self.token_by_page.get(self.page - 1)
            self.page -= 1
            screen = cast('MainScreen', self.screen)  # type:ignore[name-defined] # noqa: F821
            await screen.search_issues(next_page_token, page=self.page)
            self.refresh_bindings()

    async def action_next_issues_page(self):
        next_page_token = self.token_by_page.get(self.page + 1)
        self.page += 1
        screen = cast('MainScreen', self.screen)  # type:ignore[name-defined] # noqa: F821
        await screen.search_issues(next_page_token, page=self.page)
        self.refresh_bindings()

    def action_open_go_to_screen(self) -> None:
        """Opens a modal screen to show the work items related to the work item selected by the user in the search
        results table.

        The screen will be opened only if `config.enable_goto == True` and there is a work item selected.

        Returns:
            None
        """

        if CONFIGURATION.get().enable_goto and self.current_work_item_key:
            self.app.push_screen(
                GotToScreen(self.current_work_item_key, self.app.api),  # type:ignore[attr-defined]
                callback=self._close_goto_screen,
            )
        elif not self.current_work_item_key:
            self.notify('Select/Highlight an item to view its related items')
        else:
            self.notify('This feature is disabled. Check config.enable_goto', severity='warning')

    def _close_goto_screen(self, work_item_key: str) -> None:
        # sends a message to request the handler, the Main Screen, to search for the work item with the given key
        if work_item_key:
            self.post_message(SearchWorkItem(work_item_key))


class SearchResultsContainer(Container):
    """The container that holds the DataTable widget with the search results.

    This widget provides a reactive attribute called `pagination`. The attribute accepts a dictionary with the details
    of the search results' pagination. This includes `current_page_number` and `total`. When this attribute is updated
    the widget will update the legend in the border subtitle to display the number of results and the page number.
    """

    pagination: Reactive[dict | None] = reactive(None)
    """Reactive attribute that contains pagination details associated to the search results. This is used setting the
    widget's border subtitle with the page number and total records in the result."""

    def __init__(self, *args, **kwargs):
        border_title = kwargs.pop('border_title', None)
        super().__init__(*args, **kwargs)
        self.border_title = border_title or 'Work Items'
        self.config = CONFIGURATION.get()
        self._total_results = None
        self._page_number = None
        self._total_pages = None

    def _update_border_subtitle(self) -> None:
        if self._total_results is None:
            self.border_subtitle = (
                None if self._page_number is None else f'Page {self._page_number}'
            )
        else:
            self._total_pages = self._total_results // self.config.search_results_per_page
            if (self._total_results % self.config.search_results_per_page) > 0:
                self._total_pages += 1
            if self._page_number is not None:
                self.border_subtitle = f'Page {self._page_number} of {self._total_pages} (total: {self._total_results})'
            else:
                self.border_subtitle = None

    def watch_pagination(self, response: dict) -> None:
        if response:
            self._page_number = max(1, response.get('current_page_number'))
            self._total_results = response.get('total', 0)
            self._update_border_subtitle()

    @on(IssuesSearchResultsTable.WorkItemDeleted)
    def update_pagination_details_after_delete(
        self, message: IssuesSearchResultsTable.WorkItemDeleted
    ) -> None:
        # update the total number of records and the border legend
        self._total_results = 0 if self._total_results is None else self._total_results - 1
        self._update_border_subtitle()
