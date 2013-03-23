#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup

setup(
    name='TracVote',
    version='0.1.5',
    packages=['tracvote'],
	package_data={'tracvote' : ['htdocs/*.*', 'htdocs/js/*.js', 'htdocs/css/*.css']},
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
