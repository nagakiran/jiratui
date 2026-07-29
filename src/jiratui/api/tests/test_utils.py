from datetime import datetime

from jiratui.api.utils import build_issue_search_jql, parse_required_fields_from_meta
from jiratui.models import SortSpec, WorkItemsSearchOrderBy


def test_build_issue_search_jql():
    # WHEN
    result = build_issue_search_jql()
    # THEN
    assert result == ''


def test_build_issue_search_jql_with_parameters():
    # WHEN
    result = build_issue_search_jql(
        project_key='P1',
        created_from=datetime(2025, 12, 1).date(),
        created_until=datetime(2025, 12, 2).date(),
        updated_from=datetime(2025, 12, 3).date(),
        updated_until=datetime(2025, 12, 4).date(),
        status=1,
        assignee='1',
        issue_type=2,
    )
    # THEN
    assert result == (
        'project = "P1" and created >= "2025-12-01" and created <= "2025-12-02" and updated >= "2025-12-03" and updated <= "2025-12-04" and status = "1" and assignee = "1" and type = 2'
    )


def test_build_issue_search_jql_with_parameters_and_jql_query():
    # WHEN
    result = build_issue_search_jql(
        project_key='P1',
        created_from=datetime(2025, 12, 1).date(),
        created_until=datetime(2025, 12, 2).date(),
        updated_from=datetime(2025, 12, 3).date(),
        updated_until=datetime(2025, 12, 4).date(),
        status=1,
        assignee='1',
        issue_type=2,
        jql_query='q=5',
    )
    # THEN
    assert result == (
        'project = "P1" and created >= "2025-12-01" and created <= "2025-12-02" and updated >= "2025-12-03" and updated <= "2025-12-04" and status = "1" and assignee = "1" and type = 2 and (q=5)'
    )


def test_build_issue_search_jql_without_parameters_and_jql_query():
    # WHEN
    result = build_issue_search_jql(jql_query='q=5')
    # THEN
    assert result == ('q=5')


def test_build_issue_search_jql_without_parameters_and_jql_query_with_order():
    # WHEN
    result = build_issue_search_jql(jql_query='q=5', order_by=WorkItemsSearchOrderBy.KEY_ASC)
    # THEN
    assert result == ('q=5 order by key asc')


def test_build_issue_search_jql_with_parameters_and_jql_query_with_order():
    # WHEN
    result = build_issue_search_jql(
        project_key='P1',
        created_from=datetime(2025, 12, 1).date(),
        created_until=datetime(2025, 12, 2).date(),
        updated_from=datetime(2025, 12, 3).date(),
        updated_until=datetime(2025, 12, 4).date(),
        status=1,
        assignee='1',
        issue_type=2,
        jql_query='q=5',
        order_by=WorkItemsSearchOrderBy.KEY_ASC,
    )
    # THEN
    assert result == (
        'project = "P1" and created >= "2025-12-01" and created <= "2025-12-02" and updated >= "2025-12-03" and updated <= "2025-12-04" and status = "1" and assignee = "1" and type = 2 and (q=5) order by key asc'
    )


def test_parse_required_fields_from_meta():
    # GIVEN
    metadata = {
        'fields': [
            {
                'required': True,
                'key': 'value 1',
            },
            {
                'required': False,
                'key': 'value 2',
            },
        ]
    }
    # WHEN
    result = parse_required_fields_from_meta(metadata)
    # THEN
    assert result == ['value 1']


def test_parse_required_fields_from_meta_with_no_fields():
    # GIVEN
    metadata = {'fields': []}
    # WHEN
    result = parse_required_fields_from_meta(metadata)
    # THEN
    assert result == []


def test_parse_required_fields_from_meta_with_all_fields_not_required():
    # GIVEN
    metadata = {
        'fields': [
            {
                'required': False,
                'key': 'value 1',
            },
            {
                'required': False,
                'key': 'value 2',
            },
        ]
    }
    # WHEN
    result = parse_required_fields_from_meta(metadata)
    # THEN
    assert result == []


def test_build_issue_search_jql_with_a_sort_spec():
    # GIVEN
    sort_spec = SortSpec(field='cf[10343]', descending=True)
    # WHEN
    jql = build_issue_search_jql(project_key='SB', order_by=sort_spec)
    # THEN
    assert jql == 'project = "SB" order by cf[10343] desc'


def test_build_issue_search_jql_with_an_ascending_sort_spec():
    assert build_issue_search_jql(order_by=SortSpec(field='created')) == 'order by created asc'


def test_build_issue_search_jql_with_a_sort_spec_and_a_user_defined_order_by():
    # the JQL of the user already sorts the results, so the sorting of the column cannot be applied
    # GIVEN
    jql_query = 'project = "SB" order by key desc'
    # WHEN
    jql = build_issue_search_jql(jql_query=jql_query, order_by=SortSpec(field='created'))
    # THEN
    assert jql == jql_query


def test_build_issue_search_jql_groups_a_user_expression_that_uses_or():
    # without the parentheses the `or` would bind more loosely than the `and` that joins the criteria, and the search
    # would return items of other projects
    # WHEN
    jql = build_issue_search_jql(
        project_key='SB', jql_query='assignee = currentUser() or labels in MNHA'
    )
    # THEN
    assert jql == 'project = "SB" and (assignee = currentUser() or labels in MNHA)'


def test_build_issue_search_jql_keeps_a_user_defined_order_by_at_the_end():
    # the `ORDER BY` clause cannot stay inside the parentheses; JQL only accepts it at the end of the expression
    # WHEN
    jql = build_issue_search_jql(project_key='SB', jql_query='labels in MNHA order by assignee asc')
    # THEN
    assert jql == 'project = "SB" and (labels in MNHA) order by assignee asc'


def test_build_issue_search_jql_sorts_when_a_value_contains_the_words_order_by():
    # the words are part of a value, not of a clause, so they do not sort the results
    # WHEN
    jql = build_issue_search_jql(
        jql_query='summary ~ "order by"', order_by=SortSpec(field='created')
    )
    # THEN
    assert jql == 'summary ~ "order by" order by created asc'


def test_sort_spec_from_order_by():
    assert SortSpec.from_order_by(WorkItemsSearchOrderBy.CREATED_DESC) == SortSpec(
        field='created', descending=True
    )
    assert SortSpec.from_order_by(WorkItemsSearchOrderBy.KEY_ASC) == SortSpec(
        field='key', descending=False
    )


def test_sort_spec_toggled():
    assert SortSpec(field='created').toggled() == SortSpec(field='created', descending=True)
    assert SortSpec(field='created', descending=True).toggled() == SortSpec(field='created')
