from contextlib import contextmanager
import os
from unittest.mock import MagicMock

from jiratui.utils.editor import open_in_external_editor


class AppStub:
    """A stand-in for the running app: `open_in_external_editor` only suspends it and notifies through it."""

    def __init__(self):
        self.notifications: list[dict] = []
        self.suspended = False

    @contextmanager
    def suspend(self):
        self.suspended = True
        yield
        self.suspended = False

    def notify(self, message: str = '', **kwargs) -> None:
        self.notifications.append({'message': message, **kwargs})


def test_open_in_external_editor_returns_the_content_left_by_the_editor(monkeypatch):
    # GIVEN an editor that replaces the content of the file it is given
    file_names: list[str] = []

    def fake_call(args: list[str]) -> int:
        file_names.append(args[-1])
        with open(args[-1], 'w', encoding='utf-8') as temp_file:
            temp_file.write('edited by the user')
        return 0

    monkeypatch.setattr('jiratui.utils.editor.subprocess.call', fake_call)
    app = AppStub()
    # WHEN
    result = open_in_external_editor(app, 'vim', 'original')
    # THEN
    assert result == 'edited by the user'
    # the app is suspended while the editor runs, and resumed afterwards
    assert app.suspended is False
    # the temporary file is removed
    assert not os.path.exists(file_names[0])


def test_open_in_external_editor_passes_the_content_and_the_command_to_the_editor(monkeypatch):
    call = MagicMock(return_value=0)
    monkeypatch.setattr('jiratui.utils.editor.subprocess.call', call)
    # WHEN
    open_in_external_editor(AppStub(), 'code --wait', 'the original content', suffix='.jql')
    # THEN the command is split into arguments and the temporary file is appended to them
    args = call.call_args.args[0]
    assert args[:2] == ['code', '--wait']
    assert args[-1].endswith('.jql')


def test_open_in_external_editor_keeps_the_content_when_the_editor_cannot_run(monkeypatch):
    def fake_call(args: list[str]) -> int:
        raise OSError('no such editor')

    monkeypatch.setattr('jiratui.utils.editor.subprocess.call', fake_call)
    app = AppStub()
    # WHEN
    result = open_in_external_editor(app, 'not-an-editor', 'original')
    # THEN
    assert result == 'original'
    assert app.notifications[0]['severity'] == 'error'
    assert app.suspended is False
