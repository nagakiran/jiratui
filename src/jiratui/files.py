import os
from pathlib import Path

from xdg_base_dirs import xdg_cache_home, xdg_config_home, xdg_state_home

from jiratui.constants import LOG_FILE_FILE_NAME, SAVED_JQL_FILE_NAME


def _jiratui_directory(root: Path) -> Path:
    """Returns the path to a `jiratui` directory associated with the application.

    Args:
        root: the root directory path where the jiratui directory exists or is created.

    Returns:
        A `Path` expression of a `jiratui` directory.
    """
    directory = root / 'jiratui'
    directory.mkdir(exist_ok=True, parents=True)
    return directory


def get_config_directory() -> Path:
    """Retrieves the (default) directory where the configuration file of the application will be stored.

    Returns:
        A `Path` of the config directory.
    """
    return _jiratui_directory(xdg_config_home())


def get_logs_directory() -> Path:
    """Retrieves the (default) directory where the logs of the application will be stored.

    Returns:
        A `Path` of the logs directory.
    """
    return _jiratui_directory(xdg_state_home())


def get_cache_directory() -> Path:
    """Retrieves the directory where the application keeps data that it can always fetch again.

    Returns:
        A `Path` of the cache directory.
    """
    return _jiratui_directory(xdg_cache_home())


def get_config_file() -> Path:
    """Retrieves the (default) path of the config file.

    Returns:
        A `Path` of the config file.
    """
    return get_config_directory() / 'config.yaml'


def get_log_file() -> Path:
    """Retrieves the (default) path of the logs file.

    Returns:
        A `Path` of the logs file.
    """
    return get_logs_directory() / LOG_FILE_FILE_NAME


def get_saved_jql_file() -> Path:
    """Retrieves the path of the file that holds the JQL expressions saved from the app.

    The expressions that the user saves are kept apart from the configuration file, which is written by hand: a file
    that the app owns can be rewritten without losing the comments and the order of the keys of a file that it does
    not.

    Returns:
        A `Path` of the file, next to the configuration file in use.
    """

    if jira_tui_config_file := os.getenv('JIRA_TUI_CONFIG_FILE'):
        return Path(jira_tui_config_file).resolve().parent / SAVED_JQL_FILE_NAME
    return get_config_directory() / SAVED_JQL_FILE_NAME
