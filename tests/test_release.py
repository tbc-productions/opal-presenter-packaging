"""Exercise release publication with fake network responses."""
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize('tag,expected', [
    ('4.0.4a2', 'true'), ('v4.0.4b1', 'true'), ('4.0.4rc1', 'true'),
    ('4.0.4.dev1', 'true'), ('4.0.4', 'false'), ('v4.0.4', 'false'),
])
def test_release_channel(tag, expected):
    workflow = (Path(__file__).parents[1] / '.gitea/workflows/build.yml').read_text()
    script = workflow.split('          PRERELEASE=false', 1)[1].split('          BODY=', 1)[0]
    result = subprocess.run(['bash', '-c', 'PRERELEASE=false\n' + script + '\necho "$PRERELEASE"'],
                            env={**os.environ, 'OPAL_TAG': tag}, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == expected


@pytest.mark.parametrize('results,draft,published,success', [
    (('success', 'success', 'success'), 'true', True, True),
    (('success', 'failure', 'success'), 'true', False, False),
    (('success', 'success', 'skipped'), 'false', False, True),
    (('skipped', 'skipped', 'skipped'), 'true', False, False),
])
def test_publish_only_completed_draft(tmp_path, results, draft, published, success):
    workflow = (Path(__file__).parents[1] / '.gitea/workflows/build.yml').read_text()
    script = workflow.split('      - name: Publish completed draft release', 1)[1].split('        run: |', 1)[1]
    script = '\n'.join(line[10:] for line in script.splitlines() if line.startswith('          '))
    for name, body in {
        'curl': '#!/bin/sh\necho "$*" >> "$CALLS"\nprintf \'{"draft":%s}\\n\' "$DRAFT"\n',
        'jq': '#!/bin/sh\ncat >/dev/null\necho "$DRAFT"\n',
    }.items():
        executable = tmp_path / name
        executable.write_text(body)
        executable.chmod(0o755)
    calls = tmp_path / 'calls'
    environment = {**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH'],
                   'MACOS_RESULT': results[0], 'WINDOWS_RESULT': results[1], 'FLATPAK_RESULT': results[2],
                   'DRAFT': draft, 'CALLS': str(calls), 'RELEASE_ID': '1', 'RELEASE_REPO': 'test/opal',
                   'GITHUB_SERVER_URL': 'https://example.invalid', 'CI_TOKEN': 'test'}
    result = subprocess.run(['bash', '-c', script], env=environment, capture_output=True, text=True)
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    requests = calls.read_text() if calls.exists() else ''
    assert ('-X PATCH' in requests) == published
    assert '-X DELETE' not in requests
