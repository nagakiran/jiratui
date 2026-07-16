from contextvars import ContextVar
from typing import Any

_SESSION: dict[str, Any] = {}
"""The data of the session.

```{important}
This is one dictionary for the whole app, and the widgets rely on that: a value cached by a worker — e.g. the JQL
reference data — has to be visible to the widget that reads it later. The dictionary is only ever mutated in place;
rebinding `ContextVar` here would hand a private copy of the session to whichever task happened to touch it first, and
that task's writes would be lost to everybody else.
```
"""


class ApplicationSession:
    """Session storage shared by the whole app.

    Example:
    # create the session object
    session = ApplicationSession()
    # set a variable
    session.some_variable = 42
    # if you know the variable has been set you can retrieve its value using
    value = session.get('some_variable')
    # with explicit default value
    value = session.get('some_variable', default=1)
    # or, if you don't know whether the variable has been set or not
    try:
        value = session.some_variable
    except AttributeError:
        value = None
    # clear the session
    session.clear()
    """

    _session_var: ContextVar[dict[str, Any]] = ContextVar('application_session', default=_SESSION)

    @classmethod
    def _get_session(cls) -> dict[str, Any]:
        return cls._session_var.get()

    def __setattr__(self, name: str, value):
        if name.startswith('_'):
            super().__setattr__(name, value)
        else:
            self._get_session()[name] = value

    def __getattr__(self, name: str):
        if name.startswith('_'):
            return super().__getattribute__(name)
        try:
            return self._get_session()[name]
        except KeyError as e:
            raise AttributeError(f"ApplicationSession has no attribute '{name}'") from e

    def get(self, name: str, default=None):
        return self._get_session().get(name, default)

    def clear(self):
        self._get_session().clear()
