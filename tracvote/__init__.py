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

import pkg_resources
import re
from fnmatch import fnmatchcase
from functools import partial

from datetime import datetime

from genshi import Markup
from genshi.builder import tag
from pkg_resources import resource_filename

from trac.config import ListOption
from trac.core import Component, TracError, implements
from trac.db import DatabaseManager, Table, Column
from trac.env import IEnvironmentSetupParticipant
from trac.perm import IPermissionRequestor
from trac.resource import Resource, ResourceSystem, get_resource_description
from trac.resource import get_resource_url, resource_exists
from trac.ticket.api import IMilestoneChangeListener
from trac.util import as_int, get_reporter_id
from trac.util.datefmt import format_datetime, to_datetime, to_utimestamp, utc
from trac.util.text import to_unicode
from trac.util.translation import domain_functions
from trac.web.api import IRequestFilter, IRequestHandler
from trac.web.chrome import Chrome, ITemplateProvider
from trac.web.chrome import add_notice, add_script, add_stylesheet
from trac.wiki.api import IWikiChangeListener, IWikiMacroProvider, parse_args

import tracvote.compat

_, add_domain, tag_ = domain_functions('tracvote', ('_', 'add_domain', 'tag_'))

pkg_resources.require('Trac >= 1.0')


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
    if isinstance(path, basestring):
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


class VoteSystem(Component):
    """Allow up- and down-voting on Trac resources."""

    def __init__(self):
        """Set up translation domain"""
        try:
            locale_dir = resource_filename(__name__, 'locale')
        except KeyError:
            pass
        else:
            add_domain(self.env.path, locale_dir)

    implements(IEnvironmentSetupParticipant,
               IMilestoneChangeListener,
               IPermissionRequestor,
               IRequestFilter,
               IRequestHandler,
               ITemplateProvider,
               IWikiChangeListener,
               IWikiMacroProvider)

    image_map = {-1: ('aupgray.png', 'adownmod.png'),
                  0: ('aupgray.png', 'adowngray.png'),
                 +1: ('aupmod.png', 'adowngray.png')}

    path_re = re.compile(r'/vote/(up|down)/(.*)')

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
    # Database schema version identifier, used for automatic upgrades.
    schema_version = 2
    schema_version_key = 'vote_version'

    # Default database values
    # (table, (column1, column2), ((row1col1, row1col2), (row2col1, row2col2)))
    db_data = [
        ('permission',
            ('username', 'action'),
                (('anonymous', 'VOTE_VIEW'),
                 ('authenticated', 'VOTE_MODIFY'))),
    ]

    voteable_paths = ListOption('vote', 'paths', '/ticket*,/wiki*',
        doc="List of URL paths to allow voting on. Globs are supported.",
        doc_domain='tracvote')

    # Public methods

    def get_top_voted(self, req, realm=None, top=0):
        """Return resources ordered top-down by vote count."""
        args = []
        if realm:
            args.append(realm)
        if top:
            args.append(top)
        for row in self.env.db_query("""
                SELECT realm,resource_id,SUM(vote) AS count
                  FROM votes%s
                 GROUP by realm,resource_id
                 ORDER by count DESC,resource_id%s
                """ % (' WHERE realm=%s' if realm else '',
                       ' LIMIT %s' if top else ''), args):
            yield row

    def get_vote_counts(self, resource):
        """Get negative, total and positive vote counts and return them in a
        tuple.
        """
        with self.env.db_query as db:
            total = negative = positive = 0
            for sum_vote, in db("""
                    SELECT sum(vote)
                      FROM votes
                     WHERE realm=%s
                       AND resource_id=%s
                    """, (resource.realm, resource.id)):
                total = sum_vote
            for sum_vote, in db("""
                    SELECT sum(vote)
                      FROM votes
                     WHERE vote < 0
                       AND realm=%s
                       AND resource_id=%s
                    """, (resource.realm, resource.id)):
                negative = sum_vote
            for sum_vote, in db("""
                    SELECT sum(vote)
                      FROM votes
                     WHERE vote > 0
                       AND realm=%s
                       AND resource_id=%s
                    """, (resource.realm, to_unicode(resource.id))):
                positive = sum_vote
            return negative or 0, total or 0, positive or 0

    def get_vote(self, req, resource):
        """Return the current users vote for a resource."""
        for vote, in self.env.db_query("""
                SELECT vote
                  FROM votes
                 WHERE username=%s
                   AND realm=%s
                   AND resource_id=%s
                """, (get_reporter_id(req), resource.realm,
                      to_unicode(resource.id))):
            return vote

    def set_vote(self, req, resource, vote):
        """Vote for a resource."""
        now_ts = to_utimestamp(datetime.now(utc))
        args = [now_ts, resource.version, vote, get_reporter_id(req),
                resource.realm, to_unicode(resource.id)]
        if not resource.version:
            args.pop(1)
        with self.env.db_transaction as db:
            db("""
                UPDATE votes
                   SET changetime=%%s%s,vote=%%s
                 WHERE username=%%s
                   AND realm=%%s
                   AND resource_id=%%s
            """ % (',version=%s' if resource.version else ''), args)
            if self.get_vote(req, resource) is None:
                db("""
                    INSERT INTO votes
                      (realm,resource_id,version,username,vote,
                       time,changetime)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                """, (resource.realm, to_unicode(resource.id),
                      resource.version, get_reporter_id(req), vote,
                      now_ts, now_ts))

    def reparent_votes(self, resource, old_id):
        """Update resource reference of votes on a renamed resource."""
        self.env.db_transaction("""
            UPDATE votes
               SET resource_id=%s
             WHERE realm=%s
               AND resource_id=%s
            """, (to_unicode(resource.id), resource.realm,
                  to_unicode(old_id)))

    def delete_votes(self, resource):
        """Delete votes for a resource."""
        args = list((resource.realm, to_unicode(resource.id)))
        if resource.version:
            args.append(resource.version)
        self.env.db_transaction("""
            DELETE
              FROM votes
             WHERE realm=%%s
               AND resource_id=%%s%s
            """ % (' AND version=%s' if resource.version else ''), args)

    def get_votes(self, req, resource=None, top=0):
        """Return most recent votes, optionally only for one resource."""
        args = [resource.realm, to_unicode(resource.id)] if resource else []
        if top:
            args.append(top)
        for row in self.env.db_query("""
            SELECT realm,resource_id,vote,username,changetime
              FROM votes
             WHERE changetime is not NULL%s
             ORDER BY changetime DESC%s
            """ % (' AND realm=%s AND resource_id=%s' if resource else '',
                   ' LIMIT %s' if top else ''), args):
            yield row

    def get_total_vote_count(self, realm):
        """Return the total vote count for a realm, like 'ticket'."""
        with self.env.db_query as db:
            total = negative = positive = 0
            for sum_vote, in db(
                    'SELECT sum(vote) FROM votes WHERE resource LIKE %s',
                    (realm + '%',)):
                total = sum_vote
            for sum_vote, in db("""
                    SELECT sum(vote)
                      FROM votes
                     WHERE vote < 0
                       AND resource LIKE %s
                    """, (realm + '%',)):
                negative = sum_vote
            for sum_vote, in db("""
                    SELECT sum(vote)
                      FROM votes
                     WHERE vote > 0
                       AND resource=%s
                    """, (realm + '%',)):
                positive = sum_vote
            return negative, total, positive

    def get_realm_votes(self, realm):
        """Return a dictionary of vote count for a realm."""
        resources = set()
        for i, in self.env.db_query(
                'SELECT resource FROM votes WHERE resource LIKE %s',
                (realm + '%',)):
            resources.add(i)
        votes = {}
        for resource in resources:
            votes[resource] = self.get_vote_counts(resource)
        return votes

    def get_max_votes(self, realm):
        votes = self.get_realm_votes(realm)
        if not votes:
            return 0
        return max(i[1] for i in votes.values())

    # IMilestoneChangeListener methods

    def milestone_created(self, milestone):
        """Called when a milestone is created."""
        pass

    def milestone_changed(self, milestone, old_values):
        """Called when a milestone is modified."""
        old_name = old_values.get('name')
        if old_name and milestone.resource.id != old_name:
            self.reparent_votes(milestone.resource, old_name)

    def milestone_deleted(self, milestone):
        """Called when a milestone is deleted."""
        self.delete_votes(milestone.resource)

    # IPermissionRequestor method

    def get_permission_actions(self):
        action = 'VOTE_VIEW'
        return [('VOTE_MODIFY', [action]), action]

    # IRequestHandler methods

    def match_request(self, req):
        match = self.path_re.match(req.path_info)
        if match:
            req.args['vote'] = match.group(1)
            req.args['path'] = match.group(2)
            return True

    def process_request(self, req):
        vote, path = req.args.get('vote'), req.args.get('path')
        resource = resource_from_path(self.env, path)
        if resource is None:
            raise TracError(_("Invalid request path. Path does not "
                              "contain a valid realm."))
        req.perm(resource).require('VOTE_MODIFY')

        vote = +1 if vote == 'up' else -1
        old_vote = self.get_vote(req, resource)

        # Protect against CSRF attacks: Validate the token like done in Trac
        # core for all POST requests with a content-type corresponding
        # to form submissions.
        msg = ''
        if req.args.get('token') != req.form_token:
            if self.env.secure_cookies and req.scheme == 'http':
                msg = _("Secure cookies are enabled, you must use https "
                        "for your requests.")
            else:
                msg = _("Do you have cookies enabled?")
            raise TracError(msg)
        else:
            if old_vote == vote:
                # Second click on same icon revokes previous vote.
                vote = 0
            self.set_vote(req, resource, vote)

        if req.args.get('js'):
            body, title = self.format_votes(resource)
            content = ':'.join(
                          (req.href.chrome('vote/' + self.image_map[vote][0]),
                           req.href.chrome('vote/' + self.image_map[vote][1]),
                           body, title))
            if isinstance(content, unicode):
                content = content.encode('utf-8')
            req.send(content)

        req.redirect(get_resource_url(self.env, resource(version=None),
                                      req.href))

    # IRequestFilter methods

    def pre_process_request(self, req, handler):
        return handler

    def post_process_request(self, req, template, data, content_type):
        if template is not None:
            for path in self.voteable_paths:
                if fnmatchcase(req.path_info, path):
                    resource = resource_from_path(self.env, req.path_info)
                    if resource and 'VOTE_VIEW' in req.perm(resource):
                        self.render_voter(req)
                        break
        return template, data, content_type

    # ITemplateProvider methods

    def get_templates_dirs(self):
        return []

    def get_htdocs_dirs(self):
        return [('vote', resource_filename(__name__, 'htdocs'))]

    # IWikiChangeListener methods

    def wiki_page_added(self, page):
        """Called whenever a new Wiki page is added."""
        pass

    def wiki_page_changed(self, page, version, t, comment, author, ipnr=None):
        """Called when a page has been modified."""
        pass

    def wiki_page_deleted(self, page):
        """Called when a page has been deleted."""
        page.resource.version = None
        self.delete_votes(page.resource)

    def wiki_page_version_deleted(self, page):
        """Called when a version of a page has been deleted."""
        self.delete_votes(page.resource)

    def wiki_page_renamed(self, page, old_name):
        """Called when a page has been renamed."""
        # Correct references for all page versions.
        page.resource.version = None
        # Work around issue t:#11138.
        page.resource.id = page.name
        self.reparent_votes(page.resource, old_name)

    # IWikiMacroProvider methods

    def get_macros(self):
        yield 'LastVoted'
        yield 'TopVoted'
        yield 'VoteList'

    def get_macro_description(self, name):
        if name == 'LastVoted':
            return _("Show most recently voted resources.")
        elif name == 'TopVoted':
            return _("Show listing of voted resources ordered by total score.")
        elif name == 'VoteList':
            return _("Show listing of most recent votes for a resource.")

    def expand_macro(self, formatter, name, content):
        env = formatter.env
        req = formatter.req
        if 'VOTE_VIEW' not in req.perm('vote'):
            return
        # Simplify function calls.
        format_author = partial(Chrome(self.env).format_author, req)
        if not content:
            args = []
            compact = None
            kw = {}
            top = 5
        else:
            args, kw = parse_args(content)
            compact = 'compact' in args
            top = as_int(kw.get('top'), 5, min=0)

        if name == 'LastVoted':
            lst = tag.ul()
            for i in self.get_votes(req, top=top):
                resource = Resource(i[0], i[1])
                # Anotate who and when.
                voted = _("by %(author)s at %(time)s",
                          author=format_author(i[3]),
                          time=format_datetime(to_datetime(i[4])))
                lst(tag.li(tag.a(
                    get_resource_description(
                                env, resource,
                                'compact' if compact else 'default'),
                    href=get_resource_url(env, resource, formatter.href),
                    title=('%+i %s' % (i[2], voted) if compact else None)),
                    (Markup(' %s %s' % (tag.b('%+i' % i[2]),
                                        voted)) if not compact else '')))
            return lst

        elif name == 'TopVoted':
            realm = kw.get('realm')
            lst = tag.ul()
            for i in self.get_top_voted(req, realm=realm, top=top):
                if 'up-only' in args and i[2] < 1:
                    break
                resource = Resource(i[0], i[1])
                lst(tag.li(tag.a(
                    get_resource_description(
                                env, resource,
                                'compact' if compact else 'default'),
                    href=get_resource_url(env, resource, formatter.href),
                    title=('%+i' % i[2] if compact else None)),
                    (' (%+i)' % i[2] if not compact else '')))
            return lst

        elif name == 'VoteList':
            lst = tag.ul()
            resource = resource_from_path(env, req.path_info)
            for i in self.get_votes(req, resource, top=top):
                vote = _("at %(date)s",
                         date=format_datetime(to_datetime(i[4])))
                lst(tag.li(format_author(i[3]) if compact else
                    tag_("%(count)s by %(author)s %(vote)s",
                         count=tag.b('%+i' % i[2]),
                         author=tag(format_author(i[3])),
                         vote=vote)),
                    title=('%+i %s' % (i[2], vote) if compact else None))
            return lst

    # IEnvironmentSetupParticipant methods

    def environment_created(self):
        self.upgrade_environment()

    def environment_needs_upgrade(self, db=None):
        schema_ver = self.get_schema_version()
        if schema_ver < self.schema_version:
            return True
        elif schema_ver > self.schema_version:
            raise TracError(
                _("A newer version of VotePlugin has been installed before, "
                  "but downgrading is unsupported."))
        return False

    def upgrade_environment(self, db=None):
        """Each schema version should have its own upgrade module, named
        upgrades/dbN.py, where 'N' is the version number (int).
        """
        dbm = DatabaseManager(self.env)
        schema_version = self.get_schema_version()
        if not schema_version:
            with self.env.db_transaction:
                dbm.create_tables(self.schema)
                dbm.set_database_version(self.schema_version,
                                         self.schema_version_key)
                dbm.insert_into_tables(self.db_data)
        else:
            # Care for pre-tracvote-0.2 installations.
            if schema_version == 1:
                dbm.set_database_version(1, self.schema_version_key)
            dbm.upgrade(self.schema_version, self.schema_version_key,
                        'tracvote.upgrades')

    # Internal methods

    def get_schema_version(self):
        """Return the current schema version for this plugin."""
        dbm = DatabaseManager(self.env)
        schema_ver = dbm.get_database_version('vote_version')
        if schema_ver > 1:
            # The expected outcome for any recent installation.
            return schema_ver
        # Care for pre-tracvote-0.2 installations.
        tables = dbm.get_table_names()
        if 'votes' in tables:
            return 1
        # This is a new installation.
        return 0

    def render_voter(self, req):
        path = req.path_info.strip('/')
        resource = resource_from_path(self.env, path)
        vote = resource and self.get_vote(req, resource) or 0
        up = tag.img(src=req.href.chrome('vote/' + self.image_map[vote][0]),
                     alt=_("Up-vote"))
        down = tag.img(src=req.href.chrome('vote/' + self.image_map[vote][1]),
                       alt=_("Down-vote"))
        if 'action' not in req.args and \
                'VOTE_MODIFY' in req.perm(resource) and \
                get_reporter_id(req) != 'anonymous':
            down = tag.a(down, id='downvote',
                         href=req.href.vote('down', path,
                                            token=req.form_token),
                         title=_("Down-vote"))
            up = tag.a(up, id='upvote',
                       href=req.href.vote('up', path, token=req.form_token),
                       title=_("Up-vote"))
            add_script(req, 'vote/js/tracvote.js')
            shown = req.session.get('shown_vote_message')
            if not shown:
                add_notice(req, _("You can vote for resources on this Trac "
                                  "install by clicking the up-vote/down-vote "
                                  "arrows in the context navigation bar."))
                req.session['shown_vote_message'] = '1'
        body, title = self.format_votes(resource)
        votes = tag.span(body, id='votes')
        add_stylesheet(req, 'vote/css/tracvote.css')
        elm = tag.span(up, votes, down, id='vote', title=title)
        req.chrome.setdefault('ctxtnav', []).insert(0, elm)

    def format_votes(self, resource):
        """Return a tuple of (body_text, title_text) describing the votes on a
        resource.
        """
        negative, total, positive = \
            self.get_vote_counts(resource) if resource else (0, 0, 0)
        count_detail = ['%+i' % i for i in (positive, negative) if i]
        if count_detail:
            count_detail = ' (%s)' % ', '.join(count_detail)
        else:
            count_detail = ''
        return '%+i' % total, _("Vote count%(detail)s", detail=count_detail)
