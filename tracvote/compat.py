# -*- coding: utf-8 -*-
#
# Copyright (C) 2012 Rob Guttman <guttman@alum.mit.edu>
# Copyright (C) 2015 Ryan J Ollos <ryan.j.ollos@gmail.com>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

# Methods backported from Trac 1.2

from trac.core import TracError
from trac.db.api import DatabaseManager
from trac.db.schema import Table
from trac.util.translation import _


if not hasattr(DatabaseManager, 'drop_tables'):
    def drop_tables(self, schema):
        """Drop the specified tables.

        :param schema: an iterable of `Table` objects or table names.

        :since: version 1.0.2
        """
        with self.env.db_transaction as db:
            for table in schema:
                table_name = table.name if isinstance(table, Table) else table
                db.drop_table(table_name)
    DatabaseManager.drop_tables = drop_tables


if not hasattr(DatabaseManager, 'insert_into_tables'):
    def insert_into_tables(self, data_or_callable):
        """Insert data into existing tables.

        :param data_or_callable: Nested tuples of table names, column names
                                 and row data:
                                 (table1,
                                  (column1, column2),
                                  ((row1col1, row1col2), (row2col1, row2col2)),
                                  table2, ...)
                                or a callable that takes a single parameter
                                `db` and returns the aforementioned nested
                                tuple.
        :since: version 1.1.3
        """
        with self.env.db_transaction as db:
            data = data_or_callable(db) if callable(data_or_callable) \
                                        else data_or_callable
            for table, cols, vals in data:
                db.executemany("INSERT INTO %s (%s) VALUES (%s)"
                               % (table, ','.join(cols),
                                  ','.join(['%s'] * len(cols))), vals)
    DatabaseManager.insert_into_tables = insert_into_tables


if not hasattr(DatabaseManager, 'create_tables'):
    def create_tables(self, schema):
        """Create the specified tables.

        :param schema: an iterable of table objects.

        :since: version 1.0.2
        """
        connector = self.get_connector()[0]
        with self.env.db_transaction as db:
            for table in schema:
                for sql in connector.to_sql(table):
                    db(sql)
    DatabaseManager.create_tables = create_tables


if not hasattr(DatabaseManager, 'get_database_version'):
    def get_database_version(self, name='database_version'):
        """Returns the database version from the SYSTEM table as an int,
        or `False` if the entry is not found.

        :param name: The name of the entry that contains the database version
                     in the SYSTEM table. Defaults to `database_version`,
                     which contains the database version for Trac.
        """
        rows = self.env.db_query("""
                SELECT value FROM system WHERE name=%s
                """, (name,))
        return int(rows[0][0]) if rows else False
    DatabaseManager.get_database_version = get_database_version


if not hasattr(DatabaseManager, 'set_database_version'):
    def set_database_version(self, version, name='database_version'):
        """Sets the database version in the SYSTEM table.

        :param version: an integer database version.
        :param name: The name of the entry that contains the database version
                     in the SYSTEM table. Defaults to `database_version`,
                     which contains the database version for Trac.
        """
        current_database_version = self.get_database_version(name)
        if current_database_version is False:
            self.env.db_transaction("""
                    INSERT INTO system (name, value) VALUES (%s, %s)
                    """, (name, version))
        else:
            self.env.db_transaction("""
                    UPDATE system SET value=%s WHERE name=%s
                    """, (version, name))
            self.log.info("Upgraded %s from %d to %d",
                          name, current_database_version, version)
    DatabaseManager.set_database_version = set_database_version


if not hasattr(DatabaseManager, 'get_table_names'):
    def get_table_names(self):
        dburi = self.config.get('trac', 'database')
        if dburi.startswith('sqlite:'):
            query = "SELECT name FROM sqlite_master" \
                    " WHERE type='table' AND NOT name='sqlite_sequence'"
        elif dburi.startswith('postgres:'):
            query = "SELECT tablename FROM pg_tables" \
                    " WHERE schemaname = ANY (current_schemas(false))"
        elif dburi.startswith('mysql:'):
            query = "SHOW TABLES"
        else:
            raise TracError('Unsupported %s database' % dburi.split(':')[0])
        return sorted(row[0] for row in self.env.db_transaction(query))
    DatabaseManager.get_table_names = get_table_names


if not hasattr(DatabaseManager, 'needs_upgrade'):
    def needs_upgrade(self, version, name='database_version'):
        """Checks the database version to determine if an upgrade is needed.

        :param version: the expected integer database version.
        :param name: the name of the entry in the SYSTEM table that contains
                     the database version. Defaults to `database_version`,
                     which contains the database version for Trac.

        :return: `True` if the stored version is less than the expected
                  version, `False` if it is equal to the expected version.
        :raises TracError: if the stored version is greater than the expected
                           version.
        """
        dbver = self.get_database_version(name)
        if dbver == version:
            return False
        elif dbver > version:
            raise TracError(_("Need to downgrade %(name)s.", name=name))
        self.log.info("Need to upgrade %s from %d to %d",
                      name, dbver, version)
        return True
    DatabaseManager.needs_upgrade = needs_upgrade


if not hasattr(DatabaseManager, 'upgrade'):
    def upgrade(self, version, name='database_version', pkg=None):
        """Invokes `do_upgrade(env, version, cursor)` in module
        `"%s/db%i.py" % (pkg, version)`, for each required version upgrade.

        :param version: the expected integer database version.
        :param name: the name of the entry in the SYSTEM table that contains
                     the database version. Defaults to `database_version`,
                     which contains the database version for Trac.
        :param pkg: the package containing the upgrade modules.

        :raises TracError: if the package or module doesn't exist.
        """
        dbver = self.get_database_version(name)
        for i in range(dbver + 1, version + 1):
            module = 'db%i' % i
            try:
                upgrades = __import__(pkg, globals(), locals(), [module])
            except ImportError:
                raise TracError(_("No upgrade package %(pkg)s", pkg=pkg))
            try:
                script = getattr(upgrades, module)
            except AttributeError:
                raise TracError(_("No upgrade module %(module)s.py",
                                  module=module))
            with self.env.db_transaction as db:
                cursor = db.cursor()
                script.do_upgrade(self.env, i, cursor)
                self.set_database_version(i, name)
    DatabaseManager.upgrade = upgrade
