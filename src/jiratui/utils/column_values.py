"""This module provides a renderer for arbitrary Jira field values.

The search results table can display any field of a work item, including custom fields. The value of a custom field is
whatever JSON the Jira instance returns for it, so the renderer in this module needs to cope with any shape: scalars,
dates, user objects, option objects, arrays of any of those, and rich text in Atlassian Document Format.
"""

from datetime import date, datetime
from decimal import Decimal
import logging
from typing import Any

from dateutil.parser import isoparse  # type:ignore[import-untyped]

from jiratui.utils.adf import convert_adf_to_markdown

logger = logging.getLogger(__name__)

DEFAULT_MAXIMUM_ITEMS = 3
"""The number of items of a multivalued field that are rendered before the value is summarized."""

DEFAULT_MAXIMUM_LENGTH = 120
"""The maximum length of a rendered value. Values longer than this are truncated."""

DISPLAY_KEYS = ('displayName', 'name', 'value', 'text', 'key', 'id')
"""The keys of an object-like field value that hold a human-readable value, in order of preference."""


def _render_datetime(value: datetime | date) -> str:
    if isinstance(value, datetime):
        if value.hour or value.minute or value.second:
            return value.strftime('%Y-%m-%d %H:%M')
        return value.strftime('%Y-%m-%d')
    return value.strftime('%Y-%m-%d')


def _render_string(value: str) -> str:
    # Jira returns dates and timestamps as strings; render them the same way as the fields the factory parses.
    try:
        return _render_datetime(isoparse(value))
    except (ValueError, OverflowError, TypeError):
        return value


def _render_dict(value: dict, max_items: int) -> str:
    if value.get('type') == 'doc' and 'content' in value:
        # the field holds rich text in Atlassian Document Format (REST API v3)
        try:
            return convert_adf_to_markdown(value)
        except Exception:
            logger.debug('Unable to render an ADF field value', exc_info=True)
            return ''
    for key in DISPLAY_KEYS:
        if (found := value.get(key)) not in (None, ''):
            rendered = _render(found, max_items)
            if child := value.get('child'):
                # a cascading select holds the second level of the selection in `child`
                if child_rendered := _render(child, max_items):
                    rendered = f'{rendered} - {child_rendered}'
            return rendered
    return ''


def _render_list(value: list | tuple, max_items: int) -> str:
    rendered = [item for raw in value if (item := _render_safely(raw, max_items))]
    if not rendered:
        return ''
    if len(rendered) > max_items:
        return f'{", ".join(rendered[:max_items])} (+{len(rendered) - max_items})'
    return ', '.join(rendered)


def _render_safely(value: Any, max_items: int) -> str:
    """Renders a value, degrading to an empty string when the value cannot be rendered.

    An item of a multivalued field is rendered on its own so that one unexpected item does not discard the items
    around it.
    """

    try:
        return _render(value, max_items)
    except Exception:
        logger.debug('Unable to render a field value', exc_info=True)
        return ''


def _render(value: Any, max_items: int) -> str:
    if value is None:
        return ''
    # `bool` MUST be checked before `int`: bool is a subclass of int, so the int branch would render `True` as `1`
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    if isinstance(value, str):
        return _render_string(value)
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return _render_datetime(value)
    if isinstance(value, (list, tuple, set)):
        return _render_list(list(value), max_items)
    if isinstance(value, dict):
        return _render_dict(value, max_items)
    return str(value)


def render_field_value(
    value: Any,
    max_items: int = DEFAULT_MAXIMUM_ITEMS,
    max_length: int = DEFAULT_MAXIMUM_LENGTH,
) -> str:
    """Renders the value of any Jira field as a single line of text.

    ```{important}
    This function never raises. The value of a custom field is arbitrary JSON defined by the Jira instance, and it is
    rendered while building a row of the search results table; an unexpected shape must degrade to a best-effort string
    rather than break the table.
    ```

    Args:
        value: the value of the field, as returned by the API.
        max_items: the number of items of a multivalued field to render before summarizing the rest.
        max_length: the maximum length of the rendered value.

    Returns:
        A single-line string. Empty if the field has no value.
    """

    rendered = _render_safely(value, max_items)
    # a value that spans several lines would break the layout of the row that displays it
    rendered = ' '.join(rendered.split())
    if len(rendered) > max_length:
        rendered = f'{rendered[: max_length - 1].rstrip()}…'
    return rendered
