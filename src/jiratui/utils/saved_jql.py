"""This module stores the JQL expressions that the user saves from the JQL expression editor.

The expressions live in a file of their own, next to the configuration file, because the configuration file is written
by hand: rewriting it would cost the user the comments and the order of the keys that they put there. The file that
this module owns holds the same shape as the `pre_defined_jql_expressions` setting, so the two are offered together
without translating either of them.

```{important}
A file that cannot be read must never keep the app from starting, or keep the editor from opening: a malformed file
degrades to no saved expressions at all, and says so in the log.
```
"""

import logging
import os
from pathlib import Path
import re
import tempfile
from typing import Any

import yaml

from jiratui.constants import LOGGER_NAME
from jiratui.files import get_saved_jql_file

logger = logging.getLogger(LOGGER_NAME)

ROOT_KEY = 'saved_jql_expressions'
"""The key of the mapping of expressions within the file."""

_SLUG_PATTERN = re.compile(r'[^a-z0-9]+')


def slugify(label: str) -> str:
    """The key under which an expression with the given label is stored.

    The key is derived from the label so that saving an expression under a label that is already taken replaces that
    expression instead of leaving the user with two entries of the same name.

    Args:
        label: the name that the user gave to the expression.

    Returns:
        The key; `'expression'` when the label is made entirely of characters that a key cannot hold.
    """

    slug = _SLUG_PATTERN.sub('-', label.strip().lower()).strip('-')
    return slug or 'expression'


def load_saved_expressions(path: Path | None = None) -> dict[str, dict[str, str]]:
    """Reads the expressions that the user has saved.

    Args:
        path: the file to read; the file next to the configuration file by default.

    Returns:
        The expressions, keyed the way `pre_defined_jql_expressions` is: a key mapped to a `label` and an
        `expression`. An empty mapping when the file does not exist, or cannot be made sense of.
    """

    path = path or get_saved_jql_file()
    try:
        content = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return {}
    except OSError as e:
        logger.warning(f'Unable to read the saved JQL expressions from {path}: {e}')
        return {}
    try:
        document: Any = yaml.safe_load(content)
    except yaml.YAMLError as e:
        logger.warning(f'Unable to parse the saved JQL expressions in {path}: {e}')
        return {}
    if not isinstance(document, dict):
        return {}
    expressions: Any = document.get(ROOT_KEY)
    if not isinstance(expressions, dict):
        return {}
    # an entry that is not shaped the way the app expects is dropped rather than allowed to break the dropdown
    return {
        str(key): {'label': str(entry['label']), 'expression': str(entry['expression'])}
        for key, entry in expressions.items()
        if isinstance(entry, dict) and entry.get('label') and entry.get('expression')
    }


def _write(expressions: dict[str, dict[str, str]], path: Path) -> None:
    """Replaces the file with the given expressions.

    The content is written to a temporary file in the same directory and moved into place, so that a failure halfway
    through leaves the previous file intact rather than a truncated one.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    document = yaml.safe_dump({ROOT_KEY: expressions}, allow_unicode=True, sort_keys=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f'.{path.name}-', suffix='.tmp'
    )
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as temporary_file:
            temporary_file.write(
                '# The JQL expressions saved from the JQL expression editor of jiratui.\n'
                '# This file is written by the app; edit it while the app is not running.\n'
            )
            temporary_file.write(document)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.remove(temporary_name)
        except OSError:
            pass
        raise


def save_expression(label: str, expression: str, path: Path | None = None) -> str:
    """Saves an expression under a label, replacing the expression already saved under that label.

    Args:
        label: the name to give to the expression.
        expression: the JQL expression to save.
        path: the file to write; the file next to the configuration file by default.

    Returns:
        The key under which the expression was saved.
    """

    path = path or get_saved_jql_file()
    expressions = load_saved_expressions(path)
    key = slugify(label)
    expressions[key] = {'label': label.strip(), 'expression': expression.strip()}
    _write(expressions, path)
    return key


def delete_expression(key: str, path: Path | None = None) -> bool:
    """Removes a saved expression.

    Args:
        key: the key of the expression to remove.
        path: the file to write; the file next to the configuration file by default.

    Returns:
        Whether an expression was removed; `False` when the key is not one of the saved expressions.
    """

    path = path or get_saved_jql_file()
    expressions = load_saved_expressions(path)
    if key not in expressions:
        return False
    del expressions[key]
    _write(expressions, path)
    return True
