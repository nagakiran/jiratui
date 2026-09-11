from pathlib import Path

import pytest
import yaml

from jiratui.utils.saved_jql import (
    ROOT_KEY,
    delete_expression,
    load_saved_expressions,
    save_expression,
    slugify,
)


@pytest.fixture()
def saved_jql_file(tmp_path) -> Path:
    return tmp_path / 'saved_jql.yaml'


@pytest.mark.parametrize(
    'label, expected',
    [
        pytest.param('My unresolved bugs', 'my-unresolved-bugs', id='words'),
        pytest.param('  Spaced  out  ', 'spaced-out', id='trims-and-collapses'),
        pytest.param('SB: In Progress!', 'sb-in-progress', id='drops-punctuation'),
        pytest.param('***', 'expression', id='nothing-usable-is-left'),
    ],
)
def test_slugify(label, expected):
    assert slugify(label) == expected


def test_loading_a_file_that_does_not_exist_returns_no_expressions(saved_jql_file):
    # the file only exists once the user saves something; the editor has to open either way
    assert load_saved_expressions(saved_jql_file) == {}


def test_loading_a_malformed_file_returns_no_expressions(saved_jql_file):
    # a malformed pre_defined_jql_expressions used to crash the app; this file must never do that
    saved_jql_file.write_text('saved_jql_expressions: [oops\n', encoding='utf-8')
    assert load_saved_expressions(saved_jql_file) == {}


def test_loading_a_file_without_the_root_key_returns_no_expressions(saved_jql_file):
    saved_jql_file.write_text('something_else: 1\n', encoding='utf-8')
    assert load_saved_expressions(saved_jql_file) == {}


def test_an_entry_that_is_not_shaped_as_expected_is_dropped(saved_jql_file):
    saved_jql_file.write_text(
        yaml.safe_dump(
            {
                ROOT_KEY: {
                    'good': {'label': 'Good', 'expression': 'project = SB'},
                    'no-expression': {'label': 'Incomplete'},
                    'not-a-mapping': 'project = SB',
                }
            }
        ),
        encoding='utf-8',
    )
    assert load_saved_expressions(saved_jql_file) == {
        'good': {'label': 'Good', 'expression': 'project = SB'}
    }


def test_saving_an_expression_makes_it_readable_again(saved_jql_file):
    key = save_expression('My unresolved bugs', '  type = Bug  ', saved_jql_file)
    assert key == 'my-unresolved-bugs'
    assert load_saved_expressions(saved_jql_file) == {
        'my-unresolved-bugs': {'label': 'My unresolved bugs', 'expression': 'type = Bug'}
    }


def test_saving_under_a_label_that_is_taken_replaces_the_expression(saved_jql_file):
    # otherwise the user ends up with two entries of the same name and no way to tell them apart
    save_expression('My bugs', 'type = Bug', saved_jql_file)
    save_expression('My bugs', 'type = Bug AND assignee = currentUser()', saved_jql_file)
    assert load_saved_expressions(saved_jql_file) == {
        'my-bugs': {
            'label': 'My bugs',
            'expression': 'type = Bug AND assignee = currentUser()',
        }
    }


def test_saving_keeps_the_expressions_already_saved(saved_jql_file):
    save_expression('First', 'project = SB', saved_jql_file)
    save_expression('Second', 'project = AB', saved_jql_file)
    assert sorted(load_saved_expressions(saved_jql_file)) == ['first', 'second']


def test_deleting_an_expression_removes_only_that_one(saved_jql_file):
    save_expression('First', 'project = SB', saved_jql_file)
    save_expression('Second', 'project = AB', saved_jql_file)
    assert delete_expression('first', saved_jql_file) is True
    assert list(load_saved_expressions(saved_jql_file)) == ['second']


def test_deleting_an_expression_that_is_not_saved_does_nothing(saved_jql_file):
    save_expression('First', 'project = SB', saved_jql_file)
    assert delete_expression('unknown', saved_jql_file) is False
    assert list(load_saved_expressions(saved_jql_file)) == ['first']


def test_the_file_is_created_with_its_parent_directory(tmp_path):
    path = tmp_path / 'nested' / 'saved_jql.yaml'
    save_expression('First', 'project = SB', path)
    assert path.exists()


def test_a_failed_write_leaves_the_previous_file_intact(saved_jql_file, monkeypatch):
    # the content is moved into place, so a failure halfway through does not truncate what was already saved
    save_expression('First', 'project = SB', saved_jql_file)
    monkeypatch.setattr(
        'jiratui.utils.saved_jql.os.replace',
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError('disk is full')),
    )
    with pytest.raises(OSError):
        save_expression('Second', 'project = AB', saved_jql_file)
    assert list(load_saved_expressions(saved_jql_file)) == ['first']
    # and the temporary file it wrote is not left behind
    assert [path.name for path in saved_jql_file.parent.iterdir()] == ['saved_jql.yaml']
