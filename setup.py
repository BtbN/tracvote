#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2008 Alec Thomas <alec@swapoff.org>
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
    version='0.3.0',
    packages=find_packages(exclude=['*.tests']),
    package_data={
        'tracvote': [
            'htdocs/*.*',
            'htdocs/js/*.js',
            'htdocs/css/*.css',
            'locale/*/LC_MESSAGES/*.mo'
        ]
    },
    author='Alec Thomas',
    maintainer = 'Ryan J Ollos',
    maintainer_email = 'ryan.j.ollos@gmail.com',

    license='BSD',

    test_suite = 'tracvote.tests.suite',
    zip_safe=True,
    install_requires = ['Trac'],
    url='http://trac-hacks.org/wiki/VotePlugin',
    description='A plugin for voting on Trac resources.',
    entry_points = {'trac.plugins': ['tracvote = tracvote']},
    **extra
)
