from typing import cast

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Select, TextArea

from jiratui.config import CONFIGURATION
from jiratui.widgets.commons.jql_autocomplete import JQLTextArea, JQLTextAreaAutoComplete


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

    BINDINGS = [('escape', 'app.pop_screen', 'Close')]
    TITLE = 'JQL Expression Editor'

    def __init__(self, content: str | None = None):
        super().__init__()
        self.content = content or ''
        self.predefined_jql_expressions: dict | None = self._pre_defined_jql_expressions

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

    def compose(self) -> ComposeResult:
        with Vertical() as widget:
            widget.border_title = self.TITLE
            yield PreDefinedJQLExpressionsWidget(
                [(item.get('label'), key) for key, item in self.expressions]
            )
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

    def dismiss_with_current_text(self) -> None:
        self.dismiss(self.query_one(TextArea).text.strip())

    @on(PreDefinedJQLExpressionsWidget.Changed)
    def select_pre_defined_expression(self, event: Select.Changed) -> None:
        if event.value != Select.NULL:
            if (data := self.predefined_jql_expressions.get(event.value)) and (
                expression := data.get('expression')
            ):
                self.query_one(TextArea).text = expression
