from setuptools import setup

setup(
    name='VotePlugin',
    version='0.1',
    packages=['tracvote'],
	package_data={'tracvote' : ['htdocs/js/*.js', 'htdocs/css/*.css']},
    author='Alec Thomas',
    license='BSD',
    url='http://trac-hacks.org/wiki/VotePlugin',
    description='A plugin for voting on Trac resources.',
    entry_points = {'trac.plugins': ['tracvote = tracvote']},
    )
