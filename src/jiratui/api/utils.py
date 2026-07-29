from datetime import date

from jiratui.models import SortSpec, WorkItemsSearchOrderBy
from jiratui.utils.jql import split_order_by


def parse_required_fields_from_meta(metadata: dict) -> list[str]:
    """Extracts required field keys from issue create metadata.

    Args:
        metadata: Response from get_issue_create_meta()

    Returns:
        List of required field keys (e.g., ['summary', 'components', 'customfield_10712'])
    """

    required_fields = []
    for field in metadata.get('fields', []):
        if field.get('required', False):
            required_fields.append(field['key'])
    return required_fields


def build_issue_search_jql(
    project_key: str | None = None,
    created_from: date | None = None,
    created_until: date | None = None,
    updated_from: date | None = None,
    updated_until: date | None = None,
    status: int | None = None,
    assignee: str | None = None,
    issue_type: int | None = None,
    jql_query: str | None = None,
    search_in_active_sprint: bool = False,
    order_by: WorkItemsSearchOrderBy | SortSpec | None = None,
) -> str:
    """Builds a JQL query expression to search issues based on different criteria.

    Args:
        project_key: the case-sensitive key of a project.
        created_from: a date to search for issues.
        created_until: a date to search for issues.
        updated_from: a date to search for issues.
        updated_until: a date to search for issues.
        status: find work items whose status matches this status name/ID.
        assignee: find work items assigned to the given user. The user is specified by the account ID, email address or
        name of a user.
        issue_type: the type of issue.
        jql_query: a string with a JQL query expression.
        search_in_active_sprint: if `True` only work items that belong to the currently active sprint will be
        retrieved.
        order_by: used to specify the fields by whose values the search results will be sorted. This requirement needs
        to be placed at the end of the JQL query, otherwise the JQL will be invalid.

    Returns:
        A string with the JQL query.
    """
    fields: list[str] = []
    if project_key:
        fields.append(f'project = "{project_key}"')
    if created_from:
        value = date.strftime(created_from, '%Y-%m-%d')
        fields.append(f'created >= "{value}"')
    if created_until:
        value = date.strftime(created_until, '%Y-%m-%d')
        fields.append(f'created <= "{value}"')
    if updated_from:
        value = date.strftime(updated_from, '%Y-%m-%d')
        fields.append(f'updated >= "{value}"')
    if updated_until:
        value = date.strftime(updated_until, '%Y-%m-%d')
        fields.append(f'updated <= "{value}"')
    if status:
        fields.append(f'status = "{status}"')
    if assignee:
        fields.append(f'assignee = "{assignee}"')
    if issue_type:
        fields.append(f'type = {issue_type}')
    if search_in_active_sprint:
        fields.append('sprint in openSprints()')

    jql: str = ''
    if fields:
        jql = ' and '.join(fields)

    # the `ORDER BY` clause has to be the last thing in the expression, so it is taken out of the caller's expression
    # and put back once every criterion has been joined
    order_by_clause: str | None = None
    if jql_query:
        filters, order_by_clause = split_order_by(jql_query)
        if filters:
            # the caller's expression is grouped: without the parentheses an `or` in it would bind more loosely than
            # the `and` that joins it to the criteria above, and the search would return items that match neither
            jql = f'{jql} and ({filters})' if jql else filters

    if order_by_clause is None and order_by:
        order_by_clause = f'order by {order_by.value}'
    if order_by_clause:
        jql = f'{jql} {order_by_clause}' if jql else order_by_clause
    return jql
