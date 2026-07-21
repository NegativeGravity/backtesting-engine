$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$UvLock = Join-Path $Root "uv.lock"
$PackageLock = Join-Path $Root "apps\dashboard_web\package-lock.json"
$Utf8 = [System.Text.UTF8Encoding]::new($false)

if (Test-Path $UvLock) {
  $Content = [System.IO.File]::ReadAllText($UvLock)
  $Content = [regex]::Replace(
    $Content,
    'https://[^"\s]+/artifactory/api/pypi/[^"\s]+/simple',
    'https://pypi.org/simple'
  )
  $Content = [regex]::Replace(
    $Content,
    'https://[^"\s]+/artifactory/api/pypi/[^"\s]+/packages/packages/',
    'https://files.pythonhosted.org/packages/'
  )
  [System.IO.File]::WriteAllText($UvLock, $Content, $Utf8)
}

if (Test-Path $PackageLock) {
  $Content = [System.IO.File]::ReadAllText($PackageLock)
  $Content = [regex]::Replace(
    $Content,
    'https://[^"\s]+/artifactory/api/npm/[^"\s]+/',
    'https://registry.npmjs.org/'
  )
  [System.IO.File]::WriteAllText($PackageLock, $Content, $Utf8)
}

$Contaminated = @()
foreach ($Path in @($UvLock, $PackageLock)) {
  if (Test-Path $Path) {
    $Match = Select-String -Path $Path -Pattern '/artifactory/api/' -SimpleMatch
    if ($Match) {
      $Contaminated += $Path
    }
  }
}

if ($Contaminated.Count -gt 0) {
  throw "Non-portable registry URLs remain in: $($Contaminated -join ', ')"
}
