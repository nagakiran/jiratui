from unittest.mock import Mock, PropertyMock, patch

import pytest
from textual.widgets import Input, Select, TextArea

from jiratui.config import CONFIGURATION
from jiratui.utils.saved_jql import load_saved_expressions, save_expression
from jiratui.widgets.screen import MainScreen
from jiratui.widgets.screens.jql import JQLEditorScreen, PreDefinedJQLExpressionsWidget


@patch.object(JQLEditorScreen, '_pre_defined_jql_expressions', PropertyMock(return_value=None))
@pytest.mark.asyncio
async def test_open_jql_editor_screen_without_predefined_expressions(app):
    # GIVEN
    async with app.run_test() as pilot:
        # WHEN
        screen = JQLEditorScreen('some content')
        await app.push_screen(screen)
        await pilot.pause()
        # THEN
        assert isinstance(app.screen, JQLEditorScreen)
        widget = screen.query_one(PreDefinedJQLExpressionsWidget)
        assert screen.expressions == []
        assert widget.selection is None
        textarea = screen.query_one(TextArea)
        assert textarea.text == 'some content'


@patch.object(
    JQLEditorScreen,
    '_pre_defined_jql_expressions',
    PropertyMock(
        return_value={
            '1': {'label': 'Expression A', 'expression': 'expression 1'},
            '2': {'label': 'Expression B', 'expression': 'expression 2'},
        }
    ),
)
@pytest.mark.asyncio
async def test_open_jql_editor_screen_with_predefined_expressions(app):
    # GIVEN
    async with app.run_test() as pilot:
        # WHEN
        screen = JQLEditorScreen('some content')
        await app.push_screen(screen)
        await pilot.pause()
        # THEN
        assert isinstance(app.screen, JQLEditorScreen)
        widget = screen.query_one(PreDefinedJQLExpressionsWidget)
        assert screen.expressions == [
            ('1', {'label': 'Expression A', 'expression': 'expression 1'}),
            ('2', {'label': 'Expression B', 'expression': 'expression 2'}),
        ]
        assert widget.selection is None
        textarea = screen.query_one(TextArea)
        assert textarea.text == 'some content'


@patch.object(JQLEditorScreen, '_pre_defined_jql_expressions', PropertyMock(return_value=None))
@pytest.mark.asyncio
async def test_open_jql_editor_screen_without_initial_content(app):
    # GIVEN
    async with app.run_test() as pilot:
        # WHEN
        screen = JQLEditorScreen()
        await app.push_screen(screen)
        await pilot.pause()
        # THEN
        assert isinstance(app.screen, JQLEditorScreen)
        widget = screen.query_one(PreDefinedJQLExpressionsWidget)
        assert screen.expressions == []
        assert widget.selection is None
        textarea = screen.query_one(TextArea)
        assert textarea.text == ''


@pytest.mark.parametrize(
    'input_message, expected_message',
    [
        ('a', 'a'),
        ('', ''),
    ],
)
@patch.object(JQLEditorScreen, '_pre_defined_jql_expressions', PropertyMock(return_value=None))
@pytest.mark.asyncio
async def test_dismiss_jql_editor_screen_with_content(input_message, expected_message, app):
    # GIVEN
    async with app.run_test() as pilot:
        # WHEN
        screen = JQLEditorScreen()
        screen.dismiss = Mock()
        await app.push_screen(screen)
        await pilot.pause()
        await pilot.press('tab')
        await pilot.press(input_message)
        await pilot.press('escape')
        await pilot.press('escape')
        # THEN
        assert isinstance(app.screen, MainScreen)
        assert screen.dismiss.call_args[0][0] == expected_message


@patch.object(
    JQLEditorScreen,
    '_pre_defined_jql_expressions',
    PropertyMock(
        return_value={
            '1': {'label': 'Expression A', 'expression': 'expression 1'},
            '2': {'label': 'Expression B', 'expression': 'expression 2'},
        }
    ),
)
@pytest.mark.asyncio
async def test_open_jql_editor_screen_with_predefined_expressions_select_expression(app):
    # GIVEN
    async with app.run_test() as pilot:
        # WHEN
        screen = JQLEditorScreen()
        await app.push_screen(screen)
        await pilot.pause()
        # THEN
        assert isinstance(app.screen, JQLEditorScreen)
        widget = screen.query_one(PreDefinedJQLExpressionsWidget)
        assert screen.expressions == [
            ('1', {'label': 'Expression A', 'expression': 'expression 1'}),
            ('2', {'label': 'Expression B', 'expression': 'expression 2'}),
        ]
        await pilot.press('enter')
        await pilot.press('down')
        await pilot.press('enter')
        assert widget.selection == '1'
        textarea = screen.query_one(TextArea)
        assert textarea.text == 'expression 1'


@patch.object(
    JQLEditorScreen,
    '_pre_defined_jql_expressions',
    PropertyMock(
        return_value={
            '1': {'label': 'Expression A', 'expression': 'expression 1'},
            '2': {'label': 'Expression B', 'expression': 'expression 2'},
        }
    ),
)
@pytest.mark.asyncio
async def test_apply_selected_expression_with_enter_closes_editor(app):
    # GIVEN
    async with app.run_test() as pilot:
        screen = JQLEditorScreen()
        screen.dismiss = Mock()
        await app.push_screen(screen)
        await pilot.pause()
        widget = screen.query_one(PreDefinedJQLExpressionsWidget)
        # WHEN selecting a predefined expression
        await pilot.press('enter')
        await pilot.press('down')
        await pilot.press('enter')
        assert widget.selection == '1'
        assert widget.value is not Select.NULL
        # THEN pressing enter again applies/closes the editor instead of reopening the dropdown
        await pilot.press('enter')
        assert widget.expanded is False
        assert screen.dismiss.call_args[0][0] == 'expression 1'


@pytest.fixture()
def saved_jql_file(tmp_path, monkeypatch):
    """Points the saved expressions at a file of the test, so that the file of the user is left alone."""

    path = tmp_path / 'saved_jql.yaml'
    monkeypatch.setattr('jiratui.utils.saved_jql.get_saved_jql_file', lambda: path)
    return path


@patch.object(JQLEditorScreen, '_pre_defined_jql_expressions', PropertyMock(return_value=None))
@pytest.mark.asyncio
async def test_saving_an_expression_adds_it_to_the_dropdown(app, saved_jql_file):
    async with app.run_test() as pilot:
        screen = JQLEditorScreen('project = SB')
        await app.push_screen(screen)
        await pilot.pause()
        # WHEN the expression is saved under a name
        screen.action_save_expression()
        await pilot.pause()
        app.screen.query_one(Input).value = 'My project'
        await pilot.press('enter')
        await pilot.pause()
        # THEN it is offered by the dropdown, marked as one that the app saved
        assert screen.saved_jql_expressions == {
            'my-project': {'label': 'My project', 'expression': 'project = SB'}
        }
        assert screen.options == [('★ My project', 'my-project')]
        # AND it is on disk, so the next session offers it too
        assert load_saved_expressions(saved_jql_file) == screen.saved_jql_expressions


@patch.object(JQLEditorScreen, '_pre_defined_jql_expressions', PropertyMock(return_value=None))
@pytest.mark.asyncio
async def test_an_empty_expression_is_not_saved(app, saved_jql_file):
    async with app.run_test() as pilot:
        screen = JQLEditorScreen('   ')
        await app.push_screen(screen)
        await pilot.pause()
        # WHEN
        screen.action_save_expression()
        await pilot.pause()
        # THEN the name is not even asked for
        assert isinstance(app.screen, JQLEditorScreen)
        assert screen.saved_jql_expressions == {}


@patch.object(
    JQLEditorScreen,
    '_pre_defined_jql_expressions',
    PropertyMock(return_value={1: {'label': 'Expression A', 'expression': 'expression 1'}}),
)
@pytest.mark.asyncio
async def test_saved_expressions_are_offered_next_to_the_ones_of_the_config_file(
    app, saved_jql_file
):
    save_expression('My project', 'project = SB', saved_jql_file)
    async with app.run_test() as pilot:
        screen = JQLEditorScreen('')
        await app.push_screen(screen)
        await pilot.pause()
        # THEN both are offered, and the saved one is marked
        assert screen.options == [('Expression A', 1), ('★ My project', 'my-project')]
        # WHEN a saved expression is selected
        screen.query_one(PreDefinedJQLExpressionsWidget).value = 'my-project'
        await pilot.pause()
        # THEN it is written into the editor
        assert screen.query_one(TextArea).text == 'project = SB'


@patch.object(JQLEditorScreen, '_pre_defined_jql_expressions', PropertyMock(return_value=None))
@pytest.mark.asyncio
async def test_deleting_a_saved_expression_removes_it(app, saved_jql_file):
    save_expression('My project', 'project = SB', saved_jql_file)
    async with app.run_test() as pilot:
        screen = JQLEditorScreen('')
        await app.push_screen(screen)
        await pilot.pause()
        screen.query_one(PreDefinedJQLExpressionsWidget).value = 'my-project'
        await pilot.pause()
        # WHEN
        screen.action_delete_expression()
        await pilot.pause()
        # THEN
        assert screen.saved_jql_expressions == {}
        assert screen.options == []
        assert load_saved_expressions(saved_jql_file) == {}


@patch.object(
    JQLEditorScreen,
    '_pre_defined_jql_expressions',
    PropertyMock(return_value={1: {'label': 'Expression A', 'expression': 'expression 1'}}),
)
@pytest.mark.asyncio
async def test_an_expression_of_the_config_file_is_not_deleted(app, saved_jql_file):
    # the configuration file belongs to the user; the app only owns the expressions it saved itself
    async with app.run_test() as pilot:
        screen = JQLEditorScreen('')
        await app.push_screen(screen)
        await pilot.pause()
        screen.query_one(PreDefinedJQLExpressionsWidget).value = 1
        await pilot.pause()
        # WHEN
        screen.action_delete_expression()
        await pilot.pause()
        # THEN
        assert screen.options == [('Expression A', 1)]


@patch.object(JQLEditorScreen, '_pre_defined_jql_expressions', PropertyMock(return_value=None))
@pytest.mark.asyncio
async def test_the_expression_is_written_with_the_external_editor(app, saved_jql_file):
    async with app.run_test() as pilot:
        screen = JQLEditorScreen('project = SB')
        await app.push_screen(screen)
        await pilot.pause()
        with patch(
            'jiratui.widgets.screens.jql.open_in_external_editor',
            return_value='project = SB AND type = Bug\n',
        ) as editor_mock:
            # WHEN
            screen.action_edit_in_editor()
            await pilot.pause()
        # THEN the expression is handed over with a suffix that the editor highlights by
        assert editor_mock.call_args.kwargs == {'suffix': '.jql'}
        assert editor_mock.call_args.args[1:] == ('vim', 'project = SB')
        assert screen.query_one(TextArea).text == 'project = SB AND type = Bug'


@patch.object(JQLEditorScreen, '_pre_defined_jql_expressions', PropertyMock(return_value=None))
@pytest.mark.asyncio
async def test_without_a_configured_editor_nothing_is_written(app, saved_jql_file):
    async with app.run_test() as pilot:
        screen = JQLEditorScreen('project = SB')
        await app.push_screen(screen)
        await pilot.pause()
        with (
            patch.object(CONFIGURATION.get(), 'text_editor', None),
            patch('jiratui.widgets.screens.jql.open_in_external_editor') as editor_mock,
        ):
            # WHEN
            screen.action_edit_in_editor()
            await pilot.pause()
        # THEN
        editor_mock.assert_not_called()
        assert screen.query_one(TextArea).text == 'project = SB'
