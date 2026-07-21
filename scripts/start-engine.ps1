param(
  [int]$Port = 8001,
  [string]$HostAddress = "127.0.0.1",
  [switch]$Reload
)
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
$Arguments = @("run", "vex-engine", "--project-root", ".", "--host", $HostAddress, "--port", "$Port")
if ($Reload) {
  $Arguments += "--reload"
}
& uv @Arguments
