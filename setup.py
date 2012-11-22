# Copyright (c) 2012 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import setuptools


from gerritx.openstack.common import setup
from gerritx.version import version_info as version

requires = setup.parse_requirements()
tests_require = setup.parse_requirements(['tools/test-requires'])
depend_links = setup.parse_dependency_links()


def read_file(file_name):
    return open(os.path.join(os.path.dirname(__file__), file_name)).read()


setuptools.setup(
    name="gerritx",
    version=version.canonical_version_string(always=True),
    author='Hewlett-Packard Development Company, L.P.',
    author_email='openstack@lists.launchpad.net',
    description="Tools for managing gerrit projects and external sources.",
    license="Apache License, Version 2.0",
    url="https://github.com/openstack-ci/gerritx",
    packages=setuptools.find_packages(exclude=['tests', 'tests.*']),
    include_package_data=True,
    setup_requires=['setuptools_git>=0.4'],
    cmdclass=setup.get_cmdclass(),
    install_requires=requires,
    dependency_links=depend_links,
    tests_require=tests_require,
    test_suite="nose.collector",
    classifiers=[
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Intended Audience :: Information Technology",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
        "Programming Language :: Python"
    ],
    entry_points={
        'console_scripts': [
            'close-pull-requests=gerritx.cmd.close_pull_requests:main',
            'expire-old-reviews=gerritx.cmd.expire_old_reviews:main',
            'fetch-remotes=gerritx.cmd.fetch_remotes:main',
            'manage-projects=gerritx.cmd.manage_projects:main',
            'notify-impact=gerritx.cmd.notify_impact:main',
            'run-mirror=gerritx.cmd.run_mirror:main',
            'update-blueprint=gerritx.cmd.update_blueprint:main',
            'update-bug=gerritx.cmd.update_bug:main',
        ],
    }
)
