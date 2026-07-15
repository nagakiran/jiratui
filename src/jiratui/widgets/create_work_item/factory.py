from textual.widget import Widget

from jiratui.api_controller.controller import APIController
from jiratui.config import CONFIGURATION
from jiratui.widgets.commons import FieldMode
from jiratui.widgets.commons.factory_utils import (
    CUSTOM_FIELD_TYPES_NOT_SUPPORTED,
    FIELDS_IDS_NOT_SUPPORTED,
    build_widget_for_field,
)

__all__ = [
    'CREATE_FORM_DEFAULT_FIELDS_IDS',
    'CREATE_FORM_OPTIONAL_FIELDS_IDS',
    'CUSTOM_FIELD_TYPES_NOT_SUPPORTED',
    'FIELDS_IDS_NOT_SUPPORTED',
    'create_widgets_for_work_item_creation',
]


def create_widgets_for_work_item_creation(
    data: list[dict],
    api_controller: APIController | None = None,
    adf_support_enabled: bool = True,
) -> list[Widget]:
    """Creates a list of Textual widgets for the "form" that allows users to create work items.

    Fields that are statically included in the form, such as `project`, `issuetype`, `reporter`, etc. are ignored by
    this function. As a result this function will not return Textual's Widget instances for them. These fields are
    defined in [CREATE_FORM_DEFAULT_FIELDS](#src.jiratui.widgets.create_work_item.factory.CREATE_FORM_DEFAULT_FIELDS).

    The widget of each individual field is built by
    [build_widget_for_field](#src.jiratui.widgets.commons.factory_utils.build_widget_for_field), which is also used to
    build the fields of a transition screen.

    Args:
        data: a list of dictionaries with the create-metadata information for all the fields of a given type of work
        item supported in a project.
        api_controller: an optional APIController instance to make requests to the Jira API; unused, for compatibility.
        adf_support_enabled: indicates if ADF support is enabled. This means the following:
        `config.cloud and config.jira_api_version == 3`.

    Returns:
        A list of `textual.widget.Widget` instances for every supported field.
    """

    widgets: list[Widget] = []
    config = CONFIGURATION.get()
    ignore_list = config.create_additional_fields_ignore_ids or []
    enable_additional = config.enable_creating_additional_fields

    for item in data:
        field_id: str = item.get('fieldId')

        if field_id in CREATE_FORM_DEFAULT_FIELDS_IDS:
            # ignore them because they will be included in the form anyway
            continue

        if not item.get('required', False):
            if field_id in ignore_list:
                continue
            if not enable_additional and field_id not in CREATE_FORM_OPTIONAL_FIELDS_IDS:
                continue

        if widget := build_widget_for_field(
            item, adf_support_enabled=adf_support_enabled, mode=FieldMode.CREATE
        ):
            widgets.append(widget)
    return widgets


CREATE_FORM_DEFAULT_FIELDS_IDS: list[str] = [
    'project',
    'issuetype',
    'reporter',
    'summary',
    'description',
    'parent',
    'assignee',
]
CREATE_FORM_OPTIONAL_FIELDS_IDS: list[str] = [
    'duedate',
    'priority',
]
