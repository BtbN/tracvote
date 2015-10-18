# -*- coding: utf-8 -*-
#
# Copyright (C) 2013 Steffen Hoffmann <hoff.st@web.de>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.

import unittest


def suite():
    from tracvote.tests import main
    suite = unittest.TestSuite()
    suite.addTest(main.suite())
    return suite


# Start test suite directly from command line like so:
#   $> PYTHONPATH=$PWD python tracvote/tests/__init__.py
if __name__ == '__main__':
    unittest.main(defaultTest='suite')
