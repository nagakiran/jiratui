from unittest.mock import Mock, patch

import pytest

from jiratui.utils.history import HistoryEntry, HistoryManager
from jiratui.widgets.screens.history import HistoryScreen, HistoryWorkItemsTable


@pytest.mark.asyncio
async def test_history_screen(app):
    # GIVEN
    manager = HistoryManager()
    manager.add_work_item(
        HistoryEntry(key='key-1', item_type='task', status='completed', summary='summary 1')
    )
    async with app.run_test():
        # WHEN
        screen = HistoryScreen(manager)
        await app.push_screen(screen)
        table = screen.query_one(HistoryWorkItemsTable)
        # THEN
        assert table.row_count == 1


@pytest.mark.asyncio
async def test_history_screen_focuses_the_table(app):
    # GIVEN
    manager = HistoryManager()
    manager.add_work_item(
        HistoryEntry(key='key-1', item_type='task', status='completed', summary='summary 1')
    )
    async with app.run_test():
        # WHEN
        screen = HistoryScreen(manager)
        await app.push_screen(screen)
        # THEN: the arrow keys, `enter` and the key bindings of the table work without focusing it first
        assert app.focused is screen.query_one(HistoryWorkItemsTable)


@pytest.mark.asyncio
async def test_history_screen_empty_history(app):
    # GIVEN
    manager = HistoryManager()
    manager.add_work_item(
        HistoryEntry(key='key-1', item_type='task', status='completed', summary='summary 1')
    )
    async with app.run_test() as pilot:
        # WHEN
        screen = HistoryScreen(manager)
        await app.push_screen(screen)
        table = screen.query_one(HistoryWorkItemsTable)
        assert table.row_count == 1
        await pilot.press('d')
        # THEN
        table = screen.query_one(HistoryWorkItemsTable)
        assert table.row_count == 0


@pytest.mark.asyncio
async def test_history_screen_copy_key(app):
    # GIVEN
    manager = HistoryManager()
    manager.add_work_item(
        HistoryEntry(key='key-1', item_type='task', status='completed', summary='summary 1')
    )
    async with app.run_test() as pilot:
        app.copy_to_clipboard = Mock()
        # WHEN
        screen = HistoryScreen(manager)
        await app.push_screen(screen)
        await pilot.press('ctrl+k')
        # THEN
        app.copy_to_clipboard.assert_called_once_with('key-1')


@pytest.mark.asyncio
async def test_history_screen_copy_key_with_an_empty_history(app):
    # GIVEN
    # an empty history leaves the table without rows, so no item is highlighted
    manager = HistoryManager()
    async with app.run_test() as pilot:
        app.copy_to_clipboard = Mock()
        # WHEN
        screen = HistoryScreen(manager)
        await app.push_screen(screen)
        await pilot.press('ctrl+k')
        # THEN
        app.copy_to_clipboard.assert_not_called()


@pytest.mark.asyncio
async def test_history_screen_copy_key_and_summary(app):
    # GIVEN
    manager = HistoryManager()
    manager.add_work_item(
        HistoryEntry(key='key-1', item_type='task', status='completed', summary='summary 1')
    )
    async with app.run_test() as pilot:
        app.copy_to_clipboard = Mock()
        # WHEN
        screen = HistoryScreen(manager)
        await app.push_screen(screen)
        await pilot.press('ctrl+t')
        # THEN
        app.copy_to_clipboard.assert_called_once_with('key-1 - summary 1')


@pytest.mark.asyncio
async def test_history_screen_copy_key_and_summary_untruncated(app):
    # GIVEN: a summary longer than the width of the column that displays it
    summary = 'a' * 100
    manager = HistoryManager()
    manager.add_work_item(
        HistoryEntry(key='key-1', item_type='task', status='completed', summary=summary)
    )
    async with app.run_test() as pilot:
        app.copy_to_clipboard = Mock()
        # WHEN
        screen = HistoryScreen(manager)
        await app.push_screen(screen)
        await pilot.press('ctrl+t')
        # THEN: the full summary is copied, not the truncated one displayed in the row
        app.copy_to_clipboard.assert_called_once_with(f'key-1 - {summary}')


@pytest.mark.asyncio
async def test_history_screen_copy_key_and_summary_with_an_empty_history(app):
    # GIVEN
    # an empty history leaves the table without rows, so no item is highlighted
    manager = HistoryManager()
    async with app.run_test() as pilot:
        app.copy_to_clipboard = Mock()
        # WHEN
        screen = HistoryScreen(manager)
        await app.push_screen(screen)
        await pilot.press('ctrl+t')
        # THEN
        app.copy_to_clipboard.assert_not_called()


@patch('jiratui.widgets.screens.history.build_external_url_for_issue')
@pytest.mark.asyncio
async def test_history_screen_copy_url(build_external_url_for_issue_mock: Mock, app):
    # GIVEN
    manager = HistoryManager()
    manager.add_work_item(
        HistoryEntry(key='key-1', item_type='task', status='completed', summary='summary 1')
    )
    build_external_url_for_issue_mock.return_value = 'http://foo.bar/key-1'
    async with app.run_test() as pilot:
        app.copy_to_clipboard = Mock()
        # WHEN
        screen = HistoryScreen(manager)
        await app.push_screen(screen)
        await pilot.press('ctrl+j')
        # THEN
        app.copy_to_clipboard.assert_called_once_with('http://foo.bar/key-1')


@pytest.mark.asyncio
async def test_history_screen_copy_url_with_an_empty_history(app):
    # GIVEN
    # an empty history leaves the table without rows, so no item is highlighted
    manager = HistoryManager()
    async with app.run_test() as pilot:
        app.copy_to_clipboard = Mock()
        # WHEN
        screen = HistoryScreen(manager)
        await app.push_screen(screen)
        await pilot.press('ctrl+j')
        # THEN
        app.copy_to_clipboard.assert_not_called()


@patch('jiratui.widgets.screens.history.build_external_url_for_issue')
@pytest.mark.asyncio
async def test_history_screen_open_url(build_external_url_for_issue_mock: Mock, app):
    # GIVEN
    manager = HistoryManager()
    manager.add_work_item(
        HistoryEntry(key='key-1', item_type='task', status='completed', summary='summary 1')
    )
    build_external_url_for_issue_mock.return_value = 'http://foo.bar/key-1'
    async with app.run_test() as pilot:
        app.open_url = Mock()
        # WHEN
        screen = HistoryScreen(manager)
        await app.push_screen(screen)
        await pilot.press('ctrl+o')
        # THEN
        app.open_url.assert_called_once_with('http://foo.bar/key-1')


@pytest.mark.asyncio
async def test_history_screen_open_url_with_an_empty_history(app):
    # GIVEN
    # an empty history leaves the table without rows, so no item is highlighted
    manager = HistoryManager()
    async with app.run_test() as pilot:
        app.open_url = Mock()
        # WHEN
        screen = HistoryScreen(manager)
        await app.push_screen(screen)
        await pilot.press('ctrl+o')
        # THEN
        app.open_url.assert_not_called()


@pytest.mark.asyncio
async def test_history_screen_select_item_row(app):
    # GIVEN
    manager = HistoryManager()
    manager.add_work_item(
        HistoryEntry(key='key-1', item_type='task', status='completed', summary='summary 1')
    )
    async with app.run_test() as pilot:
        # WHEN
        screen = HistoryScreen(manager)
        screen.dismiss = Mock()
        await app.push_screen(screen)
        await pilot.press('enter')
        # THEN
        assert screen.dismiss.call_args[0][0] == 'key-1'
