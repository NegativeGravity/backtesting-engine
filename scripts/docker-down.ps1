param(
  [switch]$RemoveVolumes
)
$ErrorActionPreference = "Stop"
if ($RemoveVolumes) {
  docker compose down --volumes --remove-orphans
} else {
  docker compose down --remove-orphans
}
