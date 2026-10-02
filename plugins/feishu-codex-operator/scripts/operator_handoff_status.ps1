#requires -Version 7.0
[CmdletBinding()]
param([Parameter(Mandatory)][string]$RunDirectory,
      [Parameter(Mandatory)][ValidatePattern('^[a-f0-9]{64}$')][string]$Session,
      [switch]$Preview, [switch]$Library)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($RunDirectory)
if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw 'Maintenance directory missing.' }
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$form = [Windows.Forms.Form]::new()
$form.Text = 'Codex-Operator 更新状态'
if ($Preview) { $form.Text += '（界面测试）' }
$form.ClientSize = [Drawing.Size]::new(500,250)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.Font = [Drawing.Font]::new('Microsoft YaHei UI',10)
$title = [Windows.Forms.Label]::new()
$title.SetBounds(24,22,452,36)
$title.Font = [Drawing.Font]::new('Microsoft YaHei UI',15,[Drawing.FontStyle]::Bold)
$body = [Windows.Forms.Label]::new()
$body.SetBounds(24,66,452,105)
$hint = [Windows.Forms.Label]::new()
$hint.SetBounds(24,176,452,26)
$hint.ForeColor = [Drawing.Color]::DimGray
$button = [Windows.Forms.Button]::new()
$button.SetBounds(350,207,125,30)
$button.Text = '暂不升级'
$form.Controls.AddRange(@($title,$body,$hint,$button))
$script:phase = 'preparing'
$script:terminal = $false
$script:deferred = $false
$script:opened = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$title.Text = '正在准备更新'
$body.Text = '请先保持 Codex 打开。准备完成后，这里会显示下一步。'

function Write-Signal([string]$Name, $Value) {
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($Value | ConvertTo-Json -Compress))
    $temporary = Join-Path $root ($Name + '.pending')
    $file = [IO.File]::Open($temporary,[IO.FileMode]::CreateNew)
    try { $file.Write($bytes,0,$bytes.Length); $file.Flush($true) } finally { $file.Dispose() }
    [IO.File]::Move($temporary,(Join-Path $root $Name))
}

function Read-Status {
    # Read the final complete record from the bounded single-writer journal.
    # Do not rename a status file underneath an open Windows reader.
    $file = [IO.File]::Open((Join-Path $root 'feedback.jsonl'),[IO.FileMode]::Open,
        [IO.FileAccess]::Read,([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
    try {
        if ($file.Length -gt 524288) { throw 'Status bound.' }
        $reader = [IO.StreamReader]::new($file,[Text.UTF8Encoding]::new($false,$true))
        try {
            $text = $reader.ReadToEnd()
            $end = $text.LastIndexOf("`n")
            if ($end -lt 0) { throw 'Incomplete status.' }
            $complete = $text.Substring(0,$end)
            $last = $complete.Substring($complete.LastIndexOf("`n")+1)
            if ($last.Length -gt 4096) { throw 'Status record bound.' }
            return ($last | ConvertFrom-Json)
        } finally { $reader.Dispose() }
    } finally { $file.Dispose() }
}

function Request-Defer {
    if ($script:terminal) { $form.Close(); return }
    if ($script:phase -notin @('preparing','waiting') -or $script:deferred) { return }
    Write-Signal 'defer.json' @{schema_version=1;session=$Session}
    $script:deferred = $true
    $button.Enabled = $false
    $hint.Text = '已请求暂不升级，正在等待后台确认。'
}
$button.Add_Click({ try { Request-Defer } catch { Show-Terminal 'review_required' } })
$form.Add_FormClosing({
    param($sender,$event)
    if (-not $script:terminal) {
        $event.Cancel = $true
        try { Request-Defer } catch { Show-Terminal 'review_required' }
    }
})
$form.Add_Shown({
    if (-not $form.Visible -or -not $form.IsHandleCreated -or $form.WindowState -eq 'Minimized') {
        throw 'Maintenance window is not shown.'
    }
    Write-Signal 'feedback-ready.json' @{schema_version=1;session=$Session;pid=$PID}
})
function Show-Terminal([string]$Outcome) {
    $script:terminal = $true
    $button.Text = '关闭'
    $button.Enabled = $true
    $hint.Text = '本次结果已保存。'
    switch ($Outcome) {
        'complete' { $title.Text='已更新并启动 Codex'; $body.Text='配置已启用。请在 Codex 主窗口确认模型选择和对话是否正常。'; }
        'native_entry_updated' { $title.Text='入口已更新，已打开原生 Codex'; $body.Text='拓展模型选择入口已更新。当前仍为官方原生模式，请先确认主窗口正常；使用自定义模型时再从拓展入口选择。'; }
        'deferred' { $title.Text='本次暂不升级'; $body.Text='配置未改动。可以继续使用 Codex，下次由助手重新检查后安排。'; }
        'wait_expired' { $title.Text='尚未确认 Codex 完全退出'; $body.Text='本次等待已结束，配置未改动。窗口关闭不一定代表应用退出。请告诉助手这个结果，不需要结束任务管理器中的进程。'; }
        'preflight_failed' { $title.Text='更新尚未开始'; $body.Text='准备或退出检查未能完成，配置未改动。请保留当前状态并告知助手。'; }
        'native_recovered' { $title.Text='更新中止，已打开官方模式'; $body.Text='本次更新未完成。官方直连已核实并重新打开，请告知助手继续检查。'; }
        default { $title.Text='更新结果需要检查'; $body.Text='后台未确认完整完成。请保留现场并告知助手，不必再次退出或重复升级。'; }
    }
}
$timer = [Windows.Forms.Timer]::new()
$timer.Interval = 500
$timer.Add_Tick({
    try {
        $value = Read-Status
        if ($value.schema_version -ne 1 -or $value.session -cne $Session -or
            $value.phase -notin @('preparing','waiting','applying','opening','finished')) { throw 'Status identity.' }
        $script:phase = $value.phase
        if ($value.phase -eq 'finished') { Show-Terminal $value.outcome; $timer.Stop(); return }
        $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        if ($now - $value.updated_at -gt 150 -or $now - $script:opened -gt 900) { throw 'Status expired.' }
        $button.Enabled = -not $script:deferred -and $value.phase -in @('preparing','waiting')
        switch ($value.phase) {
            'waiting' {
                $title.Text = '等待 Codex 完全退出'
                $body.Text = '请先保存工作，通过 Codex 的退出功能完全退出应用。仅关闭主窗口可能仍留在后台。退出确认后会自动更新并打开 Codex，无需在关闭期间回复。'
                if ($Preview) { $body.Text = '这是独立的界面测试，请保持 Codex 打开。测试窗口不会升级配置、停止服务或重开应用。可以点击“暂不升级”验证取消等待。' }
                if (-not $script:deferred) {
                    $seconds = [Math]::Max(0,[Math]::Min(600,[int]$value.remaining_seconds))
                    $hint.Text = "剩余等待 $seconds 秒；也可以选择暂不升级。"
                }
            }
            'applying' { $title.Text='正在更新配置'; $body.Text='已确认 Codex 退出。正在完成已审核的更新步骤，请稍候。'; $hint.Text='完成后会自动打开 Codex。' }
            'opening' { $title.Text='正在打开 Codex'; $body.Text='配置已启用，正在等待官方应用启动确认。'; $hint.Text='这里会显示最终结果。' }
        }
    } catch {
        Show-Terminal 'review_required'
        $timer.Stop()
    }
})
if ($Library) { return }
$timer.Start()
try { [Windows.Forms.Application]::Run($form) } finally { $timer.Dispose(); $form.Dispose() }
