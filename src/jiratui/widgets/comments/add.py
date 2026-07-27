from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import ItemGrid, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Static, TextArea

from jiratui.config import CONFIGURATION
from jiratui.utils.editor import open_in_external_editor


class AddCommentScreen(Screen[str]):
    """A modal screen that allows users to add a comment to a work item.

    The screen does not add the comment to the work item. Instead, it returns the comment's text to the caller via the
    `dismiss()` call and the caller will proceed to add the comment via the API.

    **See Also**:
    - [Add Comment Screen Design](#components-add-comment-screen)
    - [Use Case: Add Comment](#use-case-add-comment)
    - [Architecture](#architecture-work-item-comments-classes)
    """

    BINDINGS = [
        Binding('escape', 'app.pop_screen', 'Close', show=True),
        # the binding takes precedence over the textarea, which binds ctrl+e to "move to the end of the line"; the
        # rich text widgets of the app make the same trade-off, and the `end` key still moves to the end of the line
        Binding(
            'ctrl+e',
            'edit_in_editor',
            'Editor',
            show=True,
            key_display='^e',
            priority=True,
            tooltip='Writes the comment with the editor set in config.text_editor',
        ),
    ]

    def __init__(self, work_item_key: str | None = None):
        super().__init__()
        self.__work_item_key = work_item_key
        self.title = f'Add comment to the work item {self.__work_item_key}'

    @property
    def comment_textarea(self) -> TextArea:
        return self.query_one(TextArea)

    @property
    def save_button(self) -> Button:
        return self.query_one('#add-comment-button-save', expect_type=Button)

    def compose(self) -> ComposeResult:
        vertical = Vertical()
        vertical.border_title = self.title
        with vertical:
            yield Static(
                Text(
                    'Tip: tab works as indentation control. Use Escape or shift+tab to focus/unfocus elements in the '
                    'screen. Press ^e to write the comment with your editor.'
                ),
                classes='tip',
            )
            textarea = TextArea.code_editor(
                '', language='markdown', show_line_numbers=False, compact=True
            )
            textarea.border_title = 'Comment'
            textarea.border_subtitle = 'Markdown Enabled'
            yield textarea
            with ItemGrid(classes='add-comment-grid-buttons'):
                yield Button('Save', variant='success', id='add-comment-button-save', disabled=True)
                yield Button('Cancel', variant='error', id='add-comment-button-quit')
        yield Footer(show_command_palette=False, compact=True)

    def action_edit_in_editor(self) -> None:
        """Writes the comment with the external editor set in the configuration.

        The text left by the editor replaces the content of the textarea. An empty result leaves the Save button
        disabled, which is what happens when the user quits the editor without writing anything.
        """

        editor: str | None = CONFIGURATION.get().text_editor
        if not editor:
            self.notify(
                'No text editor is configured. Check the setting [b]text_editor[/b].',
                severity='error',
                title='Add Comment',
            )
            return
        textarea = self.comment_textarea
        # setting the text posts a TextArea.Changed message, which updates the state of the Save button
        textarea.text = open_in_external_editor(self.app, editor, textarea.text).strip()
        textarea.focus()

    @on(TextArea.Changed, 'TextArea')
    def validate_comment(self):
        value = self.comment_textarea.text
        self.save_button.disabled = False if (value and value.strip()) else True

    @on(Button.Pressed, '#add-comment-button-save')
    def handle_save(self) -> None:
        self.dismiss(self.comment_textarea.text.strip() or '')

    @on(Button.Pressed, '#add-comment-button-quit')
    def handle_cancel(self) -> None:
        self.dismiss('')
