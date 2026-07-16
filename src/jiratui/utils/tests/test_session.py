from contextvars import Context

import pytest

from jiratui.utils.session import ApplicationSession


@pytest.fixture(autouse=True)
def clear_session():
    ApplicationSession().clear()
    yield
    ApplicationSession().clear()


def test_a_value_is_read_back():
    session = ApplicationSession()
    session.some_variable = 42
    assert session.get('some_variable') == 42
    assert ApplicationSession().some_variable == 42


def test_an_unknown_variable():
    assert ApplicationSession().get('nope') is None
    assert ApplicationSession().get('nope', default=1) == 1
    with pytest.raises(AttributeError):
        _ = ApplicationSession().nope


def test_clear():
    session = ApplicationSession()
    session.some_variable = 42
    session.clear()
    assert session.get('some_variable') is None


def test_a_value_cached_from_another_context_is_not_lost():
    # the widgets cache the reference data from a worker and read it from another task; a session that gave a context
    # its own copy of the data would drop the write, and the app would fetch the data again on the next keystroke
    def write_from_a_fresh_context():
        ApplicationSession().cached_by_the_worker = 'the value'

    Context().run(write_from_a_fresh_context)

    assert ApplicationSession().get('cached_by_the_worker') == 'the value'


def test_a_value_is_visible_from_another_context():
    ApplicationSession().written_by_the_parent = 'the value'

    def read_from_a_fresh_context():
        return ApplicationSession().get('written_by_the_parent')

    assert Context().run(read_from_a_fresh_context) == 'the value'
