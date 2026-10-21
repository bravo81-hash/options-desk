# Opens Market & Options Desk when TradingView or TWS starts.
# Started at login by the "Desk launcher" shortcut in your Startup folder.
# Remove it with uninstall-launcher.ps1 next to this file.

$url      = 'http://127.0.0.1:8810/'
$app      = Join-Path (Split-Path $PSScriptRoot -Parent) 'app.py'
$watch    = @('TradingView', 'tws')   # process names
$interval = 5                         # seconds between checks
$quiet    = 15                        # minutes: don't reopen if TradingView and TWS start close together

$created = $false
$mutex = New-Object System.Threading.Mutex($true, 'Local\DeskLauncher', [ref]$created)
if (-not $created) { exit }

function Test-Desk {
    try { (Invoke-WebRequest -UseBasicParsing "${url}api/md/status" -TimeoutSec 10).StatusCode -eq 200 } catch { $false }
}

function Start-Desk {
    if (Test-Desk) { return $true }
    $pyw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
    if (-not $pyw) { return $false }
    Start-Process -FilePath $pyw -ArgumentList "`"$app`" --no-browser" -WorkingDirectory (Split-Path $app -Parent)
    for ($i = 0; $i -lt 20; $i++) { Start-Sleep -Seconds 2; if (Test-Desk) { return $true } }
    return $false
}

$was = @{}
foreach ($p in $watch) { $was[$p] = $false }
$lastOpen = [datetime]::MinValue
while ($true) {
    foreach ($p in $watch) {
        $running = [bool](Get-Process -Name $p -ErrorAction SilentlyContinue)
        if ($running -and -not $was[$p] -and ((Get-Date) - $lastOpen).TotalMinutes -ge $quiet) {
            # TWS needs ~90 s to finish logging in; a client connecting earlier can get fills without a
            # timezone (lesson from TWS Matcher), so give it that time before the desk talks to it
            if ($p -eq 'tws') { Start-Sleep -Seconds 90 }
            if (Start-Desk) { Start-Process $url; $lastOpen = Get-Date }
        }
        $was[$p] = $running
    }
    Start-Sleep -Seconds $interval
}
