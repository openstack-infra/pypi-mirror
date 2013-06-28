#!/usr/bin/env python
# Copyright (c) 2012 OpenStack, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

# This is designed to be called by a gerrit hook.  It searched new
# patchsets for strings like "bug FOO" and updates corresponding Launchpad
# bugs status.

import argparse
import os
import re
import smtplib
import subprocess

from email.mime import text
from launchpadlib import launchpad
from launchpadlib import uris

BASE_DIR = '/home/gerrit2/review_site'
EMAIL_TEMPLATE = """
Hi, I'd like you to take a look at this patch for potential
%s.
%s

Log:
%s
"""

GERRIT_CACHE_DIR = os.path.expanduser(
    os.environ.get('GERRIT_CACHE_DIR',
                   '~/.launchpadlib/cache'))
GERRIT_CREDENTIALS = os.path.expanduser(
    os.environ.get('GERRIT_CREDENTIALS',
                   '~/.launchpadlib/creds'))


def create_bug(git_log, args, lp_project):
    """Create a bug for a change.

    Create a launchpad bug in lp_project, titled with the first line of
    the git commit message, with the content of the git_log prepended
    with the Gerrit review URL. Tag the bug with the name of the repository
    it came from. Don't create a duplicate bug. Returns link to the bug.
    """
    lpconn = launchpad.Launchpad.login_with(
        'Gerrit User Sync',
        uris.LPNET_SERVICE_ROOT,
        GERRIT_CACHE_DIR,
        credentials_file=GERRIT_CREDENTIALS,
        version='devel')

    lines_in_log = git_log.split("\n")
    bug_title = lines_in_log[4]
    bug_descr = args.change_url + '\n' + git_log
    project = lpconn.projects[lp_project]
    # check for existing bugs by searching for the title, to avoid
    # creating multiple bugs per review
    potential_dupes = project.searchTasks(search_text=bug_title)
    if len(potential_dupes) == 0:
        buginfo = lpconn.bugs.createBug(
            target=project, title=bug_title,
            description=bug_descr, tags=args.project.split('/')[1])
        buglink = buginfo.web_link

    return buglink


def process_impact(git_log, args):
    """Process DocImpact flag.

    If the 'DocImpact' flag is present, create a new documentation bug in
    the openstack-manuals launchpad project based on the git_log, then
    (and for non-documentation impacts) notify the mailing list of impact,
    unless a bug was created.
    """
    if args.impact.lower() == 'docimpact':
        buglink = create_bug(git_log, args, 'openstack-manuals')
        if buglink is not None:
            return

    email_content = EMAIL_TEMPLATE % (args.impact,
                                      args.change_url, git_log)

    msg = text.MIMEText(email_content)
    msg['Subject'] = '[%s] %s review request change %s' % \
        (args.project, args.impact, args.change)
    msg['From'] = 'gerrit2@review.openstack.org'
    msg['To'] = args.dest_address

    s = smtplib.SMTP('localhost')
    s.sendmail('gerrit2@review.openstack.org',
               args.dest_address, msg.as_string())
    s.quit()


def impacted(git_log, impact_string):
    """Determine if a changes log indicates there is an impact."""
    return re.search(impact_string, git_log, re.IGNORECASE)


def extract_git_log(args):
    """Extract git log of all merged commits."""
    cmd = ['git',
           '--git-dir=' + BASE_DIR + '/git/' + args.project + '.git',
           'log', '--no-merges', args.commit + '^1..' + args.commit]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE).communicate()[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('hook')
    #common
    parser.add_argument('--change', default=None)
    parser.add_argument('--change-url', default=None)
    parser.add_argument('--project', default=None)
    parser.add_argument('--branch', default=None)
    parser.add_argument('--commit', default=None)
    #change-merged
    parser.add_argument('--submitter', default=None)
    #patchset-created
    parser.add_argument('--uploader', default=None)
    parser.add_argument('--patchset', default=None)
    # Not passed by gerrit:
    parser.add_argument('--impact', default=None)
    parser.add_argument('--dest-address', default=None)

    args = parser.parse_args()

    # Get git log
    git_log = extract_git_log(args)

    # Process impacts found in git log
    if impacted(git_log, args.impact):
        process_impact(git_log, args)

if __name__ == "__main__":
    main()
