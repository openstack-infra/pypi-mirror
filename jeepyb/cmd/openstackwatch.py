#!/usr/bin/env python
# Copyright (c) 2013 Chmouel Boudjnah, eNovance
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

# This script is designed to generate rss feeds for subscription from updates
# to various gerrit tracked projects. It is intended to be run periodically,
# for example hourly via cron. It takes an optional argument to specify the
# path to a configuration file.
# -*- encoding: utf-8 -*-
__author__ = "Chmouel Boudjnah <chmouel@chmouel.com>"
import json
import datetime
import os
import sys
import time
import cStringIO
import ConfigParser
import urllib

import PyRSS2Gen

PROJECTS = ['openstack/nova', 'openstack/keystone', 'opensack/swift']
JSON_URL = 'https://review.openstack.org/query'
DEBUG = False
OUTPUT_MODE = 'multiple'

curdir = os.path.dirname(os.path.realpath(sys.argv[0]))


class ConfigurationError(Exception):
    pass


def get_config(config, section, option, default=None):
    if not config.has_section(section):
        raise ConfigurationError("Invalid configuration, missing section: %s" %
                                 section)
    if config.has_option(section, option):
        return config.get(section, option)
    elif not default is None:
        return default
    else:
        raise ConfigurationError("Invalid configuration, missing "
                                 "section/option: %s/%s" % (section, option))


def parse_ini(inifile):
    ret = {}
    if not os.path.exists(inifile):
        return
    config = ConfigParser.RawConfigParser(allow_no_value=True)
    config.read(inifile)

    if config.has_section('swift'):
        ret['swift'] = dict(config.items('swift'))

    ret['projects'] = get_config(config, 'general', 'projects', PROJECTS)
    if type(ret['projects']) is not list:
        ret['projects'] = [x.strip() for x in ret['projects'].split(',')]
    ret['json_url'] = get_config(config, 'general', 'json_url', JSON_URL)
    ret['debug'] = get_config(config, 'general', 'debug', DEBUG)
    ret['output_mode'] = get_config(config, 'general', 'output_mode',
                                    OUTPUT_MODE)
    return ret

try:
    conffile = sys.argv[1]
except IndexError:
    conffile = os.path.join(curdir, '..', 'config', 'openstackwatch.ini')
CONFIG = parse_ini(conffile)


def debug(msg):
    if DEBUG:
        print msg


def get_javascript(project=None):
    url = CONFIG['json_url']
    if project:
        url += "+project:" + project
    fp = urllib.urlretrieve(url)
    ret = open(fp[0]).read()
    return ret


def parse_javascript(javascript):
    for row in javascript.splitlines():
        try:
            json_row = json.loads(row)
        except(ValueError):
            continue
        if not json_row or not 'project' in json_row or \
                json_row['project'] not in CONFIG['projects']:
            continue
        yield json_row


def upload_rss(xml, output_object):
    if not 'swift' in CONFIG:
        print xml
        return

    import swiftclient
    cfg = CONFIG['swift']
    client = swiftclient.Connection(cfg['auth_url'],
                                    cfg['username'],
                                    cfg['password'],
                                    auth_version=cfg.get('auth_version',
                                                         '2.0'))
    try:
        client.get_container(cfg['container'])
    except(swiftclient.client.ClientException):
        client.put_container(cfg['container'])
        # eventual consistenties
        time.sleep(1)

    client.put_object(cfg['container'], output_object,
                      cStringIO.StringIO(xml))


def generate_rss(javascript, project=""):
    title = "OpenStack %s watch RSS feed" % (project)
    rss = PyRSS2Gen.RSS2(
        title=title,
        link="http://github.com/chmouel/openstackwatch.rss",
        description="The latest reviews about Openstack, straight "
                    "from Gerrit.",
        lastBuildDate=datetime.datetime.now()
    )
    for row in parse_javascript(javascript):
        author = row['owner']['name']
        author += " <%s>" % ('email' in row['owner'] and
                             row['owner']['email']
                             or row['owner']['username'])
        rss.items.append(
            PyRSS2Gen.RSSItem(
                title="%s [%s]: %s" % (os.path.basename(row['project']),
                                       row['status'],
                                       row['subject']),
                author=author,
                link=row['url'],
                guid=PyRSS2Gen.Guid(row['id']),
                description=row['subject'],
                pubDate=datetime.datetime.fromtimestamp(row['lastUpdated']),
            ))
    return rss.to_xml()


def main():
    if CONFIG['output_mode'] == "combined":
        upload_rss(generate_rss(get_javascript()),
                   CONFIG['swift']['combined_output_object'])
    elif CONFIG['output_mode'] == "multiple":
        for project in CONFIG['projects']:
            upload_rss(
                generate_rss(get_javascript(project), project=project),
                "%s.xml" % (os.path.basename(project)))

if __name__ == '__main__':
    main()
