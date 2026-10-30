param([ValidateSet("toggle", "start", "stop", "status", "log", "shortcut")][string]$Action = "toggle")

$dir = $PSScriptRoot
$python = Join-Path $dir ".venv\Scripts\python.exe"
$pidFile = Join-Path $dir ".voxcord.pid"
$logFile = Join-Path $dir "voxcord.log"

function Get-BotProcess {
    if (-not (Test-Path $pidFile)) { return $null }
    $id = [int](Get-Content $pidFile -ErrorAction SilentlyContinue)
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($p -and $p.StartTime -lt (Get-Item $pidFile).LastWriteTime.AddSeconds(5)) { return $p }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    return $null
}

function Show-Message($text) {
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show($text, "voxcord")
}

function Start-Bot {
    if (Get-BotProcess) { return "voxcord is already running." }
    if (-not (Test-Path $python)) { return "Missing .venv. Run the install steps in README.md first." }
    if (-not (Test-Path (Join-Path $dir ".env"))) { return "Missing .env. Copy .env.example to .env and add your DISCORD_TOKEN." }

    $p = Start-Process -FilePath $python -ArgumentList "-X", "utf8", "bot.py" -WorkingDirectory $dir `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err"
    # Idle-priority: the bot only wakes up when a message arrives, so never compete with foreground apps
    $p.PriorityClass = "BelowNormal"
    $p.Id | Set-Content $pidFile

    Start-Sleep -Seconds 4
    if ($p.HasExited) {
        Remove-Item $pidFile -ErrorAction SilentlyContinue
        $tail = (Get-Content "$logFile.err" -Tail 5 -ErrorAction SilentlyContinue) -join "`n"
        return "voxcord failed to start:`n$tail"
    }
    return "voxcord is ON. Join a voice channel and use /join."
}

function Stop-Bot {
    $p = Get-BotProcess
    if (-not $p) { return "voxcord is not running." }
    # /T also kills the child process the venv launcher spawns
    taskkill /PID $p.Id /T /F | Out-Null
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    return "voxcord is OFF."
}

switch ($Action) {
    "toggle" { Show-Message $(if (Get-BotProcess) { Stop-Bot } else { Start-Bot }) }
    "start"  { Show-Message (Start-Bot) }
    "stop"   { Show-Message (Stop-Bot) }
    "status" { Show-Message $(if ($p = Get-BotProcess) { "voxcord is running (PID $($p.Id), $([int]($p.WorkingSet64 / 1MB)) MB)." } else { "voxcord is not running." }) }
    "log"    { Get-Content "$logFile.err" -Tail 30 -ErrorAction SilentlyContinue }
    "shortcut" {
        $shell = New-Object -ComObject WScript.Shell
        $targets = @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))
        foreach ($t in $targets) {
            $lnk = $shell.CreateShortcut((Join-Path $t "voxcord.lnk"))
            $lnk.TargetPath = "powershell.exe"
            $lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSCommandPath`""
            $lnk.WorkingDirectory = $dir
            $lnk.IconLocation = "$env:SystemRoot\System32\mmres.dll,0"
            $lnk.Description = "Toggle the voxcord bot on/off"
            $lnk.Save()
        }
        "Created shortcuts on the Desktop and in the Start menu."
    }
}
