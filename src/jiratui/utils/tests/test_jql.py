import pytest

from jiratui.utils.jql import (
    JQLContext,
    JQLTokenKind,
    context_at,
    operator_completion,
    quote_if_needed,
    resolve_values,
    split_order_by,
    strip_quotes,
    tokenize,
)


def context_for(text_with_cursor: str):
    """Builds the context for an expression whose cursor is marked with a `|`."""

    cursor = text_with_cursor.index('|')
    return context_at(text_with_cursor.replace('|', '', 1), cursor)


def test_tokenize_empty_expression():
    assert tokenize('') == []


def test_tokenize_a_simple_clause():
    tokens = tokenize('project = SB')
    assert [(token.kind, token.text) for token in tokens] == [
        (JQLTokenKind.FIELD, 'project'),
        (JQLTokenKind.OPERATOR, '='),
        (JQLTokenKind.VALUE, 'SB'),
    ]


def test_tokenize_a_quoted_value():
    tokens = tokenize('status = "In Progress"')
    assert tokens[-1].kind is JQLTokenKind.VALUE
    assert tokens[-1].value == 'In Progress'
    assert tokens[-1].quoted is True


def test_tokenize_an_unterminated_quoted_value():
    tokens = tokenize('status = "In Prog')
    assert tokens[-1].quoted is True
    assert tokens[-1].value == 'In Prog'


def test_tokenize_a_custom_field():
    tokens = tokenize('cf[10343] = x')
    assert (tokens[0].kind, tokens[0].text) == (JQLTokenKind.FIELD, 'cf[10343]')


def test_tokenize_a_quoted_field():
    tokens = tokenize('"Dev Engineers" = x')
    assert tokens[0].kind is JQLTokenKind.FIELD
    assert tokens[0].value == 'Dev Engineers'


@pytest.mark.parametrize(
    'expression, operator',
    [
        pytest.param('a != b', '!=', id='not-equal'),
        pytest.param('a >= b', '>=', id='greater-or-equal'),
        pytest.param('a <= b', '<=', id='less-or-equal'),
        pytest.param('a !~ b', '!~', id='not-contains'),
        pytest.param('a ~ b', '~', id='contains'),
        pytest.param('a in (b)', 'in', id='in'),
        pytest.param('a not in (b)', 'not in', id='not-in'),
        pytest.param('a is empty', 'is', id='is'),
        pytest.param('a is not empty', 'is not', id='is-not'),
        pytest.param('a was b', 'was', id='was'),
        pytest.param('a was not b', 'was not', id='was-not'),
        pytest.param('a was in (b)', 'was in', id='was-in'),
        pytest.param('a changed b', 'changed', id='changed'),
    ],
)
def test_tokenize_operators(expression, operator):
    # the operators must be matched longest-first; e.g. '>=' must not be read as '>'
    tokens = tokenize(expression)
    assert [token.text.lower() for token in tokens if token.kind is JQLTokenKind.OPERATOR] == [
        operator
    ]


def test_tokenize_keywords():
    tokens = tokenize('a = 1 AND b = 2 ORDER BY created DESC')
    keywords = [token.text.lower() for token in tokens if token.kind is JQLTokenKind.KEYWORD]
    assert keywords == ['and', 'order by', 'desc']


def test_tokenize_a_function():
    tokens = tokenize('assignee = currentUser()')
    assert tokens[2].text == 'currentUser'
    assert [token.text for token in tokens[3:]] == ['(', ')']


def test_a_field_named_like_an_operator_is_a_field():
    # 'in' at the start of a clause is the name of a field, not an operator
    tokens = tokenize('and in = 1')
    assert (tokens[1].kind, tokens[1].text) == (JQLTokenKind.FIELD, 'in')


@pytest.mark.parametrize(
    'expression',
    [
        pytest.param('|', id='empty'),
        pytest.param('pro|', id='partial-field'),
        pytest.param('project = SB and |', id='after-and'),
        pytest.param('project = SB and assi|', id='partial-field-after-and'),
        pytest.param('project = SB order by |', id='after-order-by'),
        pytest.param('not |', id='after-not'),
    ],
)
def test_field_context(expression):
    assert context_for(expression).context is JQLContext.FIELD


def test_field_context_prefix_and_span():
    context = context_for('pro|ject = SB')
    assert context.context is JQLContext.FIELD
    assert context.prefix == 'pro'
    # the whole token is replaced, not only the part before the cursor
    assert (context.replace_start, context.replace_end) == (0, 7)


def test_field_context_at_the_start():
    context = context_for('|project = SB')
    # the cursor is before the first token, so nothing has been typed at this position yet
    assert context.context is JQLContext.FIELD
    assert context.prefix == ''


def test_operator_context():
    context = context_for('project |')
    assert context.context is JQLContext.OPERATOR
    assert context.field == 'project'
    assert context.prefix == ''


def test_operator_context_while_typing():
    context = context_for('project !|= SB')
    assert context.context is JQLContext.OPERATOR
    assert context.field == 'project'


def test_operator_context_for_a_quoted_field():
    context = context_for('"Dev Engineers" |')
    assert context.context is JQLContext.OPERATOR
    assert context.field == 'Dev Engineers'


def test_operator_context_for_a_custom_field():
    context = context_for('cf[10343] |')
    assert context.context is JQLContext.OPERATOR
    assert context.field == 'cf[10343]'


def test_value_context():
    context = context_for('project = |')
    assert context.context is JQLContext.VALUE
    assert context.field == 'project'
    assert context.operator == '='


def test_value_context_while_typing():
    context = context_for('project = SB|')
    assert context.context is JQLContext.VALUE
    assert context.field == 'project'
    assert context.prefix == 'SB'


def test_value_context_inside_a_quoted_value():
    context = context_for('status = "In Prog|')
    assert context.context is JQLContext.VALUE
    assert context.field == 'status'
    assert context.prefix == 'In Prog'
    # a suggestion applied here must not be quoted again
    assert context.quoted is True


def test_value_context_in_a_list():
    context = context_for('status in (Open, |)')
    assert context.context is JQLContext.VALUE
    assert context.field == 'status'
    assert context.operator == 'in'


def test_value_context_of_the_first_item_of_a_list():
    context = context_for('status in (|)')
    assert context.context is JQLContext.VALUE
    assert context.field == 'status'


def test_value_context_for_a_custom_field():
    context = context_for('cf[10343] in (naga|)')
    assert context.context is JQLContext.VALUE
    assert context.field == 'cf[10343]'
    assert context.prefix == 'naga'


def test_value_context_for_the_user_scenario():
    # this is the expression from the Jira web UI: "Dev Engineers[User Picker (multiple users)]" in (naga
    context = context_for('"Dev Engineers" in (naga|')
    assert context.context is JQLContext.VALUE
    assert context.field == 'Dev Engineers'
    assert context.operator == 'in'
    assert context.prefix == 'naga'


def test_keyword_context_after_a_complete_clause():
    context = context_for('project = SB |')
    assert context.context is JQLContext.KEYWORD
    assert 'and' in context.keywords
    assert 'order by' in context.keywords


def test_keyword_context_after_a_closing_parenthesis():
    context = context_for('status in (Open) |')
    assert context.context is JQLContext.KEYWORD


def test_keyword_context_for_an_order_by_direction():
    context = context_for('project = SB order by created |')
    assert context.context is JQLContext.KEYWORD
    assert 'asc' in context.keywords
    assert 'desc' in context.keywords


def test_keyword_context_while_typing_an_order_by_direction():
    context = context_for('order by created de|')
    assert context.context is JQLContext.KEYWORD
    assert context.prefix == 'de'


def test_a_field_after_order_by_is_a_field():
    context = context_for('order by crea|')
    assert context.context is JQLContext.FIELD
    assert context.prefix == 'crea'


def test_nothing_is_suggested_after_a_direction():
    assert context_for('order by created desc |').context is JQLContext.NONE


def test_cursor_at_the_end_of_the_expression():
    context = context_for('project = SB|')
    assert context.replace_end == len('project = SB')


def test_context_of_a_multiline_expression():
    # the JQL editor is multi-line; the offsets are over the flat text
    text = 'project = SB\nand assi'
    context = context_at(text, len(text))
    assert context.context is JQLContext.FIELD
    assert context.prefix == 'assi'
    assert (context.replace_start, context.replace_end) == (17, 21)


def test_cursor_beyond_the_end_of_the_expression_is_clamped():
    context = context_at('project', 999)
    assert context.context is JQLContext.FIELD
    assert context.prefix == 'project'


def test_negative_cursor_is_clamped():
    context = context_at('project', -5)
    assert context.context is JQLContext.FIELD
    assert context.prefix == ''


@pytest.mark.parametrize(
    'value, expected',
    [
        pytest.param('SB', 'SB', id='no-quotes-needed'),
        pytest.param('In Progress', '"In Progress"', id='contains-a-space'),
        pytest.param('a,b', '"a,b"', id='contains-a-comma'),
        pytest.param('currentUser()', 'currentUser()', id='a-function-is-not-quoted'),
        pytest.param('say "hi"', '"say \\"hi\\""', id='escapes-quotes'),
        pytest.param("Won't", '"Won\'t"', id='contains-an-apostrophe'),
        pytest.param("Won't Fix", '"Won\'t Fix"', id='an-apostrophe-and-a-space'),
        pytest.param('', '', id='empty'),
    ],
)
def test_quote_if_needed(value, expected):
    assert quote_if_needed(value) == expected


@pytest.mark.parametrize(
    'text, expected',
    [
        pytest.param('"Dev Complete"', 'Dev Complete', id='double-quotes'),
        pytest.param("'Dev Complete'", 'Dev Complete', id='single-quotes'),
        pytest.param('SB', 'SB', id='no-quotes'),
        pytest.param('"In Prog', 'In Prog', id='the-user-is-still-typing-it'),
        pytest.param('"say \\"hi\\""', 'say "hi"', id='unescapes-the-quotes-inside'),
        pytest.param('"', '', id='only-the-opening-quote'),
        pytest.param('', '', id='empty'),
    ],
)
def test_strip_quotes(text, expected):
    assert strip_quotes(text) == expected


def test_quoting_a_value_that_arrived_quoted_does_not_quote_it_twice():
    # the API returns '"Dev Complete"'; written as-is into an expression it would search for a status whose name
    # includes the quotes, which matches nothing
    assert quote_if_needed(strip_quotes('"Dev Complete"')) == '"Dev Complete"'


@pytest.mark.parametrize(
    'operator, text_after, expected',
    [
        pytest.param('in', '', ('in ()', 4), id='in-opens-a-list'),
        pytest.param('not in', '', ('not in ()', 8), id='not-in-opens-a-list'),
        pytest.param('was in', '', ('was in ()', 8), id='was-in-opens-a-list'),
        pytest.param('was not in', '', ('was not in ()', 12), id='was-not-in-opens-a-list'),
        pytest.param('IN', '', ('IN ()', 4), id='the-case-does-not-matter'),
        pytest.param('=', '', ('= ', 2), id='an-equality-does-not-open-a-list'),
        pytest.param('!=', ' "Dev Complete"', ('!= ', 3), id='an-inequality-does-not-open-a-list'),
        pytest.param('in', ' (MNHA)', ('in ', 3), id='the-list-is-already-there'),
    ],
)
def test_operator_completion(operator, text_after, expected):
    assert operator_completion(operator, text_after) == expected


@pytest.mark.parametrize(
    'expression, expected',
    [
        pytest.param('project = SB', ('project = SB', None), id='no-order-by'),
        pytest.param(
            'project = SB order by key desc',
            ('project = SB', 'order by key desc'),
            id='an-order-by-clause',
        ),
        pytest.param(
            'project = SB ORDER BY key',
            ('project = SB', 'ORDER BY key'),
            id='the-case-does-not-matter',
        ),
        pytest.param(
            'summary ~ "order by"',
            ('summary ~ "order by"', None),
            id='the-words-are-part-of-a-value',
        ),
        pytest.param('order by created', ('', 'order by created'), id='only-an-order-by-clause'),
    ],
)
def test_split_order_by(expression, expected):
    assert split_order_by(expression) == expected


ALIASES = {
    ('dev engineers', 'Naga Kiran K - naga@example.com'): '5c017f7dc22785142f67f57b',
    ('dev engineers', 'Ritesh Agrawal - ritesh@example.com'): '6a117f7dc22785142f67f99c',
    ('assignee', 'Naga Kiran K - naga@example.com'): '5c017f7dc22785142f67f57b',
}


def test_resolve_values_replaces_a_known_alias():
    assert (
        resolve_values('"Dev Engineers" in ("Naga Kiran K - naga@example.com")', ALIASES)
        == '"Dev Engineers" in (5c017f7dc22785142f67f57b)'
    )


def test_resolve_values_replaces_every_value_of_a_list():
    assert (
        resolve_values(
            '"Dev Engineers" in ("Naga Kiran K - naga@example.com", '
            '"Ritesh Agrawal - ritesh@example.com")',
            ALIASES,
        )
        == '"Dev Engineers" in (5c017f7dc22785142f67f57b, 6a117f7dc22785142f67f99c)'
    )


def test_resolve_values_leaves_an_unknown_value_untouched():
    # an expression that does not use a suggestion has to survive unchanged
    expression = 'project = SB AND status = "In Progress"'
    assert resolve_values(expression, ALIASES) == expression


def test_resolve_values_does_not_apply_an_alias_of_another_field():
    # 'Ritesh Agrawal' is an alias of "Dev Engineers", not of 'reporter'
    expression = 'reporter = "Ritesh Agrawal - ritesh@example.com"'
    assert resolve_values(expression, ALIASES) == expression


def test_resolve_values_resolves_each_clause_against_its_own_field():
    assert (
        resolve_values(
            'assignee = "Naga Kiran K - naga@example.com" AND status = Open '
            'AND "Dev Engineers" in ("Ritesh Agrawal - ritesh@example.com")',
            ALIASES,
        )
        == 'assignee = 5c017f7dc22785142f67f57b AND status = Open '
        'AND "Dev Engineers" in (6a117f7dc22785142f67f99c)'
    )


def test_resolve_values_does_not_touch_a_field_name_that_matches_an_alias():
    # the ORDER BY clause names fields, not values
    expression = 'project = SB ORDER BY assignee DESC'
    assert resolve_values(expression, ALIASES) == expression


def test_resolve_values_quotes_a_resolved_value_that_needs_it():
    aliases = {('status', 'Doing'): 'In Progress'}
    assert resolve_values('status = Doing', aliases) == 'status = "In Progress"'


def test_resolve_values_does_not_quote_a_resolved_value_twice():
    # an alias recorded before the values were unquoted at the source would otherwise turn the clause into
    # `status != "\"Dev Complete\""`, which matches no status at all
    aliases = {('status', 'Dev Complete'): '"Dev Complete"'}
    assert resolve_values("status != 'Dev Complete'", aliases) == 'status != "Dev Complete"'


@pytest.mark.parametrize(
    'expression, aliases',
    [
        pytest.param('', ALIASES, id='empty-expression'),
        pytest.param('project = SB', {}, id='no-aliases'),
    ],
)
def test_resolve_values_with_nothing_to_do(expression, aliases):
    assert resolve_values(expression, aliases) == expression
