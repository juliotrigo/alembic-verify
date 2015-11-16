# -*- coding: utf-8 -*-
import json
import os
import unittest

from alembic import command
from sqlalchemydiff import compare
from sqlalchemydiff.util import (
    destroy_database,
    get_temporary_uri,
    new_db,
    prepare_schema_from_models,
    walk_dict,
)

from alembicverify.util import (
    get_current_revision,
    get_head_revision,
    make_alembic_config,
    prepare_schema_from_migrations,
)
from test import assert_items_equal
from .models import Base


alembic_root = os.path.join(os.path.dirname(__file__), 'migrations', 'alembic')


class TestExample(unittest.TestCase):

    def setUp(self):
        uri = "mysql+mysqlconnector://root:@localhost/alembicverify"

        self.uri_left = get_temporary_uri(uri)
        self.uri_right = get_temporary_uri(uri)

        self.alembic_config_left = make_alembic_config(
            self.uri_left, alembic_root)
        self.alembic_config_right = make_alembic_config(
            self.uri_right, alembic_root)

        new_db(self.uri_left)
        new_db(self.uri_right)

    def tearDown(self):
        destroy_database(self.uri_left)
        destroy_database(self.uri_right)

    def test_upgrade_and_downgrade(self):
        """Test all migrations up and down.

        Tests that we can apply all migrations from a brand new empty
        database, and also that we can remove them all.
        """
        engine, script = prepare_schema_from_migrations(
            self.uri_left, self.alembic_config_left)

        head = get_head_revision(self.alembic_config_left, engine, script)
        current = get_current_revision(
            self.alembic_config_left, engine, script)

        assert head == current

        while current is not None:
            command.downgrade(self.alembic_config_left, '-1')
            current = get_current_revision(
                self.alembic_config_left, engine, script)

    def test_same_schema_is_the_same(self):
        """Compare two databases both from migrations.

        Makes sure the schema comparer validates a database to an exact
        replica of itself.
        """
        prepare_schema_from_migrations(
            self.uri_left, self.alembic_config_left)
        prepare_schema_from_migrations(
            self.uri_right, self.alembic_config_right)

        result = compare(
            self.uri_left, self.uri_right, set(['alembic_version']))

        assert result.is_match

    def test_model_and_migration_schemas_are_the_same(self):
        """Compare two databases.

        Compares the database obtained with all migrations against the
        one we get out of the models.  It produces a text file with the
        results to help debug differences.
        """
        prepare_schema_from_migrations(self.uri_left, self.alembic_config_left)
        prepare_schema_from_models(self.uri_right, Base)

        result = compare(
            self.uri_left, self.uri_right, set(['alembic_version']))

        assert result.is_match

    def test_model_and_migration_schemas_are_not_the_same(self):
        """Compares the database obtained with the first migration against
        the one we get out of the models.  It produces a text file with the
        results to help debug differences.
        """
        prepare_schema_from_migrations(
            self.uri_left, self.alembic_config_left, revision="+1")
        prepare_schema_from_models(self.uri_right, Base)

        result = compare(
            self.uri_left, self.uri_right, set(['alembic_version']))

        errors = {
            'tables': {
                'left_only': ['addresses'],
                'right_only': ['roles']
            },
            'tables_data': {
                'employees': {
                    'columns': {
                        'left_only': [
                            {
                                'default': None,
                                'name': 'favourite_meal',
                                'nullable': False,
                                'type': "ENUM('meat','vegan','vegetarian')"
                            }
                        ],
                        'right_only': [
                            {
                                'autoincrement': False,
                                'default': None,
                                'name': 'role_id',
                                'nullable': False,
                                'type': 'INTEGER(11)'
                            },
                            {
                                'autoincrement': False,
                                'default': None,
                                'name': 'number_of_pets',
                                'nullable': False,
                                'type': 'INTEGER(11)'
                            },
                        ]
                    },
                    'foreign_keys': {
                        'right_only': [
                            {
                                'constrained_columns': ['role_id'],
                                'name': 'fk_employees_roles',
                                'options': {},
                                'referred_columns': ['id'],
                                'referred_schema': None,
                                'referred_table': 'roles'
                            }
                        ]
                    },
                    'indexes': {
                        'left_only': [
                            {
                                'column_names': ['name'],
                                'name': 'name',
                                'type': 'UNIQUE',
                                'unique': True
                            }
                        ],
                        'right_only': [
                            {
                                'column_names': ['role_id'],
                                'name': 'fk_employees_roles',
                                'unique': False
                            },
                            {
                                'column_names': ['name'],
                                'name': 'ix_employees_name',
                                'type': 'UNIQUE',
                                'unique': True
                            }
                        ]
                    }
                },
                'phone_numbers': {
                    'columns': {
                        'diff': [
                            {
                                'key': 'number',
                                'left': {
                                    'default': None,
                                    'name': 'number',
                                    'nullable': True,
                                    'type': 'VARCHAR(40)'
                                },
                                'right': {
                                    'default': None,
                                    'name': 'number',
                                    'nullable': False,
                                    'type': 'VARCHAR(40)'
                                }
                            }
                        ]
                    }
                }
            },
            'uris': {
                'left': self.uri_left,
                'right': self.uri_right,
            }
        }

        self.compare_error_dicts(errors, result.errors)

    def compare_error_dicts(self, err1, err2):
        """Smart comparer of error dicts.

        We cannot directly compare a nested dict structure that has lists
        as values on some level. The order of the same list in the two dicts
        could be different, which would lead to a failure in the comparison,
        but it would be wrong as for us the order doesn't matter and we need
        a comparison that only checks that the same items are in the lists.
        In order to do this, we use the walk_dict function to perform a
        smart comparison only on the lists.

        This function compares the ``tables`` and ``uris`` items, then it does
        an order-insensitive comparison of all lists, and finally it compares
        that the sorted JSON dump of both dicts is the same.
        """
        assert err1['tables'] == err2['tables']
        assert err1['uris'] == err2['uris']

        paths = [
            ['tables_data', 'employees', 'columns', 'left_only'],
            ['tables_data', 'employees', 'columns', 'right_only'],
            ['tables_data', 'employees', 'indexes', 'left_only'],
            ['tables_data', 'employees', 'indexes', 'right_only'],
            ['tables_data', 'employees', 'foreign_keys', 'right_only'],

            ['tables_data', 'phone_numbers', 'columns', 'diff'],
        ]

        for path in paths:
            assert_items_equal(walk_dict(err1, path), walk_dict(err2, path))

        assert sorted(json.dumps(err1)) == sorted(json.dumps(err2))