"""IEC 60870-5-104 Protocol Constants."""

# ── APCI Frame Constants ──────────────────────────────────────────
START_BYTE = 0x68                  # 起始字节
APCI_LENGTH = 4                    # 控制域长度（字节）
MAX_ASDU_LENGTH = 253              # 最大ASDU长度
MAX_APDU_LENGTH = 255              # 最大APDU长度 = APCI(4) + ASDU(253) - 但实际APDU=2+length+ASDU
I_FORMAT_LENGTH = 4                # I帧控制域长度
S_FORMAT_LENGTH = 4                # S帧控制域长度
U_FORMAT_LENGTH = 4                # U帧控制域长度

# ── U-Frame Control Bits ──────────────────────────────────────────
# 第1字节(control field byte 1)
U_STARTDT_ACT  = 0x07   # 0000 0111 - 启动激活
U_STARTDT_CON  = 0x0B   # 0000 1011 - 启动确认
U_STOPDT_ACT   = 0x13   # 0001 0011 - 停止激活
U_STOPDT_CON   = 0x23   # 0010 0011 - 停止确认
U_TESTFR_ACT   = 0x43   # 0100 0011 - 测试激活
U_TESTFR_CON   = 0x83   # 1000 0011 - 测试确认

# U帧掩码
U_TYPE_MASK    = 0xC3   # 取 bit7,6,1,0 (类型位)
U_DIR_MASK     = 0x04   # bit2: 方向位 (保留，总为0)

# ── Timer Defaults (seconds) ──────────────────────────────────────
T0_DEFAULT = 30    # 连接建立超时
T1_DEFAULT = 15    # 发送/测试超时（等待S帧或U帧确认）
T2_DEFAULT = 10    # 无数据确认超时（收到I帧后多久发S帧）
T3_DEFAULT = 20    # 空闲测试超时（无任何报文时发TESTFR）

# ── Flow Control Defaults ─────────────────────────────────────────
K_DEFAULT = 12     # 未确认I帧最大数量（发送方上限）
W_DEFAULT = 8      # 接收方确认阈值（收到w个I帧后发S帧确认）

# ── Common Address Length ─────────────────────────────────────────
CA_LENGTH_1 = 1    # 公共地址1字节
CA_LENGTH_2 = 2    # 公共地址2字节

# ── IOA Length ────────────────────────────────────────────────────
IOA_LENGTH_1 = 1   # 信息对象地址1字节
IOA_LENGTH_2 = 2   # 信息对象地址2字节
IOA_LENGTH_3 = 3   # 信息对象地址3字节（最常用）

# ── ASDU Structure Constants ──────────────────────────────────────
ASDU_TYPE_LENGTH = 1       # 类型标识
ASDU_VSQ_LENGTH = 1        # 可变结构限定词
ASDU_COT_LENGTH = 2        # 传送原因 (1字节原因 + 1字节发起地址)
ASDU_CA_LENGTH_DEFAULT = 2 # 公共地址默认2字节

# ── Sequence Flags ────────────────────────────────────────────────
VSQ_SQ_BIT = 0x80          # bit7: 顺序标志 (1=连续, 0=单独)
VSQ_NUM_MASK = 0x7F        # bit6-0: 信息对象数量
