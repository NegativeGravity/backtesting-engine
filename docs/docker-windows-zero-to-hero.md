# Docker on Windows — Zero to Hero

## 1. Install Docker Desktop

Install Docker Desktop for Windows and use the WSL 2 backend.

After installation, restart Windows when requested and open Docker Desktop once.

Verify from PowerShell:

```powershell
docker version
docker compose version
```

## 2. Extract the Project

Extract the project to a short path such as:

```text
G:\PythonProject\vex-phase6
```

Open PowerShell in the project root:

```powershell
cd G:\PythonProject\vex-phase6
```

## 3. Confirm the MT5 CSV Files

The following files must exist:

```text
data\mt5\XAUUSD_M1_202501020105_202607131322.csv
data\mt5\XAUUSD_M5_202501020105_202607131320.csv
data\mt5\XAUUSD_M15_202501020100_202607131315.csv
data\mt5\XAUUSD_H1_202501020100_202607131300.csv
data\mt5\XAUUSD_H4_202501020000_202607131200.csv
data\mt5\XAUUSD_D1_202501020000_202607130000.csv
```

## 4. Build and Start Everything

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\docker-up.ps1
```

The script waits until the health, catalog, and analytics endpoints pass.

The bootstrap container will:

1. Import the CSV files when the Parquet cache is missing.
2. Build the SMA Cross replay bundle.
3. Generate analytics.
4. Run the offline MT5 compatibility validation.
5. Start the application after bootstrap succeeds.

Open:

```text
http://127.0.0.1:8000
```

## 5. Inspect Status and Logs

```powershell
docker compose ps
docker compose logs bootstrap
docker compose logs -f app
```

Run the smoke test again at any time:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\docker-smoke.ps1
```

The MT5 compatibility endpoint is `http://127.0.0.1:8000/api/mt5/compatibility`.

The application health endpoint is:

```text
http://127.0.0.1:8000/api/health
```

## 6. Force a Full Rebuild

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\docker-up.ps1 -ForceRebuild
```

A larger demo run can be requested:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\docker-up.ps1 -MaxCloseBatches 20000
```

## 7. Stop the Stack

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\docker-down.ps1
```

The bind-mounted `data` directory is retained.

To remove optional Docker volumes:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\docker-down.ps1 -RemoveVolumes
```

## 8. Rebuild Manually

```powershell
docker compose build --no-cache
docker compose run --rm bootstrap
docker compose up -d app
```

## 9. Run Optional Infrastructure

PostgreSQL and Redis are reserved for the orchestration phase and are disabled by default.

```powershell
docker compose --profile infra up -d
```

## 10. MT5 Compatibility on Windows Host

The MetaTrader terminal is not run inside the Linux application container.

Install the optional bridge package in the local Windows virtual environment:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\setup.ps1
powershell -ExecutionPolicy ByPass -File .\scripts\install-mt5-bridge.ps1
```

Open MetaTrader 5, log into the target account, and enable external Python API access.

Set the password only for the current PowerShell session:

```powershell
$env:MT5_PASSWORD = "your-password"
```

Update `examples\configs\mt5_bridge.yaml` with the login, server, and optional terminal path.

Collect:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\mt5-collect.ps1
```

Change `snapshot_path` in `examples\configs\mt5_validation.yaml` to the live snapshot and run:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\mt5-validate.ps1
```

Do not add the password to YAML, Docker Compose, Git, or generated snapshots.

## 11. Common Problems

### Docker command is not found

Start Docker Desktop and reopen PowerShell.

### WSL 2 is unavailable

Run PowerShell as Administrator:

```powershell
wsl --install
wsl --update
```

Restart Windows.

### Port 8000 is occupied

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\docker-up.ps1 -Port 8080
```

Open `http://127.0.0.1:8080`.

### Bootstrap fails because a CSV is missing

Restore the six canonical files under `data\mt5`, then run with `-ForceRebuild`.

### The live MT5 report fails

Generate a new symbol profile from the live snapshot, update the run profile reference, and rerun validation. Do not widen tolerances before identifying the cause.
