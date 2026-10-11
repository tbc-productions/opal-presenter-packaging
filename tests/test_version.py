"""Exercise version conversion in the Windows builder used for release MSIs."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def windows_builder(monkeypatch):
    builders = Path(__file__).parents[1] / 'builders'
    monkeypatch.syspath_prepend(str(builders))
    spec = importlib.util.spec_from_file_location('windows_builder', builders / 'windows-builder.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.WindowsBuilder.__new__(module.WindowsBuilder)


@pytest.mark.parametrize('pep440_version, windows_version', [
    ('2.9.1', '2.9.1.5000'), ('3.1rc1', '3.1.0.3001'), ('3.0.2b2', '3.0.2.2002'),
    ('1.9a1', '1.9.0.1001'), ('4.0.4a2', '4.0.4.1002'),
])
def test_pep440_to_windows_version(windows_builder, pep440_version, windows_version):
    assert windows_builder._pep440_to_windows_version(pep440_version) == windows_version


@pytest.mark.parametrize('version,filename_version', [
    ('4.0.4a2', '4.0.4a2'), ('v4.0.4a2', '4.0.4a2'), ('4.0.4a2+g12345', '4.0.4a2'),
])
def test_prerelease_download_filename(windows_builder, version, filename_version):
    windows_builder.version = version
    assert windows_builder.filename_version_slug() == filename_version
