# -*- coding: utf-8 -*-
#
# Copyright (C) 2010-2015 Ryan J Ollos <ryan.j.ollos@gmail.com>
# Copyright (C) 2013-2015 Steffen Hoffmann <hoff.st@web.de>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.

import re

from trac.db import Table, Column, DatabaseManager
from trac.resource import Resource, ResourceSystem, resource_exists


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


def get_versioned_resource(env, resource):
    """Find the current version for a Trac resource.

    Because versioned resources with no version value default to 'latest',
    the current version has to be retrieved separately.
    """
    realm = resource.realm
    if realm == 'ticket':
        for count, in env.db_query("""
                SELECT COUNT(DISTINCT time)
                FROM ticket_change WHERE ticket=%s
                """, (resource.id,)):
            if count != 0:
                resource.version = count
    elif realm == 'wiki':
        for version, in env.db_query("""
                SELECT version
                  FROM wiki
                 WHERE name=%s
                 ORDER BY version DESC LIMIT 1
                """, (resource.id,)):
            resource.version = version
    return resource


def _resource_exists(env, resource):
    """Avoid exception in database for Trac < 1.0.7.
    http://trac.edgewall.org/ticket/12076
    """
    try:
        return resource_exists(env, resource)
    except env.db_exc.DatabaseError:
        return False


def resource_from_path(env, path):
    """Find realm and resource ID from resource URL.

    Assuming simple resource paths to convert to Trac resource identifiers.
    """
    path = path.strip('/')
    # Special-case: Default TracWiki start page.
    if path == 'wiki':
        path += '/WikiStart'
    for realm in ResourceSystem(env).get_known_realms():
        if path.startswith(realm):
            resource_id = re.sub(realm, '', path, 1).lstrip('/')
            resource = Resource(realm, resource_id)
            if _resource_exists(env, resource) in (None, True):
                return get_versioned_resource(env, resource)


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
