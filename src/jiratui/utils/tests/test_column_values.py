from decimal import Decimal

import pytest

from jiratui.utils.column_values import render_field_value


@pytest.mark.parametrize(
    'value, expected',
    [
        pytest.param(None, '', id='none'),
        pytest.param('', '', id='empty-string'),
        pytest.param('plain text', 'plain text', id='string'),
        pytest.param(42, '42', id='int'),
        pytest.param(0, '0', id='zero'),
        pytest.param(1.5, '1.5', id='float'),
        pytest.param(Decimal('3.25'), '3.25', id='decimal'),
        # bool is a subclass of int; it must not be rendered as 1/0
        pytest.param(True, 'Yes', id='true'),
        pytest.param(False, 'No', id='false'),
    ],
)
def test_render_scalar_values(value, expected):
    assert render_field_value(value) == expected


@pytest.mark.parametrize(
    'value, expected',
    [
        pytest.param('2024-01-05T10:00:00.000+0000', '2024-01-05 10:00', id='timestamp'),
        pytest.param('2024-01-05', '2024-01-05', id='date-only'),
        pytest.param('2024-01-05T00:00:00.000+0000', '2024-01-05', id='midnight-drops-time'),
    ],
)
def test_render_dates(value, expected):
    assert render_field_value(value) == expected


@pytest.mark.parametrize(
    'value, expected',
    [
        pytest.param({'displayName': 'Naga Kiran K'}, 'Naga Kiran K', id='user'),
        pytest.param({'name': 'High'}, 'High', id='name'),
        pytest.param({'value': 'Yes'}, 'Yes', id='value'),
        pytest.param({'key': 'SB-1'}, 'SB-1', id='key'),
        pytest.param({'id': '10001'}, '10001', id='id'),
        # displayName wins over the other keys
        pytest.param({'id': '1', 'displayName': 'Bart'}, 'Bart', id='preferred-key'),
        pytest.param({'unknown': 'x'}, '', id='no-display-key'),
        pytest.param({}, '', id='empty-dict'),
        pytest.param(
            {'value': 'Parent', 'child': {'value': 'Child'}}, 'Parent - Child', id='cascading'
        ),
    ],
)
def test_render_objects(value, expected):
    assert render_field_value(value) == expected


@pytest.mark.parametrize(
    'value, expected',
    [
        pytest.param([], '', id='empty-list'),
        pytest.param(['a', 'b'], 'a, b', id='strings'),
        pytest.param(
            [{'displayName': 'A'}, {'displayName': 'B'}], 'A, B', id='users-the-dev-engineers-case'
        ),
        pytest.param([None, 'a', None], 'a', id='drops-empty-items'),
        pytest.param(['a', 'b', 'c', 'd', 'e'], 'a, b, c (+2)', id='truncates-past-max-items'),
    ],
)
def test_render_collections(value, expected):
    assert render_field_value(value) == expected


def test_render_flattens_multiline_values():
    # a multi-line value would break the height of the row that displays it
    assert render_field_value('line one\nline two\ttabbed') == 'line one line two tabbed'


def test_render_truncates_long_values():
    rendered = render_field_value('x' * 200, max_length=10)
    assert rendered == f'{"x" * 9}…'
    assert len(rendered) == 10


def test_render_adf_document():
    document = {
        'type': 'doc',
        'version': 1,
        'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': 'hello world'}]}],
    }
    assert render_field_value(document) == 'hello world'


def test_render_never_raises_on_unexpected_values():
    class Exploding:
        def __str__(self):
            raise RuntimeError('boom')

    # the value of a custom field is arbitrary; rendering it must not break the results table
    assert render_field_value(Exploding()) == ''
    assert render_field_value([Exploding()]) == ''
