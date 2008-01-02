import re
from trac.core import *
from trac.config import ListOption
from trac.env import IEnvironmentSetupParticipant
from trac.web.api import IRequestFilter, IRequestHandler
from trac.web.chrome import ITemplateProvider, add_ctxtnav, add_stylesheet, \
                            add_script, add_warning
from trac.resource import get_resource_url
from trac.db import DatabaseManager, Table, Column
from trac.perm import IPermissionRequestor
from trac.util import get_reporter_id
from genshi import Markup, Stream
from genshi.builder import tag
from pkg_resources import resource_filename


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

    # Public methods
    def get_vote_count(self, resource):
        """Get vote count for a resource."""
        resource = self.normalise_resource(resource)
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        cursor.execute('SELECT sum(vote) FROM votes WHERE resource=%s',
                       (resource,))
        row = cursor.fetchone()
        return row[0] or 0

    def get_vote(self, req, resource):
        """Return the current users vote for a resource."""
        resource = self.normalise_resource(resource)
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        cursor.execute('SELECT vote FROM votes WHERE username=%s '
                       'AND resource = %s', (get_reporter_id(req), resource))
        row = cursor.fetchone()
        vote = row and row[0] or 0
        return vote

    def set_vote(self, req, resource, vote):
        """Vote for a resource."""
        resource = self.normalise_resource(resource)
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        cursor.execute('DELETE FROM votes WHERE username=%s '
                       'AND resource = %s', (get_reporter_id(req), resource))
        if vote:
            cursor.execute('INSERT INTO votes (resource, username, vote) '
                           'VALUES (%s, %s, %s)',
                           (resource, get_reporter_id(req), vote))
        db.commit()

    # IPermissionRequestor methods
    def get_permission_actions(self):
        return ['VOTE_VIEW', 'VOTE_MODIFY']

    # ITemplateProvider methods
    def get_templates_dirs(self):
        return [resource_filename(__name__, 'templates')]

    def get_htdocs_dirs(self):
        return [('vote', resource_filename(__name__, 'htdocs'))]

    # IRequestHandler methods
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
            req.send(':'.join((req.href.chrome('vote/' + self.image_map[vote][0]),
                               req.href.chrome('vote/' + self.image_map[vote][1]),
                               self.str_count(resource))))
        req.redirect(resource)

    # IRequestFilter methods
    def pre_process_request(self, req, handler):
        if 'VOTE_VIEW' not in req.perm:
            return handler

        for path in self.voteable_paths:
            if re.match(path, req.path_info):
                self.render_voter(req)
                break

        return handler

    def post_process_request(self, req, template, data, content_type):
        return (template, data, content_type)

    # IEnvironmentSetupParticipant methods
    def environment_created(self):
        self.upgrade_environment(self.env.get_db_cnx())

    def environment_needs_upgrade(self, db):
        cursor = db.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM VOTES")
            cursor.fetchone()
            return False
        except:
            return True

    def upgrade_environment(self, db):
        db_backend, _ = DatabaseManager(self.env)._get_connector()
        cursor = db.cursor()
        for table in self.schema:
            for stmt in db_backend.to_sql(table):
                self.env.log.debug(stmt)
                cursor.execute(stmt)
        db.commit()

    # Internal methods
    def render_voter(self, req):
        resource = self.normalise_resource(req.path_info)
        vote = self.get_vote(req, resource)
        up = tag.img(src=req.href.chrome('vote/' + self.image_map[vote][0]))
        down = tag.img(src=req.href.chrome('vote/' + self.image_map[vote][1]))
        if 'VOTE_MODIFY' in req.perm:
            down = tag.a(down, id='downvote', href=req.href.vote('down', resource),
                         title='Down-vote')
            up = tag.a(up, id='upvote', href=req.href.vote('up', resource),
                       title='Up-vote')
            add_script(req, 'vote/js/tracvote.js')
            shown = req.session.get('shown_vote_message')
            if not shown:
                add_warning(req, 'You can vote for resources on this Trac '
                            'install by clicking the up-vote/down-vote arrows '
                            'in the context navigation bar.')
                req.session['shown_vote_message'] = True
        votes = tag.span(self.str_count(resource), id='votes',
                         title='Votes for this resource')
        add_stylesheet(req, 'vote/css/tracvote.css')
        add_ctxtnav(req, tag.span(up, votes, down, id='vote'))

    def str_count(self, resource):
        vote = self.get_vote_count(resource)
        return '%+i' % vote

    def normalise_resource(self, resource):
        if isinstance(resource, basestring):
            resource = resource.strip('/')
            # Special-case start page
            if resource == 'wiki':
                resource += '/WikiStart'
            return resource
        return get_resource_url(self.env, resource, Href('')).strip('/')
