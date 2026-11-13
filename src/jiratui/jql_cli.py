"""`jiratui-jql`: a lightweight command to search work items with JQL and to complete JQL expressions.

It is meant to be called by other tools many times per minute: by fzf, to reload the work items as the expression is
edited and to preview one of them; by a shell widget, to complete the expression under the cursor; and by an editor
(e.g. Neovim), to do both. That is why it lives apart from `jiratui`: it never imports Textual, and it imports the API
only when a command needs it, so that a completion that the disk cache can answer starts in a fraction of a second.

```{important}
Like the CLI and the UI, this module only talks to Jira through the `APIController`.
```
"""

import asyncio
from collections.abc import Coroutine
from datetime import datetime
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING, Any, TypeVar

import click

from jiratui.utils.jql import JQLContext, resolve_values
from jiratui.utils.jql_completion import (
    Candidate,
    Completion,
    JQLReferenceCache,
    apply_choice,
    complete,
    needs_api,
)
from jiratui.utils.shell_jql import (
    DEFAULT_JQL_COMMANDS,
    DEFAULT_JQL_FLAGS,
    find_jql_region,
)

if TYPE_CHECKING:
    from jiratui.api_controller.controller import APIController
    from jiratui.commands.handler import CommandHandler
    from jiratui.models import JiraIssue

T = TypeVar('T')

SEARCH_FIELDS = ['id', 'key', 'summary', 'status', 'issuetype', 'assignee', 'updated', 'priority']
"""The fields fetched for every work item of a search."""

SHOW_FIELDS = [
    'key',
    'summary',
    'status',
    'issuetype',
    'assignee',
    'reporter',
    'priority',
    'created',
    'updated',
    'labels',
    'components',
    'parent',
    'description',
    'comment',
]
"""The fields fetched to preview a work item."""

EMPTY_QUERY_HINT = 'Type a JQL expression. tab: complete  ctrl-r: saved queries  ctrl-s: save  ctrl-e: edit in $EDITOR'

ISSUE_KEY_PATTERN = re.compile(r'[A-Za-z][A-Za-z0-9_]*-\d+')
"""The shape of the key of a work item; e.g. `SB-123`."""

_HANDLER: 'CommandHandler | None' = None


def _echo(text: str = '', err: bool = False) -> None:
    """Prints a line, keeping its colours even when the output is a pipe; fzf is what displays them."""

    click.echo(text, err=err, color=True)


def _run(coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine)


def _handler() -> 'CommandHandler':
    """The command handler, created the first time it is needed so that commands that do not need it stay fast."""

    global _HANDLER
    if _HANDLER is None:
        from pydantic import ValidationError

        from jiratui.commands.handler import CommandHandler

        try:
            _HANDLER = CommandHandler()
        except ValidationError as e:
            missing = ', '.join(str(error['loc'][0]) for error in e.errors() if error.get('loc'))
            raise click.ClickException(
                f'The jiratui configuration is incomplete ({missing}); e.g. is JIRA_API_TOKEN exported?'
            ) from e
    return _HANDLER


def _controller() -> 'APIController':
    return _handler().api


def _base_url() -> str | None:
    from jiratui.config import CONFIGURATION

    try:
        config = CONFIGURATION.get()
    except LookupError:
        return None
    return config.jira_api_base_url


def _load_cache(refresh_if_stale: bool) -> JQLReferenceCache:
    """Loads the JQL reference data, fetching it again when it is stale and the caller can afford the API."""

    cache = JQLReferenceCache.load()
    if refresh_if_stale and cache.is_stale():
        controller = _controller()
        cache = JQLReferenceCache.load(base_url=_base_url())
        if _run(cache.refresh(controller)):
            cache.base_url = _base_url()
            cache.save()
    return cache


def _complete(expression: str, cursor: int | None) -> tuple[Completion, JQLReferenceCache]:
    """Completes an expression, using the API only when the position or the state of the cache requires it."""

    cache = JQLReferenceCache.load()
    use_api = needs_api(expression, cursor) or cache.is_stale()
    if use_api:
        cache = _load_cache(refresh_if_stale=True)
    controller = _controller() if needs_api(expression, cursor) else None
    aliases_before = len(cache.alias_mapping())
    completion = _run(complete(expression, cursor, cache, controller))
    if len(cache.alias_mapping()) != aliases_before:
        cache.save()
    return completion, cache


def _candidate_lines(candidates: list[Candidate], colour: bool) -> list[str]:
    """Lines for fzf: the display text, padded so that the details line up, a tab, and then the kind and detail."""

    width = min(max((len(c.display) for c in candidates), default=0), 40)
    lines = []
    for candidate in candidates:
        detail = f'{candidate.kind} {candidate.detail}'.strip()
        if colour:
            detail = f'\x1b[2m{detail}\x1b[0m'
        lines.append(f'{candidate.display.ljust(width)}\t{detail}')
    return lines


def _fzf_pick(
    candidates: list[Candidate],
    prompt: str,
    reload_command: str | None = None,
    accept_query: bool = False,
) -> str | None:
    """Lets the user pick a suggestion with fzf.

    fzf draws on the terminal (`/dev/tty`) by itself, so this works from a shell widget and from another fzf.

    Args:
        candidates: the suggestions.
        prompt: the prompt of fzf.
        reload_command: a command that prints the suggestions for the query of fzf (`{q}`); the suggestions are
            reloaded with it as the user types. Used for the values of a field, which Jira filters by what is typed.
        accept_query: whether the query is picked when it matches no suggestion; e.g. a value that Jira does not
            suggest.

    Returns:
        The display text of the suggestion picked; `None` when nothing was picked.
    """

    if not candidates and not reload_command:
        return None
    fzf = shutil.which('fzf')
    if fzf is None:
        raise click.ClickException('fzf is not installed')
    options = [
        '--ansi',
        '--delimiter=\t',
        '--nth=1,2',
        '--height=40%',
        '--reverse',
        '--no-multi',
        '--print-query',
        f'--prompt={prompt}> ',
    ]
    if reload_command:
        options.append(f'--bind=change:reload:sleep 0.25; {reload_command} || true')
    else:
        options.extend(['--select-1', '--exit-0'])
    options.extend(shlex.split(os.getenv('JIRATUI_JQL_FZF_OPTS', '')))
    lines = '\n'.join(_candidate_lines(candidates, colour=True))
    result = subprocess.run(
        [fzf, *options], input=lines, stdout=subprocess.PIPE, text=True, check=False
    )
    if result.returncode not in (0, 1):  # 1: no match; 130: cancelled
        return None
    output = result.stdout.split('\n')
    query = output[0].strip() if output else ''
    selection = output[1] if len(output) > 1 else ''
    if selection.strip():
        return selection.split('\t', 1)[0].strip()
    if accept_query and query:
        return query
    return None


def _context_label(completion: Completion) -> str:
    context = completion.context
    if context.context is JQLContext.OPERATOR and context.field:
        return f'{context.field} operator'
    if context.context is JQLContext.VALUE and context.field:
        return f'{context.field} value'
    return context.context.value


@click.group(
    help='Search work items with JQL and complete JQL expressions; for fzf, shells and editors.'
)
def cli() -> None:
    pass


# -- COMPLETION --


@cli.command('complete')
@click.option('--cursor', '-c', type=int, default=None, help='Cursor position. Default: the end.')
@click.option(
    '--format',
    '-f',
    'output_format',
    type=click.Choice(['lines', 'fzf', 'json']),
    default='lines',
    help='lines: one suggestion per line; fzf: suggestion<TAB>kind; json: everything, for editors.',
)
@click.argument('expression', default='')
def complete_command(expression: str, cursor: int | None, output_format: str) -> None:
    """Prints the suggestions for the position of the cursor in EXPRESSION."""

    completion, _ = _complete(expression, cursor)
    if output_format == 'json':
        context = completion.context
        click.echo(
            json.dumps(
                {
                    'context': context.context.value,
                    'field': context.field,
                    'operator': context.operator,
                    'prefix': context.prefix,
                    'replace_start': context.replace_start,
                    'replace_end': context.replace_end,
                    'candidates': [
                        {
                            'display': c.display,
                            'insert': c.insert,
                            'cursor_offset': c.cursor_offset,
                            'kind': c.kind,
                            'detail': c.detail,
                        }
                        for c in completion.candidates
                    ],
                }
            )
        )
        return
    for candidate in completion.candidates:
        click.echo(
            _candidate_lines([candidate], colour=False)[0]
            if output_format == 'fzf'
            else candidate.display
        )


@cli.command('apply')
@click.option('--cursor', '-c', type=int, default=None, help='Cursor position. Default: the end.')
@click.option('--choice', required=True, help='The suggestion picked, as printed by `complete`.')
@click.option(
    '--print-cursor', is_flag=True, help='Print the new cursor position on the first line.'
)
@click.argument('expression', default='')
def apply_command(expression: str, cursor: int | None, choice: str, print_cursor: bool) -> None:
    """Applies a suggestion to EXPRESSION and prints the new expression."""

    text, new_cursor = apply_choice(expression, cursor, choice, JQLReferenceCache.load())
    if print_cursor:
        click.echo(new_cursor)
    click.echo(text)


@cli.command('pick')
@click.option('--cursor', '-c', type=int, default=None, help='Cursor position. Default: the end.')
@click.option(
    '--shell',
    'shell_line',
    is_flag=True,
    help='The argument is a whole command line; the JQL is the value of --jql/-q or an argument of `jqls`. '
    'Prints the new cursor position and then the new command line.',
)
@click.argument('text', default='')
def pick_command(text: str, cursor: int | None, shell_line: bool) -> None:
    """Completes the JQL under the cursor by picking a suggestion with fzf.

    Exits, printing nothing, with status 1 when nothing was picked, and with status 2 when the cursor of a command
    line (`--shell`) is not in a JQL expression; a shell widget falls back to its usual completion on the latter.
    """

    expression, expression_cursor = text, cursor
    region = None
    if shell_line:
        flags = tuple(os.getenv('JIRATUI_JQL_FLAGS', ' '.join(DEFAULT_JQL_FLAGS)).split())
        commands = tuple(os.getenv('JIRATUI_JQL_COMMANDS', ' '.join(DEFAULT_JQL_COMMANDS)).split())
        region = find_jql_region(text, len(text) if cursor is None else cursor, flags, commands)
        if region is None:
            sys.exit(2)
        expression, expression_cursor = region.expression, region.cursor

    try:
        completion, cache = _complete(expression, expression_cursor)
    except Exception as e:  # a failure must leave the command line as it is
        click.echo(f'jiratui-jql: {e}', err=True)
        sys.exit(1)
    context = completion.context
    reload_command = None
    if context.context is JQLContext.VALUE and context.field:
        reload_command = shlex.join(
            [sys.executable, '-m', 'jiratui.jql_cli', 'values', '--field', context.field, '--']
        )
        reload_command = f'{reload_command} {{q}}'
    choice = _fzf_pick(
        completion.candidates,
        _context_label(completion),
        reload_command=reload_command,
        accept_query=context.context is JQLContext.VALUE,
    )
    if choice is None:
        sys.exit(1)
    candidate = completion.find(choice)
    if candidate is not None:
        new_expression, new_cursor = completion.apply(candidate)
    else:
        new_expression, new_cursor = apply_choice(expression, expression_cursor, choice, cache)

    if region is not None:
        new_line, line_cursor = region.replace(text, new_expression, new_cursor)
        click.echo(line_cursor)
        click.echo(new_line)
        return
    if cursor is None and new_expression[new_cursor:] == ')':
        # the caller (e.g. the query of fzf) puts the cursor at the end of what is printed, so a list is left open
        # for its values to be completed next, rather than closed with the cursor after it
        new_expression = new_expression[:new_cursor]
    click.echo(new_expression)


@cli.command('values')
@click.option('--field', required=True, help='The field whose values to suggest.')
@click.argument('prefix', default='')
def values_command(field: str, prefix: str) -> None:
    """Prints the values of FIELD that contain PREFIX, as lines for fzf; used to reload a picker as the user types."""

    from jiratui.utils.jql import JQLCursorContext
    from jiratui.utils.jql_completion import value_candidates

    cache = _load_cache(refresh_if_stale=True)
    aliases_before = len(cache.alias_mapping())
    context = JQLCursorContext(context=JQLContext.VALUE, prefix=prefix.strip(), field=field)
    candidates = _run(value_candidates(cache, context, _controller()))
    if len(cache.alias_mapping()) != aliases_before:
        cache.save()
    for line in _candidate_lines(candidates, colour=True):
        _echo(line)


@cli.command('refresh')
def refresh_command() -> None:
    """Fetches the JQL fields and functions again; they are cached for a day otherwise."""

    controller = _controller()
    cache = JQLReferenceCache.load(base_url=_base_url())
    if not _run(cache.refresh(controller)):
        raise click.ClickException('Unable to fetch the JQL reference data')
    cache.base_url = _base_url()
    cache.save()
    click.echo(
        f'{len(cache.fields)} fields and {len(cache.functions)} functions cached in {cache.path}'
    )


# -- SAVED EXPRESSIONS --


def _saved_expressions() -> list[dict[str, str]]:
    """The expressions saved from the app, followed by the ones defined in the configuration file."""

    from jiratui.utils.saved_jql import load_saved_expressions

    entries: list[dict[str, str]] = []
    for key, entry in load_saved_expressions().items():
        entries.append({'key': key, 'source': 'saved', **entry})
    try:
        from jiratui.config import CONFIGURATION, ApplicationConfiguration

        try:
            config = CONFIGURATION.get()
        except LookupError:
            config = ApplicationConfiguration()  # type:ignore[call-arg]
            CONFIGURATION.set(config)
        for key, entry in (config.pre_defined_jql_expressions or {}).items():
            if isinstance(entry, dict) and entry.get('expression'):
                entries.append(
                    {
                        'key': str(key),
                        'source': 'config',
                        'label': str(entry.get('label') or key),
                        'expression': ' '.join(str(entry['expression']).split()),
                    }
                )
    except Exception as e:
        click.echo(f'jiratui-jql: unable to read the configuration: {e}', err=True)
    return entries


def find_saved_expression(name: str) -> str:
    name_lower = name.strip().lower()
    for entry in _saved_expressions():
        if name_lower in (entry['key'].lower(), entry['label'].lower()):
            return entry['expression']
    raise click.BadParameter(f'No saved JQL expression with the key or label {name!r}')


@cli.command('saved')
@click.option(
    '--format',
    '-f',
    'output_format',
    type=click.Choice(['tsv', 'json']),
    default='tsv',
    help='tsv: label<TAB>expression<TAB>key<TAB>source; json: a list of objects.',
)
def saved_command(output_format: str) -> None:
    """Lists the saved JQL expressions: those saved from the app and those in the configuration file."""

    entries = _saved_expressions()
    if output_format == 'json':
        click.echo(json.dumps(entries))
        return
    for entry in entries:
        click.echo(f'{entry["label"]}\t{entry["expression"]}\t{entry["key"]}\t{entry["source"]}')


@cli.command('save')
@click.option('--label', '-l', help='The name of the expression; asked for when not given.')
@click.argument('expression')
def save_command(expression: str, label: str | None) -> None:
    """Saves EXPRESSION; the app offers it in its JQL editor too."""

    from jiratui.utils.saved_jql import save_expression

    if not expression.strip():
        raise click.BadParameter('An expression is required')
    if not label:
        click.echo(f'Saving: {expression}', err=True)
        label = click.prompt('Label', err=True)
    if not label or not label.strip():
        raise click.BadParameter('A label is required')
    key = save_expression(label, ' '.join(expression.split()))
    click.echo(f'Saved as {key!r}', err=True)


@cli.command('pick-saved')
def pick_saved_command() -> None:
    """Picks a saved expression with fzf and prints it; exits with status 1 when nothing was picked."""

    entries = _saved_expressions()
    fzf = shutil.which('fzf')
    if fzf is None:
        raise click.ClickException('fzf is not installed')
    lines = '\n'.join(
        f'{entry["expression"]}\t\x1b[1m{entry["label"]}\x1b[0m \x1b[2m({entry["source"]})\x1b[0m'
        f'\t{entry["expression"]}'
        for entry in entries
    )
    result = subprocess.run(
        [
            fzf,
            '--ansi',
            '--delimiter=\t',
            '--with-nth=2,3',
            '--accept-nth=1',
            '--height=50%',
            '--reverse',
            '--no-multi',
            '--prompt=saved> ',
            *shlex.split(os.getenv('JIRATUI_JQL_FZF_OPTS', '')),
        ],
        input=lines,
        stdout=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        sys.exit(1)
    click.echo(result.stdout.strip())


@cli.command('edit')
@click.argument('expression', default='')
def edit_command(expression: str) -> None:
    """Opens EXPRESSION in $VISUAL/$EDITOR, as a `.jql` file, and prints it on one line once the editor exits.

    The expression is split before each `and`/`or`/`order by` to make it easier to edit; the lines are joined again
    afterwards. Prints the expression unchanged when the editor is closed without saving.
    """

    from jiratui.utils.jql import JQLTokenKind, tokenize

    # one clause per line
    pretty = expression
    for token in reversed(tokenize(expression)):
        if (
            token.kind is JQLTokenKind.KEYWORD
            and token.text.lower() in ('and', 'or')
            or (token.kind is JQLTokenKind.KEYWORD and token.text.lower().startswith('order'))
        ):
            if token.start > 0:
                pretty = f'{pretty[: token.start].rstrip()}\n{pretty[token.start :]}'
    edited = _edit_in_terminal(pretty)
    click.echo(' '.join((edited if edited is not None else expression).split()))


def _edit_in_terminal(text: str) -> str | None:
    """Edits a text in $VISUAL/$EDITOR, as a `.jql` file, and returns it; `None` when it was not saved.

    The callers capture the output of this command (e.g. fzf writes it to a file, or `$(...)` in a shell), so the
    editor must not inherit the standard streams: it would draw its screen into the capture and appear to hang.
    It is attached to the terminal (`/dev/tty`) instead.
    """

    import tempfile

    editor = os.getenv('VISUAL') or os.getenv('EDITOR') or 'vi'
    descriptor, path = tempfile.mkstemp(prefix='jiratui-', suffix='.jql')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
            file.write(f'{text}\n')
        modified = os.path.getmtime(path)
        try:
            tty = open('/dev/tty', 'r+b', buffering=0)
        except OSError:
            tty = None
        try:
            streams: dict[str, Any] = {'stdin': tty, 'stdout': tty, 'stderr': tty} if tty else {}
            result = subprocess.run([*shlex.split(editor), path], check=False, **streams)
        finally:
            if tty:
                tty.close()
        if result.returncode != 0 or os.path.getmtime(path) == modified:
            return None
        with open(path, encoding='utf-8') as file:
            return file.read()
    finally:
        os.remove(path)


# -- SEARCH --


def resolve_expression(expression: str) -> str:
    """The expression with the readable values picked from the suggestions replaced by what the API understands."""

    cache = JQLReferenceCache.load()
    return resolve_values(' '.join(expression.split()), cache.alias_mapping())


def _issue_url(key: str) -> str:
    from jiratui.utils.urls import build_external_url_for_issue

    return build_external_url_for_issue(key) or ''


def _truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text.ljust(width)
    return f'{text[: width - 1]}…'


def _fzf_lines(
    issues: list['JiraIssue'],
    depths: list[int] | None = None,
    matched: list[bool] | None = None,
) -> list[str]:
    """One line per work item: the key, the line to display, the URL and the summary, separated by tabs.

    With `depths` (the threaded view of `search --tree`), each line also has the depth of its work item as a 5th field
    and \\x1f before the summary, where liveq draws the branches; the work items that the expression did not find
    (`matched` false: the children added under them) are dimmed.
    """

    rows = []
    for issue in issues:
        rows.append(
            (
                issue.key,
                issue.work_item_type_name,
                issue.status_name,
                issue.assignee_display_name or '-',
                issue.updated.strftime('%Y-%m-%d') if issue.updated else '',
                ' '.join(issue.summary.split()),
            )
        )
    key_width = max((len(row[0]) for row in rows), default=0)
    type_width = min(max((len(row[1]) for row in rows), default=0), 10)
    status_width = min(max((len(row[2]) for row in rows), default=0), 16)
    assignee_width = min(max((len(row[3]) for row in rows), default=0), 18)
    lines = []
    for i, (key, issue_type, status, assignee, updated, summary) in enumerate(rows):
        tree = '\x1f' if depths is not None else ''
        if matched is not None and not matched[i]:
            display = (
                f'\x1b[2m{key.ljust(key_width)} {_truncate(issue_type, type_width)} '
                f'{_truncate(status, status_width)} {_truncate(assignee, assignee_width)} '
                f'{updated} {tree}{summary}\x1b[0m'
            )
        else:
            display = (
                f'\x1b[35m{key.ljust(key_width)}\x1b[0m '
                f'\x1b[2m{_truncate(issue_type, type_width)}\x1b[0m '
                f'\x1b[36m{_truncate(status, status_width)}\x1b[0m '
                f'\x1b[33m{_truncate(assignee, assignee_width)}\x1b[0m '
                f'\x1b[2m{updated}\x1b[0m {tree}{summary}'
            )
        line = f'{key}\t{display}\t{_issue_url(key)}\t{summary}'
        if depths is not None:
            line += f'\t{depths[i]}'
        lines.append(line)
    return lines


def _tree_rows(
    issues: list['JiraIssue'], children: list['JiraIssue']
) -> tuple[list['JiraIssue'], list[int], list[bool]]:
    """The work items found and their children as a tree, in display order: each one followed by its children (an
    epic, its stories, their subtasks). A work item found whose parent was found too goes under it rather than at the
    top. Returns the work items, their depths, and whether each was found by the expression.
    """

    found = {issue.key for issue in issues}
    every = {issue.key: issue for issue in [*issues, *children]}
    kids: dict[str, list['JiraIssue']] = {}
    roots = []
    for issue in [*issues, *children]:
        parent = issue.parent_issue_key
        if parent and parent in every and parent != issue.key:
            kids.setdefault(parent, []).append(issue)
        elif issue.key in found:
            roots.append(issue)
    ordered: list['JiraIssue'] = []
    depths: list[int] = []
    seen: set[str] = set()

    def walk(issue: 'JiraIssue', depth: int) -> None:
        if issue.key in seen:  # a cycle of parents, which Jira should not allow
            return
        seen.add(issue.key)
        ordered.append(issue)
        depths.append(depth)
        for child in kids.get(issue.key, []):
            walk(child, depth + 1)

    for root in roots:
        walk(root, 0)
    # the found work items that only a cycle reaches
    for issue in issues:
        if issue.key not in seen:
            walk(issue, 0)
    return ordered, depths, [issue.key in found for issue in ordered]


def _search(
    expression: str, limit: int, fallback_expression: str | None = None
) -> tuple[list['JiraIssue'], list[str], str]:
    """Searches work items; returns them, the errors of the expression when it is invalid, and the expression used."""

    from jiratui.exceptions import CLIException

    try:
        return _handler().search_issues_by_jql(
            expression, limit=limit, fields=SEARCH_FIELDS, fallback_expression=fallback_expression
        )
    except CLIException as e:
        raise click.ClickException(str(e)) from e


def _search_tree(
    expression: str, limit: int, fallback_expression: str | None = None
) -> tuple[list['JiraIssue'], list['JiraIssue'], list[str], str]:
    """Like `_search`, with the children of the work items found (subtasks, the stories of an epic)."""

    from jiratui.exceptions import CLIException

    try:
        return _handler().search_issue_tree(
            expression, limit=limit, fields=SEARCH_FIELDS, fallback_expression=fallback_expression
        )
    except CLIException as e:
        raise click.ClickException(str(e)) from e


def text_search_expression(expression: str) -> str | None:
    """The full-text search for an expression made of plain words; `None` when the expression is meant as JQL.

    An expression is meant as JQL as soon as it uses an operator (`=`, `in`, `~`, ...) or a keyword; plain words such
    as `mnha resync` have neither.
    """

    from jiratui.utils.jql import JQLTokenKind, tokenize

    words = ' '.join(expression.split())
    if not words:
        return None
    if any(
        token.kind in (JQLTokenKind.OPERATOR, JQLTokenKind.KEYWORD) for token in tokenize(words)
    ):
        return None
    escaped = words.replace('\\', '\\\\').replace('"', '\\"')
    return f'text ~ "{escaped}"'


@cli.command('search')
@click.option('--saved', '-s', 'saved_name', help='Use a saved expression, by key or label.')
@click.option('--limit', '-l', type=int, default=50, show_default=True)
@click.option(
    '--format',
    '-f',
    'output_format',
    type=click.Choice(['fzf', 'tsv', 'json', 'keys']),
    default='tsv',
    show_default=True,
    help='fzf: key<TAB>coloured line<TAB>url<TAB>summary; tsv: key, type, status, assignee, updated, summary, url; '
    'json: a list of objects; keys: one key per line.',
)
@click.option(
    '--text-fallback/--no-text-fallback',
    default=True,
    help='Search plain words as text when they are not valid JQL.',
)
@click.option(
    '--tree',
    is_flag=True,
    help='With -f fzf: the work items as a tree, each followed by its children (the stories of an epic, the subtasks '
    'of a story), also those the expression does not find (dimmed); a 5th field has the depth (see liveq).',
)
@click.argument('expression', default='')
def search_command(
    expression: str,
    saved_name: str | None,
    limit: int,
    output_format: str,
    text_fallback: bool,
    tree: bool,
) -> None:
    """Searches the work items that match EXPRESSION, a JQL expression.

    When EXPRESSION is not valid JQL and has no operator (i.e. it is plain words), the words are searched as text
    (`text ~ "..."`), unless --no-text-fallback is given.

    Errors are printed as lines of the output with the fzf format, so that they show up in the list of fzf.
    """

    if saved_name:
        expression = find_saved_expression(saved_name)
    if not expression.strip():
        if output_format == 'fzf':
            _echo(f'\t\x1b[2m{EMPTY_QUERY_HINT}\x1b[0m\t')
            return
        raise click.BadParameter('A JQL expression, or --saved, is required')

    def report(lines: list[str]) -> None:
        if output_format == 'fzf':
            for line in lines:
                _echo(f'\t\x1b[31m{line}\x1b[0m\t')
            return
        for line in lines:
            click.echo(line, err=True)
        sys.exit(1)

    try:
        # plain words are not JQL; they are searched as text, the way the search box of Jira does
        fallback = text_search_expression(expression) if text_fallback else None
        tree = tree and output_format == 'fzf'
        children: list['JiraIssue'] = []
        if tree:
            issues, children, errors, used = _search_tree(
                resolve_expression(expression), limit, fallback
            )
        else:
            issues, errors, used = _search(resolve_expression(expression), limit, fallback)
        if fallback and used == fallback:
            note = f'Not JQL; searching the text: {fallback}'
            if output_format == 'fzf':
                _echo(f'\t\x1b[2m{note}\x1b[0m\t')
            else:
                click.echo(note, err=True)
    except click.ClickException as e:
        report([e.message])
        return
    except (
        Exception
    ) as e:  # anything else is still shown in the list of fzf, rather than as a traceback
        report([f'{type(e).__name__}: {e}'])
        return
    if errors:
        report(errors)
        return
    if not issues:
        if output_format == 'fzf':
            _echo('\t\x1b[2mNo work items match the expression\x1b[0m\t')
        return

    if output_format == 'fzf':
        if tree:
            ordered, depths, matched = _tree_rows(issues, children)
            lines = _fzf_lines(ordered, depths, matched)
        else:
            lines = _fzf_lines(issues)
        for line in lines:
            _echo(line)
    elif output_format == 'keys':
        for issue in issues:
            click.echo(issue.key)
    elif output_format == 'json':
        click.echo(
            json.dumps(
                [
                    {
                        'key': issue.key,
                        'summary': issue.summary,
                        'type': issue.work_item_type_name,
                        'status': issue.status_name,
                        'assignee': issue.assignee_display_name,
                        'priority': issue.priority.name if issue.priority else None,
                        'updated': issue.updated.isoformat() if issue.updated else None,
                        'url': _issue_url(issue.key),
                    }
                    for issue in issues
                ]
            )
        )
    else:
        for issue in issues:
            fields = [
                issue.key,
                issue.work_item_type_name,
                issue.status_name,
                issue.assignee_display_name,
                issue.updated.strftime('%Y-%m-%d') if issue.updated else '',
                issue.summary,
                _issue_url(issue.key),
            ]
            click.echo('\t'.join(' '.join(str(f or '').split()) for f in fields))


@cli.command('validate')
@click.argument('expression')
def validate_command(expression: str) -> None:
    """Prints the errors of EXPRESSION; exits with status 1 when there are any."""

    response = _run(_controller().validate_jql(resolve_expression(expression)))
    if not response.success:
        raise click.ClickException(response.error or 'Unable to validate the expression')
    for error in response.result:
        click.echo(error)
    sys.exit(1 if response.result else 0)


@cli.command('url')
@click.argument('key')
def url_command(key: str) -> None:
    """Prints the URL of a work item."""

    _controller()
    click.echo(_issue_url(key.strip()))


_HTML_BREAK = re.compile(r'<br\s*/?>', re.IGNORECASE)
_HTML_EMPTY_PARAGRAPH = re.compile(r'<p>\s*</p>', re.IGNORECASE)
_HTML_PARAGRAPH_TAG = re.compile(r'</?p>', re.IGNORECASE)


def _markdown(content: Any) -> str:
    """The Markdown of a rich-text field: ADF (REST v3) is converted, wiki markup or plain text (v2) is kept as-is.

    The conversion of ADF leaves some HTML behind (`<br>` for a hard break, `<p></p>` for an empty paragraph), which a
    Markdown renderer drops; those are turned into their Markdown equivalents.
    """

    if not content:
        return ''
    if isinstance(content, dict):
        from jiratui.utils.adf import convert_adf_to_markdown

        try:
            text = convert_adf_to_markdown(content)
        except Exception:
            return json.dumps(content)
    else:
        text = str(content)
    text = _HTML_BREAK.sub('\\\n', text)
    text = _HTML_EMPTY_PARAGRAPH.sub('', text)
    text = _HTML_PARAGRAPH_TAG.sub('\n\n', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _render_markdown(text: str, plain: bool) -> str:
    """Renders Markdown for a terminal (bold, code, lists, wrapping), or keeps it as Markdown for an editor.

    The width is the one of the preview window of fzf when there is one.
    """

    if plain:
        # an underscore inside a word is never emphasis, so its escape is only noise in an editor
        text = re.sub(r'(?<=\w)\\_', '_', text)
        # a hard break written as two trailing spaces, which is invisible, rather than as a trailing backslash
        return text.replace('\\\n', '  \n')
    import io

    from rich.console import Console
    from rich.markdown import Markdown
    from rich.theme import Theme

    try:
        width = int(os.getenv('FZF_PREVIEW_COLUMNS') or shutil.get_terminal_size((100, 24)).columns)
    except ValueError:
        width = 100
    buffer = io.StringIO()
    console = Console(
        file=buffer,
        width=max(width - 1, 20),
        force_terminal=True,
        color_system='256',
        # the default draws inline code on a black background, which clashes with the theme of the terminal
        theme=Theme({'markdown.code': 'bold cyan'}),
    )
    console.print(Markdown(text, code_theme='ansi_dark'))
    return '\n'.join(line.rstrip() for line in buffer.getvalue().rstrip().split('\n'))


def _format_datetime(value: datetime | None) -> str:
    return value.strftime('%Y-%m-%d %H:%M') if value else ''


@cli.command('show')
@click.option(
    '--comments', '-n', type=int, default=3, show_default=True, help='Latest comments to show.'
)
@click.option('--plain', is_flag=True, help='No colours; Markdown headings, for editors.')
@click.argument('key')
def show_command(key: str, comments: int, plain: bool) -> None:
    """Prints a work item as text; meant for the preview window of fzf and for editors."""

    key = key.strip()
    if not ISSUE_KEY_PATTERN.fullmatch(key):
        # e.g. a hint or an error line of the list of fzf, whose first field is not a key
        return
    controller = _controller()
    response = _run(controller.get_issue(issue_id_or_key=key, fields=SHOW_FIELDS))
    if not response.success or not response.result or not response.result.issues:
        raise click.ClickException(response.error or f'Unable to find the work item {key}')
    issue = response.result.issues[0]

    bold, dim, reset = ('', '', '') if plain else ('\x1b[1m', '\x1b[2m', '\x1b[0m')
    heading = '## ' if plain else ''
    _echo(f'{"# " if plain else ""}{bold}{issue.key}{reset}  {issue.summary}')
    rows = [
        ('Type', issue.work_item_type_name),
        ('Status', issue.status_name),
        ('Priority', issue.priority.name if issue.priority else ''),
        ('Assignee', issue.assignee_display_name),
        ('Reporter', issue.reporter_display_name),
        ('Parent', issue.parent_issue_key or ''),
        ('Labels', ', '.join(issue.labels or [])),
        ('Components', ', '.join(c.name for c in issue.components or [] if c.name)),
        ('Created', _format_datetime(issue.created)),
        ('Updated', _format_datetime(issue.updated)),
        ('URL', _issue_url(issue.key)),
    ]
    for label, value in rows:
        if value:
            _echo(f'- **{label}**: {value}' if plain else f'{dim}{label:<11}{reset}{value}')
    if description := _markdown(issue.description):
        _echo(f'\n{heading}{bold}Description{reset}\n{_render_markdown(description, plain)}')
    if comments > 0 and issue.comments:
        latest = sorted(issue.comments, key=lambda c: c.created or datetime.min)[-comments:]
        _echo(f'\n{heading}{bold}Comments{reset} {dim}({len(issue.comments)}){reset}')
        for comment in latest:
            author = comment.author.display_name if comment.author else ''
            _echo(
                f'{"**" if plain else dim}{_format_datetime(comment.created)} {author}{"**" if plain else reset}'
            )
            _echo(f'{_render_markdown(_markdown(comment.body), plain)}\n')


def main() -> None:
    import logging

    from jiratui.constants import LOGGER_NAME

    # the output of this command is read by fzf and editors, so the errors that the app logs must not leak onto the
    # terminal: without a handler, Python prints them to stderr. JIRATUI_JQL_DEBUG=1 shows them.
    logger = logging.getLogger(LOGGER_NAME)
    if os.getenv('JIRATUI_JQL_DEBUG'):
        logging.basicConfig(level=logging.DEBUG)
    else:
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
    cli(prog_name='jiratui-jql')


if __name__ == '__main__':
    main()
