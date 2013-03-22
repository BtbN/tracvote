# -*- coding: utf-8 -*-

import re

from genshi import Markup, Stream
from genshi.builder import tag
from pkg_resources import resource_filename

from trac.config import ListOption
from trac.core import Component, implements
from trac.db import DatabaseManager, Table, Column
from trac.env import IEnvironmentSetupParticipant
from trac.perm import IPermissionRequestor
from trac.resource import get_resource_url
from trac.util import get_reporter_id
from trac.web.api import IRequestFilter, IRequestHandler, Href
from trac.web.chrome import ITemplateProvider, add_ctxtnav, add_stylesheet
from trac.web.chrome import add_script, add_notice


class VoteSystem(Component):
    """Allow up and down-voting on Trac resources."""

    implements(ITemplateProvider, IRequestFilter, IRequestHandler,
               IEnvironmentSetupParticipant, IPermissionRequestor)

    voteable_paths = ListOption('vote', 'paths', '/wiki*,/ticket*',
        doc='List of URL paths to allow voting on. Globs are supported.')

    schema = [
        Table('votes', key=('resource', 'username', 'vote'))[
            Column('resource'),
            Column('username'),
            Column('vote', 'int'),
            ]
        ]

    path_match = re.compile(r'/vote/(up|down)/(.*)')

    image_map = {-1: ('aupgray.png', 'adownmod.png'),
                  0: ('aupgray.png', 'adowngray.png'),
                 +1: ('aupmod.png', 'adowngray.png')}

    ### Public methods

    def get_vote_counts(self, resource):
        """Get negative, total and positive vote counts and return them in a
        tuple.
        """
        resource = self.normalise_resource(resource)
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        cursor.execute('SELECT sum(vote) FROM votes WHERE resource=%s',
                       (resource,))
        total = cursor.fetchone()[0] or 0
        cursor.execute("""
            SELECT sum(vote)
              FROM votes
             WHERE vote < 0
               AND resource=%s
        """, (resource,))
        negative = cursor.fetchone()[0] or 0
        cursor.execute("""
            SELECT sum(vote)
              FROM votes
             WHERE vote > 0
               AND resource=%s
        """,
                       (resource,))
        positive = cursor.fetchone()[0] or 0
        return (negative, total, positive)

    def get_vote(self, req, resource):
        """Return the current users vote for a resource."""
        resource = self.normalise_resource(resource)
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        cursor.execute("""
            SELECT vote
              FROM votes
             WHERE username=%s
               AND resource=%s
        """, (get_reporter_id(req), resource))
        row = cursor.fetchone()
        vote = row and row[0] or 0
        return vote

    def set_vote(self, req, resource, vote):
        """Vote for a resource."""
        resource = self.normalise_resource(resource)
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        cursor.execute("""
            DELETE
              FROM votes
             WHERE username=%s
               AND resource=%s
        """, (get_reporter_id(req), resource))
        if vote:
            cursor.execute('INSERT INTO votes (resource, username, vote) '
                           'VALUES (%s, %s, %s)',
                           (resource, get_reporter_id(req), vote))
        db.commit()

    def get_total_vote_count(self, realm):
        """Return the total vote count for a realm, like 'ticket'."""
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        cursor.execute('SELECT sum(vote) FROM votes WHERE resource LIKE %s',
                       (realm + '%',))
        total = cursor.fetchone()[0] or 0
        cursor.execute("""
            SELECT sum(vote)
              FROM votes
             WHERE vote < 0
               AND resource LIKE %s
        """, (realm + '%',))
        negative = cursor.fetchone()[0] or 0
        cursor.execute("""
            SELECT sum(vote)
              FROM votes
             WHERE vote > 0
               AND resource=%s
        """, (realm + '%',))
        positive = cursor.fetchone()[0] or 0
        return (negative, total, positive)
        
    def get_realm_votes(self, realm):
        """Return a dictionary of vote count for a realm."""
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        cursor.execute('SELECT resource FROM votes WHERE resource LIKE %s',
                       (realm + '%',))
        resources = set([i[0] for i in cursor.fetchall()])
        votes = {}
        for resource in resources:
            votes[resource] = self.get_vote_counts(resource)
        return votes

    def get_max_votes(self, realm):
        votes = self.get_realm_votes(realm)
        if not votes:
            return 0
        return max([i[1] for i in votes.values()])

    ### IPermissionRequestor method
    def get_permission_actions(self):
        action = 'VOTE_VIEW'
        return [('VOTE_MODIFY', [action]), action]

    ### ITemplateProvider methods

    def get_templates_dirs(self):
        return []
        #resource_filename(__name__, 'templates')]

    def get_htdocs_dirs(self):
        return [('vote', resource_filename(__name__, 'htdocs'))]

    ### IRequestHandler methods

    def match_request(self, req):
        return 'VOTE_VIEW' in req.perm and self.path_match.match(req.path_info)

    def process_request(self, req):
        req.perm.require('VOTE_MODIFY')
        match = self.path_match.match(req.path_info)
        vote, resource = match.groups()
        resource = self.normalise_resource(resource)
        vote = vote == 'up' and +1 or -1
        old_vote = self.get_vote(req, resource)

        if old_vote == vote:
            vote = 0
            self.set_vote(req, resource, 0)
        else:
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

        req.redirect(req.href(resource))

    ### IRequestFilter methods

    def pre_process_request(self, req, handler):
        return handler

    def post_process_request(self, req, template, data, content_type):
        if 'VOTE_VIEW' in req.perm:
            for path in self.voteable_paths:
                if re.match(path, req.path_info):
                    self.render_voter(req)
                    break
        return template, data, content_type

    ### IEnvironmentSetupParticipant methods

    def environment_created(self):
        self.upgrade_environment(self.env.get_db_cnx())

    def environment_needs_upgrade(self, db):
        cursor = db.cursor()
        try:
            cursor.execute('SELECT COUNT(*) FROM votes')
            cursor.fetchone()
            return False
        except:
            cursor.connection.rollback()
            return True

    def upgrade_environment(self, db):
        db_backend, _ = DatabaseManager(self.env)._get_connector()
        cursor = db.cursor()
        for table in self.schema:
            for stmt in db_backend.to_sql(table):
                self.env.log.debug(stmt)
                cursor.execute(stmt)
        db.commit()

    ### Internal methods

    def render_voter(self, req):
        resource = self.normalise_resource(req.path_info)
        vote = self.get_vote(req, resource)
        up = tag.img(src=req.href.chrome('vote/' + self.image_map[vote][0]), 
                     alt='Up-vote')
        down = tag.img(src=req.href.chrome('vote/' + self.image_map[vote][1]), 
                     alt='Down-vote')         
        if 'VOTE_MODIFY' in req.perm and get_reporter_id(req) != 'anonymous':
            down = tag.a(down, id='downvote',
                         href=req.href.vote('down', resource),
                         title='Down-vote')
            up = tag.a(up, id='upvote', href=req.href.vote('up', resource),
                       title='Up-vote')
            add_script(req, 'vote/js/tracvote.js')
            shown = req.session.get('shown_vote_message')
            if not shown:
                add_notice(req, 'You can vote for resources on this Trac '
                           'install by clicking the up-vote/down-vote arrows '
                           'in the context navigation bar.')
                req.session['shown_vote_message'] = '1'
        body, title = self.format_votes(resource)
        votes = tag.span(body, id='votes')
        add_stylesheet(req, 'vote/css/tracvote.css')
        elm = tag.span(up, votes, down, id='vote', title=title)
        req.chrome.setdefault('ctxtnav', []).insert(0, elm)

    def normalise_resource(self, resource):
        if isinstance(resource, basestring):
            resource = resource.strip('/')
            # Special-case: Default TracWiki start page.
            if resource == 'wiki':
                resource += '/WikiStart'
            return resource
        return get_resource_url(self.env, resource, Href('')).strip('/')

    def format_votes(self, resource):
        """Return a tuple of (body_text, title_text) describing the votes on a
        resource.
        """
        negative, total, positive = self.get_vote_counts(resource)
        count_detail = ['%+i' % i for i in (positive, negative) if i]
        if count_detail:
            count_detail = ' (%s)' % ', '.join(count_detail)
        else:
            count_detail = ''
        return ('%+i' % total, 'Vote count%s' % count_detail)
