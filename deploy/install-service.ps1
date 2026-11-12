<#
.SYNOPSIS
  以 Windows 服务方式安装 IEC104 Tester（WP10b）。

.DESCRIPTION
  用 Windows 自带 sc.exe 注册服务（不依赖 NSSM，避免多一个第三方二进制）。
  服务以 `--no-gui` 无头模式跑，日志写入 logs\service.log，可用
  `Get-Content logs\service.log -Wait` 查看。

  ⚠ 安全边界：本工具是协议调试工具，不是生产 SCADA 网关（见 SECURITY.md）。
    监听非回环地址时**必须**设置访问令牌，否则同网段任何主机都能下发遥控。

.EXAMPLE
  # 需以管理员身份运行
  .\deploy\install-service.ps1 -ExePath .\dist\iec104-tester.exe -AuthToken 'your-long-token'
  .\deploy\install-service.ps1 -Action uninstall
#>
[CmdletBinding()]
param(
  [ValidateSet('install', 'uninstall', 'status')]
  [string]$Action = 'install',

  [string]$ExePath = ".\dist\iec104-tester.exe",
  [string]$ServiceName = 'iec104-tester',
  [string]$DisplayName = 'IEC104 Tester',

  # 访问令牌；为空时**拒绝安装并提示**（不留"裸奔"的服务配置）
  [string]$AuthToken = '',
  [string]$HttpHost = '127.0.0.1',
  [int]$HttpPort = 8765,
  [string]$Mode = 'both'
)

$ErrorActionPreference = 'Stop'

function Assert-Admin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($id)
  if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw '请以管理员身份运行（注册/删除服务需要提权）。'
  }
}

switch ($Action) {
  'uninstall' {
    Assert-Admin
    if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
      Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
      sc.exe delete $ServiceName | Out-Null
      Write-Host "已卸载服务 $ServiceName"
    } else {
      Write-Host "服务 $ServiceName 不存在，无需卸载"
    }
    break
  }

  'status' {
    Get-Service -Name $ServiceName -ErrorAction SilentlyContinue |
      Format-List Name, Status, StartType, DisplayName
    break
  }

  'install' {
    Assert-Admin
    if (-not (Test-Path -LiteralPath $ExePath)) {
      throw "找不到可执行文件：$ExePath（先运行 python build/build_all.py --onefile）"
    }
    if ([string]::IsNullOrWhiteSpace($AuthToken)) {
      throw '必须提供 -AuthToken：本服务会监听端口并具备遥控下发能力，无令牌等于对同网段完全开放。'
    }
    $exe = (Resolve-Path -LiteralPath $ExePath).Path
    $logDir = Join-Path (Split-Path $exe -Parent) 'logs'
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null

    $binPath = '"{0}" --mode {1} --no-browser --no-gui --http-host {2} --http-port {3}' -f `
      $exe, $Mode, $HttpHost, $HttpPort
    # 令牌经环境变量传入（不写进服务命令行，避免出现在任务管理器/事件日志里）
    [Environment]::SetEnvironmentVariable('IEC104_AUTH_TOKEN', $AuthToken, 'Machine')

    if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
      Write-Host "服务已存在，先停止并删除后重装"
      Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
      sc.exe delete $ServiceName | Out-Null
      Start-Sleep -Seconds 1
    }

    sc.exe create $ServiceName binPath= $binPath start= auto DisplayName= $DisplayName | Out-Null
    sc.exe description $ServiceName 'IEC 60870-5-104 协议调试工作台（Web）' | Out-Null
    # 崩溃自动重启：失败后 5s、10s、30s 各重试一次
    sc.exe failure $ServiceName reset= 86400 actions= restart/5000/restart/10000/restart/30000 | Out-Null
    sc.exe start $ServiceName | Out-Null

    Start-Sleep -Seconds 2
    Get-Service -Name $ServiceName | Format-List Name, Status, StartType
    Write-Host ""
    Write-Host "已安装。Web UI: http://$HttpHost`:$HttpPort/  （令牌见 Machine 级环境变量 IEC104_AUTH_TOKEN）"
    Write-Host "查看状态：.\deploy\install-service.ps1 -Action status"
    Write-Host "卸载：    .\deploy\install-service.ps1 -Action uninstall"
  }
}
