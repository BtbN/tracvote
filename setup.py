#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2008 Alec Thomas <alec@swapoff.org>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.

from setuptools import find_packages, setup

setup(
    name='TracVote',
    version='0.2',
    packages=find_packages(exclude=['*.tests']),
    package_data={
        'tracvote': ['htdocs/*.*', 'htdocs/js/*.js', 'htdocs/css/*.css']
    },
    author='Alec Thomas',
    maintainer = 'Ryan J Ollos',
    maintainer_email = 'ryano@physiosonics.com',

    license='BSD',

    test_suite = 'tracvote.tests.suite',
    zip_safe=True,
    install_requires = ['Trac >= 0.11'],
    url='http://trac-hacks.org/wiki/VotePlugin',
    description='A plugin for voting on Trac resources.',
    entry_points = {'trac.plugins': ['tracvote = tracvote']},
)
