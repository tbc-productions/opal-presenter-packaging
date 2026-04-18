# Windows Gitea Actions Runner Setup

Step-by-step for registering a self-hosted Gitea Actions runner on Windows so
the `build-windows` job in `openlp-packaging/.gitea/workflows/build.yml` can
pick up work.

> Run every PowerShell block in an **elevated PowerShell** (right-click →
> *Run as Administrator*) unless noted otherwise.

---

## 1. Prerequisites

Install these on the Windows machine:

- **Git for Windows** — <https://gitforwindows.org/>
- **Node.js LTS** — <https://nodejs.org/> (required for Node-based actions like
  `actions/checkout` when the runner is in host mode)
- **Python 3.14** — <https://www.python.org/downloads/> (tick *Add to PATH*;
  install for all users so the LocalSystem service account can see it)
- **PowerShell 7** *(optional but nicer)* — `winget install Microsoft.PowerShell`
- **WiX Toolset** — `choco install wixtoolset` (needed by `windows-builder.py`
  for MSI creation)
- **Visual C++ Build Tools** — for any native Python wheels that might compile:
  `winget install Microsoft.VisualStudio.2022.BuildTools`
- **PortableApps.com Launcher** and **PortableApps.com Installer** — required
  when the workflow passes `--portable` (it does by default). Download and run
  the installers from <https://portableapps.com/apps/development>; accept the
  default install location so they land in
  `C:\PortableApps\PortableApps.comLauncher\` and
  `C:\PortableApps\PortableApps.comInstaller\` — which is what
  `windows/config-gitea.ini` expects. If you install elsewhere, edit that
  config's `[executables]` section to match.

If you don't have Chocolatey:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
```

### 1a. Put Git Bash on the machine `PATH`

The `build-windows` job uses `shell: bash` (via Git for Windows), which means
`bash.exe` must be resolvable from the service account's `PATH`. Git for
Windows installs `bash.exe` at `C:\Program Files\Git\bin\bash.exe` but only
adds `C:\Program Files\Git\cmd` to `PATH` by default.

Append both the `bin` and `usr\bin` directories (the latter brings POSIX
helpers like `printf`, `tar`, `grep`) to the **machine** `PATH` so the
LocalSystem-ish service account inherits them:

```powershell
$extra = @(
    'C:\Program Files\Git\bin',
    'C:\Program Files\Git\usr\bin'
)
$current = [Environment]::GetEnvironmentVariable('Path', 'Machine')
foreach ($dir in $extra) {
    if ($current -notlike "*$dir*") { $current = "$current;$dir" }
}
[Environment]::SetEnvironmentVariable('Path', $current, 'Machine')
```

You'll need to restart the runner service (see step 7e) after changing this.

### 1b. Relax the machine PowerShell ExecutionPolicy

act_runner writes each step's script as a `.ps1` wrapper and asks PowerShell
to dot-source it. The default `Restricted` policy on Windows Server / fresh
client installs refuses to load those wrappers, producing errors such as:

```
. : File C:\...\act\workflow\2.ps1 cannot be loaded because running scripts
is disabled on this system.
```

Set the machine policy to `RemoteSigned` once:

```powershell
Set-ExecutionPolicy -Scope LocalMachine -ExecutionPolicy RemoteSigned -Force
```

`RemoteSigned` allows local (runner-authored) scripts to run while still
requiring signatures on scripts downloaded from the internet. If your
organisation forbids even that, use `Set-ExecutionPolicy -Scope LocalMachine
-ExecutionPolicy Bypass -Force` — but only on a dedicated build machine.

---

## 2. Get a registration token from Gitea

1. Sign in to `https://<your-gitea-host>` as an admin.
2. Go to **Org `<your-org>` → Settings → Actions → Runners → Create new Runner**
   (or *Site Administration → Actions → Runners* for an instance-wide runner).
3. Copy the token. Looks like `3gJBmN...`.

> Org-scoped tokens are preferred — only your org's jobs can schedule onto
> your PC.

---

## 3. Install `act_runner`

There is no winget / Chocolatey package for `act_runner` on Windows — the
binary has to be downloaded directly from Gitea's release server.

```powershell
New-Item -ItemType Directory -Force -Path C:\actions-runner | Out-Null
Invoke-WebRequest `
  -Uri "https://dl.gitea.com/act_runner/latest/act_runner-latest-windows-amd64.exe" `
  -OutFile "C:\actions-runner\act_runner.exe"
```

> Pin a specific version instead of `latest` if you want reproducible
> upgrades, e.g. `act_runner-0.2.11-windows-amd64.exe`. Browse available
> versions at <https://dl.gitea.com/act_runner/>.

---

## 4. Register the runner

```powershell
cd C:\actions-runner

.\act_runner.exe register `
  --no-interactive `
  --instance https://<your-gitea-host> `
  --token <PASTE_TOKEN_HERE> `
  --name "$($env:COMPUTERNAME)-windows" `
  --labels "windows,self-hosted,Windows,X64"
```

This creates a `.runner` file in `C:\actions-runner\` with the saved
registration. The label `windows` **must** be present — the workflow uses
`runs-on: windows`.

---

## 5. Generate a host-mode config

```powershell
.\act_runner.exe generate-config > config.yaml
```

Open `C:\actions-runner\config.yaml` and replace the `runner.labels` section
so every label ends with `:host`:

```yaml
runner:
  labels:
    - "windows:host"
    - "self-hosted:host"
    - "Windows:host"
    - "X64:host"
```

The `:host` suffix tells act_runner to execute steps directly on the Windows
host (not inside a Docker container). This is what PyInstaller needs.

Also replace the placeholder `runner.envs` block with a writable tool-cache
path, so `actions/setup-python@v5` (and any other action that uses the hosted
tool cache) doesn't try to create `C:\Users\runneradmin\hostedtoolcache`:

```yaml
runner:
  envs:
    RUNNER_TOOL_CACHE: C:\actions-runner\_tool
    AGENT_TOOLSDIRECTORY: C:\actions-runner\_tool
```

Then create the directory:

```powershell
New-Item -ItemType Directory -Force -Path C:\actions-runner\_tool | Out-Null
```

---

## 6. Smoke-test in the foreground

```powershell
cd C:\actions-runner
.\act_runner.exe daemon --config config.yaml
```

You should see something like:

```
INFO Starting runner daemon
INFO Runner: MYPC-windows, with version ..., with labels [windows self-hosted ...], is online and listening
```

Also check the Gitea UI (*Org → Settings → Actions → Runners*): the runner
should appear as **Idle** with a green dot.

Press **Ctrl-C** once confirmed.

---

## 7. Install as a Windows service (via NSSM)

`act_runner.exe daemon` is a plain console app and doesn't implement the
Windows Service Control Manager protocol, so it must be wrapped by a service
host. [NSSM](https://nssm.cc/) (Non-Sucking Service Manager) is the standard
tool for this.

### 7a. Install NSSM

```powershell
choco install nssm -y
```

Or download `nssm.exe` manually from <https://nssm.cc/download> and drop it
in `C:\Windows\System32\`.

### 7b. Create the service

```powershell
cd C:\actions-runner

nssm install gitea-actions-runner `
  "C:\actions-runner\act_runner.exe" `
  "daemon --config C:\actions-runner\config.yaml"

nssm set gitea-actions-runner AppDirectory C:\actions-runner
nssm set gitea-actions-runner DisplayName "Gitea Actions Runner"
nssm set gitea-actions-runner Description "Gitea Actions runner (act_runner daemon)"
nssm set gitea-actions-runner Start SERVICE_AUTO_START
nssm set gitea-actions-runner AppStdout C:\actions-runner\runner.log
nssm set gitea-actions-runner AppStderr C:\actions-runner\runner.err
nssm set gitea-actions-runner AppRotateFiles 1
nssm set gitea-actions-runner AppRotateBytes 10485760
```

### 7c. (Required) move the runner workspace off `C:\Windows\System32`

By default NSSM runs the service as `LocalSystem`, whose profile directory
is `C:\Windows\System32\config\systemprofile`. act_runner then places every
job's workspace under `%HOME%\.cache\act\<hash>\hostexecutor`, i.e.
`C:\Windows\System32\config\systemprofile\.cache\act\...`.

This is catastrophic for the Windows build because several tools in the
pipeline are **32-bit** — most notably WiX v3's `candle.exe` / `light.exe`
and the PortableApps launcher. When a 32-bit process on 64-bit Windows
reads any `C:\Windows\System32\...` path, the WOW64 File System Redirector
silently rewrites it to `C:\Windows\SysWOW64\...`, which doesn't contain
the workspace, so those tools fail with bewildering errors such as
`candle.exe : error CNDL0103 : The system cannot find the file
'...\OpenLP.wxs' with type 'Source'.` — even though 64-bit Python
wrote the file to the exact path on the command line.

Two ways to fix it — do one of these:

**Option A (minimal change):** keep the LocalSystem service user, but
override `HOME`/`USERPROFILE` for the service so act_runner puts its
workspace somewhere WOW64-safe:

```powershell
New-Item -ItemType Directory -Force -Path C:\act-runner-home | Out-Null

nssm set gitea-actions-runner AppEnvironmentExtra `
  HOME=C:\act-runner-home `
  USERPROFILE=C:\act-runner-home
```

**Option B (recommended):** switch the service to a regular user account.
NSSM defaults to `LocalSystem`, which also hides user-installed Python,
Chocolatey packages on the user PATH, and other developer tools. Running
as a normal user sidesteps both problems:

```powershell
nssm set gitea-actions-runner ObjectName ".\YourWindowsUsername" "YourPassword"
```

- `.\User` — local account
- `DOMAIN\User` — domain account

In either case, restart the service (step 7d) after making the change. The
Windows builder will refuse to start if the workspace is still under
`C:\Windows\System32` and print a message pointing back here.

### 7d. Start it

```powershell
nssm start gitea-actions-runner
# or: Start-Service gitea-actions-runner
```

### 7e. Verify it stays running

```powershell
Get-Service gitea-actions-runner
Get-Content C:\actions-runner\runner.log -Tail 50 -Wait
```

You should see:

```
INFO Runner: MYPC-windows, ..., is online and listening
```

and the service status should be `Running`.

---

## 8. Confirm Gitea sees it

1. Open `https://<your-gitea-host>`.
2. Go to **Org `<your-org>` → Settings → Actions → Runners**.
3. The runner should be **Idle / green**.
4. Confirm the labels listed include `windows` exactly (case sensitive).

---

## 9. Trigger a test run

1. On Gitea: `<your-org>/openlp-packaging` → *Actions* → *Build OpenLP+* →
   *Run workflow* → leave inputs blank → *Run*.
2. Watch the `build-windows` job. It should go **Queued → Running** as soon
   as the Linux runner finishes `prepare-source`.
3. Tail `C:\actions-runner\runner.log` to see the job executing locally.

> **Skipping the Windows build.** The `Build OpenLP+` workflow exposes a
> `build_windows` input (default `true`). Set it to `false` on a manual
> run to skip this job — useful if the Windows box is offline for
> maintenance and you still want a macOS-only build to go through.

---

## Troubleshooting

### Service starts then stops within seconds
Check `C:\actions-runner\runner.err`:

```powershell
Get-Content C:\actions-runner\runner.err -Tail 50
```

Common causes:
- `config.yaml` path is relative or wrong — use the absolute path.
- `.runner` registration file is not in `C:\actions-runner\`. Re-register in
  that folder, or copy the `.runner` file there.

### Job stays "queued" forever
The runner's labels don't match `runs-on: windows` in the workflow. Check
the runner row in Gitea's UI — `windows` must appear exactly (case sensitive).

### Job runs but fails with "exec: docker: not found"
You skipped the `:host` suffix in `config.yaml`. act_runner is trying to run
inside a Docker container that doesn't exist on Windows. Edit `config.yaml`
so every label ends with `:host`, then:

```powershell
Restart-Service gitea-actions-runner
```

### Node.js / Python / choco installs aren't found during a job
The service is running as `LocalSystem`. Switch to your user account (step
7c) and restart the service.

### `Cannot find: bash in PATH`
Git Bash isn't on the machine `PATH`. Run the snippet in **step 1a** to add
`C:\Program Files\Git\bin` (and `usr\bin`) to the machine `PATH`, then
`Restart-Service gitea-actions-runner`. The service needs a restart before
it picks up the new environment.

### `running scripts is disabled on this system` / `NativeCommandFailed`
Both symptoms come from PowerShell refusing to load the `.ps1` step
wrappers act_runner writes to `C:\...\act\workflow\<n>.ps1`. Apply the
ExecutionPolicy change in **step 1b** (`Set-ExecutionPolicy -Scope
LocalMachine -ExecutionPolicy RemoteSigned -Force`) and restart the
service.

### `PortableApps.com Launcher was not found at the configured path`
The PortableApps Launcher and/or Installer aren't installed where
`windows/config-gitea.ini` is looking for them. Install both tools from
<https://portableapps.com/apps/development> with the default install
location (`C:\PortableApps\PortableApps.com*`), or edit the
`[executables]` section of `windows/config-gitea.ini` to point at wherever
you put them.

### `candle.exe : error CNDL0103` / `light.exe` can't find files
The workspace is under `C:\Windows\System32\config\systemprofile\.cache`
because act_runner is running as `LocalSystem` with no `HOME` override.
WiX v3's candle/light are 32-bit and get redirected to `SysWOW64` by
WOW64 File System Redirection. Apply **step 7c** (override `HOME` /
`USERPROFILE`, or switch the service user) and restart the service.
The `build-windows` job will self-detect this on the next run and bail
out early with a pointer back here.

### Signing / permissions prompts during the build
The first interactive run may prompt; once approved the service runs
unattended afterwards. If the job runs as `LocalSystem`, certain Windows
prompts will never appear — another reason to run as your user account.

### Updating the runner

```powershell
Stop-Service gitea-actions-runner

# Download the newer act_runner.exe, overwriting the existing one
Invoke-WebRequest `
  -Uri "https://dl.gitea.com/act_runner/latest/act_runner-latest-windows-amd64.exe" `
  -OutFile "C:\actions-runner\act_runner.exe"

Start-Service gitea-actions-runner
```

---

## Uninstall (if needed)

```powershell
nssm stop gitea-actions-runner
nssm remove gitea-actions-runner confirm
Remove-Item C:\actions-runner -Recurse -Force
```

Then in Gitea, remove the now-offline runner from **Settings → Actions → Runners**.
