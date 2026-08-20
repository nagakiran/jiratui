"""This module provides the integration with the clipboard of the operating system.

Textual copies text by writing an OSC 52 escape sequence to the terminal. That sequence only reaches the clipboard when
the terminal supports it *and* every terminal multiplexer in between forwards it; e.g. `tmux` drops it unless
`set-clipboard` is enabled, and macOS Terminal.app does not support it at all. So the text is also piped to the
clipboard tool of the operating system, which does not depend on the terminal.
"""

import logging
import shutil
import subprocess
import sys

from textual.app import App

from jiratui.constants import LOGGER_NAME

CLIPBOARD_COMMANDS: dict[str, tuple[list[str], ...]] = {
    'darwin': (['pbcopy'],),
    'win32': (['clip'],),
}
"""The commands that write to the clipboard, by platform. The first command that is installed is the one used."""

DEFAULT_CLIPBOARD_COMMANDS: tuple[list[str], ...] = (
    ['wl-copy'],
    ['xclip', '-selection', 'clipboard'],
    ['xsel', '--clipboard', '--input'],
)
"""The commands tried on the platforms that are not listed in `CLIPBOARD_COMMANDS`; i.e. Linux and the BSDs, where the
tool to use depends on whether the session runs on Wayland or X11."""

COMMAND_TIMEOUT_IN_SECONDS = 2
"""How long to wait for the clipboard tool. The app calls this from an action, so a tool that hangs would freeze the
UI; the text copied is a few dozen bytes, so a tool that has not finished by then is not going to."""


def clipboard_command() -> list[str] | None:
    """Works out the command that writes to the clipboard of this operating system.

    Returns:
        The command to run; or `None` when none of the candidates is installed.
    """

    candidates = CLIPBOARD_COMMANDS.get(sys.platform, DEFAULT_CLIPBOARD_COMMANDS)
    for candidate in candidates:
        if shutil.which(candidate[0]):
            return list(candidate)
    return None


def copy_to_clipboard(app: App, text: str) -> bool:
    """Copies a piece of text to the clipboard.

    The text is handed to Textual, which writes an OSC 52 escape sequence, *and* to the clipboard tool of the operating
    system. Both are attempted because they cover each other's blind spots: the escape sequence is the only thing that
    works when the app runs on a remote host over SSH, and the clipboard tool is the only thing that works when the
    terminal does not let the escape sequence through.

    Args:
        app: the running app. Used to write the OSC 52 escape sequence.
        text: the text to copy.

    Returns:
        `True` when the clipboard tool of the operating system accepted the text; `False` when no tool is installed or
        the tool failed. Note that a `False` does not mean that nothing was copied: the escape sequence may still have
        reached the terminal.
    """

    app.copy_to_clipboard(text)

    logger = logging.getLogger(LOGGER_NAME)
    command = clipboard_command()
    if command is None:
        logger.debug(
            'No clipboard tool is installed; the text was only copied with an escape sequence',
            extra={'platform': sys.platform},
        )
        return False
    try:
        subprocess.run(
            command,
            input=text,
            text=True,
            encoding='utf-8',
            timeout=COMMAND_TIMEOUT_IN_SECONDS,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning(
            'Failed to copy the text with the clipboard tool of the operating system',
            extra={'command': command, 'error': str(error)},
        )
        return False
    return True
