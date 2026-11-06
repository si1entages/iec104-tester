# 互操作报文语料库

回放回归的输入目录。`tests/test_frame_corpus_replay.py` 会自动发现：

- 本目录下的 `*.i104` / `*.json`（合成基线）
- `real/` 子目录下的 `*.i104` / `*.json`（真机抓包，可选）

## 来源与边界

- **合成基线**（本目录）：由 `generate_corpus.py` 用协议构造器生成，覆盖
  总召、SOE、CP24/CP56 变体、SBO、参数/文件传输、畸形帧等路径。
  它锁定的是**解码行为**，不代表真机时序/私有语义。
- **真机语料**（`real/`）：从现场录制的报文。请先脱敏再入库；`.i104`
  只含裸 APDU，不含 IP/MAC，但仍可能通过 IOA/公共地址/业务值暴露现场信息。

## 重新生成合成基线

```bash
python tests/fixtures/frames/generate_corpus.py
```

生成后提交 `*.i104` 与 `manifest.json`。`manifest.json` 是每帧解码后的
golden 快照（含 `direction/frame_type/tx_seq/rx_seq/type_id/cot/objects`），
以及回放后应看到的点值（`master_checks`）。**不要手改**，改生成器后重跑。

## 添加真机语料

1. 用主站/子站或 `capture_tool.py` 录制为 `.i104` 或 `.json`；
2. 按需脱敏（IOA、公共地址、业务值、时间戳）；
3. 放入 `real/`，文件名建议 `<装置/场景>-<日期>.i104`；
4. 在 `tests/test_frame_corpus_replay.py` 的 `REAL_EXPECTATIONS` 中登记
   需要断言的帧/点值（未登记的真机文件仍会跑“逐帧可解码”冒烟）。

## 与 pcap 的关系

`.i104` 是主站视角的收发帧序列，可用以下命令转成 Wireshark 可打开的 pcap：

```bash
python capture_tool.py convert tests/fixtures/frames/gi_basic.i104 -o /tmp/gi_basic.pcap
```

pcap 中的以太网/IP/TCP 头是合成的（见 `core/capture/format.py` 的说明），
仅用于 Wireshark 识别 IEC 104 解析器，不代表真实网络拓扑。
