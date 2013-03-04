#! /usr/bin/env python
# Copyright (C) 2011 OpenStack, LLC.
# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
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

# run_mirrors reads a project config file called projects.yaml
# It should look like:
#
# - project: PROJECT_NAME
#
# The algorithm it attempts to follow is:
#
# for each project in projects.yaml:
#   clone if necessary and fetch origin
#   for each project-branch:
#     create new virtualenv
#     pip install reqs into virtualenv
#     if installation succeeds:
#       pip freeze > full-reqs
#       create new virtualenv
#       pip install (download only) full-reqs into virtualenv
#
# By default only summary information is printed on stdout, but if
# DEFAULT is enabled in the calling environment then stdout of all
# shell commands run is also printed. Due to its copiousness and
# buffering, however, DEBUG level output is best suited to file
# redirection.
#
# If "pip install" for a branch's requirements fails to complete
# (based on parsing of its output), that output will be copied to
# stderr and the script will skip ahead to the next branch. This
# makes it suitable for running in a cron job with only stdout
# redirected to a log, and also avoids one broken project preventing
# caching of requirements for others.

import os
import subprocess
import shlex
import shutil
import sys
import tempfile
import yaml


def run_command(cmd):
    cmd_list = shlex.split(str(cmd))
    p = subprocess.Popen(cmd_list, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    (out, nothing) = p.communicate()
    return out.strip()


def main():

    DEBUG = True if os.environ.get('DEBUG', '').lower() in ('enabled',
                                                            'enable',
                                                            'true',
                                                            'yes',
                                                            'on',
                                                            '1') else False
    PROJECTS_YAML = os.environ.get('PROJECTS_YAML',
                                   '/etc/openstackci/projects.yaml')
    PIP_TEMP_DOWNLOAD = os.environ.get('PIP_TEMP_DOWNLOAD',
                                       '/var/lib/pip-download')
    PIP_DOWNLOAD_CACHE = os.environ.get('PIP_DOWNLOAD_CACHE',
                                        '/var/cache/pip')
    GIT_SOURCE = os.environ.get('GIT_SOURCE', 'https://github.com')
    pip_format = "%s install -M -U %s --exists-action=w -b %s -r %s"
    venv_format = ("/usr/local/bin/virtualenv --clear --distribute "
                   "--extra-search-dir=%s %s")

    (defaults, config) = [config for config in
                          yaml.load_all(open(PROJECTS_YAML))]

    workdir = tempfile.mkdtemp()
    reqs = os.path.join(workdir, "reqs")
    venv = os.path.join(workdir, "venv")
    pip = os.path.join(venv, "bin", "pip")

    for section in config:
        project = section['project']
        if DEBUG:
            print("*********************\nupdating %s repository" % project)

        os.chdir(PIP_TEMP_DOWNLOAD)
        short_project = project.split('/')[1]
        if not os.path.isdir(short_project):
            out = run_command("git clone %s/%s.git %s" % (GIT_SOURCE, project,
                                                          short_project))
            if DEBUG:
                print(out)
        os.chdir(short_project)
        out = run_command("git fetch origin")
        if DEBUG:
            print(out)

        for branch in run_command("git branch -a").split("\n"):
            branch = branch.strip()
            if (not branch.startswith("remotes/origin")
                    or "origin/HEAD" in branch):
                continue
            print("*********************")
            print("Fetching pip requires for %s:%s" % (project, branch))
            out = run_command("git reset --hard %s" % branch)
            if DEBUG:
                print(out)
            out = run_command("git clean -x -f -d -q")
            if DEBUG:
                print(out)
            reqlist = []
            for requires_file in ("requirements.txt",
                                  "test-requirements.txt",
                                  "tools/pip-requires",
                                  "tools/test-requires"):
                if os.path.exists(requires_file):
                    reqlist.append(requires_file)
            if reqlist:
                out = run_command(venv_format % (PIP_DOWNLOAD_CACHE, venv))
                if DEBUG:
                    print(out)
                out = run_command(pip_format % (pip, "", PIP_DOWNLOAD_CACHE,
                                                " -r ".join(reqlist)))
                if DEBUG:
                    print(out)
                if "\nSuccessfully installed " not in out:
                    sys.stderr.write(out)
                    print("pip install did not indicate success")
                else:
                    freeze = run_command("%s freeze -l" % pip)
                    reqfd = open(reqs, "w")
                    for line in freeze.split("\n"):
                        if "==" in line:
                            reqfd.write(line + "\n")
                    reqfd.close()
                    out = run_command(venv_format % (PIP_DOWNLOAD_CACHE, venv))
                    if DEBUG:
                        print(out)
                    out = run_command(pip_format % (pip, "--no-install",
                                      PIP_DOWNLOAD_CACHE, reqs))
                    if DEBUG:
                        print(out)
                    if "\nSuccessfully installed " not in out:
                        sys.stderr.write(out)
                        print("pip install did not indicate success")
                    print("cached:\n%s" % freeze)
            else:
                print("no requirements")

    shutil.rmtree(workdir)
