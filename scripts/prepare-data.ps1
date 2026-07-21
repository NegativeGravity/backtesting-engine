param(
    [Parameter(Mandatory = $true)]
    [string]$SourceDirectory
)

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$targetDirectory = Join-Path $projectRoot "data\mt5"
New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null

$files = @(
    @{ Pattern = "XAUUSD_M1_202501020105_202607131322*.csv"; Target = "XAUUSD_M1_202501020105_202607131322.csv" },
    @{ Pattern = "XAUUSD_M5_202501020105_202607131320*.csv"; Target = "XAUUSD_M5_202501020105_202607131320.csv" },
    @{ Pattern = "XAUUSD_M15_202501020100_202607131315*.csv"; Target = "XAUUSD_M15_202501020100_202607131315.csv" },
    @{ Pattern = "XAUUSD_H1_202501020100_202607131300*.csv"; Target = "XAUUSD_H1_202501020100_202607131300.csv" },
    @{ Pattern = "XAUUSD_H4_202501020000_202607131200*.csv"; Target = "XAUUSD_H4_202501020000_202607131200.csv" },
    @{ Pattern = "XAUUSD_Daily_202501020000_202607130000*.csv"; Target = "XAUUSD_D1_202501020000_202607130000.csv" }
)

foreach ($item in $files) {
    $matches = @(Get-ChildItem -Path $SourceDirectory -File -Filter $item.Pattern)
    if ($matches.Count -ne 1) {
        throw "Expected exactly one file matching $($item.Pattern), found $($matches.Count)"
    }
    Copy-Item -Path $matches[0].FullName -Destination (Join-Path $targetDirectory $item.Target) -Force
}

Get-ChildItem -Path $targetDirectory -File | Sort-Object Name | Select-Object Name, Length
