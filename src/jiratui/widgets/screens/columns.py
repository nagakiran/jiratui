from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, OptionList, Static
from textual.widgets.option_list import Option

from jiratui.utils.columns import ColumnSpec

SELECTED_MARKER = '[x]'
UNSELECTED_MARKER = '[ ]'


class ColumnSelectionScreen(ModalScreen[list[str] | None]):
    """A modal screen that lets the user choose the columns displayed in the search results table.

    The screen displays the columns that are currently selected first, in the order in which they are displayed by the
    table, followed by every other field that the user can add as a column.

    The screen dismisses with the ids of the selected columns, in the order chosen by the user; or with `None` when the
    user cancels.

    ```{important}
    The list of available columns includes every field of the Jira instance, which can easily be a hundred entries;
    hence the filter input at the top of the screen.
    ```
    """

    BINDINGS = [
        Binding('escape', 'cancel', 'Cancel', show=True),
        Binding('space', 'toggle_column', 'Add/Remove', show=True),
        Binding('enter', 'apply', 'Apply', show=True, priority=True),
        Binding('shift+up', 'move_up', 'Move up', show=True, key_display='shift+↑'),
        Binding('shift+down', 'move_down', 'Move down', show=True, key_display='shift+↓'),
        Binding('ctrl+r', 'reset', 'Reset', show=True, key_display='^r'),
    ]
    TITLE = 'Configure Columns'
    HELP = 'Choose the columns displayed in the search results'

    def __init__(
        self,
        available_columns: list[ColumnSpec],
        selected_column_ids: list[str],
        default_column_ids: list[str] | None = None,
    ):
        """Initializes the screen.

        Args:
            available_columns: every column that the user can display; including the ones currently selected.
            selected_column_ids: the ids of the columns currently displayed, in the order in which they are displayed.
            default_column_ids: the ids of the columns defined in the configuration file. Used to reset the selection.
        """

        super().__init__()
        self._columns_by_id: dict[str, ColumnSpec] = {
            column.id: column for column in available_columns
        }
        self._selected_ids: list[str] = [
            column_id for column_id in selected_column_ids if column_id in self._columns_by_id
        ]
        self._default_ids: list[str] = list(
            default_column_ids if default_column_ids is not None else self._selected_ids
        )
        self._filter_term: str = ''

    @property
    def option_list(self) -> OptionList:
        return self.query_one('#column-selection-list', expect_type=OptionList)

    @property
    def filter_input(self) -> Input:
        return self.query_one('#column-selection-filter', expect_type=Input)

    @property
    def selected_column_ids(self) -> list[str]:
        """The ids of the columns currently selected, in the order in which they will be displayed."""

        return list(self._selected_ids)

    def compose(self) -> ComposeResult:
        container = Vertical(id='column-selection-container')
        container.border_title = self.TITLE
        with container:
            yield Static(
                'Press space to add/remove a column; shift+up/shift+down to re-order it.',
                classes='message-tip',
            )
            yield Input(
                placeholder='Filter columns...',
                id='column-selection-filter',
                compact=True,
            )
            yield OptionList(id='column-selection-list')
        yield Footer(show_command_palette=False, compact=True)

    def on_mount(self) -> None:
        self._rebuild_options()
        self.option_list.focus()

    def _ordered_ids(self) -> list[str]:
        """The ids of every column: the selected ones first, in order, followed by the rest sorted by label."""

        unselected = sorted(
            (column_id for column_id in self._columns_by_id if column_id not in self._selected_ids),
            key=lambda column_id: self._columns_by_id[column_id].label.lower(),
        )
        return self._selected_ids + unselected

    def _matches_filter(self, column: ColumnSpec) -> bool:
        if not self._filter_term:
            return True
        term = self._filter_term.lower()
        return term in column.label.lower() or term in column.id.lower()

    def _rebuild_options(self, highlight_column_id: str | None = None) -> None:
        option_list = self.option_list
        option_list.clear_options()
        for column_id in self._ordered_ids():
            column = self._columns_by_id[column_id]
            if not self._matches_filter(column):
                continue
            marker = SELECTED_MARKER if column_id in self._selected_ids else UNSELECTED_MARKER
            option_list.add_option(Option(f'{marker} {column.label}', id=column_id))
        if highlight_column_id:
            self._highlight(highlight_column_id)

    def _highlight(self, column_id: str) -> None:
        option_list = self.option_list
        try:
            option_list.highlighted = option_list.get_option_index(column_id)
        except Exception:
            # the column is not displayed because it does not match the filter
            pass

    @property
    def _highlighted_column_id(self) -> str | None:
        option_list = self.option_list
        if option_list.highlighted is None:
            return None
        return option_list.get_option_at_index(option_list.highlighted).id

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != 'column-selection-filter':
            return
        self._filter_term = event.value.strip()
        self._rebuild_options()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        # selecting an option with the mouse toggles the column
        event.stop()
        if event.option.id:
            self._toggle(event.option.id)

    def _toggle(self, column_id: str) -> None:
        if column_id in self._selected_ids:
            self._selected_ids.remove(column_id)
        else:
            self._selected_ids.append(column_id)
        self._rebuild_options(highlight_column_id=column_id)

    def action_toggle_column(self) -> None:
        """Adds the highlighted column to the table, or removes it when it is already displayed."""

        if column_id := self._highlighted_column_id:
            self._toggle(column_id)

    def _move(self, offset: int) -> None:
        column_id = self._highlighted_column_id
        if not column_id or column_id not in self._selected_ids:
            # only the columns displayed by the table can be re-ordered
            return
        position = self._selected_ids.index(column_id)
        new_position = position + offset
        if new_position < 0 or new_position >= len(self._selected_ids):
            return
        self._selected_ids.insert(new_position, self._selected_ids.pop(position))
        self._rebuild_options(highlight_column_id=column_id)

    def action_move_up(self) -> None:
        """Displays the highlighted column one position to the left."""

        self._move(-1)

    def action_move_down(self) -> None:
        """Displays the highlighted column one position to the right."""

        self._move(1)

    def action_reset(self) -> None:
        """Restores the columns defined in the configuration file."""

        self._selected_ids = [
            column_id for column_id in self._default_ids if column_id in self._columns_by_id
        ]
        self._rebuild_options()

    def action_apply(self) -> None:
        """Closes the screen and applies the selected columns."""

        if not self._selected_ids:
            self.notify('Select at least one column.', title=self.TITLE, severity='warning')
            return
        self.dismiss(self._selected_ids)

    def action_cancel(self) -> None:
        """Closes the screen without changing the columns of the table."""

        self.dismiss(None)
