# -*- coding: utf-8 -*-
#
# Copyright (C) 2013 Steffen Hoffmann <hoff.st@web.de>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#
# Author: Steffen Hoffmann

import shutil
import tempfile
import unittest

from trac.db import Table, Column, Index
from trac.db.api import DatabaseManager, get_column_names
from trac.perm import PermissionCache, PermissionSystem
from trac.test import EnvironmentStub, Mock
from trac.ticket.model import Ticket
from trac.web.chrome import Chrome
from trac.wiki.model import WikiPage

from tracvote import VoteSystem, resource_check


_ACTIONS = dict(view='VOTE_VIEW', modify='VOTE_MODIFY')


class EnvironmentSetupTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(enable=['trac.*'])
        self.env.path = tempfile.mkdtemp()
        self.db_mgr = DatabaseManager(self.env)
        self.votes = VoteSystem(self.env)

    def tearDown(self):
        # Really close db connections.
        self.env.shutdown()
        shutil.rmtree(self.env.path)

    # Helpers

    def _schema_init(self, schema=None):
        with self.env.db_transaction as db:
            db("DROP TABLE IF EXISTS votes")
            if schema:
                connector = self.db_mgr._get_connector()[0]
                for table in schema:
                    for stmt in connector.to_sql(table):
                        db(stmt)

    def _verify_curr_schema(self):
        self.assertFalse(self.votes.environment_needs_upgrade())
        with self.env.db_query as db:
            cursor = db.cursor()
            cursor.execute('SELECT * FROM votes')
            cols = get_column_names(cursor)
            self.assertTrue('resource' not in cols)
            self.assertEquals(['realm', 'resource_id', 'version', 'username',
                               'vote', 'time', 'changetime'], cols)
            for ver, in db("""
                    SELECT value
                      FROM system
                     WHERE name='vote_version'
                    """):
                schema_ver = int(ver)
            self.assertEquals(self.votes.schema_version, schema_ver)

    def _verify_schema_unregistered(self):
        for ver, in self.env.db_query("""
                    SELECT value
                      FROM system
                     WHERE name='vote_version'
                """):
            self.assertFalse(ver)

    # Tests

    def test_new_install(self):
        # Current tracvotes schema is setup with enabled component anyway.
        #   Revert these changes for clean install testing.
        self._schema_init()

        self.assertEquals(0, self.votes.get_schema_version())
        self.assertTrue(self.votes.environment_needs_upgrade())

        self.votes.upgrade_environment()
        self._verify_curr_schema()

    def test_upgrade_v1_to_current(self):
        # The initial db schema from r2963 - 02-Jan-2008 by Alec Thomas.
        schema = [
            Table('votes', key=('resource', 'username', 'vote'))[
                Column('resource'),
                Column('username'),
                Column('vote', 'int'),
                ]
            ]
        self._schema_init(schema)

        # Populate tables with test data.
        with self.env.db_query as db:
            cursor = db.cursor()
            cursor.executemany("""
                INSERT INTO votes
                       (resource,username,vote)
                VALUES (%s,%s,%s)
            """, (('ticket/1','user',-1), ('ticket/2','user',1),
                  ('wiki/DeletedPage','user',-1), ('wiki/ExistingPage','user',1)))
            # Resources must exist for successful data migration.
            t = Ticket(self.env)
            t['summary'] = 'test ticket'
            t.insert()
            w = WikiPage(self.env, 'ExistingPage')
            w.text = 'content'
            w.save('author', 'comment', '::1')
            self._verify_schema_unregistered()
            self.assertEquals(1, self.votes.get_schema_version())
            self.assertTrue(self.votes.environment_needs_upgrade())

            # Data migration and registration of unversioned schema.
            self.votes.upgrade_environment()
            self._verify_curr_schema()

            t_votes = []
            w_votes = []
            for realm, id, ver, u, v, t, c in db('SELECT * FROM votes'):
                if realm == 'ticket':
                    t_votes.append(id)
                elif realm == 'wiki':
                    w_votes.append(id)
            self.assertTrue('1' in t_votes)
            if resource_check:
                self.assertFalse('2' in t_votes)
                self.assertFalse('DeletedPage' in w_votes)
            self.assertTrue('ExistingPage' in w_votes)


class VoteSystemTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(default_data=True,
                                   enable=['trac.*', 'tracvote.*'])
        # OK, this is a quick hack... I didn't have time to investigate
        # why I got ''Cannot find implementation(s) of the `IPermissionPolicy`
        # interface named `ReadonlyWikiPolicy`.''
        self.env.config.set('trac', 'permission_policies',
                            ', '.join(
                ['DefaultPermissionPolicy',
                 'LegacyAttachmentPolicy']))
        self.env.path = tempfile.mkdtemp()
        self.perm = PermissionSystem(self.env)
        self.req = Mock()

        self.votes = VoteSystem(self.env)
        # Current tracvotes schema is setup with enabled component anyway.
        #   Revert these changes for getting default permissions inserted.
        self._revert_schema_init()
        self.votes.upgrade_environment()

    def tearDown(self):
        # Really close db connections.
        self.env.shutdown()
        shutil.rmtree(self.env.path)

    # Helpers

    def _revert_schema_init(self):
        with self.env.db_transaction as db:
            db("DROP TABLE IF EXISTS votes")
            db("DELETE FROM system WHERE name='vote_version'")
            db("DELETE FROM permission WHERE action %s" % db.like(),
               ('VOTE_%',))

    # Tests

    def test_available_actions_no_perms(self):
        self.assertTrue(_ACTIONS['view'] in PermissionCache(self.env))
        self.assertFalse(_ACTIONS['modify'] in PermissionCache(self.env))

    def test_available_actions_full_perms(self):
        perm_map = dict(voter='VOTE_MODIFY', admin='TRAC_ADMIN')
        for user in perm_map:
            self.perm.grant_permission(user, perm_map[user])
            for action in _ACTIONS.values():
                self.assertTrue(action in PermissionCache(self.env,
                                                          username=user))

    def test_resource_provider(self):
        self.assertTrue(self.votes in Chrome(self.env).template_providers)


def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(EnvironmentSetupTestCase))
    suite.addTest(unittest.makeSuite(VoteSystemTestCase))
    return suite

if __name__ == '__main__':
    unittest.main(defaultTest='suite')
