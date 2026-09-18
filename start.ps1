param([switch]$Stop)
$ErrorActionPreference = 'Stop'
$workspacePath = $PSScriptRoot
$pythonWindowless = Join-Path $workspacePath '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonWindowless)) {
    $pythonCommand = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) { $pythonWindowless = $pythonCommand.Source }
    else {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show('Please install Python 3.11 or newer, then start WeWrite again.', 'WeWrite') | Out-Null
        exit 1
    }
}
$launcherPath = Join-Path $workspacePath 'launcher.pyw'
$launchArguments = @('"' + $launcherPath + '"')
if ($Stop) { $launchArguments += '--stop' }
Start-Process -FilePath $pythonWindowless -ArgumentList $launchArguments -WorkingDirectory $workspacePath -WindowStyle Hidden
