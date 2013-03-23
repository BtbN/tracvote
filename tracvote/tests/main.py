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

from trac.perm import PermissionSystem
from trac.test import EnvironmentStub, Mock
from trac.web.chrome import Chrome

from tracvote import VoteSystem


_ACTIONS = ('VOTE_VIEW', 'VOTE_MODIFY')


class VoteSystemTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(default_data=True,
                enable=['trac.*', 'tracvote.*']
        )
        self.env.path = tempfile.mkdtemp()
        self.perm = PermissionSystem(self.env)
        self.req = Mock()

        self.db = self.env.get_db_cnx()
        self.votes = VoteSystem(self.env)

    def tearDown(self):
        self.db.close()
        # Really close db connections.
        self.env.shutdown()
        shutil.rmtree(self.env.path)

    def test_available_actions_no_perms(self):
        for action in _ACTIONS:
            self.assertFalse(self.perm.check_permission(action, 'anonymous'))

    def test_available_actions_full_perms(self):
        perm_map = dict(voter='VOTE_MODIFY', admin='TRAC_ADMIN')
        for user in perm_map:
            self.perm.grant_permission(user, perm_map[user])
            for action in _ACTIONS:
                self.assertTrue(self.perm.check_permission(action, user))

    def test_resource_provider(self):
        self.assertTrue(self.votes in Chrome(self.env).template_providers)


def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(VoteSystemTestCase, 'test'))
    return suite

if __name__ == '__main__':
    unittest.main(defaultTest='suite')
