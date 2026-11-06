# 真机/现场抓包目录（用户提供）

把真机抓包放在本目录，`tests/test_frame_corpus_replay.py` 会自动发现
`*.i104` / `*.json` 并执行逐帧可解码冒烟；如已在测试里登记期望值，
还会执行主站回放与点值断言（`REAL_EXPECTATIONS`）。

## 采集与脱敏

1. 用主站/子站 `capture_tool.py record` 或现场抓包工具录制为 `.i104` / `.json`；
2. 按需脱敏：IOA、公共地址、业务值、时间戳（`.i104` 不含 IP/MAC，但仍可能
   通过业务地址暴露现场信息）；
3. 文件名建议 `<装置或场景>-<YYYYMMDD>.i104`；
4. 提交前确认已获得数据使用授权。

## 说明

- 真机语料是**用户提供的现场资产**，仓库默认不内置（无真机抓包时不要伪造）；
- 合成基线在上一级目录，由 `generate_corpus.py` 生成，用于锁定解码行为；
- 新增真机文件后先跑：

  ```bash
  python -m pytest tests/test_frame_corpus_replay.py -q
  ```
