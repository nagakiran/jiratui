from unittest.mock import Mock

import pytest

from jiratui.models import IssueTransition, IssueTransitionState
from jiratui.widgets.commons.widgets import SelectionWidget, SingleUserPickerWidget
from jiratui.widgets.screens.transition import (
    TransitionScreen,
    create_widgets_for_transition,
    normalize_transition_fields,
)

DEV_COMPLETE_REASON_FIELD = {
    'customfield_10343': {
        'required': False,
        'schema': {
            'type': 'option',
            'custom': 'com.atlassian.jira.plugin.system.customfieldtypes:select',
            'customId': 10343,
        },
        'name': 'Dev Complete Reason',
        'key': 'customfield_10343',
        'operations': ['set'],
        'allowedValues': [
            {'value': 'Fixed', 'id': '11623'},
            {'value': "Won't Fix", 'id': '11624'},
            {'value': 'Invalid', 'id': '11625'},
            {'value': 'Duplicate', 'id': '11626'},
            {'value': 'Cannot Reproduce', 'id': '11627'},
        ],
    }
}

ASSIGNEE_FIELD = {
    'assignee': {
        'required': False,
        'schema': {'type': 'user', 'system': 'assignee'},
        'name': 'Assignee',
        'key': 'assignee',
        'operations': ['set'],
    }
}


def _transition(fields: dict, name: str = 'Dev Complete') -> IssueTransition:
    return IssueTransition(
        id='31',
        name=name,
        to_state=IssueTransitionState(id='10001', name=name),
        has_screen=True,
        fields=fields,
    )


def test_normalize_transition_fields_adds_the_field_id():
    # WHEN
    result = normalize_transition_fields(DEV_COMPLETE_REASON_FIELD)

    # THEN
    assert len(result) == 1
    assert result[0]['fieldId'] == 'customfield_10343'
    assert result[0]['name'] == 'Dev Complete Reason'


def test_normalize_transition_fields_without_fields():
    assert normalize_transition_fields({}) == []


def test_create_widgets_for_transition_builds_a_selection_widget(config_for_testing):
    # WHEN
    widgets = create_widgets_for_transition(DEV_COMPLETE_REASON_FIELD)

    # THEN
    assert len(widgets) == 1
    widget = widgets[0]
    assert isinstance(widget, SelectionWidget)
    assert widget.field_id == 'customfield_10343'
    assert widget.border_title == 'Dev Complete Reason'
    # the field is optional, so a blank option precedes the allowed values
    assert [option[0] for option in widget._options][1:] == [
        'Fixed',
        "Won't Fix",
        'Invalid',
        'Duplicate',
        'Cannot Reproduce',
    ]


def test_create_widgets_for_transition_builds_a_user_picker_for_a_system_user_field(
    config_for_testing,
):
    # WHEN
    widgets = create_widgets_for_transition(ASSIGNEE_FIELD)

    # THEN
    assert len(widgets) == 1
    assert isinstance(widgets[0], SingleUserPickerWidget)


@pytest.mark.asyncio
async def test_transition_screen_returns_the_selected_value(app):
    async with app.run_test() as pilot:
        # GIVEN
        screen = TransitionScreen('SB-23587', _transition(DEV_COMPLETE_REASON_FIELD))
        await app.push_screen(screen)
        await pilot.pause()

        # WHEN the user picks "Fixed" and saves
        selector = screen.fields_container.query_one(SelectionWidget)
        selector.value = '11623'
        screen.dismiss = Mock()
        screen.handle_save()

        # THEN
        assert screen.dismiss.call_args[0][0] == {'customfield_10343': {'id': '11623'}}


@pytest.mark.asyncio
async def test_transition_screen_focuses_the_first_field_so_its_dropdown_can_be_expanded(app):
    async with app.run_test() as pilot:
        # GIVEN
        screen = TransitionScreen('SB-23587', _transition(DEV_COMPLETE_REASON_FIELD))
        await app.push_screen(screen)
        await pilot.pause()

        # THEN the field has the focus; if the scrollable container takes it instead, the keys never reach the field
        selector = screen.fields_container.query_one(SelectionWidget)
        assert app.focused is selector
        assert screen.fields_container.can_focus is False

        # WHEN the user expands the dropdown
        await pilot.press('enter')
        await pilot.pause()

        # THEN
        assert selector.expanded is True


@pytest.mark.asyncio
async def test_transition_screen_without_a_value_returns_an_empty_payload(app):
    async with app.run_test() as pilot:
        # GIVEN
        screen = TransitionScreen('SB-23587', _transition(DEV_COMPLETE_REASON_FIELD))
        await app.push_screen(screen)
        await pilot.pause()

        # WHEN the user saves without selecting a value
        screen.dismiss = Mock()
        screen.handle_save()

        # THEN
        assert screen.dismiss.call_args[0][0] == {}


@pytest.mark.asyncio
async def test_transition_screen_cancelled_returns_none(app):
    async with app.run_test() as pilot:
        # GIVEN
        screen = TransitionScreen('SB-23587', _transition(DEV_COMPLETE_REASON_FIELD))
        await app.push_screen(screen)
        await pilot.pause()

        # WHEN
        screen.dismiss = Mock()
        screen.handle_cancel()

        # THEN the caller is told to not perform the transition
        assert screen.dismiss.call_args[0][0] is None
