# pcap / pcapng 导出说明（T23）

## 用途

把 `.i104` / `.json` 录制文件导出为 Wireshark 可直接打开的 `pcap` / `pcapng`，
便于现场排障时用熟悉的抓包工具查看 IEC 60870-5-104 报文。

```bash
# 默认：合成 TCP 头（Wireshark 原生识别为 IEC 104）
python capture_tool.py convert session.i104 -o session.pcap
python capture_tool.py convert session.i104 -o session.pcapng

# 裸 APDU（LINKTYPE_USER0，Wireshark 需手工 Decode As / 外部工具解析）
python capture_tool.py convert session.i104 -o session_raw.pcap --raw
```

编程接口：`core.capture.format.CaptureFile.save_pcap / save_pcapng / load_pcap / load_pcapng`；
`CaptureFile.save(path, frames, raw=False)` 按扩展名分派（`.pcap` / `.pcapng` / `.ntar`）。

---

## ⚠️ 诚实性声明：合成头，非真实网络层信息

录制文件保存的是**裸 APDU 字节流**（IEC 104 应用层报文），**不含**真实的
链路层 / IP / TCP 头。而 Wireshark 的 IEC 60870-5-104 解析器**依赖 TCP 上下文**
（端口 2404）才能识别。因此在默认（非 `--raw`）导出时，本工具会为每条报文
**合成**一个以太网 + IPv4 + TCP 头：

| 项 | 合成值 | 说明 |
|----|--------|------|
| 目的端口（IEC 104） | `2404` | 触发 Wireshark 的 IEC 104 解析器 |
| 源/目的 IP | `192.0.2.1` / `192.0.2.2` | **TEST-NET-1 文档用地址段**，非真实 |
| 源端口 | `40000` | 合成临时端口 |
| MAC / TCP 序号 / 窗口 | 固定合成值 | 与真实抓包无关 |

**结论：导出的 pcap/pcapng 中，只有 TCP 载荷（APDU）是真实录制内容；
网络层/链路层头一律为合成信息，不得据此推断真实拓扑、端口或网络行为。**

该声明同时出现在：模块常量区注释（`core/capture/format.py` 顶部
「诚实性声明」块）、`capture_tool.py` 的 docstring 与 `convert` 子命令帮助、
以及转换到 pcap/pcapng 时的 CLI 输出（打印 ⚠️ 提示）。

### 方向约定

为使 Wireshark 把双向报文归入**同一条 TCP 会话**：

- `TX`（主站→子站）：`192.0.2.1:40000 → 192.0.2.2:2404`
- `RX`（主站←子站）：`192.0.2.2:2404  → 192.0.2.1:40000`

回读时据 TCP 源端口还原方向（源端口 `2404` → RX，否则 TX）。

---

## 在 Wireshark 中查看

**默认导出（合成 TCP 头）**：
1. 打开 `.pcap` / `.pcapng`；
2. 报文应自动被识别为 `IEC 60870-5-104`（显示过滤器可直接用 `iec60870_104`）；
3. 若未自动识别：右键任一报文 → **Decode As…** → 选中 TCP 端口 2404 → 选择
   `IEC 60870-5-104`。

**`--raw` 导出（裸 APDU，LINKTYPE_USER0）**：
- 每帧载荷即完整 APDU 字节，但**无 TCP 头**，Wireshark 无法自动识别为 IEC 104；
- 查看方式：在「Packet Bytes」面板按十六进制人工分析，或导出后用项目自带
  `python capture_tool.py show session_raw.pcap` / `analyze` 解析；
- 也可用外部脚本按 APCI（起始 `0x68` + 长度域）自行切帧。

---

## 校验方式（无需安装 Wireshark）

`tests/test_capture_pcap.py` 自行解析回读并校验：

- **经典 pcap**：全局头魔数/版本/`linktype`；每条记录 `incl_len == orig_len`；
  合成帧长度 = `14(Eth) + 20(IPv4) + 20(TCP) + len(APDU)`；`EtherType=0x0800`、
  IPv4 版本 4 / `proto=TCP`、IPv4 头校验和重算为 0（有效）；TCP 端口与方向映射；
  TCP 载荷等于原始 APDU；时间戳（秒/微秒）与录制绝对时间一致。
- **pcapng**：块遍历校验**首尾长度一致**且块长 **4 字节对齐**；SHB 的 BOM
  `0x1A2B3C4D`；IDB 的 `linktype`；EPB 数等于帧数，`ts_high/ts_low` 合成的
  µs 时间戳与绝对时间一致，载荷等于 APDU。
- **往返**：帧数、字节内容、方向、时间戳一致（µs 精度）；`.i104 → .pcap` 互转保真。
- **CLI**：`capture_tool.py convert` 生成的文件可被回读，且输出含合成头警示。
