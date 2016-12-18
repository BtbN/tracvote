# -*- coding: utf-8 -*-
#
# Copyright (C) 2010-2015 Ryan J Ollos <ryan.j.ollos@gmail.com>
# Copyright (C) 2013-2015 Steffen Hoffmann <hoff.st@web.de>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.

import re

from trac.db import Table, Column, Index, DatabaseManager

from tracvote import resource_from_path


schema = [
    Table('votes', key=('realm', 'resource_id', 'username', 'vote'))[
        Column('realm'),
        Column('resource_id'),
        Column('version', 'int'),
        Column('username'),
        Column('vote', 'int'),
        Column('time', type='int64'),
        Column('changetime', type='int64'),
        ]
    ]


def do_upgrade(env, ver, cursor):
    """Changes to votes db table:

    'votes.resource' --> 'votes.realm' + 'votes.resource_id' + 'votes.version'
    + 'votes.time', 'votes.changetime'
    """

    cursor.execute("""
        CREATE TEMPORARY TABLE votes_old
            AS SELECT * FROM votes
    """)
    cursor.execute('DROP TABLE votes')

    connector = DatabaseManager(env).get_connector()[0]
    for table in schema:
        for stmt in connector.to_sql(table):
            env.log.debug(stmt)
            cursor.execute(stmt)
    # Migrate old votes.
    votes_columns = ('resource', 'username', 'vote')

    sql = 'SELECT ' + ', '.join(votes_columns) + ' FROM votes_old'
    cursor.execute(sql)
    votes = cursor.fetchall()
    for old_vote in votes:
        vote = dict(zip(votes_columns, old_vote))
        # Extract realm and resource ID from path.
        # Entries for invalid paths will get deleted effectively.
        resource = resource_from_path(env, vote.pop('resource'))
        if resource:
            vote['realm'] = resource.realm
            vote['resource_id'] = resource.id
            cols = vote.keys()
            cursor.execute(
                'INSERT INTO votes (' + ','.join(cols) + ') '
                'VALUES (' + ','.join(['%s' for c in xrange(len(cols))]) + ')',
                vote.values())
    # Finally drop old table.
    cursor.execute('DROP TABLE votes_old')
    cursor.execute("SELECT COUNT(*) FROM system WHERE name='vote_version'")
    exists = cursor.fetchone()
    if not exists[0]:
        # Create entry for tracvote<0.2 without version entry, but value
        # doesn't matter, because it will be updated after upgrade.
        cursor.execute("""
            INSERT INTO system
                   (name,value)
            VALUES ('vote_version','0')
            """)
