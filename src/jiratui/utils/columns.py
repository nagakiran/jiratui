"""This module provides the registry of columns that the search results table can display.

A column is described by a `ColumnSpec`. The registry knows about the fields modelled by `JiraIssue` (the built-in
columns) and can synthesize a spec for any other field known to the Jira instance, including custom fields.

```{important}
`ColumnSpec.api_fields` is what makes a column work: a column renders an empty value unless the fields it needs are
requested from the API when the work items are searched. Use `api_fields_for` to build the list of fields to request.
```
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
import re
from typing import TYPE_CHECKING, Any

from jiratui.utils.jql import strip_quotes

if TYPE_CHECKING:
    from jiratui.models import JiraField, JiraIssue

INDEX_COLUMN_ID = 'index'
"""The id of the column that displays the position of a work item within the current page of results."""

SUMMARY_COLUMN_ID = 'summary'
"""The id of the column that displays the summary of a work item. This column absorbs the remaining width."""

STATUS_COLUMN_ID = 'status'
WORK_ITEM_TYPE_COLUMN_ID = 'issuetype'

BASELINE_API_FIELDS = ('id', 'key', 'status', 'summary', 'issuetype', 'parent')
"""The fields that are always requested from the API.

The table dereferences the status and the type of every work item, and the key of the row is built from the id and the
key of the work item; so these are requested even when no column displays them.
"""

DEFAULT_CUSTOM_COLUMN_WIDTH = 20
"""The nominal width assumed for a column that displays a field that is not known to the registry."""

TYPE_HINT_PATTERN = re.compile(r'\s*\[[^\]]*\]\s*$')
"""Matches the type hint that Jira appends to the name of a field; e.g. the `[Date]` of `Fix-ETA[Date]`."""


@dataclass(frozen=True)
class ColumnSpec:
    """Describes a column of the search results table."""

    id: str
    """The id of the column. For a field that is not built-in this is the id of the Jira field."""
    label: str
    """The name of the column, as displayed in the header of the table."""
    api_fields: tuple[str, ...] = ()
    """The fields to request from the API in order to render the column."""
    width: int = DEFAULT_CUSTOM_COLUMN_WIDTH
    """The nominal width of the column. Used to work out the width left for the summary column."""
    getter: Callable[['JiraIssue'], Any] | None = None
    """Extracts the value of the column from a work item. If this is `None` the value is extracted from the raw
    fields of the work item and rendered generically."""
    sortable_jql_field: str | None = None
    """The name to use in an `ORDER BY` clause to sort by this column. `None` if the column cannot be sorted."""


BUILTIN_COLUMNS: dict[str, ColumnSpec] = {
    INDEX_COLUMN_ID: ColumnSpec(id=INDEX_COLUMN_ID, label='#', width=4),
    'key': ColumnSpec(
        id='key',
        label='Key',
        api_fields=('key',),
        width=12,
        getter=lambda issue: issue.key,
        sortable_jql_field='key',
    ),
    'parent': ColumnSpec(
        id='parent',
        label='Parent',
        api_fields=('parent',),
        width=10,
        getter=lambda issue: issue.parent_key,
        sortable_jql_field='parent',
    ),
    STATUS_COLUMN_ID: ColumnSpec(
        id=STATUS_COLUMN_ID,
        label='Status',
        api_fields=('status',),
        width=8,
        getter=lambda issue: issue.status_name,
        sortable_jql_field='status',
    ),
    WORK_ITEM_TYPE_COLUMN_ID: ColumnSpec(
        id=WORK_ITEM_TYPE_COLUMN_ID,
        label='Type',
        api_fields=('issuetype',),
        width=8,
        getter=lambda issue: issue.work_item_type_name,
        sortable_jql_field='issuetype',
    ),
    SUMMARY_COLUMN_ID: ColumnSpec(
        id=SUMMARY_COLUMN_ID,
        label='Summary',
        api_fields=('summary',),
        width=0,
        getter=lambda issue: issue.cleaned_summary(),
        sortable_jql_field='summary',
    ),
    'assignee': ColumnSpec(
        id='assignee',
        label='Assignee',
        api_fields=('assignee',),
        width=22,
        getter=lambda issue: issue.display_assignee(),
        sortable_jql_field='assignee',
    ),
    'reporter': ColumnSpec(
        id='reporter',
        label='Reporter',
        api_fields=('reporter',),
        width=22,
        getter=lambda issue: issue.display_reporter(),
        sortable_jql_field='reporter',
    ),
    'priority': ColumnSpec(
        id='priority',
        label='Priority',
        api_fields=('priority',),
        width=10,
        getter=lambda issue: issue.priority_name,
        sortable_jql_field='priority',
    ),
    'created': ColumnSpec(
        id='created',
        label='Created',
        api_fields=('created',),
        width=17,
        getter=lambda issue: issue.created_on,
        sortable_jql_field='created',
    ),
    'updated': ColumnSpec(
        id='updated',
        label='Updated',
        api_fields=('updated',),
        width=17,
        getter=lambda issue: issue.updated_on,
        sortable_jql_field='updated',
    ),
    'resolutiondate': ColumnSpec(
        id='resolutiondate',
        label='Resolved',
        api_fields=('resolutiondate',),
        width=17,
        getter=lambda issue: issue.resolved_on,
        sortable_jql_field='resolutiondate',
    ),
    'duedate': ColumnSpec(
        id='duedate',
        label='Due',
        api_fields=('duedate',),
        width=12,
        getter=lambda issue: issue.display_due_date,
        sortable_jql_field='duedate',
    ),
    'labels': ColumnSpec(
        id='labels',
        label='Labels',
        api_fields=('labels',),
        width=20,
        getter=lambda issue: ', '.join(issue.labels or []),
        sortable_jql_field='labels',
    ),
    'components': ColumnSpec(
        id='components',
        label='Components',
        api_fields=('components',),
        width=20,
        getter=lambda issue: ', '.join(
            component.name for component in issue.components or [] if component.name
        ),
        sortable_jql_field='component',
    ),
    'sprint': ColumnSpec(
        id='sprint',
        label='Sprint',
        api_fields=(),
        width=18,
        getter=lambda issue: issue.sprint_name,
        sortable_jql_field='sprint',
    ),
}
"""The columns that display a field modelled by `JiraIssue`."""

DEFAULT_COLUMNS: tuple[str, ...] = (
    INDEX_COLUMN_ID,
    'key',
    'parent',
    STATUS_COLUMN_ID,
    WORK_ITEM_TYPE_COLUMN_ID,
    SUMMARY_COLUMN_ID,
)
"""The columns displayed when the configuration does not specify any."""


def column_ids_from_config(config: Any) -> list[str]:
    """Extracts the ids of the columns to display from the configuration.

    Args:
        config: an instance of `ApplicationConfiguration`.

    Returns:
        The ids of the columns configured by the user; or the ids of the default columns when the configuration does
        not define usable values.
    """

    ids = getattr(config, 'search_results_columns', None)
    if not isinstance(ids, (list, tuple)):
        return list(DEFAULT_COLUMNS)
    valid = [column_id for column_id in ids if isinstance(column_id, str) and column_id]
    return valid or list(DEFAULT_COLUMNS)


def field_name_without_type(value: str) -> str:
    """Removes the trailing type hint from the name of a field.

    The JQL auto-complete data, and the Jira UI itself, refer to a field as `Fix-ETA[Date]`. Users naturally copy that
    form into the configuration file, so the type hint is tolerated when a column is looked up by name.

    Args:
        value: the name of a field, possibly followed by a type hint between square brackets.

    Returns:
        The name of the field without the type hint.
    """

    return TYPE_HINT_PATTERN.sub('', value).strip()


CUSTOM_FIELD_REFERENCE_PATTERN = re.compile(r'^cf\[(\d+)]$', re.IGNORECASE)
"""The way a JQL expression refers to a custom field. E.g.: `cf[10109]`."""


def custom_field_id(reference: str | None) -> str | None:
    """The id of the custom field that a JQL reference points at.

    The JQL auto-complete data refers to a custom field as `cf[10109]`, while the fields of the API — and therefore
    the ids of the columns — spell the same field `customfield_10109`. The two have to be brought to the same form
    before they can be compared.

    Args:
        reference: a reference to a custom field, as it appears in the JQL auto-complete data.

    Returns:
        The id of the field; the reference unchanged when it is not a `cf[...]` reference, and `None` when there is no
        reference at all.
    """

    if not reference:
        return None
    if match := CUSTOM_FIELD_REFERENCE_PATTERN.match(reference.strip()):
        return f'customfield_{match.group(1)}'
    return reference


def resolve_columns(
    ids: Sequence[str],
    jira_fields: Sequence['JiraField'] | None = None,
    widths: dict[str, int] | None = None,
) -> list[ColumnSpec]:
    """Builds the specs of the columns to display.

    Args:
        ids: the columns to display, in the order in which they should be displayed. An entry that is not a built-in
        column is looked up among the fields of the Jira instance, first by id and then by name; e.g. both
        `customfield_10109` and `Fix-ETA` resolve to the same column. An entry that matches nothing is assumed to be
        the id of a Jira field.
        jira_fields: the fields known to the Jira instance. Used to resolve and label the columns that display a field
        that is not built-in. When a field is unknown the id of the field is used as the label.
        widths: optional widths that override the nominal width of a column, keyed by the id of the column; or by the
        name of the field when the column was configured by name.

    Returns:
        A list of `ColumnSpec`. Ids that appear more than once are resolved once, keeping the first occurrence.
    """

    fields_by_id: dict[str, JiraField] = {}
    fields_by_name: dict[str, JiraField] = {}
    for jira_field in jira_fields or []:
        fields_by_id[jira_field.id] = jira_field
        if jira_field.key:
            fields_by_id.setdefault(jira_field.key, jira_field)
        if jira_field.name:
            fields_by_name.setdefault(jira_field.name.lower(), jira_field)

    columns: list[ColumnSpec] = []
    # the widths of the columns that the user configured by name are keyed by name; keep track of the original entry
    # so those can be matched too
    configured_as: dict[str, str] = {}
    seen: set[str] = set()
    for entry in ids:
        if not entry:
            continue
        if builtin := BUILTIN_COLUMNS.get(entry):
            if builtin.id in seen:
                continue
            seen.add(builtin.id)
            columns.append(builtin)
            continue
        jira_field = fields_by_id.get(entry) or fields_by_name.get(
            field_name_without_type(entry).lower()
        )
        column_id = jira_field.id if jira_field else entry
        if column_id in seen:
            continue
        seen.add(column_id)
        configured_as[column_id] = entry
        columns.append(
            ColumnSpec(
                id=column_id,
                label=jira_field.name if jira_field and jira_field.name else column_id,
                api_fields=(column_id,),
            )
        )
    if not columns:
        columns = [BUILTIN_COLUMNS[column_id] for column_id in DEFAULT_COLUMNS]
    if widths:
        resized: list[ColumnSpec] = []
        for column in columns:
            width = widths.get(column.id)
            if width is None:
                width = widths.get(configured_as.get(column.id, column.id))
            resized.append(replace(column, width=width) if width is not None else column)
        columns = resized
    return columns


def config_snippet_for(columns: Sequence[ColumnSpec]) -> str:
    """Builds the `search_results_columns` snippet that reproduces a set of columns.

    The ids of the custom fields are not displayed anywhere else in the app, so a user who picks the columns
    interactively has no way of working out what to write in the configuration file. This renders the snippet that they
    can paste into it.

    Args:
        columns: the columns to display, in the order in which they should be displayed.

    Returns:
        A block of YAML. The id of a column is annotated with the name of the field when the two differ.
    """

    lines: list[str] = ['search_results_columns:']
    for column in columns:
        comment = f'  # {column.label}' if column.label != column.id else ''
        lines.append(f'  - {column.id}{comment}')
    return '\n'.join(lines)


def api_fields_for(columns: Sequence[ColumnSpec]) -> list[str]:
    """Builds the list of fields to request from the API in order to render a set of columns.

    Args:
        columns: the columns to display.

    Returns:
        A list of field ids. This always includes the baseline fields required by the table itself.
    """

    fields: list[str] = list(BASELINE_API_FIELDS)
    for column in columns:
        for api_field in column.api_fields:
            if api_field not in fields:
                fields.append(api_field)
    return fields


def fixed_width_of(columns: Sequence[ColumnSpec]) -> int:
    """Calculates the width taken by the columns that do not absorb the remaining width of the table.

    Args:
        columns: the columns to display.

    Returns:
        The total nominal width of every column other than the summary column.
    """

    return sum(column.width for column in columns if column.id != SUMMARY_COLUMN_ID)


def sortable_field_for(column: ColumnSpec, jql_fields: Sequence[Any] | None = None) -> str | None:
    """Works out the name to use in an `ORDER BY` clause to sort by a column.

    Args:
        column: the column to sort by.
        jql_fields: the fields that can be referenced in a JQL expression, as returned by
        [get_jql_autocomplete_data](#jiratui.api_controller.controller.APIController.get_jql_autocomplete_data). Used to
        work out whether a custom field can be sorted, and how to reference it.

    Returns:
        The name of the field to sort by, or `None` if the column cannot be sorted.
    """

    if column.sortable_jql_field:
        return column.sortable_jql_field
    label = (column.label or '').strip().lower()
    for jql_field in jql_fields or []:
        if not jql_field.orderable:
            continue
        # the auto-complete data spells a custom field `cf[10109]` and a column spells it `customfield_10109`
        if custom_field_id(jql_field.cfid) == column.id:
            return jql_field.value
        if jql_field.value == column.id:
            return jql_field.value
        # the column may have been configured by name; the API quotes a name that needs quoting, and the name of the
        # column never carries those quotes
        if label and strip_quotes(jql_field.value).lower() == label:
            return jql_field.value
    return None
