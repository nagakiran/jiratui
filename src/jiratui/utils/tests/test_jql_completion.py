from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from jiratui.api_controller.controller import APIControllerResponse
from jiratui.models import JQLAutocompleteData, JQLAutocompleteSuggestion, JQLFieldRef
from jiratui.utils.jql import JQLContext
from jiratui.utils.jql_completion import JQLReferenceCache, apply_choice, complete, needs_api

USER_TYPE = 'com.atlassian.jira.user.ApplicationUser'


@pytest.fixture
def cache(tmp_path) -> JQLReferenceCache:
    return JQLReferenceCache(
        base_url='https://foo.bar',
        fetched_at=datetime.now(UTC),
        fields=[
            JQLFieldRef(
                value='project', display_name='project', operators=['=', '!=', 'in'], orderable=True
            ),
            JQLFieldRef(
                value='status',
                display_name='status',
                operators=['=', 'in', 'not in'],
                orderable=True,
            ),
            JQLFieldRef(
                value='assignee', display_name='assignee', operators=['=', 'in'], types=[USER_TYPE]
            ),
            JQLFieldRef(
                value='"Dev Complete Reason"',
                display_name='Dev Complete Reason - cf[10050]',
                operators=['=', 'in'],
                cfid='cf[10050]',
            ),
        ],
        functions=[
            JQLFieldRef(value='currentUser()', types=[USER_TYPE]),
            JQLFieldRef(value='now()', types=['java.util.Date']),
        ],
        path=tmp_path / 'cache.json',
    )


def controller_with_values(*suggestions: JQLAutocompleteSuggestion) -> Mock:
    controller = Mock()
    controller.get_jql_autocomplete_suggestions = AsyncMock(
        return_value=APIControllerResponse(result=list(suggestions))
    )
    return controller


@pytest.mark.asyncio
async def test_complete_fields_by_name_or_display_name(cache):
    completion = await complete('dev', None, cache)
    assert [c.display for c in completion.candidates] == ['Dev Complete Reason']
    # the name is written the way an expression needs it
    assert completion.apply(completion.candidates[0]) == ('"Dev Complete Reason" ', 22)


@pytest.mark.asyncio
async def test_complete_fields_after_order_by_are_only_the_orderable_ones(cache):
    completion = await complete('project = SB order by ', None, cache)
    assert {c.display for c in completion.candidates} == {'project', 'status'}


@pytest.mark.asyncio
async def test_complete_operators_of_the_field(cache):
    completion = await complete('status ', None, cache)
    assert [c.display for c in completion.candidates] == ['=', 'in', 'not in']
    text, cursor = completion.apply(completion.candidates[1])
    assert (text, cursor) == ('status in ()', len('status in ('))


@pytest.mark.asyncio
async def test_complete_values_come_from_the_api_and_are_quoted(cache):
    controller = controller_with_values(
        JQLAutocompleteSuggestion(value='"In Progress"', display_name='In Progress')
    )
    completion = await complete('status = In', None, cache, controller)
    controller.get_jql_autocomplete_suggestions.assert_awaited_once_with(
        field_name='status', field_value='In'
    )
    assert completion.apply(completion.candidates[0])[0] == 'status = "In Progress"'


@pytest.mark.asyncio
async def test_complete_values_of_a_custom_field_are_asked_by_its_id(cache):
    controller = controller_with_values()
    await complete('"Dev Complete Reason" = ', None, cache, controller)
    controller.get_jql_autocomplete_suggestions.assert_awaited_once_with(
        field_name='cf[10050]', field_value=None
    )


@pytest.mark.asyncio
async def test_complete_values_record_aliases_and_add_the_matching_functions(cache):
    controller = controller_with_values(
        JQLAutocompleteSuggestion(value='5c01', display_name='Jane Doe - jane@x.com')
    )
    completion = await complete('assignee = ', None, cache, controller)
    assert [(c.display, c.kind) for c in completion.candidates] == [
        ('Jane Doe - jane@x.com', 'value'),
        ('currentUser()', 'function'),
    ]
    assert cache.alias_mapping() == {('assignee', 'Jane Doe - jane@x.com'): '5c01'}


@pytest.mark.asyncio
async def test_complete_keywords_after_a_clause(cache):
    completion = await complete('project = SB an', None, cache)
    assert completion.context.context is JQLContext.KEYWORD
    assert [c.display for c in completion.candidates] == ['and']
    assert completion.apply(completion.candidates[0]) == ('project = SB and ', 17)


def test_needs_api_only_for_values():
    assert needs_api('status = ', None)
    assert not needs_api('stat', None)
    assert not needs_api('status ', None)


@pytest.mark.parametrize(
    'text, choice, expected',
    [
        pytest.param('dev', 'Dev Complete Reason', '"Dev Complete Reason" ', id='field'),
        pytest.param('status ', 'not in', 'status not in ()', id='operator'),
        pytest.param('status = In', 'In Progress', 'status = "In Progress"', id='value'),
        pytest.param('assignee = ', 'currentUser()', 'assignee = currentUser()', id='function'),
        pytest.param('a = b o', 'order by', 'a = b order by ', id='keyword'),
    ],
)
def test_apply_choice_without_the_api(cache, text, choice, expected):
    assert apply_choice(text, None, choice, cache)[0] == expected


def test_cache_round_trip(cache):
    cache.add_alias('Assignee', 'Jane', '5c01')
    cache.save()
    loaded = JQLReferenceCache.load(cache.path, base_url='https://foo.bar')
    assert [f.value for f in loaded.fields] == [f.value for f in cache.fields]
    assert loaded.fields[3].cfid == 'cf[10050]'
    assert loaded.aliases == {'assignee': {'Jane': '5c01'}}
    assert not loaded.is_stale()


def test_cache_of_another_instance_is_discarded(cache):
    cache.save()
    loaded = JQLReferenceCache.load(cache.path, base_url='https://other')
    assert loaded.fields == [] and loaded.is_stale()


def test_cache_is_stale_after_its_ttl(cache):
    cache.fetched_at = datetime.now(UTC) - timedelta(days=2)
    assert cache.is_stale()


def test_cache_unreadable_file_is_empty(tmp_path):
    path = tmp_path / 'cache.json'
    path.write_text('{not json')
    assert JQLReferenceCache.load(path).fields == []


@pytest.mark.asyncio
async def test_cache_refresh(cache):
    controller = Mock()
    controller.get_jql_autocomplete_data = AsyncMock(
        return_value=APIControllerResponse(
            result=JQLAutocompleteData(visible_field_names=[JQLFieldRef(value='labels')])
        )
    )
    assert await cache.refresh(controller)
    assert [f.value for f in cache.fields] == ['labels']
