# Runs the game at several aspect ratios at once, one window each, stacked on the
# screen, to compare widescreen culling side by side. A controller drives every
# window together (background input, in general.json, is on); the keyboard only
# reaches the focused one.
#   powershell -File host\multi_aspect.ps1 [-Aspects "16x9,21x9,32x9"] [-Height 300] [-Seconds N] [-Shots "20,40"] [-Env "NAME=value,NAME"]
# Each window gets its own data folder, host\build-win\instances\<aspect>: links to
# the build, and copies of the settings, save and ROMs kept next to the build (the
# portable data in host\build-win, or else %LOCALAPPDATA%\ConkerRecompiled), set to
# windowed. So the instances never touch the player's own saves or each other's.
# -Seconds starts the game directly (no launcher) and quits after that long; -Shots
# saves a screenshot of every window at those seconds (instances\<aspect>\shotN.png).
# -Env sets environment variables for every window (a name alone sets it to 1), such
# as the debug switches; anything they log lands in the window's instance folder.
param(
    [string]$Aspects = "16x9,21x9,32x9",
    [int]$Height = 300,
    [int]$Seconds = 0,
    [string]$Shots = "",
    [string]$Env = ""
)
$ErrorActionPreference = "Stop"
$build = Join-Path $PSScriptRoot "build-win"
$source = if (Test-Path (Join-Path $build "portable.txt")) { $build } else { Join-Path $env:LOCALAPPDATA "ConkerRecompiled" }
$instancesDir = Join-Path $build "instances"

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class MultiAspectWin {
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int w, int ht, uint flags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

function New-Instance([string]$name) {
    $dir = Join-Path $instancesDir $name
    New-Item -ItemType Directory -Force $dir | Out-Null
    # The build: hard links to the exe and its libraries (made again every run, so a
    # rebuild is picked up), and a junction to the menus' assets.
    Get-ChildItem -LiteralPath $build -File | Where-Object { $_.Extension -in ".exe", ".dll" } | ForEach-Object {
        $link = Join-Path $dir $_.Name
        if (Test-Path -LiteralPath $link) { Remove-Item -LiteralPath $link -Force }
        New-Item -ItemType HardLink -Path $link -Target $_.FullName | Out-Null
    }
    $assets = Join-Path $dir "assets"
    if (-not (Test-Path -LiteralPath $assets)) {
        New-Item -ItemType Junction -Path $assets -Target (Join-Path $build "assets") | Out-Null
    }
    # The data: ROMs linked, settings and save copied once (an instance keeps its own).
    $data = @(Get-ChildItem -LiteralPath $source -File | Where-Object { $_.Extension -in ".z64", ".json", ".bak" -and $_.Name -ne "compile_commands.json" })
    foreach ($sub in "saves", "mods", "rom_versions") {
        $subDir = Join-Path $source $sub
        if (Test-Path -LiteralPath $subDir) { $data += Get-ChildItem -LiteralPath $subDir -File }
    }
    $data | ForEach-Object {
        $relative = $_.FullName.Substring($source.Length).TrimStart("\")
        $target = Join-Path $dir $relative
        if (Test-Path -LiteralPath $target) { return }
        New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
        if ($_.Extension -eq ".z64") {
            # A hard link can't cross drives (the data in %LOCALAPPDATA% on C:, the build on D:): copy then.
            $rom = $_.FullName
            try { New-Item -ItemType HardLink -Path $target -Target $rom -ErrorAction Stop | Out-Null }
            catch { Copy-Item -LiteralPath $rom -Destination $target }
        }
        else { Copy-Item -LiteralPath $_.FullName -Destination $target }
    }
    Set-Content -LiteralPath (Join-Path $dir "portable.txt") -Value "Test instance ($name): data lives next to the exe." -Encoding utf8
    $graphics = Join-Path $dir "graphics.json"
    if (Test-Path -LiteralPath $graphics) {
        (Get-Content -LiteralPath $graphics -Raw) -replace '"wm_option":\s*"[A-Za-z]+"', '"wm_option": "Windowed"' | Set-Content -LiteralPath $graphics -Encoding utf8 -NoNewline
    }
    return $dir
}

# The windows inherit this script's environment, which ends with it.
foreach ($pair in ($Env.Split(",") | Where-Object { $_.Trim() })) {
    $name, $value = $pair.Trim().Split("=", 2)
    if ($null -eq $value) { $value = "1" }
    Set-Item -Path "Env:$name" -Value $value
    Write-Output "Env: $name=$value"
}

$y = 0
$processes = @()
foreach ($aspect in $Aspects.Split(",")) {
    $parts = $aspect.Trim().Split("x")
    $width = [int][math]::Round($Height * [double]$parts[0] / [double]$parts[1])
    $dir = New-Instance $aspect.Trim()
    $arguments = @("--window", "${width}x${Height}")
    if ($Seconds -gt 0) { $arguments += @("--seconds", "$Seconds") }
    $p = Start-Process -FilePath (Join-Path $dir "ConkerRecomp.exe") -ArgumentList $arguments -WorkingDirectory $dir -PassThru `
        -RedirectStandardOutput (Join-Path $dir "run-out.txt") -RedirectStandardError (Join-Path $dir "run-err.txt")
    $processes += [pscustomobject]@{ Name = $aspect.Trim(); Process = $p; Dir = $dir; Y = $y }
    $y += $Height + 45
}

# Stack the windows at the left of the screen once they exist.
$deadline = (Get-Date).AddSeconds(30)
foreach ($entry in $processes) {
    while ($entry.Process.MainWindowHandle -eq 0 -and (Get-Date) -lt $deadline -and -not $entry.Process.HasExited) {
        Start-Sleep -Milliseconds 250
        $entry.Process.Refresh()
    }
    if ($entry.Process.MainWindowHandle -ne 0) {
        [MultiAspectWin]::SetWindowPos($entry.Process.MainWindowHandle, [IntPtr]::Zero, 0, $entry.Y, 0, 0, 0x0001 -bor 0x0004) | Out-Null
    }
}
Write-Output ("Running: " + (($processes | ForEach-Object { "$($_.Name) (pid $($_.Process.Id))" }) -join ", "))

if ($Shots) {
    $start = $processes[0].Process.StartTime
    foreach ($t in ($Shots.Split(",") | ForEach-Object { [double]$_ })) {
        $wait = $start.AddSeconds($t) - (Get-Date)
        if ($wait.TotalMilliseconds -gt 0) { Start-Sleep -Milliseconds ([int]$wait.TotalMilliseconds) }
        foreach ($entry in $processes) {
            $r = New-Object MultiAspectWin+RECT
            if ($entry.Process.HasExited -or -not [MultiAspectWin]::GetWindowRect($entry.Process.MainWindowHandle, [ref]$r)) { continue }
            $bitmap = New-Object System.Drawing.Bitmap ($r.Right - $r.Left), ($r.Bottom - $r.Top)
            $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
            $graphics.CopyFromScreen($r.Left, $r.Top, 0, 0, $bitmap.Size)
            $bitmap.Save((Join-Path $entry.Dir "shot$t.png"))
            $graphics.Dispose(); $bitmap.Dispose()
        }
    }
}
if ($Seconds -gt 0) {
    foreach ($entry in $processes) { $entry.Process.WaitForExit(($Seconds + 30) * 1000) | Out-Null }
}
