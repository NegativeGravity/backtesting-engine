$ErrorActionPreference = "Stop"
$Dashboard = Resolve-Path (Join-Path $PSScriptRoot "..\apps\dashboard_web")
$env:NPM_CONFIG_REGISTRY = "https://registry.npmjs.org/"
npm ci --prefix $Dashboard --registry=https://registry.npmjs.org/ --replace-registry-host=always
