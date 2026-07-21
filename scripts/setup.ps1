$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "normalize-registry-locks.ps1")
$env:UV_INDEX_URL = $null
$env:UV_INDEX = $null
$env:UV_EXTRA_INDEX_URL = $null
$env:UV_DEFAULT_INDEX = "https://pypi.org/simple"
$env:UV_INSECURE_HOST = $null
$env:PIP_INDEX_URL = $null
$env:PIP_EXTRA_INDEX_URL = $null
uv python install 3.12
uv sync --frozen --all-groups --python 3.12 --default-index https://pypi.org/simple
$NodeRaw = (node --version).TrimStart("v")
$NodeParts = $NodeRaw.Split(".")
$NodeMajor = [int]$NodeParts[0]
$NodeMinor = [int]$NodeParts[1]
$Supported = ($NodeMajor -gt 22) -or ($NodeMajor -eq 22 -and $NodeMinor -ge 12) -or ($NodeMajor -eq 20 -and $NodeMinor -ge 19)
if (-not $Supported) {
  throw "Node.js 20.19+ or 22.12+ is required. Install the current LTS release with: winget install OpenJS.NodeJS.LTS"
}
& (Join-Path $PSScriptRoot "install-dashboard.ps1")
uv run vex-contracts validate --kind dataset-manifest --path examples\configs\dataset.yaml
uv run vex-contracts validate --kind data-engine-config --path examples\configs\data_engine.yaml
uv run vex-contracts validate --kind symbol-profile --path examples\configs\symbol_xauusd.yaml
uv run vex-contracts validate --kind strategy-descriptor --path examples\configs\strategy.yaml
uv run vex-contracts validate --kind run-config --path examples\configs\run.yaml
uv run vex-contracts validate --kind strategy-runtime-config --path examples\configs\strategy_runtime.yaml
uv run vex-contracts validate --kind analytics-config --path examples\configs\analytics.yaml
uv run vex-contracts validate --kind strategy-descriptor --path examples\configs\strategy_sdk_smoke.yaml
uv run vex-contracts validate --kind run-config --path examples\configs\run_strategy_smoke.yaml

uv run vex-contracts validate --kind mt5-bridge-config --path examples\configs\mt5_bridge.yaml
uv run vex-contracts validate --kind mt5-validation-config --path examples\configs\mt5_validation.yaml
uv run vex-contracts validate --kind strategy-package-manifest --path strategies\sma_cross_demo\package.yaml
uv run vex-contracts validate --kind strategy-descriptor --path examples\configs\strategy_sma_cross.yaml
uv run vex-contracts validate --kind run-config --path examples\configs\run_sma_cross.yaml
