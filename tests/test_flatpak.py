"""Exercise the source-checkout route used by the Linux release workflow."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from ruamel.yaml import YAML


@pytest.fixture
def builder():
    path = Path(__file__).parents[1] / 'builders/flatpak-builder.py'
    spec = importlib.util.spec_from_file_location('flatpak_builder', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_workflow_checkout_routes_without_published_release(builder, monkeypatch, tmp_path):
    (tmp_path / 'opal').mkdir()
    (tmp_path / 'pyproject.toml').touch()
    monkeypatch.setattr('sys.argv', ['flatpak-builder.py', '--branch', str(tmp_path), '4.0.4'])
    monkeypatch.setattr(builder, 'get_releases', Mock(side_effect=AssertionError('No release lookup required')))
    appdata, manifest = Mock(return_value=True), Mock(return_value=True)
    monkeypatch.setattr(builder, 'update_appdata_xml', appdata)
    monkeypatch.setattr(builder, 'update_build_yml', manifest)
    monkeypatch.setattr(builder, 'build_flatpak', Mock(return_value=True))
    assert builder.main() == 0
    assert appdata.call_args.args[0][0][0] == '4.0.4'
    manifest.assert_called_once_with('4.0.4', '', '', tmp_path)


def test_invalid_checkout_fails_before_building(builder, monkeypatch, tmp_path):
    monkeypatch.setattr('sys.argv', ['flatpak-builder.py', '--branch', str(tmp_path), '4.0.4'])
    build = Mock()
    monkeypatch.setattr(builder, 'build_flatpak', build)
    assert builder.main() == 2
    build.assert_not_called()


def test_manifest_uses_authenticated_checkout(builder, monkeypatch, tmp_path):
    flatpak = tmp_path / 'flatpak'
    flatpak.mkdir()
    manifest = flatpak / 'net.tbcproductions.OpalPresenter.yml'
    manifest.write_text("modules:\n  - name: OpalPresenter\n    sources:\n      - type: git\n"
                        "        url: https://example.invalid/source.git\n        tag: old\n"
                        "      - type: file\n        path: metadata.xml\n")
    monkeypatch.setattr(builder, 'get_base_path', lambda: tmp_path)
    source = tmp_path / 'source'
    builder.update_build_yml('4.0.4', '', '', source)
    sources = YAML().load(manifest)['modules'][0]['sources']
    assert sources == [{'type': 'dir', 'path': str(source), 'skip': ['.git', '.venv', '.cache', 'build', 'dist']},
                       {'type': 'file', 'path': 'metadata.xml'}]
    assert YAML().load(manifest)['modules'][0]['build-options']['env']['SETUPTOOLS_SCM_PRETEND_VERSION'] == '4.0.4'


def test_public_releases_do_not_receive_private_credentials(builder, monkeypatch):
    response = Mock()
    response.json.return_value = [
        {'tag_name': '4.0.4', 'published_at': '2026-10-11T10:00:00Z', 'draft': False, 'prerelease': False},
        {'tag_name': '4.0.4a2', 'published_at': '2026-10-11T10:00:00Z', 'draft': False, 'prerelease': True},
    ]
    get = Mock(return_value=response)
    monkeypatch.setattr(builder.requests, 'get', get)
    assert builder.get_releases('unused', 'private-token', 'unused') == [
        ('4.0.4', '2026-10-11', 'https://github.com/tbc-productions/opal-presenter/archive/refs/tags/4.0.4.tar.gz')]
    get.assert_called_once_with('https://api.github.com/repos/tbc-productions/opal-presenter/releases', timeout=30)
    response.raise_for_status.assert_called_once()


@pytest.mark.parametrize('codes,success', [
    ([0, 0, 0, 0, 0, 0], True), ([1], False), ([0, 1], False), ([0, 0, 1], False),
    ([0, 0, 0, 1], False), ([0, 0, 0, 0, 1], False), ([0, 0, 0, 0, 0, 1], False),
])
def test_successful_bundle_returns_true(builder, monkeypatch, tmp_path, codes, success):
    (tmp_path / 'flatpak').mkdir()
    monkeypatch.setattr(builder, 'get_base_path', lambda: tmp_path)
    monkeypatch.setattr(builder.requests, 'get', lambda *args, **kwargs: Mock(text='from packaging import tags;'))
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=codes[len(calls) - 1])
    monkeypatch.setattr(builder, 'run', run)
    assert builder.build_flatpak('4.0.4', '1') is success
    assert len(calls) == len(codes)
    assert (tmp_path / 'flatpak/flatpak-pip-generator').read_text() == 'from pip._vendor.packaging import tags;'


def test_dependencies_come_from_the_tagged_project_and_matching_sdk(builder, monkeypatch, tmp_path):
    (tmp_path / 'flatpak').mkdir()
    source = tmp_path / 'source'
    (source / 'scripts').mkdir(parents=True)
    (source / 'scripts/build_fluentqt.py').write_text('QT_VERSION = "6.11.1"\n')
    monkeypatch.setattr(builder, 'get_base_path', lambda: tmp_path)
    monkeypatch.setattr(builder.requests, 'get', lambda *args, **kwargs: Mock(text='generator'))
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(builder, 'run', run)
    assert builder.build_flatpak('4.0.4a3', '1', source)
    assert 'linux_gcc_64' in calls[0]
    assert 'icu' in calls[0]
    assert '--pyproject-file' in calls[1]
    assert str(source / 'pyproject.toml') in calls[1]
    assert '--ignore-pkg' in calls[1] and 'FluentQt' in calls[1]
    assert builder.RUNTIME in calls[1]
    assert 'Qt 6.11.1 passed' in calls[-2][-1]
    assert 'OpalPresenter-4.0.4a3-1.flatpak' in calls[-1]
    assert '--runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo' in calls[-1]


def test_source_selection_rejects_python2_eggs(builder, monkeypatch, tmp_path):
    (tmp_path / 'flatpak').mkdir()
    generator = ('files = [{"filename": "odfpy-1.4.1-py2.7.egg", "packagetype": "bdist_egg"},\n'
                 '         {"filename": "odfpy-1.4.1.tar.gz", "packagetype": "sdist"}]\n'
                 'def find_sdist():\n'
                 '    return next((f for f in files if not f["filename"].endswith(".whl")), None)\n')
    monkeypatch.setattr(builder, 'get_base_path', lambda: tmp_path)
    monkeypatch.setattr(builder.requests, 'get', lambda *args, **kwargs: Mock(text=generator))
    monkeypatch.setattr(builder, 'run', Mock(return_value=SimpleNamespace(returncode=0)))
    assert builder.build_flatpak('4.0.4a3', '1')
    generated = builder.runpy.run_path(str(tmp_path / 'flatpak/flatpak-pip-generator'))
    assert generated['find_sdist']()['filename'] == 'odfpy-1.4.1.tar.gz'


def test_native_sources_keep_the_tagged_fluent_revision(builder, monkeypatch, tmp_path):
    flatpak = tmp_path / 'flatpak'
    flatpak.mkdir()
    manifest = flatpak / 'net.tbcproductions.OpalPresenter.yml'
    manifest.write_text('modules:\n  - name: OpalPresenter\n    sources:\n'
                        '      - type: git\n        url: https://example.invalid/opal.git\n        tag: old\n'
                        '      - type: dir\n        path: qt\n        dest: qt\n'
                        '      - type: git\n        url: old\n        commit: old\n        dest: fluentqt\n')
    source = tmp_path / 'source'
    (source / 'scripts').mkdir(parents=True)
    (source / 'scripts/build_fluentqt.py').write_text(
        'SOURCE_URL="https://example.invalid/fluent.git"\nSOURCE_REVISION="pinned-revision"\n')
    monkeypatch.setattr(builder, 'get_base_path', lambda: tmp_path)
    builder.update_build_yml('4.0.4a3', '', '', source)
    sources = YAML().load(manifest)['modules'][0]['sources']
    assert sources[0]['path'] == str(source)
    assert sources[1] == {'type': 'dir', 'path': str(flatpak / 'qt'), 'dest': 'qt'}
    assert sources[2] == {'type': 'git', 'url': 'https://example.invalid/fluent.git',
                          'commit': 'pinned-revision', 'dest': 'fluentqt'}
