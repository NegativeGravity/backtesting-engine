$ErrorActionPreference = "Stop"
$Root = (Get-Location).Path
$UvLock = Join-Path $Root "uv.lock"
$PackageLock = Join-Path $Root "apps\dashboard_web\package-lock.json"
$NpmRc = Join-Path $Root "apps\dashboard_web\.npmrc"
$Utf8 = [System.Text.UTF8Encoding]::new($false)

if (-not (Test-Path (Join-Path $Root "pyproject.toml"))) {
  throw "Run this script from the project root."
}

if (-not (Test-Path $UvLock)) {
  throw "uv.lock was not found."
}

if (-not (Test-Path $PackageLock)) {
  throw "apps\dashboard_web\package-lock.json was not found."
}

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

$Content = [System.IO.File]::ReadAllText($PackageLock)
$Content = [regex]::Replace(
  $Content,
  'https://[^"\s]+/artifactory/api/npm/[^"\s]+/',
  'https://registry.npmjs.org/'
)
[System.IO.File]::WriteAllText($PackageLock, $Content, $Utf8)

[System.IO.File]::WriteAllText(
  $NpmRc,
  "registry=https://registry.npmjs.org/`nreplace-registry-host=always`nfund=false`naudit=false`n",
  $Utf8
)

Remove-Item -Recurse -Force (Join-Path $Root ".venv") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $Root "apps\dashboard_web\node_modules") -ErrorAction SilentlyContinue

$env:UV_INDEX_URL = $null
$env:UV_INDEX = $null
$env:UV_EXTRA_INDEX_URL = $null
$env:UV_DEFAULT_INDEX = "https://pypi.org/simple"
$env:UV_INSECURE_HOST = $null
$env:PIP_INDEX_URL = $null
$env:PIP_EXTRA_INDEX_URL = $null
$env:NPM_CONFIG_REGISTRY = "https://registry.npmjs.org/"

uv python install 3.12
uv sync --frozen --all-groups --python 3.12 --default-index https://pypi.org/simple
npm ci --prefix apps\dashboard_web --registry=https://registry.npmjs.org/ --replace-registry-host=always
