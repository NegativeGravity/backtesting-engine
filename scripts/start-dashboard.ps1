param(
  [int]$Port = 8000,
  [int]$EnginePort = 8001,
  [switch]$SkipBuild
)
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "start-dashboard-only.ps1") `
  -Port $Port `
  -EnginePort $EnginePort `
  -SkipBuild:$SkipBuild
