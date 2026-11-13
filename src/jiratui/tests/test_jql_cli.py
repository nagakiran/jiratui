from datetime import UTC, datetime
from unittest.mock import Mock, patch

from click.testing import CliRunner
import pytest

from jiratui import jql_cli
from jiratui.models import IssueStatus, IssueType, JiraIssue, JQLFieldRef
from jiratui.utils.jql_completion import JQLReferenceCache


@pytest.fixture
def cache(tmp_path, monkeypatch) -> JQLReferenceCache:
    cache = JQLReferenceCache(
        fetched_at=datetime.now(UTC),
        fields=[JQLFieldRef(value='status', operators=['=', 'in']), JQLFieldRef(value='project')],
        path=tmp_path / 'cache.json',
    )
    cache.add_alias('assignee', 'Jane Doe', '5c01')
    cache.save()
    # every load and save goes to the file of the test
    monkeypatch.setattr('jiratui.utils.jql_completion.get_cache_file', lambda: cache.path)
    return cache


@pytest.fixture
def handler(monkeypatch) -> Mock:
    handler = Mock()
    monkeypatch.setattr(jql_cli, '_HANDLER', handler)
    monkeypatch.setattr(jql_cli, '_issue_url', lambda key: f'https://jira/browse/{key}')
    return handler


def issue(key: str, summary: str) -> JiraIssue:
    return JiraIssue(
        id='1',
        key=key,
        summary=summary,
        status=IssueStatus(id='1', name='Open'),
        issue_type=IssueType(id='1', name='Bug'),
    )


def test_complete_fields_without_the_api(cache):
    result = CliRunner().invoke(jql_cli.cli, ['complete', '--', 'sta'])
    assert result.exit_code == 0
    assert result.output.splitlines() == ['status']


def test_complete_json_has_the_span_to_replace(cache):
    result = CliRunner().invoke(
        jql_cli.cli, ['complete', '-f', 'json', '--', 'project = SB and sta']
    )
    assert '"replace_start": 17' in result.output and '"insert": "status "' in result.output


def test_apply(cache):
    result = CliRunner().invoke(
        jql_cli.cli, ['apply', '--print-cursor', '--choice', 'in', '--', 'status ']
    )
    assert result.output.splitlines() == ['11', 'status in ()']


def test_pick_outside_a_jql_argument_exits_with_2(cache):
    result = CliRunner().invoke(jql_cli.cli, ['pick', '--shell', '--cursor', '6', '--', 'git st'])
    assert result.exit_code == 2 and result.output == ''


def test_pick_in_a_command_line(cache):
    line = "jqls 'project = SB and sta' -l 5"
    with patch.object(jql_cli, '_fzf_pick', return_value='status') as fzf_pick:
        result = CliRunner().invoke(jql_cli.cli, ['pick', '--shell', '--cursor', '26', '--', line])
    assert fzf_pick.call_args.args[1] == 'field'
    assert result.output.splitlines() == ['30', "jqls 'project = SB and status ' -l 5"]


def test_pick_leaves_a_list_open_at_the_end_of_the_query(cache):
    with patch.object(jql_cli, '_fzf_pick', return_value='in'):
        result = CliRunner().invoke(jql_cli.cli, ['pick', '--', 'status '])
    assert result.output == 'status in (\n'


def test_search_fzf_lines_and_aliases(cache, handler):
    handler.search_issues_by_jql.return_value = (
        [issue('SB-1', 'First  bug')],
        [],
        'assignee = 5c01',
    )
    result = CliRunner().invoke(jql_cli.cli, ['search', '-f', 'fzf', '--', 'assignee = "Jane Doe"'])
    assert result.exit_code == 0
    # the readable value is sent as the value it stands for
    assert handler.search_issues_by_jql.call_args.args[0] == 'assignee = 5c01'
    key, display, url, summary = result.output.rstrip('\n').split('\t')
    assert (key, url, summary) == ('SB-1', 'https://jira/browse/SB-1', 'First bug')
    assert '\x1b[35mSB-1' in display


def test_search_errors_are_lines_of_the_fzf_list(cache, handler):
    handler.search_issues_by_jql.return_value = (
        [],
        ["Field 'statuz' does not exist"],
        'statuz = x',
    )
    result = CliRunner().invoke(jql_cli.cli, ['search', '-f', 'fzf', '--', 'statuz = x'])
    assert result.exit_code == 0
    assert result.output.startswith('\t') and "Field 'statuz' does not exist" in result.output


def test_search_errors_fail_outside_fzf(cache, handler):
    handler.search_issues_by_jql.return_value = ([], ['bad'], 'statuz = x')
    result = CliRunner().invoke(jql_cli.cli, ['search', '-f', 'keys', '--', 'statuz = x'])
    assert result.exit_code == 1


def test_search_empty_query_prints_a_hint_for_fzf(cache, handler):
    result = CliRunner().invoke(jql_cli.cli, ['search', '-f', 'fzf', '--', ''])
    assert 'Type a JQL expression' in result.output
    handler.search_issues_by_jql.assert_not_called()


def test_markdown_turns_leftover_html_into_markdown():
    text = '**Description:**<br>While deploying\n\n<p></p>\n\n**Expected:**<BR/>x'
    assert jql_cli._markdown(text) == '**Description:**\\\nWhile deploying\n\n**Expected:**\\\nx'


def test_render_markdown_for_a_terminal_unescapes_and_formats(monkeypatch):
    monkeypatch.setenv('FZF_PREVIEW_COLUMNS', '80')
    rendered = jql_cli._render_markdown(
        '**Bold:**\\\ngroup mnha\\_ge-0\\_0 and `code`', plain=False
    )
    assert 'mnha_ge-0_0' in rendered and '\\_' not in rendered and '**' not in rendered
    assert rendered.splitlines()[0].endswith('Bold:\x1b[0m')
    # inline code has no background colour
    assert '\x1b[1;36mcode' in rendered


def test_render_markdown_for_an_editor_stays_markdown():
    rendered = jql_cli._render_markdown('**Bold:**\\\nmnha\\_ge and a \\_b', plain=True)
    assert rendered == '**Bold:**  \nmnha_ge and a \\_b'


def test_search_plain_words_fall_back_to_a_text_search(cache, handler):
    handler.search_issues_by_jql.return_value = (
        [issue('SB-2', 'Resync')],
        [],
        'text ~ "mnha resync"',
    )
    result = CliRunner().invoke(jql_cli.cli, ['search', '-f', 'fzf', '--', 'mnha resync'])
    assert (
        handler.search_issues_by_jql.call_args.kwargs['fallback_expression']
        == 'text ~ "mnha resync"'
    )
    note, item = result.output.splitlines()
    assert 'Not JQL; searching the text: text ~ "mnha resync"' in note and note.startswith('\t')
    assert item.startswith('SB-2\t')


@pytest.mark.parametrize(
    'expression, expected',
    [
        pytest.param('ass', 'text ~ "ass"', id='a-word'),
        pytest.param('say "hi"', 'text ~ "say \\"hi\\""', id='quotes-are-escaped'),
        pytest.param('assignee = x', None, id='an-operator'),
        pytest.param('status in (', None, id='a-list-operator'),
        pytest.param('a and', None, id='a-keyword'),
    ],
)
def test_text_search_expression(expression, expected):
    assert jql_cli.text_search_expression(expression) == expected


def child(key: str, parent: str) -> JiraIssue:
    item = issue(key, f'Child {key}')
    item.parent_issue_key = parent
    return item


def test_tree_rows_put_children_under_their_parents():
    # an epic and a story found by the expression, the story being a child of the epic; a subtask of the story and
    # another story of the epic added as children
    epic, story = issue('SB-1', 'Epic'), child('SB-2', 'SB-1')
    other_story, subtask = child('SB-4', 'SB-1'), child('SB-3', 'SB-2')
    ordered, depths, matched = jql_cli._tree_rows([epic, story], [subtask, other_story])
    assert [i.key for i in ordered] == ['SB-1', 'SB-2', 'SB-3', 'SB-4']
    assert depths == [0, 1, 2, 1]
    assert matched == [True, True, False, False]


def test_tree_rows_keep_a_found_child_of_an_unknown_parent_at_the_top():
    ordered, depths, _ = jql_cli._tree_rows([child('SB-5', 'SB-99')], [])
    assert ([i.key for i in ordered], depths) == (['SB-5'], [0])


def test_search_tree_fzf_lines_have_the_depth(cache, handler):
    handler.search_issue_tree.return_value = (
        [issue('SB-1', 'Epic')],
        [child('SB-2', 'SB-1')],
        [],
        'issuetype = Epic',
    )
    result = CliRunner().invoke(
        jql_cli.cli, ['search', '-f', 'fzf', '--tree', '--', 'issuetype = Epic']
    )
    assert result.exit_code == 0
    first, second = result.output.splitlines()
    assert first.split('\t')[0] == 'SB-1' and first.split('\t')[4] == '0'
    key, display, _url, _summary, depth = second.split('\t')
    assert (key, depth) == ('SB-2', '1')
    # the child that the expression did not find is dimmed, with the place of the branches before its summary
    assert display.startswith('\x1b[2m') and '\x1fChild SB-2' in display
    handler.search_issues_by_jql.assert_not_called()
