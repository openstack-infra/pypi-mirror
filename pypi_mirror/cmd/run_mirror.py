# Copyright (C) 2011-2013 OpenStack Foundation
# Copyright (C) 2013 Hewlett-Packard Development Company, L.P.
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

# run_mirror reads a YAML config file like:
#   cache-root: /tmp/cache
#
#   mirrors:
#     - name: openstack
#       projects:
#         - https://git.openstack.org/openstack/requirements
#       output: /tmp/mirror/openstack
#
#     - name: openstack-infra
#       projects:
#         - https://git.openstack.org/openstack-infra/config
#       output: /tmp/mirror/openstack-infra
#
# The algorithm it attempts to follow is:
#
# for each project:
#   clone if necessary and fetch origin
#   for each project-branch:
#     create new virtualenv
#     pip install reqs into virtualenv
#     if installation succeeds:
#       pip freeze > full-reqs
#       create new virtualenv
#       pip install (download only) full-reqs into virtualenv
#
# By default only summary information is printed on stdout (see the
# -d command line option to get more debug info).
#
# If "pip install" for a branch's requirements fails to complete
# (based on parsing of its output), that output will be copied to
# stderr and the script will skip ahead to the next branch. This
# makes it suitable for running in a cron job with only stdout
# redirected to a log, and also avoids one broken project preventing
# caching of requirements for others.
from __future__ import print_function

import argparse
import datetime
import functools
import md5
import os
import pkginfo
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib
import yaml


class Mirror(object):
    def __init__(self):
        parser = argparse.ArgumentParser(
            description='Build a pypi mirror from requirements')
        parser.add_argument('-b', dest='branch',
                            help='restrict run to a specified branch')
        parser.add_argument('-c', dest='config', required=True,
                            help='specify the config file')
        parser.add_argument('-n', dest='noop', action='store_true',
                            help='do not run any commands')
        parser.add_argument('-r', dest='reqlist', action='append',
                            help='specify alternative requirements file(s)')
        parser.add_argument('--no-pip', dest='no_pip', action='store_true',
                            help='do not run any pip commands')
        parser.add_argument('--verbose', dest='debug', action='store_true',
                            help='output verbose debug information')
        parser.add_argument('--no-download', dest='no_download',
                            action='store_true',
                            help='only process the pip cache into a mirror '
                            '(do not download)')
        parser.add_argument('--no-process', dest='no_process',
                            action='store_true',
                            help='only download into the pip cache '
                            '(do not process the cache into a mirror)')
        parser.add_argument('--no-update', dest='no_update',
                            action='store_true',
                            help='do not update any git repos')
        parser.add_argument('--export', dest='export_file',
                            default=None,
                            help='export installed package list to a file '
                            '(must be absolute path)')
        self.args = parser.parse_args()
        self.config = yaml.load(open(self.args.config))

    def run_command(self, *cmd_strs, **kwargs):
        env = kwargs.pop('env', None)
        if kwargs:
            badargs = ','.join(kwargs.keys())
            raise TypeError(
                "run_command() got unexpected keyword arguments %s" % badargs)

        cmd_list = []
        for cmd_str in cmd_strs:
            cmd_list.extend(shlex.split(str(cmd_str)))
        self.debug("Run: %s" % " ".join(cmd_strs))
        if self.args.noop:
            return ''
        if self.args.no_pip and cmd_list[0].endswith('pip'):
            return ''
        p = subprocess.Popen(cmd_list, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, env=env)
        (out, nothing) = p.communicate()
        out = out.strip()
        self.debug(out)
        return out

    def run(self):
        for mirror in self.config['mirrors']:
            if not self.args.no_download:
                self.build_mirror(mirror)
            if not self.args.no_process:
                self.process_cache(mirror)

    def chdir(self, dest):
        self.debug("cd %s" % dest)
        if not self.args.noop:
            os.chdir(dest)

    def debug(self, msg):
        if self.args.debug:
            print(msg)

    def process_http_requirements(self, reqlist, pip_cache_dir, pip):
        new_reqs = []
        for reqfile in reqlist:
            for req in open(reqfile):
                req = req.strip()
                # Handle http://, https://, and git+https?://
                if not re.search('https?://', req):
                    new_reqs.append(req)
                    continue
                target_url = req.split('#', 1)[0]
                target_file = os.path.join(pip_cache_dir,
                                           urllib.quote(target_url, ''))
                if os.path.exists(target_file):
                    self.debug("Unlink: %s" % target_file)
                    os.unlink(target_file)
                if os.path.exists(target_file + '.content-type'):
                    self.debug("Unlink: %s.content-type" % target_file)
                    os.unlink(target_file + '.content-type')
        return new_reqs

    def find_pkg_info(self, path):
        versions = set()
        for root, dirs, files in os.walk(path):
            if not root.endswith('.egg'):
                continue
            if not os.path.exists(os.path.join(root, 'EGG-INFO', 'PKG-INFO')):
                continue
            package = pkginfo.Develop(root)
            versions.add('%s==%s' % (package.name, package.version))
        return versions

    def build_mirror(self, mirror):
        print("Building mirror: %s" % mirror['name'])
        pip_format = (
            "%(pip)s install -U %(extra_args)s --exists-action=w"
            " --download-cache=%(download_cache)s"
            " --build %(build_dir)s -f %(find_links)s"
            " --no-use-wheel"
            " -r %(requirements_file)s")
        venv_format = (
            "virtualenv --clear --extra-search-dir=%(extra_search_dir)s"
            " %(venv_dir)s")
        upgrade_format = (
            "%(pip)s install -U --exists-action=w"
            " --download-cache=%(download_cache)s --build %(build_dir)s"
            " -f %(find_links)s %(requirement)s")
        wheel_file_format = (
            "%(pip)s wheel --download-cache=%(download_cache)s"
            " --wheel-dir %(wheel_dir)s -f %(find_links)s"
            " -r %(requirements_file)s")
        wheel_format = (
            "%(pip)s wheel --download-cache=%(download_cache)s"
            " -f %(find_links)s --wheel-dir %(wheel_dir)s %(requirement)s")

        workdir = tempfile.mkdtemp()
        reqs = os.path.join(workdir, "reqs")
        venv = os.path.join(workdir, "venv")
        build = os.path.join(workdir, "build")
        pip = os.path.join(venv, "bin", "pip")

        project_cache_dir = os.path.join(self.config['cache-root'],
                                         'projects')
        pip_cache_dir = os.path.join(self.config['cache-root'],
                                     'pip', mirror['name'])
        wheelhouse = os.path.join(self.config['cache-root'], "wheelhouse")
        if not self.args.noop:
            for new_dir in (project_cache_dir, pip_cache_dir, wheelhouse):
                if not os.path.exists(new_dir):
                    os.makedirs(new_dir)

        for project in mirror['projects']:
            print("Updating repository: %s" % project)
            self.chdir(project_cache_dir)
            short_project = project.split('/')[-1]
            if short_project.endswith('.git'):
                short_project = short_project[:-4]
            git_work_tree = os.path.join(project_cache_dir, short_project)
            if not os.path.isdir(git_work_tree):
                self.run_command("git clone %s %s" % (project, git_work_tree))
            self.chdir(git_work_tree)
            git = functools.partial(self.run_command, "git", env={
                "GIT_WORK_TREE": git_work_tree,
                "GIT_DIR": os.path.join(git_work_tree, ".git"),
            })
            git("fetch -p origin")

            if self.args.branch:
                branches = [self.args.branch]
            else:
                branches = git("branch -a").split("\n")
            for branch in branches:
                branch = branch.strip()
                if (not branch.startswith("remotes/origin")
                        or "origin/HEAD" in branch):
                    continue
                print("Fetching pip requires for %s:%s" % (project, branch))
                if not self.args.no_update:
                    git("reset --hard %s" % branch)
                    git("clean -x -f -d -q")
                if self.args.reqlist:
                    # Not filtering for existing files - they must all exist.
                    reqlist = self.args.reqlist
                elif os.path.exists('global-requirements.txt'):
                    reqlist = ['global-requirements.txt']
                else:
                    reqlist = [r for r in ["requirements.txt",
                                           "test-requirements.txt",
                                           "tools/pip-requires",
                                           "tools/test-requires"]
                               if os.path.exists(r)]
                if not reqlist:
                    print("no requirements")
                    continue

                self.run_command(
                    venv_format % dict(
                        extra_search_dir=pip_cache_dir, venv_dir=venv))
                for requirement in ["pip", "wheel", "virtualenv"]:
                    self.run_command(
                        upgrade_format % dict(
                            pip=pip, download_cache=pip_cache_dir,
                            build_dir=build, find_links=wheelhouse,
                            requirement=requirement))
                for requirement in [
                        "pip", "setuptools", "distribute", "virtualenv"]:
                    self.run_command(
                        wheel_format % dict(
                            pip=pip, download_cache=pip_cache_dir,
                            find_links=wheelhouse, wheel_dir=wheelhouse,
                            requirement=requirement))
                if os.path.exists(build):
                    shutil.rmtree(build)
                new_reqs = self.process_http_requirements(reqlist,
                                                          pip_cache_dir,
                                                          pip)
                (reqfp, reqfn) = tempfile.mkstemp()
                os.write(reqfp, '\n'.join(new_reqs))
                os.close(reqfp)
                self.run_command(
                    wheel_file_format % dict(
                        pip=pip, download_cache=pip_cache_dir,
                        find_links=wheelhouse, wheel_dir=wheelhouse,
                        requirements_file=reqfn))
                out = self.run_command(
                    pip_format % dict(
                        pip=pip, extra_args="",
                        download_cache=pip_cache_dir, build_dir=build,
                        find_links=wheelhouse, requirements_file=reqfn))
                if "\nSuccessfully installed " not in out:
                    sys.stderr.write("Installing pip requires for %s:%s "
                                     "failed.\n%s\n" %
                                     (project, branch, out))
                    print("pip install did not indicate success")
                    continue

                freeze = self.run_command("%s freeze -l" % pip)
                requires = self.find_pkg_info(build)
                reqfd = open(reqs, "w")
                for line in freeze.split("\n"):
                    if line.startswith("-e ") or (
                            "==" in line and " " not in line):
                        requires.add(line)
                for r in requires:
                    reqfd.write(r + "\n")
                reqfd.close()
                self.run_command(venv_format % dict(
                    extra_search_dir=pip_cache_dir, venv_dir=venv))
                for requirement in ["pip", "wheel"]:
                    self.run_command(
                        upgrade_format % dict(
                            pip=pip, download_cache=pip_cache_dir,
                            build_dir=build, find_links=wheelhouse,
                            requirement=requirement))
                if os.path.exists(build):
                    shutil.rmtree(build)
                self.run_command(
                    wheel_file_format % dict(
                        pip=pip, download_cache=pip_cache_dir,
                        find_links=wheelhouse, wheel_dir=wheelhouse,
                        requirements_file=reqs))
                out = self.run_command(
                    pip_format % dict(
                        pip=pip, extra_args="--no-install",
                        download_cache=pip_cache_dir, build_dir=build,
                        find_links=wheelhouse, requirements_file=reqs))
                if "\nSuccessfully downloaded " not in out:
                    sys.stderr.write("Downloading pip requires for "
                                     "%s:%s failed.\n%s\n" %
                                     (project, branch, out))
                    print("pip install did not indicate success")
                print("cached:\n%s" % freeze)
                # save the list of installed packages to a file
                if self.args.export_file:
                    print("Export installed package list to " +
                          self.args.export_file)
                    with open(self.args.export_file, "w") as package_list_file:
                        package_list_file.write(freeze)
        shutil.rmtree(workdir)

    def _get_distro(self):
        out = self.run_command('lsb_release -i -r -s')
        return out.strip().replace('\n', '-').replace(' ', '-')

    def process_cache(self, mirror):
        if self.args.noop:
            return

        self._write_tarball_mirror(mirror)
        self._write_wheel_mirror(mirror)

    def _write_tarball_mirror(self, mirror):
        pip_cache_dir = os.path.join(self.config['cache-root'],
                                     'pip', mirror['name'])
        destination_mirror = mirror['output']

        packages = {}
        package_count = 0

        for filename in os.listdir(pip_cache_dir):
            if filename.endswith('content-type'):
                continue

            realname = urllib.unquote(filename)
            # The ? accounts for sourceforge downloads
            tarball = os.path.basename(realname).split("?")[0]
            package_name = os.path.basename(os.path.dirname(realname))
            if not package_name:
                continue

            version_list = packages.get(package_name, {})
            version_list[tarball] = os.path.join(pip_cache_dir, filename)
            packages[package_name] = version_list
            package_count = package_count + 1
        self._write_mirror(destination_mirror, packages, package_count)

    def _write_wheel_mirror(self, mirror):

        distro = self._get_distro()
        wheelhouse = os.path.join(self.config['cache-root'], "wheelhouse")
        wheel_destination_mirror = os.path.join(mirror['output'], distro)
        packages = {}
        package_count = 0

        for filename in os.listdir(wheelhouse):
            package_name = filename.split('-')[0].replace('_', '-')
            version_list = packages.get(package_name, {})
            version_list[filename] = os.path.join(wheelhouse, filename)
            packages[package_name] = version_list
            package_count = package_count + 1
        self._write_mirror(wheel_destination_mirror, packages, package_count)

    def _write_mirror(self, destination_mirror, packages, package_count):
        full_html_line = "<a href='{dir}/{name}'>{name}</a><br />\n"

        if not os.path.exists(destination_mirror):
            os.makedirs(destination_mirror)

        full_html = open(os.path.join(destination_mirror, ".full.html"), 'w')
        simple_html = open(os.path.join(destination_mirror, ".index.html"),
                           'w')

        header = ("<html><head><title>PyPI Mirror</title></head>"
                  "<body><h1>PyPI Mirror</h1><h2>Last update: %s</h2>\n\n"
                  % datetime.datetime.utcnow().strftime("%c UTC"))
        full_html.write(header)
        simple_html.write(header)

        for package_name, versions in packages.items():
            destination_dir = os.path.join(destination_mirror, package_name)
            if not os.path.isdir(destination_dir):
                os.makedirs(destination_dir)
            safe_dir = urllib.quote(package_name)
            simple_html.write("<a href='%s'>%s</a><br />\n" %
                              (safe_dir, safe_dir))
            with open(os.path.join(destination_dir, ".index.html"),
                      'w') as index:
                index.write("""<html><head>
          <title>%s &ndash; PyPI Mirror</title>
        </head><body>\n""" % package_name)
                for tarball, source_path in versions.items():
                    destination_path = os.path.join(destination_dir,
                                                    tarball)
                    dot_destination_path = os.path.join(destination_dir,
                                                        '.' + tarball)
                    with open(dot_destination_path, 'w') as dest:
                        src = open(source_path, 'r').read()
                        md5sum = md5.md5(src).hexdigest()
                        dest.write(src)

                        safe_name = urllib.quote(tarball)

                        full_html.write(full_html_line.format(dir=safe_dir,
                                                              name=safe_name))
                        index.write("<a href='%s#md5=%s'>%s</a>\n" %
                                    (safe_name, md5sum, safe_name))
                    os.rename(dot_destination_path, destination_path)
                index.write("</body></html>\n")
            os.rename(os.path.join(destination_dir, ".index.html"),
                      os.path.join(destination_dir, "index.html"))
        footer = """<p class='footer'>Generated by process_cache.py; %d
        packages mirrored. </p>
        </body></html>\n""" % package_count
        full_html.write(footer)
        full_html.close()
        os.rename(os.path.join(destination_mirror, ".full.html"),
                  os.path.join(destination_mirror, "full.html"))
        simple_html.write(footer)
        simple_html.close()
        os.rename(os.path.join(destination_mirror, ".index.html"),
                  os.path.join(destination_mirror, "index.html"))


def main():
    mb = Mirror()
    mb.run()
