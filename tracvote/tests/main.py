# -*- coding: utf-8 -*-
#
# Copyright (C) 2010-2015 Ryan J Ollos <ryan.j.ollos@gmail.com>
# Copyright (C) 2013 Steffen Hoffmann <hoff.st@web.de>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.

import shutil
import tempfile
import unittest

from trac.db import Table, Column, Index
from trac.db.api import DatabaseManager, get_column_names
from trac.perm import PermissionCache, PermissionSystem
from trac.resource import Resource
from trac.test import EnvironmentStub, Mock, locale_en
from trac.ticket.model import Ticket
from trac.ticket.web_ui import TicketModule
from trac.util.datefmt import utc
from trac.web.api import HTTPForbidden, HTTPInternalError, RequestDone
from trac.web.chrome import Chrome
from trac.web.main import RequestDispatcher
from trac.wiki.model import WikiPage

from tracvote import VoteSystem, resource_from_path


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
                connector = self.db_mgr.get_connector()[0]
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
            """, (('ticket/1', 'user', -1),
                  ('ticket/2', 'user', 1),
                  ('wiki/DeletedPage', 'user', -1),
                  ('wiki/ExistingPage', 'user', 1)))
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
            self.assertFalse('2' in t_votes)
            self.assertFalse('DeletedPage' in w_votes)
            self.assertTrue('ExistingPage' in w_votes)


class VoteSystemTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(enable=['trac.*', 'tracvote.*'])
        # OK, this is a quick hack... I didn't have time to investigate
        # why I got ''Cannot find implementation(s) of the `IPermissionPolicy`
        # interface named `ReadonlyWikiPolicy`.''
        self.env.config.set('trac', 'permission_policies',
                            ', '.join(['DefaultPermissionPolicy',
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
        self.env.reset_db()
        # Really close db connections.
        self.env.shutdown()
        shutil.rmtree(self.env.path)

    # Helpers

    def create_request(self, authname='anonymous', **kwargs):
        kw = {'perm': PermissionCache(self.env, authname), 'args': {},
              'callbacks': {}, 'path_info': '', 'form_token': None,
              'href': self.env.href, 'abs_href': self.env.abs_href,
              'tz': utc, 'locale': None, 'lc_time': locale_en,
              'session': {},
              'authname': authname, 'chrome': {'notices': [], 'warnings': []},
              'method': None, 'get_header': lambda v: None, 'is_xhr': False}
        kw.update(kwargs)

        def send(self, content, content_type='text/html', status=200):
            raise RequestDone

        return Mock(send=send, **kw)

    def _revert_schema_init(self):
        with self.env.db_transaction as db:
            db("DROP TABLE IF EXISTS votes")

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

    def test_voter_rendered_on_ticket(self):
        """Voter rendered when viewing ticket with VOTE_VIEW."""
        TicketModule(self.env)
        Ticket(self.env).insert()
        PermissionSystem(self.env).grant_permission('user', 'TICKET_VIEW')

        req = self.create_request('user', path_info='/ticket/1', method='GET')
        dispatcher = RequestDispatcher(self.env)

        self.assertRaises(RequestDone, dispatcher.dispatch, req)
        found = False
        for elem in req.chrome.get('ctxtnav', []):
            found |= '<span id="vote" title="Vote count">' in unicode(elem)
        self.assertTrue(found)
        self.assertTrue('shown_vote_message' in req.session)

    def test_voter_not_rendered_on_ticket_permission_error(self):
        """Voter not rendered on permission error."""
        TicketModule(self.env)
        Ticket(self.env).insert()

        req = self.create_request('user', path_info='/ticket/1', method='GET')
        dispatcher = RequestDispatcher(self.env)

        self.assertRaises(HTTPForbidden, dispatcher.dispatch, req)
        for elem in req.chrome.get('ctxtnav', []):
            self.assertFalse('<span id="vote" title="Vote count">'
                             in unicode(elem))
        self.assertFalse('shown_vote_message' in req.session)

    def test_invalid_request_path(self):
        req = self.create_request('user',
                                  path_info='/vote/down/invalid-realm',
                                  method='GET')
        dispatcher = RequestDispatcher(self.env)

        try:
            dispatcher.dispatch(req)
        except HTTPInternalError, e:
            self.assertEqual("500 Trac Error (Invalid request path. "
                             "Path does not contain a valid realm.)",
                             unicode(e))
        else:
            self.fail("TracError not raised.")

class ResourceFromPathTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub()
        Ticket(self.env).insert()

    def test_ticket_resource_exists(self):
        resource = resource_from_path(self.env, '/ticket/1')
        self.assertEqual(Resource('ticket', '1'), resource)

    def test_ticket_resource_not_exists(self):
        resource = resource_from_path(self.env, '/ticket/2')
        self.assertIsNone(resource)

    def test_ticket_resource_invalid(self):
        resource = resource_from_path(self.env, '/ticket/a')
        self.assertIsNone(resource)


def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(EnvironmentSetupTestCase))
    suite.addTest(unittest.makeSuite(VoteSystemTestCase))
    suite.addTest(unittest.makeSuite(ResourceFromPathTestCase))
    return suite

if __name__ == '__main__':
    unittest.main(defaultTest='suite')
