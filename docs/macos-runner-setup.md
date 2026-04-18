# macOS Gitea Actions Runner Setup

Step-by-step for registering a self-hosted Gitea Actions runner on macOS so
the `build-macos` job in `openlp-packaging/.gitea/workflows/build.yml` can
pick up work.

> All commands are for `zsh` on an Apple Silicon Mac. For Intel Macs, replace
> `/opt/homebrew` paths with `/usr/local`.

---

## 1. Prerequisites

### 1a. Apple developer tooling

```bash
xcode-select --install
```

Accept the licence prompt if one appears.

### 1b. Homebrew

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow the post-install message to add Homebrew to your shell, e.g.:

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

### 1c. Runtime dependencies the build needs

```bash
brew install git node pyenv pkg-config icu4c enchant
```

- `node` — required for Node-based actions (`actions/checkout`, `actions/setup-python`, `upload-artifact`, etc.) in host mode.
- `pyenv` — used by the workflow to install Python 3.12 inside the job.
- `icu4c`, `enchant` — native deps for PyICU and pyenchant.

> If you already have a Python 3.12 on PATH, `pyenv` is optional.

---

## 2. Get a registration token from Gitea

1. Sign in to <https://git.tbcproductions.net> as an admin.
2. Go to **Org `tbcproductions` → Settings → Actions → Runners → Create new Runner**
   (or *Site Administration → Actions → Runners* for an instance-wide runner).
3. Copy the token. Looks like `3gJBmN...`.

> Org-scoped tokens are preferred — only `tbcproductions` jobs can schedule
> onto your Mac.

---

## 3. Install `act_runner`

Easiest — via Homebrew:

```bash
brew install act-runner
```

Or download the binary manually:

```bash
mkdir -p ~/actions-runner && cd ~/actions-runner
curl -L -o act_runner \
  https://dl.gitea.com/act_runner/latest/act_runner-latest-darwin-arm64
chmod +x act_runner
```

(Use `act_runner-latest-darwin-amd64` on Intel Macs.)

---

## 4. Register the runner

```bash
mkdir -p ~/actions-runner && cd ~/actions-runner

act_runner register \
  --no-interactive \
  --instance https://git.tbcproductions.net \
  --token <PASTE_TOKEN_HERE> \
  --name "$(hostname)-macos" \
  --labels "macos,self-hosted,macOS,ARM64"
```

(Use `X64` instead of `ARM64` for Intel Macs.)

This creates a `.runner` file in `~/actions-runner/`. The label `macos`
**must** be present — the workflow uses `runs-on: macos`.

---

## 5. Generate a host-mode config

```bash
cd ~/actions-runner
act_runner generate-config > config.yaml
```

Open `~/actions-runner/config.yaml` and update the `runner.labels` section so
every label ends with `:host`:

```yaml
runner:
  labels:
    - "macos:host"
    - "self-hosted:host"
    - "macOS:host"
    - "ARM64:host"
```

The `:host` suffix tells act_runner to execute steps directly on macOS (not
inside a Docker container). This is mandatory for PyInstaller because it
needs to build against the real macOS SDK and frameworks.

---

## 6. Smoke-test in the foreground

```bash
cd ~/actions-runner
act_runner daemon --config config.yaml
```

You should see:

```
INFO Starting runner daemon
INFO Runner: mymac-macos, with version ..., with labels [macos self-hosted ...], is online and listening
```

Also check the Gitea UI (*Org → Settings → Actions → Runners*): the runner
should appear as **Idle** with a green dot.

Press **Ctrl-C** once confirmed.

---

## 7. Install as a launchd service

macOS uses `launchd` to manage background services. A `LaunchAgent` runs
while **you** are logged in (preferred for a dev Mac — needed so the runner
can access your login keychain for codesigning). A `LaunchDaemon` runs at
boot regardless of login, but can't see user-scoped resources.

### 7a. Create the LaunchAgent plist

Replace `/opt/homebrew/bin/act_runner` with the path printed by
`which act_runner` if it's different (for example Intel Macs use
`/usr/local/bin/act_runner`).

```bash
ACT_RUNNER_BIN="$(command -v act_runner)"
RUNNER_DIR="$HOME/actions-runner"

cat > ~/Library/LaunchAgents/net.tbcproductions.actrunner.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>net.tbcproductions.actrunner</string>

  <key>ProgramArguments</key>
  <array>
    <string>${ACT_RUNNER_BIN}</string>
    <string>daemon</string>
    <string>--config</string>
    <string>${RUNNER_DIR}/config.yaml</string>
  </array>

  <key>WorkingDirectory</key>
  <string>${RUNNER_DIR}</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>HOME</key>
    <string>${HOME}</string>
  </dict>

  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>

  <key>StandardOutPath</key>
  <string>${RUNNER_DIR}/runner.log</string>
  <key>StandardErrorPath</key>
  <string>${RUNNER_DIR}/runner.err</string>
</dict>
</plist>
EOF
```

### 7b. Load and start it

```bash
launchctl unload ~/Library/LaunchAgents/net.tbcproductions.actrunner.plist 2>/dev/null
launchctl load  ~/Library/LaunchAgents/net.tbcproductions.actrunner.plist
```

### 7c. Verify it stays running

```bash
launchctl list | grep tbcproductions
# PID   Status  Label
# 12345 0       net.tbcproductions.actrunner

tail -n 50 -f ~/actions-runner/runner.log
```

You should see:

```
INFO Runner: mymac-macos, ..., is online and listening
```

> **Alternative (via Homebrew services):** if you installed act_runner with
> `brew install act-runner`, you can instead run `brew services start
> act-runner`. That uses Homebrew's own plist and reads config from
> `/opt/homebrew/etc/act_runner/`. The manual LaunchAgent above is more
> explicit and easier to troubleshoot.

---

## 8. Confirm Gitea sees it

1. Open <https://git.tbcproductions.net>.
2. Go to **Org `tbcproductions` → Settings → Actions → Runners**.
3. The runner should be **Idle / green**.
4. Confirm the labels listed include `macos` exactly (case sensitive).

---

## 9. Trigger a test run

1. On Gitea: `tbcproductions/openlp-packaging` → *Actions* → *Build OpenLP+* →
   *Run workflow* → leave inputs blank → *Run*.
2. Watch the `build-macos` job. It should go **Queued → Running** as soon as
   the Synology runner finishes `prepare-source`.
3. Tail `~/actions-runner/runner.log` to see the job executing locally.

---

## Troubleshooting

### Service doesn't start / `launchctl load` is silent but nothing happens

```bash
launchctl error net.tbcproductions.actrunner
tail -n 100 ~/actions-runner/runner.err
```

Common causes:
- Wrong `act_runner` path in the plist. Check with `which act_runner`.
- Relative `config.yaml` path — use the absolute path.
- The `.runner` registration file is not in `WorkingDirectory`. Re-register
  from `~/actions-runner/`, or copy `.runner` there.

### Job stays "queued" forever
The runner's labels don't match `runs-on: macos` in the workflow. Check the
runner row in Gitea's UI — `macos` must appear exactly (case sensitive).

### Job fails with "exec: docker: not found"
You skipped the `:host` suffix in `config.yaml`. act_runner is trying to run
inside a Docker container that doesn't exist on macOS. Edit `config.yaml` so
every label ends with `:host`, then reload:

```bash
launchctl unload ~/Library/LaunchAgents/net.tbcproductions.actrunner.plist
launchctl load   ~/Library/LaunchAgents/net.tbcproductions.actrunner.plist
```

### `brew`, `pyenv`, etc. not found during a job
The LaunchAgent has a minimal `PATH`. Make sure the `EnvironmentVariables`
block in the plist includes `/opt/homebrew/bin` (Apple Silicon) or
`/usr/local/bin` (Intel), then reload the agent.

### Codesigning prompts during the build
The first time an unsigned binary is built macOS may prompt for access to
the login keychain. Click **Always Allow**. Because this is a LaunchAgent
(not a LaunchDaemon) running under your user, the keychain is available.

### PyICU / pyenchant fails to build
Make sure `icu4c` and `enchant` are installed via Homebrew and the paths
are exported in the job. The workflow already sets
`PYENCHANT_LIBRARY_PATH=/opt/homebrew/lib/libenchant-2.2.dylib`; if you're
on Intel, patch the workflow to use `/usr/local/lib/libenchant-2.2.dylib`
or keep a per-runner override.

### Updating the runner

```bash
launchctl unload ~/Library/LaunchAgents/net.tbcproductions.actrunner.plist
brew upgrade act-runner
# or: replace the act_runner binary manually
launchctl load   ~/Library/LaunchAgents/net.tbcproductions.actrunner.plist
```

---

## Uninstall (if needed)

```bash
launchctl unload ~/Library/LaunchAgents/net.tbcproductions.actrunner.plist
rm ~/Library/LaunchAgents/net.tbcproductions.actrunner.plist
rm -rf ~/actions-runner
brew uninstall act-runner   # if installed via Homebrew
```

Then in Gitea, remove the now-offline runner from **Settings → Actions → Runners**.
