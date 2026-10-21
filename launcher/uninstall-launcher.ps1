# Removes the desk launcher: deletes its Startup shortcut and stops the running launcher.
# The desk itself (Options Desk recorder shortcut) is left alone.
$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'Desk launcher.lnk'
if (Test-Path $lnk) { Remove-Item $lnk; "Removed $lnk" }
Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" |
    Where-Object { $_.CommandLine -like '*desk-launcher.ps1*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId; "Stopped launcher (PID $($_.ProcessId))" }
