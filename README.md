# openlp-packaging

Packaging and CI for [OpenLP+](https://git.tbcproductions.net/tbcproductions/openlp-plus),
a fork of [OpenLP](https://openlp.org/). This repository does not contain
application source — it produces installable artifacts (macOS `.dmg`,
Windows `.msi` / portable `.exe`, Linux Flatpak) from the `openlp-plus`
source at a given tag.

Plugins live in a separate repo,
[openlp-plugins](https://git.tbcproductions.net/tbcproductions/openlp-plugins),
and are shipped as a source ZIP from their own release workflow. They are
**not** bundled into OpenLP+ builds; users install plugins manually by
dropping directories into `openlp/plugins/` inside an OpenLP+ install.

## Layout

```
.
├── builders/                 Python entry-points called from CI
│   ├── builder.py            shared logic
│   ├── macos-builder.py
│   ├── windows-builder.py
│   └── flatpak-builder.py
├── macos/                    icon, Info.plist, dmgbuild config, config-gitlab.ini
├── windows/                  WiX template, portable appinfo, config-gitlab.ini
├── flatpak/                  manifest, build script, appdata XML
├── pyinstaller-hooks/        PyInstaller hooks shared between macOS / Windows
├── scripts/                  misc helper scripts
├── docs/                     self-hosted runner setup guides
└── .gitea/workflows/build.yml   the build pipeline
```

## How builds are triggered

The workflow in `.gitea/workflows/build.yml` has two entry points:

1. **Automatic** — when `openlp-plus` pushes a `v*` tag, its `release.yml`
   creates a Gitea release and POSTs a `repository_dispatch` event
   (`upstream-release`) to this repo. The dispatch carries the tag, and
   this repo builds from that tag.
2. **Manual** — *Actions → Build OpenLP+ → Run workflow* in the Gitea
   UI. All inputs are optional.

### Workflow inputs

| Input | Default | Effect |
|---|---|---|
| `openlp_tag` | *(empty)* | Specific `openlp-plus` tag to build. Empty = latest release. |
| `create_release` | `true` | Publish a release on this repo with all artifacts attached. Set `false` to produce artifacts only. |
| `build_macos` | `true` | Run `build-macos` (requires a runner labelled `macos`). |
| `build_windows` | `true` | Run `build-windows` (requires a runner labelled `windows`). |
| `build_flatpak` | `false` | Run `build-flatpak` (requires a runner labelled `flatpak-builder`). Off by default because Flatpak builds are heavy and infrequently needed. |

`repository_dispatch` callers can override any of these via
`client_payload`, e.g. `{"build_flatpak": true}` to force a Flatpak
build from an upstream trigger.

### Jobs

- `prepare-source` — resolves which `openlp-plus` tag to build (from
  the dispatch payload, workflow input, or the latest release API)
  and exposes it as `plus_tag` / `version` outputs. Runs in
  `node:20-bookworm-slim`. Each platform build job checks out the
  source tree itself from the resolved tag, so there's no source
  artifact round-trip.
- `build-flatpak` — builds the Flatpak bundle. Off by default.
- `build-macos` — installs Python 3.14, runtime deps via Homebrew,
  then runs `builders/macos-builder.py` to produce a `.dmg`.
- `build-windows` — installs Python 3.14, deps via pip (incl.
  PyICU wheel), then runs `builders/windows-builder.py` to produce
  `.msi` and portable `.exe`.
- `publish-release` — downloads every artifact, creates a tagged
  release on this repo named `OpenLP+ <tag>`, and uploads the
  artifacts as assets. Skips if `create_release=false`. Runs
  regardless of whether individual build jobs succeeded — ships
  whatever artifacts were produced.

## Secrets

The pipeline expects a single secret, defined at **org level** so every
repo can share it:

- `CI_TOKEN` — Gitea personal access token with `repo` scope. Used by
  `prepare-source` to check out `openlp-plus` at an arbitrary tag, and
  by `publish-release` to create releases and upload assets.

## Runners

All jobs run on self-hosted runners — Gitea doesn't ship hosted
`ubuntu-latest` / `macos` / `windows` runners the way GitHub does.
Runner labels the pipeline looks for:

| Label | Needed for | Platform |
|---|---|---|
| `ubuntu-latest` | `prepare-source`, `publish-release` | Any Linux host with Docker |
| `macos` | `build-macos` | macOS, host mode (`:host` labels) |
| `windows` | `build-windows` | Windows, host mode (`:host` labels) |
| `flatpak-builder` | `build-flatpak` | Linux host with spare disk + CPU budget |

See the setup guides for each platform:

- [docs/linux-runner-setup.md](docs/linux-runner-setup.md) — Ubuntu / Fedora
- [docs/macos-runner-setup.md](docs/macos-runner-setup.md)
- [docs/windows-runner-setup.md](docs/windows-runner-setup.md)

If a platform-specific runner is offline, set the matching
`build_<platform>` input to `false` on a manual run to skip that job —
otherwise the workflow will wait in the queue.

## Local / manual builds

Each builder script can also be invoked directly. See the script for its
specific CLI. Typical invocation (macOS):

```bash
python builders/macos-builder.py \
  --release v3.2.1 \
  --skip-update \
  --config macos/config-gitlab.ini \
  --branch /path/to/openlp-plus-checkout
```

You'll need the same runtime deps the CI job installs
(`pyinstaller`, `dmgbuild`, Qt + ICU + enchant system libs, etc.).

## Licence

GPL-3.0 — see [LICENSE](LICENSE). Inherited from upstream OpenLP.
