# TLS 测试证书（测试专用自签 · 非机密 · 禁用于生产）

这些是本仓库 TLS 测试（`tests/test_tls_transport.py`）使用的**测试专用自签证书**。

> **性质声明（逐条）**
> 1. 本目录下所有 `.pem` / `.key` 均为**测试专用自签证书**及配套私钥。
> 2. 它们**不是机密**（not confidential）：私钥仅用于本地单元测试握手，
>    在仓库中公开并无泄露风险。
> 3. **不得用于任何真实环境或生产环境**（DO NOT USE IN PRODUCTION）——
>    任何人不得将它们部署到真实服务、真实客户端或任何非测试用途。
> 4. 私钥文件顶部均带 `#` 注释行作醒目警示；OpenSSL 3.x 与 Python `ssl`
>    均可正常读取带注释的 PEM（已实测）。

有效期 100 年（至 2126 年），避免测试因证书过期而失效。

## 文件

| 文件 | 说明 |
| --- | --- |
| `ca1.pem` | 受信 CA（自签根） |
| `ca2.pem` | **不受信** CA（用于"客户端拒绝不受信证书"失败路径） |
| `server.pem` / `server.key` | 服务端证书，由 `ca1` 签发，SAN = `DNS:localhost, IP:127.0.0.1` |
| `client.pem` / `client.key` | 客户端证书，由 `ca1` 签发（双向认证 / mTLS 用） |
| `badserver.pem` / `badserver.key` | 服务端证书，由**不受信的 `ca2`** 签发（失败路径用） |

## 重新生成

无需额外 Python 依赖，仅用 `openssl` CLI。

> ⚠ **必须带扩展**：OpenSSL 3.x 校验链时要求 CA 证书含
> `basicConstraints=CA:TRUE` 与 `keyUsage=keyCertSign`，否则会报
> `CA cert does not include key usage extension`（我们第一版就踩了这个坑）。
> 叶子证书需含 `basicConstraints=CA:FALSE` 与匹配的 `extendedKeyUsage`。

```bash
# ── 根 CA ──
openssl req -x509 -newkey rsa:2048 -keyout ca1.key -out ca1.pem -days 36500 -nodes \
  -subj "/CN=IEC104 Test CA 1" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

openssl req -x509 -newkey rsa:2048 -keyout ca2.key -out ca2.pem -days 36500 -nodes \
  -subj "/CN=IEC104 Test CA 2 (Untrusted)" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

# ── 叶子证书扩展 ──
printf 'subjectAltName=DNS:localhost,IP:127.0.0.1\nbasicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' > san.ext
printf 'basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=clientAuth\n' > cli.ext

# ── 服务端证书（ca1 签发）──
openssl req -newkey rsa:2048 -keyout server.key -out server.csr -nodes \
  -subj "/CN=localhost"
openssl x509 -req -in server.csr -CA ca1.pem -CAkey ca1.key -CAcreateserial \
  -out server.pem -days 36500 -extfile san.ext

# ── 客户端证书（ca1 签发，mTLS 用）──
openssl req -newkey rsa:2048 -keyout client.key -out client.csr -nodes \
  -subj "/CN=iec104-client"
openssl x509 -req -in client.csr -CA ca1.pem -CAkey ca1.key -CAcreateserial \
  -out client.pem -days 36500 -extfile cli.ext

# ── 不受信服务端证书（ca2 签发，失败路径用）──
openssl req -newkey rsa:2048 -keyout badserver.key -out badserver.csr -nodes \
  -subj "/CN=localhost"
openssl x509 -req -in badserver.csr -CA ca2.pem -CAkey ca2.key -CAcreateserial \
  -out badserver.pem -days 36500 -extfile san.ext

# ── 自检 ──
openssl verify -CAfile ca1.pem server.pem client.pem
openssl verify -CAfile ca2.pem badserver.pem
```

同样的步骤（含**生产用**证书的生成方式）见 `docs/tls.md`。

> **重新生成后**：请在每个 `.key` 文件**首行**补回警示注释
> `# TEST-ONLY self-signed key for unit tests. NOT A SECRET. DO NOT USE IN PRODUCTION.`
> （OpenSSL 3.x 的 `pkey`/`load_cert_chain` 均接受 PEM 中的 `#` 注释行，不影响解析）。

## CI / secret scanner 注意

本目录的 `.key` 是**公开的测试私钥**，非机密。若后续 CI 引入 secret scanner
（如 gitleaks / trufflehog / GitHub secret scanning），**必须在本目录的 scanner
配置中豁免**（例如 gitleaks 的 `allowlist.paths` 加入 `tests/certs/`），否则会被
误报为泄露。注意：豁免范围应**严格限定在本目录**，不要放宽到 `tests/**` 或全仓库。

