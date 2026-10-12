# vite dev server watchdog (Windows).
#
# WHY: the dev server kept dying silently mid-session (page went blank,
# 5173 stopped listening, nothing in the log). Cause was NOT vite --
# the box sat at 94.7% commit charge with only 20 MB of pagefile, so the
# process was being evicted. This script is the safety net for that, not
# the cure: free RAM (PyCharm, browser tabs) or it will just restart vite
# into the same wall.
#
# ENCODING: UTF-8 **without BOM**, per the repo rule for program-read files.
# Consequence: Windows PowerShell 5.1 reads a BOM-less .ps1 as ANSI (GBK on
# a zh-CN box), so Chinese literals in here would come out as mojibake.
# All messages below are ASCII-only on purpose.
#
# Usage:  npm run dev:watch     (from web/)
#         .\dev-watch.ps1       (same thing)
# Stop:   Ctrl+C
#
# LOGS (two files, deliberately separate):
#   dev-watch.log  - this script's own record
#   vite-out.log   - vite's stdout/stderr
# They MUST NOT be the same file: `cmd >> f` holds an exclusive handle on
# Windows, and the watcher's own appends then fail with "another program is
# using this file". Worse, the first version's catch block called this very
# function again, so the error handler itself threw and killed the watcher
# -- which is why it silently stopped watching instead of restarting vite.

param(
    [int]$Port = 5173,
    [int]$IntervalSec = 5,
    # Give up if it dies this many times inside the window, so a genuinely
    # broken build (bad vite.config, port held by something else) does not
    # become an infinite restart loop.
    [int]$MaxRestarts = 5,
    [int]$WindowSec = 60
)

$ErrorActionPreference = 'Stop'
$webDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$watchLog = Join-Path $webDir 'dev-watch.log'
$viteLog = Join-Path $webDir 'vite-out.log'
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Write-Log([string]$msg) {
    $line = "[{0:HH:mm:ss}] {1}" -f (Get-Date), $msg
    Write-Host $line
    # Never let logging take the watcher down. A watcher that dies of its own
    # error handling is worse than no watcher: it looks like it is working.
    try {
        [System.IO.File]::AppendAllText($watchLog, $line + "`r`n", $script:utf8)
    }
    catch {
        Write-Host ("  (could not write dev-watch.log: {0})" -f $_.Exception.Message)
    }
}

function Get-Listener {
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Stop-StaleListener {
    param($conn)
    if (-not $conn) { return }
    $pid_ = $conn.OwningProcess
    Write-Log "port $Port still held by PID $pid_ - stopping it before restart"
    Stop-Process -Id $pid_ -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

function Start-Vite {
    Write-Log "starting vite (npm run dev), output -> vite-out.log"
    # cmd.exe because that is what reliably does `>>` redirection on Windows.
    # Minimized + detached: the watcher must outlive the console it was
    # launched from, and vite's stdout must not share our console (their
    # Ctrl+C handling would fight).
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/c', ('npm run dev >> "{0}" 2>&1' -f $viteLog) `
        -WorkingDirectory $webDir `
        -WindowStyle Minimized
}

# Start each session on a fresh vite log; these grow by megabytes otherwise
# and nothing ever reads the old ones.
try { Remove-Item $viteLog -ErrorAction SilentlyContinue } catch { }

Write-Log "watching port $Port (check every ${IntervalSec}s, Ctrl+C to stop)"

$recent = New-Object System.Collections.ArrayList
$started = $false

while ($true) {
    try {
        $conn = Get-Listener

        if ($conn) {
            if (-not $started) {
                Write-Log "vite is up (PID $($conn.OwningProcess))"
                $started = $true
            }
            # Healthy for a while -> forgive the earlier failures.
            $cut = (Get-Date).AddSeconds(-$WindowSec)
            while ($recent.Count -gt 0 -and $recent[0] -lt $cut) { $recent.RemoveAt(0) }
        }
        else {
            if ($started) {
                Write-Log "vite DIED (nothing listening on $Port)"
                $started = $false
            }

            $now = Get-Date
            $cut = $now.AddSeconds(-$WindowSec)
            while ($recent.Count -gt 0 -and $recent[0] -lt $cut) { $recent.RemoveAt(0) }
            [void]$recent.Add($now)

            if ($recent.Count -ge $MaxRestarts) {
                Write-Log "restarted $MaxRestarts times in ${WindowSec}s - giving up (loop breaker)."
                Write-Log "Two likely causes, both need a human:"
                Write-Log "  1. out of memory - this box was at 94.7% commit with a 20 MB pagefile."
                Write-Log "     Close PyCharm / browser tabs, then: npm run dev:watch"
                Write-Log "  2. vite cannot start at all - read the last lines of vite-out.log."
                exit 1
            }

            # A port still bound after vite "died" means a zombie listener;
            # clear it or the new instance cannot bind.
            Stop-StaleListener (Get-Listener)
            Start-Vite
            Write-Log "restart issued (attempt $($recent.Count)/$MaxRestarts in ${WindowSec}s)"
        }
    }
    catch {
        Write-Log "watcher error: $($_.Exception.Message)"
    }

    Start-Sleep -Seconds $IntervalSec
}