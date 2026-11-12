# 部署与离线交付（WP10b）

> 方案：[`optimization_plan_v111.md`](optimization_plan_v111.md) §WP10 10b

## 0. 安全边界（先读这段）

本仓 `SECURITY.md` 明确：**IEC104 Tester 是协议调试/联调工具，不应作为生产
SCADA 网关使用**。容器化、systemd、Windows 服务只解决「无人值守长期跑」，
**不改变这条边界**。具体含义：

- 没有多用户协作/审计合规/高可用/冗余切换的业务保证；
- 监听非回环地址时**必须**配置 `--auth-token` 或 `--auth-config`；
  否则同网段任何主机都能下发遥控（界面会显示醒目告警，但那是提醒不是防护）；
- 面向公网请前置反向代理 + TLS（本仓的 `--web-tls-cert/--web-tls-key` 只覆盖
  到服务本身）。

## 1. 三种交付形态

| 形态 | 适用 | 入口 |
|---|---|---|
| 单文件 exe | 现场笔记本/无 Python 环境 | `python build/build_all.py --onefile` → `dist/iec104-tester.exe` |
| Docker / compose | 服务器常驻、内网平台统一编排 | `Dockerfile` + `docker-compose.yml` |
| systemd / Windows 服务 | 无人值守、开机自启 | `deploy/iec104-tester.service` / `deploy/install-service.ps1` |

三者跑的是同一份 `app.py`，行为一致。

## 2. Docker

```bash
cp deploy/.env.example .env
# 必改：IEC104_AUTH_TOKEN=<足够随机的长串>
docker compose up -d
curl -H "Authorization: Bearer $IEC104_AUTH_TOKEN" http://127.0.0.1:8765/api/status
```

- 前端在**构建阶段**用 node 编译，运行时镜像**不含 node**；
- 数据卷 `iec104-data` → 容器 `/data`（历史库/审计库/验收库都在这里），
  容器重建不丢记录；
- `configs/` 以只读方式挂进容器，现场维护的**工程配置方案**（`configs/profiles/`）
  改完即生效，不必重建镜像；
- 健康检查打 `/api/status`（无令牌时会 401，属预期）。

需要原生 PDF 报告时，在 `Dockerfile` 的 `pip install` 一行加上 `.[pdf]` 或
`reportlab`（见 §5）。

## 3. systemd（Linux）

```bash
sudo cp deploy/iec104-tester.service /etc/systemd/system/
sudo mkdir -p /etc/iec104-tester
sudo cp deploy/.env.example /etc/iec104-tester/env   # 改掉令牌
sudo systemctl daemon-reload && sudo systemctl enable --now iec104-tester
journalctl -u iec104-tester -f
```

单元里已做基础加固（`NoNewPrivileges`/`ProtectSystem=full`/`ProtectHome`，
`ReadWritePaths` 只放开 `data/` 与 `logs/`）。
**旁路抓包（WP9）需要 `CAP_NET_RAW`**：把单元里注释掉的两行
`AmbientCapabilities` / `CapabilityBoundingSet` 打开即可，不必给整个服务 root。

## 4. Windows 服务

```powershell
# 需管理员身份；先打 exe
python build/build_all.py --onefile
.\deploy\install-service.ps1 -ExePath .\dist\iec104-tester.exe -AuthToken '<长令牌>'
.\deploy\install-service.ps1 -Action status
.\deploy\install-service.ps1 -Action uninstall
```

- 用系统自带 `sc.exe` 注册，**不引入 NSSM 等第三方二进制**（离线环境少一个依赖）；
- 令牌写在**机器级环境变量**（`IEC104_AUTH_TOKEN`）而不是服务命令行里——
  否则会出现在任务管理器/事件日志；
- 未提供 `-AuthToken` 时脚本**拒绝安装**（不留裸奔配置）；
- 日志：服务的 stdout/stderr 由 `app.py` 的日志系统写 `logs/`，用
  `Get-Content logs\*.log -Wait` 跟踪；
- 开机自启由 `start= auto` + `sc.exe failure ... restart` 保证。

## 5. 离线 / 内网部署

目标：**断网机器上全功能可用**（无 CDN、无外部 Python 源）。

1. **前端不依赖 CDN**：`npm run build` 的产物全部在 `webui/static/app/`，
   字体（Carbon/PF 的 woff2）随包打进 `static`，页面加载不发外部请求。
2. **Python 依赖离线安装**（在有网机器上准备）：
   ```bash
   pip download -r requirements.txt -d wheels/
   pip download reportlab -d wheels/        # 需要原生 PDF 时
   # 拷贝 wheels/ 到离线机
   pip install --no-index --find-links=wheels -r requirements.txt
   pip install --no-index --find-links=wheels reportlab
   ```
3. **最省事的形态**：直接用 onefile exe（Python 运行时已打包，无需装任何东西）。
4. **Docker 镜像离线搬运**：
   ```bash
   docker save iec104-tester:latest -o iec104-tester.tar
   # 离线机： docker load -i iec104-tester.tar
   ```
5. 旁路抓包在离线机需要事先装好 **Npcap**（Windows）或使用 Linux（AF_PACKET 内置）。

## 6. 随包 CLI 工具

`build/build_all.py` 除 `iec104-tester` 外还产出：

| 可执行 | 用途 |
|---|---|
| `iec104-tester` | Web 工作台（默认 both：一个端口两个角色） |
| `iec104-capture` | 离线抓包分析（pcap 过滤/统计/导出） |
| `iec104-sim` | 无界面数据模拟器（压测/背景流量） |
| `iec104-multi` | 多子站编排（命令行形态） |
| `iec104-runtests` | 批量跑 `tests/scripts/*.yaml` 测试脚本 |

这些都进 `dist/`，离线机器上可直接双击/命令行使用。

## 7. 验证命令

```bash
# 容器（需 docker）
docker compose up -d && docker compose ps
curl -s -H "Authorization: Bearer $IEC104_AUTH_TOKEN" localhost:8765/api/status | head -c 200

# 无 docker 时的等价冒烟：直接用本机 Python 起同一入口
python app.py --mode both --no-browser --http-port 8799 &
curl -s localhost:8799/api/status >/dev/null && echo "可用"

# 打包器会随包带上 CLI 工具（构建后检查）
python build/build_all.py --onefile && ls dist/
```
