#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2008 Alec Thomas <alec@swapoff.org>
# Copyright (C) 2009 Noah Kantrowitz <noah@coderanger.net>
# Copyright (C) 2009 Jeff Hammel <jhammel@openplans.org>
# Copyright (C) 2010-2015 Ryan J Ollos <ryan.j.ollos@gmail.com>
# Copyright (C) 2013-2015 Steffen Hoffmann <hoff.st@web.de>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.

from setuptools import find_packages, setup

extra = {}
try:
    from trac.util.dist import get_l10n_cmdclass
    cmdclass = get_l10n_cmdclass()
    if cmdclass:
        extra['cmdclass'] = cmdclass
        extractors = [
            ('**.py', 'trac.dist:extract_python', None)
        ]
        extra['message_extractors'] = {
            'tracvote': extractors,
        }
except ImportError:
    pass

setup(
    name='TracVote',
    version='0.6.0',
    author='Alec Thomas',
    maintainer='Ryan J Ollos',
    maintainer_email='ryan.j.ollos@gmail.com',
    url='https://trac-hacks.org/wiki/VotePlugin',
    license='3-Clause BSD',
    packages=find_packages(exclude=['*.tests']),
    package_data={
        'tracvote': [
            'htdocs/*.*',
            'htdocs/js/*.js',
            'htdocs/css/*.css',
            'locale/*/LC_MESSAGES/*.mo'
        ]
    },
    test_suite='tracvote.tests.suite',
    zip_safe=True,
    install_requires=['Trac'],
    description='A plugin for voting on Trac resources.',
    entry_points={'trac.plugins': ['tracvote = tracvote']},
    **extra
)
