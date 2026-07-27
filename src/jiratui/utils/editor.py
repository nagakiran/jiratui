"""This module provides the integration with the external text editor configured by the user.

The editor is the command set in the configuration setting `text_editor`, which defaults to the value of the `EDITOR`
environment variable. The content to edit is written to a temporary file that is handed to the editor while the app is
suspended, and read back once the editor exits.
"""

import os
import shlex
import subprocess
import tempfile

from textual.app import App

DEFAULT_SUFFIX = '.md'
"""The extension of the temporary file. Editors use it to work out the syntax highlighting to apply."""


def open_in_external_editor(
    app: App, command: str, content: str, suffix: str = DEFAULT_SUFFIX
) -> str:
    """Edits a piece of text with the external editor configured by the user.

    The app is suspended while the editor runs, so that the editor takes over the terminal.

    Args:
        app: the running app. Used to suspend the UI and to notify the user when the editor cannot be run.
        command: the command that runs the editor; e.g. `vim` or `code --wait`.
        content: the text to edit.
        suffix: the extension of the temporary file handed to the editor.

    Returns:
        The text as left by the editor; or the original text when the editor could not be run.
    """

    editor_args: list[str] = shlex.split(command)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
        temp_file_name = temp_file.name
        temp_file.write(content.encode('utf-8'))
        temp_file.flush()

    editor_args.append(temp_file_name)
    new_content = content
    try:
        with app.suspend():
            try:
                subprocess.call(editor_args)
            except OSError:
                app.notify(
                    severity='error',
                    title="Can't run command",
                    message=f'The command [b]{command}[/b] failed to run.',
                )
                return content

        with open(temp_file_name, 'r', encoding='utf-8') as temp_file:
            new_content = temp_file.read()
    finally:
        # the file is created with delete=False so that the editor can replace it; remove it whatever happens
        try:
            os.remove(temp_file_name)
        except OSError:
            pass
    return new_content
