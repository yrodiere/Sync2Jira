# This file is part of sync2jira.
# Copyright (C) 2016 Red Hat, Inc.
#
# sync2jira is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# sync2jira is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with sync2jira; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110.15.0 USA
#
# Authors:  Ralph Bean <rbean@redhat.com>
from datetime import datetime
import re


class Issue(object):
    """Issue intermediary object"""

    def __init__(self, source, title, url, upstream, comments,
                 config, tags, fixVersion, priority, content,
                 reporter, assignee, status, id, upstream_id, downstream=None):
        self.source = source
        self._title = title
        self.url = url
        self.upstream = upstream
        self.comments = comments
        self.tags = tags
        self.fixVersion = fixVersion
        self.priority = priority

        # JIRA treats utf-8 characters in ways we don't totally understand, so scrub content down to
        # simple ascii characters right from the start.
        self.content = content.encode('ascii', errors='replace').decode('ascii')

        # We also apply this content in regexs to pattern match, so remove any escape characters
        self.content = self.content.replace('\\', '')

        self.reporter = reporter
        self.assignee = assignee
        self.status = status
        self.id = str(id)
        self.upstream_id = upstream_id
        if not downstream:
            self.downstream = config['sync2jira']['map'][self.source][upstream]
        else:
            self.downstream = downstream

    @property
    def title(self):
        return u'[%s] %s' % (self.upstream, self._title)

    @property
    def upstream_title(self):
        return self._title

    @classmethod
    def from_pagure(cls, upstream, issue, config):
        base = config['sync2jira'].get('pagure_url', 'https://pagure.io')
        upstream_source = 'pagure'
        comments = []
        for comment in issue['comments']:
            # Only add comments that are not Metadata updates
            if '**Metadata Update' in comment['comment']:
                continue
            # Else add the comment
            # Convert the date to datetime
            comment['date_created'] = datetime.fromtimestamp(float(comment['date_created']))
            comments.append({
                'author': comment['user']['name'],
                'body': comment['comment'],
                'name': comment['user']['name'],
                'id': comment['id'],
                'date_created': comment['date_created'],
                'changed': None
            })

        # Perform any mapping
        mapping = config['sync2jira']['map'][upstream_source][upstream].get('mapping', [])

        # Check for fixVersion
        if any('fixVersion' in item for item in mapping):
            map_fixVersion(mapping, issue)

        return Issue(
            source=upstream_source,
            title=issue['title'],
            url=base + '/%s/issue/%i' % (upstream, issue['id']),
            upstream=upstream,
            config=config,
            comments=comments,
            tags=issue['tags'],
            fixVersion=[issue['milestone']],
            priority=issue['priority'],
            content=issue['content'],
            reporter=issue['user'],
            assignee=issue['assignee'],
            status=issue['status'],
            id=issue['date_created'],
            upstream_id=issue['id']
        )

    @classmethod
    def from_github(cls, upstream, issue, config):
        upstream_source = 'github'
        comments = []
        for comment in issue['comments']:
            comments.append({
                'author': comment['author'],
                'name': comment['name'],
                'body': comment['body'],
                'id': comment['id'],
                'date_created': comment['date_created'],
                'changed': None
            })

        # Reformat the state field
        if issue['state']:
            if issue['state'] == 'open':
                issue['state'] = 'Open'
            elif issue['state'] == 'closed':
                issue['state'] = 'Closed'

        # Perform any mapping
        mapping = config['sync2jira']['map'][upstream_source][upstream].get('mapping', [])

        # Check for fixVersion
        if any('fixVersion' in item for item in mapping):
            map_fixVersion(mapping, issue)

        # TODO: Priority is broken
        return Issue(
            source=upstream_source,
            title=issue['title'],
            url=issue['html_url'],
            upstream=upstream,
            config=config,
            comments=comments,
            tags=issue['labels'],
            fixVersion=[issue['milestone']],
            priority=None,
            content=issue['body'],
            reporter=issue['user'],
            assignee=issue['assignees'],
            status=issue['state'],
            id=issue['id'],
            upstream_id=issue['number']
        )

    def __repr__(self):
        return "<Issue %s >" % self.url


class PR(object):
    """PR intermediary object"""

    def __init__(self, source, jira_key, title, url, upstream, config,
                 comments, priority, content, reporter,
                 assignee, status, id, suffix, downstream=None):
        self.source = source
        self.jira_key = jira_key
        self._title = title
        self.url = url
        self.upstream = upstream
        self.comments = comments
        # self.tags = tags
        # self.fixVersion = fixVersion
        self.priority = priority

        # JIRA treats utf-8 characters in ways we don't totally understand, so scrub content down to
        # simple ascii characters right from the start.
        if content:
            self.content = content.encode('ascii', errors='replace').decode('ascii')

            # We also apply this content in regexs to pattern match, so remove any escape characters
            self.content = self.content.replace('\\', '')
        else:
            self.content = None

        self.reporter = reporter
        self.assignee = assignee
        self.status = status
        self.id = str(id)
        self.suffix = suffix
        # self.upstream_id = upstream_id

        if not downstream:
            self.downstream = config['sync2jira']['map'][self.source][upstream]
        else:
            self.downstream = downstream
        return

    @property
    def title(self):
        return u'[%s] %s' % (self.upstream, self._title)

    @classmethod
    def from_pagure(self, upstream, pr, suffix, config):
        """Helper function to create intermediary object."""
        # Set our upstream source
        upstream_source = 'pagure'

        # Format our comments
        comments = []
        for comment in pr['comments']:
            # Only add comments that are not Metadata updates
            if '**Metadata Update' in comment['comment']:
                continue
            # Else add the comment
            # Convert the date to datetime
            comment['date_created'] = datetime.fromtimestamp(
                float(comment['date_created']))
            comments.append({
                'author': comment['user']['name'],
                'body': comment['comment'],
                'name': comment['user']['name'],
                'id': comment['id'],
                'date_created': comment['date_created'],
                'changed': None
            })

        # Build our URL
        url = f"https://pagure.io/{pr['project']['name']}/pull-request/{pr['id']}"

        # Match a JIRA
        match = matcher(pr.get('initial_comment'), comments)

        # Return our PR object
        return PR(
            source=upstream_source,
            jira_key=match,
            title=pr['title'],
            url=url,
            upstream=upstream,
            config=config,
            comments=comments,
            # tags=issue['labels'],
            # fixVersion=[issue['milestone']],
            priority=None,
            content=pr['initial_comment'],
            reporter=pr['user']['fullname'],
            assignee=pr['assignee'],
            status=pr['status'],
            id=pr['id'],
            suffix=suffix,
            # upstream_id=issue['number']
        )

    @classmethod
    def from_github(self, upstream, pr, suffix, config):
        """Helper function to create intermediary object."""
        # Set our upstream source
        upstream_source = 'github'

        # Format our comments
        comments = []
        for comment in pr['comments']:
            comments.append({
                'author': comment['author'],
                'name': comment['name'],
                'body': comment['body'],
                'id': comment['id'],
                'date_created': comment['date_created'],
                'changed': None
            })

        # Build our URL
        url = pr['html_url']

        # Match to a JIRA
        match = matcher(pr.get("body"), comments)

        # Figure out what state we're transitioning too
        if 'reopened' in suffix:
            suffix = 'reopened'
        elif 'closed' in suffix:
            # Check if we're merging or closing
            if pr['merged']:
                suffix = 'merged'
            else:
                suffix = 'closed'

        # Return our PR object
        return PR(
            source=upstream_source,
            jira_key=match,
            title=pr['title'],
            url=url,
            upstream=upstream,
            config=config,
            comments=comments,
            # tags=issue['labels'],
            # fixVersion=[issue['milestone']],
            priority=None,
            content=pr.get('body'),
            reporter=pr['user']['fullname'],
            assignee=pr['assignee'],
            # GitHub PRs do not have status
            status=None,
            id=pr['number'],
            # upstream_id=issue['number'],
            suffix=suffix,
        )


def map_fixVersion(mapping, issue):
    """
    Helper function to perform any fixVersion mapping.

    :param Dict mapping: Mapping dict we are given
    :param Dict issue: Upstream issue object
    """
    # Get our fixVersion mapping
    try:
        # for python 3 >
        fixVersion_map = list(filter(lambda d: "fixVersion" in d, mapping))[0]['fixVersion']
    except ValueError:
        # for python 2.7
        fixVersion_map = filter(lambda d: "fixVersion" in d, mapping)[0]['fixVersion']

    # Now update the fixVersion
    if issue['milestone']:
        issue['milestone'] = fixVersion_map.replace('XXX', issue['milestone'])


def matcher(content, comments):
    """
    Helper function to match to a JIRA

    :param String content: PR description
    :param List comments: Comments
    :return: JIRA match or None
    :rtype: Bool
    """
    # Build out a string with all comments and initial_comment
    all_data = " "
    for comment in reversed(comments):
        all_data += f" {comment['body']}"
    if content:
        all_data += content
    if all_data:
        # Parse to extract the JIRA information. 2 types of matches:
        # 1 - To match to JIRA issue (i.e. Relates to JIRA: FACTORY-1234)
        # 2 - To match to upstream issue (i.e. Relates to Issue: !5)
        match_jira = re.findall("Relates to JIRA: ([\w]*-[\d]*)",  # noqa W605
                                all_data)
        if match_jira:
            for match in match_jira:
                # Assert that the match was correct
                if re.match("[\w]*-[\d]*", match): # noqa W605
                    return match
        else:
            return None
