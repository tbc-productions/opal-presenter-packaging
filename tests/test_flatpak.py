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
    (tmp_path / 'openlp').mkdir()
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
    manifest.write_text("modules:\n  - name: OpalPresenter\n    sources:\n      - type: git\n        url: https://example.invalid/source.git\n        tag: old\n      - type: file\n        path: metadata.xml\n")
    monkeypatch.setattr(builder, 'get_base_path', lambda: tmp_path)
    source = tmp_path / 'source'
    builder.update_build_yml('4.0.4', '', '', source)
    sources = YAML().load(manifest)['modules'][0]['sources']
    assert sources == [{'type': 'dir', 'path': str(source)}, {'type': 'file', 'path': 'metadata.xml'}]


@pytest.mark.parametrize('codes,success', [([0, 0, 0], True), ([1], False), ([0, 1], False), ([0, 0, 1], False)])
def test_successful_bundle_returns_true(builder, monkeypatch, tmp_path, codes, success):
    (tmp_path / 'flatpak').mkdir()
    monkeypatch.setattr(builder, 'get_base_path', lambda: tmp_path)
    monkeypatch.setattr(builder.requests, 'get', lambda *args: SimpleNamespace(text='generator'))
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=codes[len(calls) - 1])
    monkeypatch.setattr(builder, 'run', run)
    assert builder.build_flatpak('4.0.4', '1') is success
    assert len(calls) == len(codes)
