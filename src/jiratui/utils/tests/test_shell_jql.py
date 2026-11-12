import pytest

from jiratui.utils.shell_jql import find_jql_region, quote, split_words


def region_for(line_with_cursor: str, **kwargs):
    """Finds the region for a command line whose cursor is marked with a `¦`."""

    cursor = line_with_cursor.index('¦')
    line = line_with_cursor.replace('¦', '', 1)
    return line, find_jql_region(line, cursor, **kwargs)


def test_split_words_removes_the_quoting():
    words = split_words("""a 'b c' "d \\"e\\"" f\\ g""")
    assert [word.value for word in words] == ['a', 'b c', 'd "e"', 'f g']
    assert [word.quote for word in words] == ['', "'", '"', '']


def test_split_words_keeps_an_unterminated_quote_open_to_the_end():
    words = split_words("cmd --jql 'status = ")
    assert words[-1].value == 'status = '
    assert words[-1].end == len("cmd --jql 'status = ")


def test_split_words_marks_command_separators():
    words = split_words('a | b; c')
    assert [word.separator for word in words] == [False, True, False, True, False]


@pytest.mark.parametrize(
    'line_with_cursor, expression, cursor',
    [
        pytest.param(
            "jiratui issues search --jql 'project = SB and sta¦'",
            'project = SB and sta',
            20,
            id='single',
        ),
        pytest.param(
            'jiratui issues search -q "status = \\"In P¦"', 'status = "In P', 14, id='double'
        ),
        pytest.param("jiratui-jql search --jql 'a = b¦' -l 5", 'a = b', 5, id='more-options-after'),
        pytest.param("jiratui-jql search --jql 'a ¦= b'", 'a = b', 2, id='cursor-in-the-middle'),
        pytest.param("jiratui-jql search --jql='a = ¦'", 'a = ', 4, id='equals-form'),
        pytest.param("jqls 'labels = x and ¦'", 'labels = x and ', 15, id='jqls-command'),
        pytest.param("echo hi | jqls 'a¦'", 'a', 1, id='after-a-pipe'),
        pytest.param("jqls 'Won'\\''t ¦'", "Won't ", 6, id='escaped-single-quote'),
    ],
)
def test_find_jql_region(line_with_cursor, expression, cursor):
    _, region = region_for(line_with_cursor)
    assert region is not None
    assert region.expression == expression
    assert region.cursor == cursor


@pytest.mark.parametrize(
    'line_with_cursor',
    [
        pytest.param('jiratui issues search -p SB¦', id='other-option'),
        pytest.param("git commit -m 'msg¦'", id='other-command'),
        pytest.param('jqls -l ¦', id='value-of-an-option'),
        pytest.param("jiratui-jql search --jq¦l 'a'", id='on-the-flag-itself'),
        pytest.param("jqls 'a' | grep ¦", id='another-command-after-a-pipe'),
    ],
)
def test_find_jql_region_outside_an_expression(line_with_cursor):
    _, region = region_for(line_with_cursor)
    assert region is None


def test_find_jql_region_where_the_expression_is_yet_to_be_typed():
    line, region = region_for('jiratui-jql search --jql ¦')
    assert region is not None and region.expression == '' and region.start == len(line)
    new_line, cursor = region.replace(line, 'project ', 8)
    assert new_line == "jiratui-jql search --jql 'project '"
    assert cursor == len(new_line) - 1


@pytest.mark.parametrize(
    'line_with_cursor, new_expression, new_cursor, expected_line, expected_cursor',
    [
        pytest.param(
            "jqls 'status ¦' -l 5",
            'status in ()',
            11,
            "jqls 'status in ()' -l 5",
            len("jqls 'status in ("),
            id='single-quotes',
        ),
        pytest.param(
            'jqls "status = ¦"',
            'status = "In Progress"',
            22,
            'jqls "status = \\"In Progress\\""',
            len('jqls "status = \\"In Progress\\"'),
            id='double-quotes-are-escaped',
        ),
        pytest.param(
            "jqls --jql='res¦'",
            'resolution = "Won\'t Do"',
            23,
            "jqls --jql='resolution = \"Won'\\''t Do\"'",
            len("jqls --jql='resolution = \"Won'\\''t Do\""),
            id='equals-form-with-a-single-quote',
        ),
        pytest.param(
            'jqls sta¦',
            'status ',
            7,
            "jqls 'status '",
            len("jqls 'status "),
            id='unquoted-becomes-quoted',
        ),
    ],
)
def test_region_replace(
    line_with_cursor, new_expression, new_cursor, expected_line, expected_cursor
):
    line, region = region_for(line_with_cursor)
    new_line, cursor = region.replace(line, new_expression, new_cursor)
    assert new_line == expected_line
    assert cursor == expected_cursor
    # what the shell sees is the new expression
    words = split_words(new_line)
    assert new_expression in [word.value for word in words] or any(
        word.value.endswith(new_expression) for word in words
    )


def test_quote_round_trips_through_the_shell_splitter():
    text = """a 'b' "c" $d `e` \\f"""
    for quote_character in ("'", '"'):
        assert split_words(quote(text, quote_character))[0].value == text
