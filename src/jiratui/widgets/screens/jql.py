from functools import partial
from typing import cast

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Select, TextArea

from jiratui.config import CONFIGURATION
from jiratui.utils.editor import open_in_external_editor
from jiratui.utils.saved_jql import delete_expression, load_saved_expressions, save_expression
from jiratui.widgets.commons.jql_autocomplete import JQLTextArea, JQLTextAreaAutoComplete

SAVED_EXPRESSION_PREFIX = '★ '
"""Marks the expressions saved from the app apart from the ones written in the configuration file.

Only the former can be deleted from the app: the configuration file belongs to the user.
"""


class NameJQLExpressionScreen(ModalScreen[str]):
    """A modal screen that asks for the name to save a JQL expression under."""

    BINDINGS = [('escape', 'app.pop_screen', 'Close')]

    def __init__(self, name: str | None = None):
        super().__init__()
        self._name = name or ''

    def compose(self) -> ComposeResult:
        name_field = Input(value=self._name, placeholder='Name this expression')
        name_field.border_title = 'Save Expression'
        yield name_field

    @on(Input.Submitted)
    def request_save(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)


class PreDefinedJQLExpressionsWidget(Select):
    """A custom [Select](#textual.widgets.Select) widget for selecting pre-defined JQL expressions loaded for the
    configuration file."""

    BINDINGS = [
        Binding('down,space,up', 'show_overlay', 'Show menu', show=False),
        Binding('enter', 'confirm_selection', 'Apply expression', show=False),
    ]

    def __init__(self, options: list):
        super().__init__(
            options=options,
            prompt='Pre-defined expressions',
            id='issue-search-predefined-jql-selector',
            type_to_search=True,
            compact=True,
            classes='dropdown',
        )
        self.border_title = 'Expression'

    def action_confirm_selection(self) -> None:
        if self.value is not Select.NULL:
            cast('JQLEditorScreen', self.screen).dismiss_with_current_text()
        else:
            self.action_show_overlay()


class JQLEditorScreen(ModalScreen[str]):
    """A screen that displays an editor for JQL expressions.

    **See Also**:
    - [Use Case: Filter-based search](#use-case-filter-based-search)
    """

    BINDINGS = [
        Binding('escape', 'app.pop_screen', 'Close'),
        # the binding takes precedence over the editor, which binds ctrl+e to "move to the end of the line"; the rich
        # text widgets of the app make the same trade-off, and the `end` key still moves to the end of the line
        Binding(
            'ctrl+e',
            'edit_in_editor',
            'Editor',
            show=True,
            key_display='^e',
            priority=True,
            tooltip='Writes the expression with the editor set in config.text_editor',
        ),
        Binding(
            'ctrl+s',
            'save_expression',
            'Save',
            show=True,
            key_display='^s',
            priority=True,
            tooltip='Saves the expression under a name, to pick it again later',
        ),
        Binding(
            'ctrl+d',
            'delete_expression',
            'Delete',
            show=True,
            key_display='^d',
            priority=True,
            tooltip='Deletes the selected saved expression',
        ),
    ]
    TITLE = 'JQL Expression Editor'

    def __init__(self, content: str | None = None):
        super().__init__()
        self.content = content or ''
        self.predefined_jql_expressions: dict | None = self._pre_defined_jql_expressions
        self.saved_jql_expressions: dict[str, dict[str, str]] = load_saved_expressions()

    @property
    def _pre_defined_jql_expressions(self) -> dict | None:
        if CONFIGURATION.get().pre_defined_jql_expressions:
            return CONFIGURATION.get().pre_defined_jql_expressions
        return None

    @property
    def expressions(self) -> list:
        if self.predefined_jql_expressions:
            return list(self.predefined_jql_expressions.items())
        return []

    @property
    def options(self) -> list[tuple[str, object]]:
        """The expressions offered by the dropdown: the ones from the configuration file, then the saved ones.

        The keys of the former are the ones that the user wrote in the configuration file, and the keys of the latter
        are slugs, so the two cannot collide.
        """

        options: list[tuple[str, object]] = [
            (item.get('label'), key) for key, item in self.expressions
        ]
        options.extend(
            (f'{SAVED_EXPRESSION_PREFIX}{item["label"]}', key)
            for key, item in sorted(self.saved_jql_expressions.items())
        )
        return options

    def compose(self) -> ComposeResult:
        with Vertical() as widget:
            widget.border_title = self.TITLE
            yield PreDefinedJQLExpressionsWidget(self.options)
            # `code_editor` is declared to return a `TextArea`, but it instantiates the class it is called on
            editor = cast(
                JQLTextArea,
                JQLTextArea.code_editor(
                    self.content,
                    language='sql',
                    id='jql-editor',
                    classes='jql-expression-editor',
                    show_line_numbers=False,
                    theme='css',
                ),
            )
            yield editor
            yield JQLTextAreaAutoComplete(
                target=editor,
                api_controller=cast('JiraApp', self.app).api,  # type:ignore[name-defined] # noqa: F821
            )
            yield Footer(show_command_palette=False, compact=True)

    @property
    def autocomplete(self) -> JQLTextAreaAutoComplete:
        return self.query_one(JQLTextAreaAutoComplete)

    @property
    def _autocomplete_is_open(self) -> bool:
        try:
            return bool(self.autocomplete.display)
        except NoMatches:
            return False

    def on_key(self, event: Key):
        if event.key == 'escape':
            if self._autocomplete_is_open:
                # the dropdown is open: escape closes the dropdown, not the editor
                return
            self.dismiss_with_current_text()

    @property
    def editor(self) -> TextArea:
        return self.query_one('#jql-editor', expect_type=TextArea)

    def action_edit_in_editor(self) -> None:
        """Writes the expression with the external editor set in the configuration.

        The expression is left as the editor wrote it, newlines included: the editor of this screen is multi-line, and
        the caller flattens the expression when the screen is dismissed.
        """

        editor: str | None = CONFIGURATION.get().text_editor
        if not editor:
            self.notify(
                'No text editor is configured. Check the setting [b]text_editor[/b].',
                severity='error',
                title=self.TITLE,
            )
            return
        textarea = self.editor
        # the suffix tells the editor which syntax highlighting to apply
        textarea.text = open_in_external_editor(
            self.app, editor, textarea.text, suffix='.jql'
        ).strip()
        textarea.focus()

    def dismiss_with_current_text(self) -> None:
        self.dismiss(self.query_one(TextArea).text.strip())

    @on(PreDefinedJQLExpressionsWidget.Changed)
    def select_pre_defined_expression(self, event: Select.Changed) -> None:
        if event.value is Select.NULL:
            return
        # the keys of the configuration file are the ones that the user wrote there; the keys of the saved
        # expressions are slugs, so the two cannot collide
        data = (self.predefined_jql_expressions or {}).get(event.value) or (
            self.saved_jql_expressions.get(str(event.value))
        )
        if data and (expression := data.get('expression')):
            self.editor.text = expression

    @property
    def expressions_selector(self) -> PreDefinedJQLExpressionsWidget:
        return self.query_one(PreDefinedJQLExpressionsWidget)

    def _refresh_options(self, selected: object = Select.NULL) -> None:
        """Rebuilds the dropdown so that a save or a delete shows without reopening the screen."""

        selector = self.expressions_selector
        selector.set_options(self.options)
        if selected is not Select.NULL:
            with selector.prevent(Select.Changed):
                selector.value = selected

    def action_save_expression(self) -> None:
        """Saves the expression under a name, so that it can be picked from the dropdown next time.

        The expressions saved this way live in a file that the app owns; the ones written in the configuration file
        are left alone.
        """

        if not (expression := self.editor.text.strip()):
            self.notify(
                'Write an expression before saving it.', title=self.TITLE, severity='warning'
            )
            return
        self.app.push_screen(
            NameJQLExpressionScreen(), callback=partial(self._save_expression_as, expression)
        )

    def _save_expression_as(self, expression: str, label: str | None) -> None:
        if not label or not (label := label.strip()):
            # the user dismissed the prompt without naming the expression
            return
        try:
            key = save_expression(label, expression)
        except OSError as e:
            self.notify(f'Unable to save the expression: {e}', title=self.TITLE, severity='error')
            return
        self.saved_jql_expressions = load_saved_expressions()
        self._refresh_options(selected=key)
        self.notify(f'Saved the expression as [b]{label}[/b].', title=self.TITLE)

    def action_delete_expression(self) -> None:
        """Deletes the selected expression, when it is one that the app saved."""

        key = self.expressions_selector.value
        if key is Select.NULL:
            self.notify(
                'Select a saved expression to delete.', title=self.TITLE, severity='warning'
            )
            return
        if key not in self.saved_jql_expressions:
            self.notify(
                'This expression comes from the configuration file; edit the file to remove it.',
                title=self.TITLE,
                severity='warning',
            )
            return
        label = self.saved_jql_expressions[key]['label']
        try:
            delete_expression(key)
        except OSError as e:
            self.notify(f'Unable to delete the expression: {e}', title=self.TITLE, severity='error')
            return
        self.saved_jql_expressions = load_saved_expressions()
        self._refresh_options()
        self.notify(f'Deleted the expression [b]{label}[/b].', title=self.TITLE)
