# TLS / IEC 62351 传输层加密（T20）

IEC 104 原生的 TCP 传输是**明文**的：报文可被窃听、篡改，任何人都能连上子站。
本功能为传输层加上 TLS 加密。

> ## ⚠ 覆盖边界（请先读这一节）
>
> **本功能只实现 TLS 传输层加密**，对应 IEC 62351 中的传输层安全部分
> （即 **IEC 62351-3** 所涉及的方向）。
>
> **它不等于"IEC 62351 合规"。** IEC 62351 是一整套标准族，以下部分
> **本次完全未实现**，请在对外表述中明确区分：
>
> | IEC 62351 内容 | 本次状态 |
> | --- | --- |
> | TLS 传输层加密（证书/密钥、CA 校验、双向认证） | ✅ **已实现** |
> | 应用层报文认证（IEC 62351-4 的 ACK/认证封装、62351-6 的签名） | ❌ **未实现** |
> | 会话密钥协商、安全关联（SA）管理 | ❌ **未实现** |
> | 访问控制、角色与权限模型（62351-8） | ❌ **未实现** |
> | 证书吊销检查（CRL / OCSP） | ❌ **未实现** |
> | 重放防护、序列完整性（除 TLS 本身外） | ❌ **未实现** |
> | 密钥轮换、证书生命周期管理 | ❌ **未实现** |
>
> 换句话说：**启用了本功能，报文在链路上是加密且服务端可被认证的；
> 但应用层"谁发了什么命令"的不可否认性、以及标准规定的安全关联机制并不存在。**
> 不要把它描述为"已支持 IEC 62351"。

## 1. 能力清单

已实现：

- TLS 1.2 及以上（`minimum_version = TLSv1_2`），禁止更老协议。
- 服务端（子站）证书 + 私钥加载。
- 客户端（主站）校验服务端证书，可指定受信 CA；未指定时用系统信任库。
- **双向认证（mTLS）**：子站可要求并校验客户端证书。
- 客户端可关闭校验（`verify=false` / `--no-verify`），**仅供自签证书联调**。
- 主机名校验可覆盖（按 IP 连接而证书只签了域名时用 `server_hostname`）。
- 主子站 CLI 与多站管理器均支持逐站 `tls.enabled`。

## 2. 配置

### 2.1 YAML

```yaml
tls:
  enabled: true
  certfile: "certs/server.pem"   # 子站必填；主站双向认证时填客户端证书
  keyfile:  "certs/server.key"   # 空 = 与证书同文件
  cafile:   "certs/ca.pem"       # 受信 CA；主站空 = 系统信任库
  verify: true                   # 主站是否校验服务端证书（生产必须 true）
  verify_client: false           # 子站是否要求客户端证书（mTLS）
  server_hostname: ""            # 主站主机名校验用域名
```

字段含义见 `core/config.py: TlsConfig` 的 docstring。
`configs/slave_config.yaml` / `configs/master_config.yaml` 已带示例块（默认 `enabled: false`）。

### 2.2 命令行

| 开关 | 说明 |
| --- | --- |
| `--tls` | 启用 TLS |
| `--tls-cert <PEM>` | 本端证书 |
| `--tls-key <PEM>` | 本端私钥 |
| `--tls-ca <PEM>` | 受信 CA |
| `--no-verify` | 主站跳过服务端证书校验（**仅联调，生产禁用**） |
| `--verify-client` | 子站要求客户端证书（mTLS） |
| `--tls-hostname <name>` | 主站主机名校验用域名 |

命令行优先级高于配置文件。

### 2.3 多站

`StationConfig.tls` 支持 `TlsConfig` 实例或 dict（Web UI 多站请求直接透传
`{"tls": {...}}` 即可，`webui/session.py` 的 `StationConfig(**s)` 会原样转发）。
见 `configs/multi_station_example.yaml`。

### 2.4 典型组合

**A. 子站启用 TLS，主站严格校验（生产推荐）**

```bash
# 子站
python app.py --mode slave --config configs/slave_config.yaml \
  --tls --tls-cert certs/server.pem --tls-key certs/server.key

# 主站
python app.py --mode master \
  --tls --tls-ca certs/ca.pem --tls-hostname iec104.local
```

**B. 自签证书联调（主站不校验）**

```bash
python app.py --mode master --tls --no-verify
```

**C. 双向认证（mTLS）**

```bash
# 子站：要求客户端证书
python app.py --mode slave \
  --tls --tls-cert certs/server.pem --tls-key certs/server.key \
  --tls-ca certs/ca.pem --verify-client

# 主站：带客户端证书并校验服务端
python app.py --mode master \
  --tls --tls-cert certs/client.pem --tls-key certs/client.key \
  --tls-ca certs/ca.pem --tls-hostname localhost
```

## 3. 证书生成

测试证书已随仓库提供（`tests/certs/`，自签、**仅供测试**，100 年有效期），
生成命令见 `tests/certs/README.md`。

生产/联调证书按下述方式自签（示例用 `openssl` CLI，无需 Python 依赖）：

```bash
# ① 根 CA（必须带 CA:TRUE 与 keyCertSign，否则 OpenSSL 3.x 不认它是信任锚）
openssl req -x509 -newkey rsa:2048 -keyout ca.key -out ca.pem -days 3650 -nodes \
  -subj "/CN=My IEC104 CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

# ② 服务端证书（SAN 必须包含主站实际连接用的名字/IP）
printf 'subjectAltName=DNS:iec104.local,IP:192.168.1.10\nbasicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' > server.ext
openssl req -newkey rsa:2048 -keyout server.key -out server.csr -nodes \
  -subj "/CN=iec104.local"
openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial \
  -out server.pem -days 3650 -extfile server.ext

# ③ 客户端证书（仅 mTLS 需要）
printf 'basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=clientAuth\n' > client.ext
openssl req -newkey rsa:2048 -keyout client.key -out client.csr -nodes \
  -subj "/CN=iec104-client"
openssl x509 -req -in client.csr -CA ca.pem -CAkey ca.key -CAcreateserial \
  -out client.pem -days 3650 -extfile client.ext

# ④ 自检
openssl verify -CAfile ca.pem server.pem client.pem
```

> **踩坑记录**：只写 `-subj`、不带 `-addext basicConstraints=CA:TRUE,keyUsage=keyCertSign`
> 生成的 CA，OpenSSL 3.x 会报
> `CA cert does not include key usage extension` 并拒绝建立信任链。
> 我们第一版测试证书就踩了这个坑，已在 `tests/certs/README.md` 标注。

## 4. 常见错误与排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `CERTIFICATE_VERIFY_FAILED: self-signed certificate` | 主站没配受信 CA | 用 `--tls-ca ca.pem`；联调用 `--no-verify`（生产禁用） |
| `CERTIFICATE_VERIFY_FAILED: CA cert does not include key usage extension` | CA 证书缺 `basicConstraints=CA:TRUE` / `keyUsage=keyCertSign` | 按 §3 重新签发 CA |
| `Hostname mismatch, certificate is not valid for '127.0.0.1'` | 用 IP 连接但证书 SAN 只有域名（或反之） | 证书 SAN 加上该 IP；或用 `--tls-hostname` 指定证书里的域名 |
| `SSLCertVerificationError` 之后再无日志 | 主站未重连（`reconnect: false`） | 预期行为：严格校验失败不重试；修好证书后重启 |
| 子站起了 TLS，主站明文连 | 一端 TLS 一端明文 | 两端都启用；子站日志会打印 `Server started on ... (TLS)` |
| `TLS 配置无效，已回退为明文传输` | 证书/密钥路径不存在 | 检查 `--tls-cert` / `--tls-key` 路径；**注意这是降级而非报错退出** |
| mTLS 下主站连不上 | 子站开了 `verify_client` 但主站没带客户端证书 | 主站补 `--tls-cert client.pem --tls-key client.key` |

> **降级策略（有意为之）**：TLS 配置无效时引擎会记 ERROR 并**回退为明文**继续启动，
> 而不是直接退出——避免一个路径笔误导致整套连接不可用。**代价是明文可能在
> 无察觉的情况下被使用**，因此部署时应 grep 启动日志确认没有
> `已回退为明文传输`，并确认看到 `TLS enabled (...)`。

## 5. 实现说明与已知接缝

- 传输层实现统一在 `core/transport/connection.py`（遵循
  `docs/transport_design.md` §4 的约定），未新增模块。
- `TCPClient` / `TCPServer` 新增可选参数 `ssl_context`（默认 `None` = 明文，
  与改动前完全一致）与 `set_ssl_context()` 注入方法；`tls_enabled` 属性可观测。
- `certfile` / `keyfile` / `cafile` 的校验集中在
  `build_server_context()` / `build_client_context()`，路径不存在会抛
  `TlsConfigError`（带明确中文说明），不会泄漏到 asyncio 层。
- **已知接缝（需要后续重构）**：`MasterEngine` / `SlaveEngine` 在构造时自行创建
  `TCPClient` / `TCPServer`，且其源码不在本次改动范围，因此
  `configure_engine_tls()` 是**按私有属性注入**（`engine._client` /
  `engine._server`）。若将来把 `ssl` 参数贯穿到引擎构造函数，该函数可整体删除。
  调用必须在引擎 `start()` 之前。
- **未覆盖**：Web UI 单站模式（`webui/server.py` → `webui/session.py` 的
  `start_master` / `start_slave`）暂未接线 TLS——`webui/session.py` 不在本次
  改动范围。多站模式**已支持**（走 `StationConfig.tls`）。
  Web 单站 TLS 需要给 `EngineSession` 增一个 `tls` 参数，属独立小任务。

## 6. 测试

`tests/test_tls_transport.py`（27 例，自签证书，无外部依赖）：

- **传输层**：自签 CA 下握手成功 + STARTDT 往返；`verify=False` 放行不受信证书；
  不受信 CA 被拒；主机名不匹配被拒；mTLS 客户端带/不带证书的成功与失败路径；
  TLS 下 `close()` 幂等、`stop()` 有界；未启用 TLS 时行为不变。
- **配置层**：`TlsConfig` YAML 往返、默认关闭、`TlsConfigError` 明确报错、
  `configure_engine_tls` 的注入/禁用/缺传输对象三种分支。
- **真引擎端到端**：真实 `MasterEngine` + `SlaveEngine` 在 TLS 下握手成功、
  进入 Running 并完成总召唤；不受信证书下始终无法进入 Running。
- **多站**：`MultiStationManager` 逐站 TLS，主站握手成功进入 Running。

```bash
./venv/Scripts/python.exe -m pytest tests/test_tls_transport.py -q
```
