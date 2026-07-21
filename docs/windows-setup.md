# Windows Setup

## Install uv

Open PowerShell and run:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen PowerShell, then verify:

```powershell
uv --version
```

Alternative installation:

```powershell
winget install --id=astral-sh.uv -e
```

## Install Node.js

Install the current LTS release:

```powershell
winget install OpenJS.NodeJS.LTS
```

Close and reopen PowerShell, then verify:

```powershell
node --version
npm --version
```

The dashboard requires Node.js 20.19+ or 22.12+.

## Install Project Dependencies

From the repository root:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\setup.ps1
```

The script installs Python 3.12 through `uv`, synchronizes Python dependencies, validates Node.js, installs frontend dependencies with `npm ci`, and validates example contracts.

## Prepare Market Data

Create `data\mt5` and copy the canonical files listed in the root README.

Build the Parquet cache:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\import-data.ps1
```

## Build Replay Data

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\replay-build.ps1
```

## Run the Dashboard

Development mode:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\dashboard-dev.ps1
```

Production mode:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\start-dashboard.ps1
```

## Validate the Project

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\quality.ps1
```

## PyCharm Interpreter

Select:

```text
<repository>\.venv\Scripts\python.exe
```

Set every Python run configuration working directory to the repository root.

## Public registry setup

The repository lockfiles target the public package registries:

```text
Python: https://pypi.org/simple
npm:    https://registry.npmjs.org/
```

Run the setup script from the repository root:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\setup.ps1
```

The setup script normalizes stale mirror URLs in both lockfiles for the current project, uses the public PyPI index for `uv`, and uses the public npm registry for the dashboard installation.

To repair an existing checkout without replacing the repository:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\normalize-registry-locks.ps1
Remove-Item -Recurse -Force .\.venv -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force .\apps\dashboard_web\node_modules -ErrorAction SilentlyContinue
powershell -ExecutionPolicy ByPass -File .\scripts\setup.ps1
```
