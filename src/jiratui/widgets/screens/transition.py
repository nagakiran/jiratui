from typing import Any

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import ItemGrid, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Input, Rule, Select, Static

from jiratui.models import IssueTransition
from jiratui.widgets.commons import FieldMode
from jiratui.widgets.commons.base import LabelsAutoComplete, MultiUserPickerAutoComplete
from jiratui.widgets.commons.factory_utils import (
    build_widget_for_field,
    format_field_value_for_api,
)
from jiratui.widgets.commons.users import UsersAutoComplete
from jiratui.widgets.commons.widgets import (
    LabelsWidget,
    MultiUserPickerWidget,
    SingleUserPickerWidget,
)


def normalize_transition_fields(fields: dict) -> list[dict]:
    """Normalizes the metadata of the fields of a transition screen.

    Jira returns the fields of a transition keyed by field ID, and each field carries its ID in a `key` attribute.
    The widget factory, however, expects the shape used by the create-metadata resource, where the ID of the field is
    stored in a `fieldId` attribute. This function bridges the 2 shapes.

    Args:
        fields: the fields of a transition, keyed by field ID, as returned by Jira.

    Returns:
        A list with the metadata of every field, each one with a `fieldId` attribute.
    """

    normalized: list[dict] = []
    for field_id, metadata in (fields or {}).items():
        normalized.append({**metadata, 'fieldId': metadata.get('fieldId') or field_id})
    return normalized


def create_widgets_for_transition(fields: dict, adf_support_enabled: bool = True) -> list[Widget]:
    """Creates the widgets for the fields displayed by the screen of a status transition.

    Args:
        fields: the fields of a transition, keyed by field ID, as returned by Jira.
        adf_support_enabled: indicates if ADF support is enabled. This means the following:
        `config.cloud and config.jira_api_version == 3`.

    Returns:
        A list of `textual.widget.Widget` instances for every supported field.
    """

    widgets: list[Widget] = []
    for item in normalize_transition_fields(fields):
        if widget := build_widget_for_field(
            item, adf_support_enabled=adf_support_enabled, mode=FieldMode.CREATE
        ):
            widgets.append(widget)
    return widgets


class TransitionScreen(ModalScreen[dict | None]):
    """A modal screen that collects the values of the fields displayed by a transition screen.

    Some Jira workflows display a screen when a work item is transitioned to a new status, e.g. to ask the user for the
    reason why the work item is being transitioned. This screen renders those fields and returns their values to the
    caller via `dismiss()`; the caller is the one that performs the transition via the API.

    The screen sends back to the caller a dictionary with the values of the fields, keyed by field ID and formatted the
    way the Jira API expects them, e.g.:

    ```python
    {'customfield_10343': {'id': '11623'}}
    ```

    If the user cancels the screen then `None` is sent back to the caller, which indicates that the transition should
    not be performed.

    Note that the fields are **not** validated before they are submitted. Jira reports a field as `required` only when
    the field is mandatory in the *field configuration*; a field that a workflow validator makes mandatory is reported
    as optional. As a result the errors raised by the workflow are reported by the API, and the caller displays them.
    """

    BINDINGS = [
        ('escape', 'cancel', 'Close'),
        Binding('ctrl+s', 'save', 'Save', key_display='^s'),
    ]
    TITLE = 'Transition Work Item'

    def __init__(
        self,
        work_item_key: str,
        transition: IssueTransition,
        adf_support_enabled: bool = True,
    ):
        super().__init__()
        self.work_item_key = work_item_key
        self.transition = transition
        self.adf_support_enabled = adf_support_enabled
        self.title = f'{transition.name} - Work Item: {work_item_key}'

    @property
    def fields_container(self) -> VerticalScroll:
        return self.query_one('#transition-fields', expect_type=VerticalScroll)

    def compose(self) -> ComposeResult:
        vertical = Vertical()
        vertical.border_title = self.title
        with vertical:
            yield Static(
                Text('Important: Fields marked with (*) are required.', style='italic orange')
            )
            yield Rule()
            yield VerticalScroll(id='transition-fields')
            with ItemGrid(classes='transition-screen-grid-buttons'):
                yield Button('Save', variant='success', id='transition-button-save')
                yield Button('Cancel', variant='error', id='transition-button-quit')

    async def on_mount(self) -> None:
        widgets: list[Widget] = create_widgets_for_transition(
            self.transition.fields, adf_support_enabled=self.adf_support_enabled
        )
        await self.fields_container.mount_all(widgets)
        # the container is only used for scrolling; if it takes the focus then the keys that the fields rely on, e.g.
        # the keys that expand a dropdown, never reach them
        self.fields_container.can_focus = False
        # the widgets that allow users to select labels and users need a companion AutoComplete widget
        api_controller = self.app.api  # type:ignore[attr-defined]
        for input_widget in self.fields_container.query(Input):
            if isinstance(input_widget, LabelsWidget):
                metadata: dict = self.transition.fields.get(input_widget.field_id, {})
                await self.fields_container.mount(
                    LabelsAutoComplete(
                        target=input_widget,
                        api_controller=api_controller,
                        required=metadata.get('required', False),
                        title=metadata.get('name', 'Labels'),
                    )
                )
            elif isinstance(input_widget, MultiUserPickerWidget):
                await self.fields_container.mount(
                    MultiUserPickerAutoComplete(target=input_widget, api_controller=api_controller)
                )
            elif isinstance(input_widget, SingleUserPickerWidget):
                await self.fields_container.mount(
                    UsersAutoComplete(target=input_widget, api_controller=api_controller)
                )

        if widgets:
            widgets[0].focus()

    def _collect_field_values(self) -> dict:
        """Extracts the values of the fields of the transition screen.

        Returns:
            A dictionary with the values of the fields that the user filled-in, keyed by field ID, formatted the way
            the Jira API expects them.
        """

        values: dict = {}
        for widget in self.fields_container.children:
            field_id: str = getattr(widget, 'field_id', '')
            if not field_id:
                continue

            value: Any
            if hasattr(widget, 'get_value_for_create'):
                # these widgets already return the value with the shape that the API expects
                if value := widget.get_value_for_create():
                    values[field_id] = value
                continue
            elif isinstance(widget, Select):
                value = widget.selection
            elif isinstance(widget, Input):
                value = widget.value
            else:
                continue

            metadata: dict = self.transition.fields.get(field_id, {})
            if (formatted := format_field_value_for_api(field_id, value, metadata)) is not None:
                values[field_id] = formatted
        return values

    @on(Button.Pressed, '#transition-button-save')
    def handle_save(self) -> None:
        self.dismiss(self._collect_field_values())

    def action_save(self) -> None:
        self.handle_save()

    @on(Button.Pressed, '#transition-button-quit')
    def handle_cancel(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.handle_cancel()
