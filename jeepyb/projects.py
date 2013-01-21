#! /usr/bin/env python
# Copyright (C) 2011 OpenStack, LLC.
# Copyright (C) 2012, 2013 Hewlett-Packard Development Company, L.P.
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


import yaml


def get_projects(registry_file):
    """
    This reads a project registry file which should look like:

    gerrit-defaults:
      acl-dir: /home/gerrit2/acls
      host: review.openstack.org
      key: /home/gerrit2/review_site/etc/ssh_host_rsa_key
      local-git-dir: /var/lib/git
      user: openstack-project-creator
    github-defaults:
      config: /etc/github/github-projects.secure.config
    project-defaults:
      homepage: http://www.openstack.org/
      options: []
    ---
    ONE_PROJECT_NAME:
      acl-append:
        - /path/to/gerrit/project.config
      acl-base: /home/gerrit2/acls/project.config
      description: This is a great project.
      homepage: Some homepage that isn't http://www.openstack.org/
      launchpad: someproject
      options:
       - has-downloads
       - has-issues
       - has-pull-requests
       - has-wiki
       - no-lp-bugs
       - release-on-merge
      remote: https://gerrit.googlesource.com/gerrit
      upstream: git://github.com/bushy/beards.git
    ANOTHER_PROJECT_NAME:
      acl-parameters:
        project: SOME_PROJECT_NAME
      description: This is an even greater project.
    """

    configs = [config for config in yaml.load_all(open(registry_file))]
    if len(configs) == 2:
        # two sections means the first one contains defaults
        configured_defaults = configs[0]
        projects = configs[1]
    else:
        # only one means there are no configured defaults
        configured_defaults = {}
        projects = configs[0]

    # start with some builtin defaults for safety
    builtin_defaults = {
        'gerrit-defaults': {
            'acl-dir': '/home/gerrit2/acls',
            'host': 'review.openstack.org',
            'key': '/home/gerrit2/review_site/etc/ssh_host_rsa_key',
            'local-git-dir': '/var/lib/git',
            'user': 'openstack-project-creator',
        },
        'github-defaults': {
            'config': '/etc/github/github-projects.secure.config',
        },
        'project-defaults': {
            'acl-append': [],
            'acl-base': None,
            'acl-parameters': {},
            'homepage': 'http://www.openstack.org/',
            'options': [],
        }
    }

    # override the builtin defaults with any provided in the registry file
    defaults = {}
    for section in builtin_defaults:
        defaults[section] = dict(
            list(builtin_defaults[section].items())
            + list(configured_defaults.get(section, {}).items())
        )

    # build the project registry
    registry = {}
    for project in projects:
        registry[project] = dict(
            list(defaults['project-defaults'].items())
            + list(projects[project].items())
        )
        if 'acl-config' not in registry[project]:
            registry[project]['acl-config'] = '%s.config' % os.path.join(
                defaults['gerrit-defaults']['acl-dir'], project)

    return (defaults, registry)
