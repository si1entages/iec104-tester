# TLS 测试证书（仅供测试，非机密）

这些是本仓库 TLS 测试（`tests/test_tls_transport.py`）使用的**自签测试证书**。
它们**不是密钥材料**，仅供单元测试握手使用；请勿用于任何真实部署。

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
