# -*- coding: utf-8 -*-
# vim: autoindent shiftwidth=4 expandtab textwidth=120 tabstop=4 softtabstop=4

##########################################################################
# OpenLP - Open Source Lyrics Projection                                 #
# ---------------------------------------------------------------------- #
# Copyright (c) 2008 OpenLP Developers                                   #
# ---------------------------------------------------------------------- #
# This program is free software: you can redistribute it and/or modify   #
# it under the terms of the GNU General Public License as published by   #
# the Free Software Foundation, either version 3 of the License, or      #
# (at your option) any later version.                                    #
#                                                                        #
# This program is distributed in the hope that it will be useful,        #
# but WITHOUT ANY WARRANTY; without even the implied warranty of         #
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the          #
# GNU General Public License for more details.                           #
#                                                                        #
# You should have received a copy of the GNU General Public License      #
# along with this program.  If not, see <https://www.gnu.org/licenses/>. #
##########################################################################
"""
Flatpak Builder
===============

This is the script that builds the Flatpak

Requirements
------------

You will need the following requirements installed (these are the names of the Debian packages):

 - flatpak
 - flatpak builder
 - python3-requests
 - python3-requirements
 - python3-ruamel.yaml
 - python3-lxml

Running the script
------------------

If you're running this within the context of a GitLab CI pipeline, all you really need to do is provide the version
number to build. The script should pick up the environment variables present in job for the rest of the arguments.
For example:

.. code::

   python builders/flatpak-builder.py $CI_COMMIT_TAG


If you're running this outside of GitLab, you'll need te generate a private token for yourself, get the project ID of
the Opal Presenter repository, and run the script the following way:

.. code::

   python builders/flatpak-builder.py 3.1.6 --project 12345 --token gl1234abcd --token-type private


This generates a flatpak in the "flatpak" directory.
"""
import os
import runpy
import sys
from argparse import ArgumentParser, Namespace
from datetime import date
from hashlib import sha256
from pathlib import Path
from subprocess import run

import requests
from lxml import etree, objectify
from ruamel.yaml import YAML


FPG_URL = 'https://raw.githubusercontent.com/flatpak/flatpak-builder-tools/master/pip/flatpak-pip-generator.py'
RUNTIME = 'org.freedesktop.Sdk//26.08'
IGNORE_VERSIONS = ['3.1.5', '3.1.4', '3.1.0', '3.1.0rc4', '3.1.0rc3', '3.1.0rc2', '3.1.0rc1', '3.0.2', '3.0.1',
                   '3.0.0', '2.9.5', '2.9.4', '2.9.3', '2.9.2', '2.9.1', '2.9.0']


def parse_args() -> Namespace:
    """Parse the command line arguments"""
    parser = ArgumentParser()
    parser.add_argument('version', help='The version to build a Flatpak for')
    parser.add_argument('--branch', type=Path, help='Use an existing source checkout instead of downloading a release')
    parser.add_argument('--project', '-p', help='The project ID from GitLab')
    parser.add_argument('--token', '-t', help='The GitLab API token for authentication')
    parser.add_argument('--token-type', default='ci', help='The type of token, "ci" or "private", defaults to "ci"')
    parser.add_argument('--bundle', '-b', default='1', help='The bundle number, defaults to 1')
    return parser.parse_args()


def get_base_path() -> Path:
    """Return the base path of the repository"""
    return Path(__file__).parent.joinpath('..').absolute()


def get_yaml():
    """Return a standardised YAML object"""
    yaml = YAML(pure=True)
    yaml.sequence_indent = 4                                                    # type: ignore[assignment]
    yaml.sequence_dash_offset = 2
    yaml.explicit_start = False                                                 # type: ignore[assignment]
    return yaml


def use_environment(args: Namespace):
    """Populate the args object with environment variables"""
    if not args.token and os.environ.get('CI_JOB_TOKEN'):
        args.token = os.environ['CI_JOB_TOKEN']
    if not args.project and os.environ.get('CI_PROJECT_ID'):
        args.project = os.environ['CI_PROJECT_ID']


def get_releases(project_id: str, api_token: str, token_type: str) -> list[tuple[str, str, str]]:
    """Get public Opal releases and their dates from GitHub

    The legacy authentication arguments are retained for callers but are not
    sent to the public API.

    :return: A list of tuples, in the format (tag, date, link-to-tarball)
    """
    response = requests.get('https://api.github.com/repos/tbc-productions/opal-presenter/releases',
                            timeout=30)
    response.raise_for_status()
    return [(release['tag_name'], release['published_at'][:10],
             'https://github.com/tbc-productions/opal-presenter/archive/refs/tags/' + release['tag_name'] + '.tar.gz')
            for release in response.json() if not release.get('draft') and not release.get('prerelease')]


def get_version_url(version: str, releases: list[tuple]) -> str:
    """Loop through the releases and get the link to the tarball for the selected version"""
    for (tag, _, url) in releases:
        if tag == version:
            return url
    return ''


def download_and_get_hash(version_url: str) -> str:
    """Download the file and generate a hash"""
    hasher = sha256()
    with requests.get(version_url, stream=True) as r:
        r.raise_for_status()
        for chunk in r.iter_content(chunk_size=8192):
            hasher.update(chunk)
    return hasher.hexdigest()


def update_appdata_xml(releases: list[tuple]) -> bool:
    """Update the releases in the appdata XML"""
    appdata_file = get_base_path().joinpath('flatpak', 'net.tbcproductions.OpalPresenter.appdata.xml')
    el = objectify.E
    with appdata_file.open('r') as fd:
        xml = objectify.parse(fd)
    component = xml.getroot()
    component.releases.clear()
    for release in releases:
        if release[0] in IGNORE_VERSIONS:
            continue
        component.releases.append(el.release(version=f'{release[0]}-1', date=release[1]))
    objectify.deannotate(component, cleanup_namespaces=True)
    with appdata_file.open('w') as fd:
        fd.write(etree.tostring(component, encoding='utf8', xml_declaration=True, pretty_print=True).decode('utf8'))
    return True


def update_build_yml(version: str, version_url: str, sha256_hash: str, source_path: Path | None = None) -> bool:
    """Build the YAML file needed to build the flatpak"""
    yaml = get_yaml()
    build_file = get_base_path().joinpath('flatpak', 'net.tbcproductions.OpalPresenter.yml')
    with build_file.open('r') as fd:
        opal_yml = yaml.load(fd)
    for module in opal_yml['modules']:
        if isinstance(module, dict) and module['name'] == 'OpalPresenter':
            module.setdefault('build-options', {}).setdefault('env', {})['SETUPTOOLS_SCM_PRETEND_VERSION'] = version
            for source in module['sources']:
                if source.get('dest') == 'fluentqt':
                    if source_path is not None:
                        config = runpy.run_path(str(source_path / 'scripts/build_fluentqt.py'))
                        source.update(url=config['SOURCE_URL'], commit=config['SOURCE_REVISION'])
                elif source.get('dest') == 'qt':
                    source['path'] = str(get_base_path().joinpath('flatpak', 'qt').resolve())
                elif source_path is not None and source['type'] in ('git', 'archive', 'dir'):
                    source.clear()
                    source.update(type='dir', path=str(source_path.resolve()),
                                  skip=['.git', '.venv', '.cache', 'build', 'dist'])
                elif source['type'] == 'git':
                    source['tag'] = version
                elif source['type'] == 'archive':
                    source['url'] = version_url
                    source['sha256'] = sha256_hash
    yaml.dump(opal_yml, build_file)
    return True


def build_flatpak(version: str, bundle: str, source_path: Path | None = None):
    """Build the flatpak"""
    base_path = get_base_path()
    response = requests.get(FPG_URL, timeout=30)
    response.raise_for_status()
    fpg_path = base_path.joinpath('flatpak', 'flatpak-pip-generator')
    with fpg_path.open('w') as fpg:
        # shortcut: use SDK pip's vendored wheel tags until the SDK exposes packaging.
        fpg.write(response.text.replace('from packaging import tags;', 'from pip._vendor.packaging import tags;'))
    runtime_options = ['--runtime', RUNTIME, '--wheel-arches', 'x86_64', '--prefer-wheels',
                       'PySide6,PySide6-Addons,PySide6-Essentials,shiboken6,shiboken6-generator,PySide6-QtAds,'
                       'numpy,pillow,lxml,imagecodecs,imageio-ffmpeg,patchelf']
    env = dict(os.environ, FLATPAK_PIP_GENERATOR_ALLOW_RESTRICTED_MODULES='1')
    dependencies = ['--requirements-file', 'requirements.txt']
    config = {'QT_VERSION': '6.11.1'}
    if source_path is not None:
        dependencies = ['--pyproject-file', str(source_path.resolve() / 'pyproject.toml'), '--ignore-pkg', 'FluentQt']
        config = runpy.run_path(str(source_path / 'scripts/build_fluentqt.py'))
    result = run([sys.executable, '-m', 'aqt', 'install-qt', 'linux', 'desktop',
                  config['QT_VERSION'], 'linux_gcc_64', '--archives', 'qtbase',
                  '-O', str(base_path / 'flatpak' / 'qt')])
    if result.returncode != 0:
        return False
    result = run([sys.executable, str(fpg_path), *dependencies, *runtime_options,
                  '--output', 'python3-requirements'], cwd=str(base_path / 'flatpak'), env=env)
    if result.returncode != 0:
        return False
    result = run([sys.executable, str(fpg_path), 'shiboken6_generator==6.11.1', 'pip', 'wheel', 'setuptools',
                  'patchelf', *runtime_options, '--output', 'python3-native-build'],
                 cwd=str(base_path / 'flatpak'), env=env)
    if result.returncode != 0:
        return False
    result = run(['flatpak-builder', '--user', '--install', '--force-clean', '--repo=repo', 'build',
                  'net.tbcproductions.OpalPresenter.yml'], cwd=str(base_path / 'flatpak'))
    if result.returncode != 0:
        return False
    result = run(['flatpak', '--user', 'run', '--command=python3', '--env=QT_QPA_PLATFORM=offscreen',
                  'net.tbcproductions.OpalPresenter', '-c',
                  'import sys, opal.core.app, fluentqt; from PySide6 import QtCore, QtWidgets, QtWebEngineWidgets; '
                  'assert sys.version_info[:2] == (3, 14); assert QtCore.qVersion() == "6.11.1"; '
                  'app = QtWidgets.QApplication([]); assert fluentqt.Button("Opal"); '
                  'assert QtWebEngineWidgets.QWebEngineView; print("Flatpak startup imports and Qt 6.11.1 passed")'])
    if result.returncode != 0:
        return False
    result = run(['flatpak', 'build-bundle', '--runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo',
                  'repo', f'OpalPresenter-{version}-{bundle}.flatpak',
                  'net.tbcproductions.OpalPresenter'],
                 cwd=str(base_path / 'flatpak'))
    if result.returncode != 0:
        return False
    return True


def main() -> int:
    """The main entrypoint for the script"""
    args = parse_args()
    use_environment(args)
    if args.branch:
        if not (args.branch / 'opal').is_dir() or not (args.branch / 'pyproject.toml').is_file():
            print(f'Invalid source checkout: {args.branch}')
            return 2
        releases = [(args.version, date.today().isoformat(), '')]
        version_url, sha256_hash = '', ''
    else:
        releases = get_releases(args.project, args.token, args.token_type)
        if not releases:
            print(f'No releases found for project "{args.project}", aborting...')
            return 1
        version_url = get_version_url(args.version, releases)
        if not version_url:
            print(f'No URL found for version "{args.version}", aborting...')
            return 2
        sha256_hash = download_and_get_hash(version_url)
        if not sha256_hash:
            print(f'Unable to download "{version_url}" to generate hash, aborting...')
            return 3
    if not update_appdata_xml(releases):
        print('Unable to update the appdata XML file, aborting...')
        return 4
    if not update_build_yml(args.version, version_url, sha256_hash, args.branch):
        print('Unable to build YAML file, aborting...')
        return 5
    if not build_flatpak(args.version, args.bundle, args.branch):
        return 6
    return 0


if __name__ == '__main__':
    sys.exit(main())
