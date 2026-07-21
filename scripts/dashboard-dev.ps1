$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Dashboard = Join-Path $Root "apps\dashboard_web"
if (-not (Test-Path (Join-Path $Dashboard "node_modules"))) {
  & (Join-Path $PSScriptRoot "install-dashboard.ps1")
}
$Engine = Start-Process powershell -ArgumentList @(
  "-NoProfile",
  "-ExecutionPolicy", "ByPass",
  "-Command", "Set-Location '$Root'; uv run vex-engine --project-root . --host 127.0.0.1 --port 8001"
) -PassThru
$Gateway = Start-Process powershell -ArgumentList @(
  "-NoProfile",
  "-ExecutionPolicy", "ByPass",
  "-Command", "Set-Location '$Root'; uv run vex-dashboard --project-root . --engine-url http://127.0.0.1:8001 --host 127.0.0.1 --port 8000"
) -PassThru
try {
  npm run dev --prefix $Dashboard
}
finally {
  foreach ($Process in @($Gateway, $Engine)) {
    if (-not $Process.HasExited) {
      Stop-Process -Id $Process.Id -Force
    }
  }
}
