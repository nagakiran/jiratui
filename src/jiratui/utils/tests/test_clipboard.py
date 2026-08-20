import subprocess
from unittest.mock import Mock, patch

import pytest

from jiratui.utils.clipboard import clipboard_command, copy_to_clipboard


@pytest.fixture()
def app() -> Mock:
    return Mock()


@pytest.mark.parametrize(
    'platform,installed,expected',
    [
        ('darwin', {'pbcopy'}, ['pbcopy']),
        ('win32', {'clip'}, ['clip']),
        ('linux', {'wl-copy'}, ['wl-copy']),
        ('linux', {'xclip'}, ['xclip', '-selection', 'clipboard']),
        ('linux', {'xsel'}, ['xsel', '--clipboard', '--input']),
        # when several tools are installed the first candidate wins
        ('linux', {'wl-copy', 'xclip', 'xsel'}, ['wl-copy']),
        ('freebsd', {'xclip'}, ['xclip', '-selection', 'clipboard']),
        ('darwin', set(), None),
        ('linux', set(), None),
    ],
)
def test_clipboard_command(platform: str, installed: set[str], expected: list[str] | None):
    with (
        patch('jiratui.utils.clipboard.sys.platform', platform),
        patch(
            'jiratui.utils.clipboard.shutil.which',
            side_effect=lambda name: name if name in installed else None,
        ),
    ):
        assert clipboard_command() == expected


def test_copy_to_clipboard(app: Mock):
    with (
        patch('jiratui.utils.clipboard.clipboard_command', return_value=['pbcopy']),
        patch('jiratui.utils.clipboard.subprocess.run') as run_mock,
    ):
        # WHEN
        result = copy_to_clipboard(app, 'key-1 - abcd')
    # THEN
    assert result is True
    # the escape sequence is written as well, so that the copy works on a remote host over SSH
    app.copy_to_clipboard.assert_called_once_with('key-1 - abcd')
    assert run_mock.call_args[0][0] == ['pbcopy']
    assert run_mock.call_args[1]['input'] == 'key-1 - abcd'


def test_copy_to_clipboard_without_a_clipboard_tool(app: Mock):
    with (
        patch('jiratui.utils.clipboard.clipboard_command', return_value=None),
        patch('jiratui.utils.clipboard.subprocess.run') as run_mock,
    ):
        # WHEN
        result = copy_to_clipboard(app, 'key-1')
    # THEN
    assert result is False
    # the escape sequence is still the app's best chance of copying the text
    app.copy_to_clipboard.assert_called_once_with('key-1')
    run_mock.assert_not_called()


@pytest.mark.parametrize(
    'error',
    [
        subprocess.CalledProcessError(returncode=1, cmd=['pbcopy']),
        subprocess.TimeoutExpired(cmd=['pbcopy'], timeout=2),
        FileNotFoundError('pbcopy'),
        OSError('broken pipe'),
    ],
)
def test_copy_to_clipboard_when_the_clipboard_tool_fails(app: Mock, error: Exception):
    with (
        patch('jiratui.utils.clipboard.clipboard_command', return_value=['pbcopy']),
        patch('jiratui.utils.clipboard.subprocess.run', side_effect=error),
    ):
        # WHEN
        result = copy_to_clipboard(app, 'key-1')
    # THEN: the failure is reported, not raised
    assert result is False
    app.copy_to_clipboard.assert_called_once_with('key-1')
