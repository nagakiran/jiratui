from unittest.mock import Mock

import pytest

from jiratui.config import ApplicationConfiguration
from jiratui.models import JiraField, JQLFieldRef
from jiratui.utils.columns import (
    BASELINE_API_FIELDS,
    DEFAULT_COLUMNS,
    api_fields_for,
    column_ids_from_config,
    fixed_width_of,
    resolve_columns,
    sortable_field_for,
)


def build_jira_field(field_id: str, name: str, custom: bool = True) -> JiraField:
    return JiraField(id=field_id, key=field_id, name=name, custom=custom, schema={})


def test_resolve_default_columns_matches_the_original_table():
    # the default set must keep rendering exactly the columns the table displayed before they were configurable
    columns = resolve_columns(list(DEFAULT_COLUMNS))
    assert [column.label for column in columns] == [
        '#',
        'Key',
        'Parent',
        'Status',
        'Type',
        'Summary',
    ]


def test_fixed_width_of_default_columns_matches_the_original_width_budget():
    # the width left for the summary column used to be `container width - 42`
    assert fixed_width_of(resolve_columns(list(DEFAULT_COLUMNS))) == 42


def test_fixed_width_ignores_the_summary_column():
    columns = resolve_columns(['key', 'summary'])
    assert fixed_width_of(columns) == 12


def test_resolve_columns_keeps_the_requested_order():
    columns = resolve_columns(['summary', 'key'])
    assert [column.id for column in columns] == ['summary', 'key']


def test_resolve_columns_ignores_duplicates():
    columns = resolve_columns(['key', 'key', 'summary'])
    assert [column.id for column in columns] == ['key', 'summary']


def test_resolve_columns_falls_back_to_the_default_columns():
    assert [column.id for column in resolve_columns([])] == list(DEFAULT_COLUMNS)


def test_resolve_columns_labels_a_custom_field_with_the_name_of_the_field():
    columns = resolve_columns(
        ['customfield_10343'], jira_fields=[build_jira_field('customfield_10343', 'Dev Engineers')]
    )
    assert columns[0].label == 'Dev Engineers'
    assert columns[0].api_fields == ('customfield_10343',)
    # the value of a field that is not modelled by JiraIssue is rendered from the raw fields of the work item
    assert columns[0].getter is None


def test_resolve_columns_labels_an_unknown_field_with_its_id():
    assert resolve_columns(['customfield_99999'])[0].label == 'customfield_99999'


def test_resolve_columns_applies_width_overrides():
    columns = resolve_columns(['key', 'assignee'], widths={'assignee': 30})
    assert [(column.id, column.width) for column in columns] == [('key', 12), ('assignee', 30)]


def test_api_fields_for_default_columns_matches_the_original_request():
    # this is the field list the controller used to request when the UI passed nothing
    assert api_fields_for(resolve_columns(list(DEFAULT_COLUMNS))) == list(BASELINE_API_FIELDS)


def test_api_fields_for_includes_the_baseline_fields():
    # the table dereferences the status and the type of every work item, and builds the row key from the id and key
    fields = api_fields_for(resolve_columns(['summary']))
    for baseline_field in BASELINE_API_FIELDS:
        assert baseline_field in fields


def test_api_fields_for_requests_the_fields_of_the_extra_columns():
    fields = api_fields_for(resolve_columns(['assignee', 'customfield_10343']))
    assert 'assignee' in fields
    assert 'customfield_10343' in fields


def test_api_fields_for_does_not_repeat_fields():
    fields = api_fields_for(resolve_columns(['key', 'status', 'summary']))
    assert len(fields) == len(set(fields))


@pytest.mark.parametrize(
    'ids, expected',
    [
        pytest.param(['key', 'summary'], ['key', 'summary'], id='configured'),
        pytest.param([], list(DEFAULT_COLUMNS), id='empty'),
        pytest.param(None, list(DEFAULT_COLUMNS), id='not-set'),
        pytest.param('key', list(DEFAULT_COLUMNS), id='not-a-list'),
        pytest.param([None, 1, ''], list(DEFAULT_COLUMNS), id='no-usable-values'),
        pytest.param(['key', 2], ['key'], id='drops-values-that-are-not-ids'),
    ],
)
def test_column_ids_from_config(ids, expected):
    config = Mock(spec=ApplicationConfiguration)
    config.configure_mock(search_results_columns=ids)
    assert column_ids_from_config(config) == expected


def test_column_ids_from_config_without_the_setting():
    # a configuration double that does not define the setting must not break the screen
    assert column_ids_from_config(Mock(spec=ApplicationConfiguration)) == list(DEFAULT_COLUMNS)


def test_sortable_field_for_builtin_column():
    assert sortable_field_for(resolve_columns(['created'])[0]) == 'created'


def test_index_column_cannot_be_sorted():
    assert sortable_field_for(resolve_columns(['index'])[0]) is None


def test_sortable_field_for_an_orderable_custom_field():
    column = resolve_columns(['customfield_10343'])[0]
    jql_fields = [
        JQLFieldRef(
            value='cf[10343]',
            display_name='Dev Engineers',
            orderable=True,
            cfid='customfield_10343',
        )
    ]
    assert sortable_field_for(column, jql_fields) == 'cf[10343]'


def test_a_custom_field_that_is_not_orderable_cannot_be_sorted():
    column = resolve_columns(['customfield_10343'])[0]
    jql_fields = [JQLFieldRef(value='cf[10343]', orderable=False, cfid='customfield_10343')]
    assert sortable_field_for(column, jql_fields) is None


def test_a_custom_field_that_is_unknown_to_jql_cannot_be_sorted():
    assert sortable_field_for(resolve_columns(['customfield_10343'])[0], []) is None
