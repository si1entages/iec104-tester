"""配置管理 — YAML 配置文件加载/保存."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from core.protocol.address import DEFAULT_ASDU_ADDRESS, AsduAddressConfig


@dataclass
class TimerConfig:
    t0: float = 30.0
    t1: float = 15.0
    t2: float = 10.0
    t3: float = 20.0


@dataclass
class FlowControlConfig:
    k: int = 12
    w: int = 8


@dataclass
class ConnectionConfig:
    host: str = "127.0.0.1"
    port: int = 2404
    common_addr: int = 1
    reconnect: bool = True
    reconnect_interval: float = 5.0
    max_connections: int = 16


@dataclass
class MasterConfig:
    auto_start: bool = True
    auto_gi: bool = True
    # WP11a：建链后（STARTDT CON）自动时钟同步。历史上该字段是「死配置」
    # （引擎无自动触发能力），本版在 master_session 的 STARTDT_CON 分支真实接线。
    # 默认 False = 行为与 v1.10.0 一致（仅手动 /api/master/clock）。
    auto_clock_sync: bool = False


@dataclass
class ComplianceConfig:
    """合规监视与解码的阈值（WP11a）：把硬编码提升为显式配置."""

    #: CP56 时标与观察时刻的最大允许偏差（秒），超出记 time-skew 违规
    max_time_skew_s: float = 300.0
    #: ASDU 信息体时标格式：auto=按 TypeID 判定 / cp24 / cp56
    time_tag_format: str = "auto"


@dataclass
class SlaveConfig:
    spontaneous_enabled: bool = True
    simulation_enabled: bool = False
    yx_interval: float = 5.0
    yc_interval: float = 2.0
    yx_change_rate: float = 0.1
    yc_change_range: float = 0.05


@dataclass
class DisplayConfig:
    theme: str = "dark"
    language: str = "zh"
    max_log_lines: int = 10000
    hex_view_bytes_per_line: int = 16
    table_page_size: int = 1000
    refresh_interval_ms: int = 500


@dataclass
class PointTableConfig:
    file: str = ""
    auto_generate: bool = False
    yx_count: int = 0
    yc_count: int = 0
    yk_count: int = 0
    ym_count: int = 0


@dataclass
class FileTransferConfig:
    """文件传输语义档位（WP3a）：把多实现歧义做成显式配置.

    Attributes:
        profile: ``ed1``（历史默认 / 项目约定）、``ed2``（lib60870.NET +
            otfabric 共识：目录 COT=REQ(5)、SCQ=0）、``project``（同 ed1，明确命名）。
        section_size: 从站分包最大节字节数；0=单节（历史行为）。
        nof_enum: 是否按 Ed.2 枚举校验 NOF；None=跟随档位。
    """
    profile: str = "ed1"
    section_size: int = 0
    nof_enum: bool | None = None

    def resolve(self):
        from core.protocol.file_semantics import resolve

        return resolve(self.profile, section_size=self.section_size,
                       nof_enum=self.nof_enum)


@dataclass
class HistoryConfig:
    """历史库配置（T17：默认开启）.

    Attributes:
        enabled: 启动时是否自动建库；``--no-history`` 可临时关闭。
        dir: 历史库所在目录；空字符串表示项目根目录下的 ``data/``。
        retention_days: 保留天数，按时间清理早于该天数的记录；``<=0`` 不按时间清理。
        max_size_mb: 库文件容量上限（MB）；超出后按最旧优先淘汰；``<=0`` 不限制。
        flush_interval: 批量落盘间隔（秒）；``<=0`` 表示仅手动/退出时刷盘。
    """
    enabled: bool = True
    dir: str = ""
    retention_days: int = 7
    max_size_mb: int = 512
    flush_interval: float = 5.0


@dataclass
class TlsConfig:
    """TLS 传输层加密配置（T20 / IEC 62351 的传输层部分）.

    ⚠ 只覆盖 TLS 传输层加密；IEC 62351 的应用层认证等**未实现**，
    详见 ``docs/tls.md`` §覆盖边界。

    Attributes:
        enabled: 是否启用 TLS。
        certfile: 本端证书（PEM）。子站必填；主站在双向认证时填。
        keyfile: 本端私钥（PEM）；为空时假定与证书同文件。
        cafile: 受信 CA（PEM）。主站校验服务端、子站校验客户端时使用；
            主站为空时退回系统信任库。
        verify: 主站是否校验服务端证书（``False`` = 自签联调用，生产禁用）。
        verify_client: 子站是否要求并校验客户端证书（双向认证 / mTLS）。
        server_hostname: 主站 TLS 主机名校验用域名。按 IP 连接而证书只签了
            域名时必填；空 = 用连接地址。
    """
    enabled: bool = False
    certfile: str = ""
    keyfile: str = ""
    cafile: str = ""
    verify: bool = True
    verify_client: bool = False
    server_hostname: str = ""


@dataclass
class RedundancyConfig:
    """主站冗余双通道配置（T21）.

    模型与局限详见 ``docs/redundancy.md``：主/备两条独立 TCP 连接指向两个
    冗余前置机，同一时刻仅一条活动收发；主用故障（TCP 断开，含 TESTFR
    超时引发的断链）→ 切换到已预连接的备用通道并重走 STARTDT+总召唤。

    Attributes:
        enabled: 是否启用冗余双通道（默认关闭，行为与单通道完全一致）。
        standby_host: 备用前置机地址。
        standby_port: 备用前置机端口。
        switch_timeout: 切换后等待新链路进入 Running（STARTDT CON）的超时秒数，
            超时则记 ERROR 并依赖备用通道自身的重连循环继续尝试。
        dedup_window: 切换窗口 I 帧 ASDU 去重时间窗（秒）；窗口内 ASDU 字节
            完全相同的重复帧只处理一次。
    """
    enabled: bool = False
    standby_host: str = "127.0.0.1"
    standby_port: int = 2404
    switch_timeout: float = 2.0
    dedup_window: float = 5.0


@dataclass
class AppConfig:
    """应用总配置."""
    mode: str = "master"            # "master" / "slave"
    connection: ConnectionConfig = field(default_factory=ConnectionConfig)
    timers: TimerConfig = field(default_factory=TimerConfig)
    flow_control: FlowControlConfig = field(default_factory=FlowControlConfig)
    master: MasterConfig = field(default_factory=MasterConfig)
    slave: SlaveConfig = field(default_factory=SlaveConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    point_table: PointTableConfig = field(default_factory=PointTableConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    tls: TlsConfig = field(default_factory=TlsConfig)
    # 主站冗余双通道（T21）；仅主站生效，子站/多站 StationConfig 不适用
    redundancy: RedundancyConfig = field(default_factory=RedundancyConfig)
    # ASDU 地址字段字节数（WP1）：对接 1 字节 CA / 2 字节 IOA 等非标装置。
    # 默认 2/3/2 与历史硬编码一致；启动时经 set_default() 注入协议层。
    asdu_address: AsduAddressConfig = field(default_factory=lambda: DEFAULT_ASDU_ADDRESS)
    # 自定义（非标准厂商私有）TypeID 结构定义（T22）：元素形如
    # ``{type_id: 128, name: VendorAlarm, fields: [{name: v, type: u8}]}``。
    custom_types: list = field(default_factory=list)
    # 文件传输语义档位（WP3a）；默认 ed1 与历史行为逐字节一致。
    file_transfer: FileTransferConfig = field(default_factory=FileTransferConfig)
    # 合规监视/时标阈值（WP11a）
    compliance: ComplianceConfig = field(default_factory=ComplianceConfig)

    def save(self, path: str | Path) -> None:
        """保存配置到 YAML."""
        data = {
            'mode': self.mode,
            'connection': {
                'host': self.connection.host,
                'port': self.connection.port,
                'common_addr': self.connection.common_addr,
                'reconnect': self.connection.reconnect,
                'reconnect_interval': self.connection.reconnect_interval,
                'max_connections': self.connection.max_connections,
            },
            'timers': {
                't0': self.timers.t0,
                't1': self.timers.t1,
                't2': self.timers.t2,
                't3': self.timers.t3,
            },
            'flow_control': {
                'k': self.flow_control.k,
                'w': self.flow_control.w,
            },
            'master': {
                'auto_start': self.master.auto_start,
                'auto_gi': self.master.auto_gi,
            },
            'slave': {
                'spontaneous_enabled': self.slave.spontaneous_enabled,
                'simulation_enabled': self.slave.simulation_enabled,
                'yx_interval': self.slave.yx_interval,
                'yc_interval': self.slave.yc_interval,
                'yx_change_rate': self.slave.yx_change_rate,
                'yc_change_range': self.slave.yc_change_range,
            },
            'display': {
                'theme': self.display.theme,
                'language': self.display.language,
                'max_log_lines': self.display.max_log_lines,
                'hex_view_bytes_per_line': self.display.hex_view_bytes_per_line,
                'table_page_size': self.display.table_page_size,
                'refresh_interval_ms': self.display.refresh_interval_ms,
            },
            'point_table': {
                'file': self.point_table.file,
                'auto_generate': self.point_table.auto_generate,
                'yx_count': self.point_table.yx_count,
                'yc_count': self.point_table.yc_count,
                'yk_count': self.point_table.yk_count,
                'ym_count': self.point_table.ym_count,
            },
            'history': {
                'enabled': self.history.enabled,
                'dir': self.history.dir,
                'retention_days': self.history.retention_days,
                'max_size_mb': self.history.max_size_mb,
                'flush_interval': self.history.flush_interval,
            },
            'tls': {
                'enabled': self.tls.enabled,
                'certfile': self.tls.certfile,
                'keyfile': self.tls.keyfile,
                'cafile': self.tls.cafile,
                'verify': self.tls.verify,
                'verify_client': self.tls.verify_client,
                'server_hostname': self.tls.server_hostname,
            },
            'redundancy': {
                'enabled': self.redundancy.enabled,
                'standby_host': self.redundancy.standby_host,
                'standby_port': self.redundancy.standby_port,
                'switch_timeout': self.redundancy.switch_timeout,
                'dedup_window': self.redundancy.dedup_window,
            },
            'asdu_address': {
                'ca_length': self.asdu_address.ca_length,
                'ioa_length': self.asdu_address.ioa_length,
                'cot_length': self.asdu_address.cot_length,
            },
            'custom_types': list(self.custom_types),
            'file_transfer': {
                'profile': self.file_transfer.profile,
                'section_size': self.file_transfer.section_size,
                'nof_enum': self.file_transfer.nof_enum,
            },
            'compliance': {
                'max_time_skew_s': self.compliance.max_time_skew_s,
                'time_tag_format': self.compliance.time_tag_format,
            },
            'master_autoclock': self.master.auto_clock_sync,
        }
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


def load_config(path: str | Path) -> AppConfig:
    """从 YAML 加载配置."""
    cfg = AppConfig()

    if not Path(path).exists():
        return cfg

    with open(path, encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}

    cfg.mode = data.get('mode', cfg.mode)

    conn = data.get('connection', {})
    cfg.connection.host = conn.get('host', cfg.connection.host)
    cfg.connection.port = conn.get('port', cfg.connection.port)
    cfg.connection.common_addr = conn.get('common_addr', cfg.connection.common_addr)
    cfg.connection.reconnect = conn.get('reconnect', cfg.connection.reconnect)
    cfg.connection.reconnect_interval = conn.get('reconnect_interval', cfg.connection.reconnect_interval)
    cfg.connection.max_connections = conn.get('max_connections', cfg.connection.max_connections)

    timers = data.get('timers', {})
    cfg.timers.t0 = timers.get('t0', cfg.timers.t0)
    cfg.timers.t1 = timers.get('t1', cfg.timers.t1)
    cfg.timers.t2 = timers.get('t2', cfg.timers.t2)
    cfg.timers.t3 = timers.get('t3', cfg.timers.t3)

    fc = data.get('flow_control', {})
    cfg.flow_control.k = fc.get('k', cfg.flow_control.k)
    cfg.flow_control.w = fc.get('w', cfg.flow_control.w)

    master = data.get('master', {})
    cfg.master.auto_start = master.get('auto_start', cfg.master.auto_start)
    cfg.master.auto_gi = master.get('auto_gi', cfg.master.auto_gi)
    # master.auto_clock_sync 已移除（死字段）：旧配置文件里的该键被忽略

    slave = data.get('slave', {})
    cfg.slave.spontaneous_enabled = slave.get('spontaneous_enabled', cfg.slave.spontaneous_enabled)
    cfg.slave.simulation_enabled = slave.get('simulation_enabled', cfg.slave.simulation_enabled)
    cfg.slave.yx_interval = slave.get('yx_interval', cfg.slave.yx_interval)
    cfg.slave.yc_interval = slave.get('yc_interval', cfg.slave.yc_interval)
    cfg.slave.yx_change_rate = slave.get('yx_change_rate', cfg.slave.yx_change_rate)
    cfg.slave.yc_change_range = slave.get('yc_change_range', cfg.slave.yc_change_range)

    disp = data.get('display', {})
    cfg.display.theme = disp.get('theme', cfg.display.theme)
    cfg.display.language = disp.get('language', cfg.display.language)
    cfg.display.max_log_lines = disp.get('max_log_lines', cfg.display.max_log_lines)
    cfg.display.hex_view_bytes_per_line = disp.get('hex_view_bytes_per_line', cfg.display.hex_view_bytes_per_line)
    cfg.display.table_page_size = disp.get('table_page_size', cfg.display.table_page_size)
    cfg.display.refresh_interval_ms = disp.get('refresh_interval_ms', cfg.display.refresh_interval_ms)

    pt = data.get('point_table', {})
    cfg.point_table.file = pt.get('file', cfg.point_table.file)
    cfg.point_table.auto_generate = pt.get('auto_generate', cfg.point_table.auto_generate)
    cfg.point_table.yx_count = pt.get('yx_count', cfg.point_table.yx_count)
    cfg.point_table.yc_count = pt.get('yc_count', cfg.point_table.yc_count)
    cfg.point_table.yk_count = pt.get('yk_count', cfg.point_table.yk_count)
    cfg.point_table.ym_count = pt.get('ym_count', cfg.point_table.ym_count)

    hist = data.get('history', {}) or {}
    cfg.history.enabled = hist.get('enabled', cfg.history.enabled)
    cfg.history.dir = hist.get('dir', cfg.history.dir)
    cfg.history.retention_days = hist.get('retention_days', cfg.history.retention_days)
    cfg.history.max_size_mb = hist.get('max_size_mb', cfg.history.max_size_mb)
    cfg.history.flush_interval = hist.get('flush_interval', cfg.history.flush_interval)

    tls = data.get('tls', {}) or {}
    cfg.tls.enabled = tls.get('enabled', cfg.tls.enabled)
    cfg.tls.certfile = tls.get('certfile', cfg.tls.certfile)
    cfg.tls.keyfile = tls.get('keyfile', cfg.tls.keyfile)
    cfg.tls.cafile = tls.get('cafile', cfg.tls.cafile)
    cfg.tls.verify = tls.get('verify', cfg.tls.verify)
    cfg.tls.verify_client = tls.get('verify_client', cfg.tls.verify_client)
    cfg.tls.server_hostname = tls.get('server_hostname', cfg.tls.server_hostname)

    red = data.get('redundancy', {}) or {}
    cfg.redundancy.enabled = red.get('enabled', cfg.redundancy.enabled)
    cfg.redundancy.standby_host = red.get('standby_host', cfg.redundancy.standby_host)
    cfg.redundancy.standby_port = red.get('standby_port', cfg.redundancy.standby_port)
    cfg.redundancy.switch_timeout = red.get('switch_timeout', cfg.redundancy.switch_timeout)
    cfg.redundancy.dedup_window = red.get('dedup_window', cfg.redundancy.dedup_window)

    # ASDU 地址字段长度（WP1）。非法值不静默吞掉：AsduAddressConfig 构造时
    # 抛 ValueError，让错误配置在启动阶段就暴露，而不是在帧解析时错位。
    aa = data.get('asdu_address', {}) or {}
    cfg.asdu_address = AsduAddressConfig(
        ca_length=aa.get('ca_length', DEFAULT_ASDU_ADDRESS.ca_length),
        ioa_length=aa.get('ioa_length', DEFAULT_ASDU_ADDRESS.ioa_length),
        cot_length=aa.get('cot_length', DEFAULT_ASDU_ADDRESS.cot_length),
    )

    ft = data.get('file_transfer', {}) or {}
    cfg.file_transfer.profile = str(ft.get('profile', cfg.file_transfer.profile))
    cfg.file_transfer.section_size = int(ft.get('section_size', cfg.file_transfer.section_size))
    nof = ft.get('nof_enum', cfg.file_transfer.nof_enum)
    cfg.file_transfer.nof_enum = None if nof is None else bool(nof)
    # 非法档位名在加载期就报错，不静默退回默认（安全配置错误不能藏）
    cfg.file_transfer.resolve()

    comp = data.get('compliance', {}) or {}
    cfg.compliance.max_time_skew_s = float(
        comp.get('max_time_skew_s', cfg.compliance.max_time_skew_s))
    cfg.compliance.time_tag_format = str(
        comp.get('time_tag_format', cfg.compliance.time_tag_format))
    if cfg.compliance.time_tag_format not in ("auto", "cp24", "cp56"):
        raise ValueError(
            f"compliance.time_tag_format 非法：{cfg.compliance.time_tag_format}")
    # 兼容两种写法：master 节的 auto_clock_sync，或顶层 master_autoclock（save 输出）
    master_cfg = data.get('master', {}) or {}
    if 'auto_clock_sync' in master_cfg:
        cfg.master.auto_clock_sync = bool(master_cfg['auto_clock_sync'])
    elif 'master_autoclock' in data:
        cfg.master.auto_clock_sync = bool(data['master_autoclock'])

    custom_types = data.get('custom_types', None)
    if isinstance(custom_types, list):
        cfg.custom_types = custom_types
    elif isinstance(custom_types, dict):
        # 映射式：键即 type_id
        cfg.custom_types = [
            {**dict(v or {}), 'type_id': int(k)}
            for k, v in custom_types.items()
        ]

    return cfg


# 方案（WP5）覆盖到 ``AppConfig`` 的节：方案文件本身就是合法 AppConfig YAML，
# 但只允许覆盖「工程参数」——显示偏好（display）与 TLS/历史库留归 ``--config``，
# 避免一份方案把证书路径或历史保留期悄悄改掉。
_PROFILE_SECTIONS = ("connection", "timers", "flow_control", "asdu_address")


def apply_profile(cfg: AppConfig, profile_path: str | Path) -> list[str]:
    """把方案文件的工程参数叠加到 ``cfg`` 上，返回被覆盖的节名列表.

    用于 ``--profile <名称>``：在 ``--config`` 之后、引擎构造之前应用，
    因此点表文件、ASDU 地址长度（WP1）、t1~t3 等都会走既有加载路径生效。

    只覆盖 :data:`_PROFILE_SECTIONS` 与 ``point_table.file``；文件不存在时
    抛 ``FileNotFoundError``（显式指定了方案却读不到，不能静默继续）。
    """
    path = Path(profile_path)
    if not path.is_file():
        raise FileNotFoundError(f"方案文件不存在：{path}")
    prof = load_config(path)
    applied: list[str] = []
    for section in _PROFILE_SECTIONS:
        setattr(cfg, section, getattr(prof, section))
        applied.append(section)
    if prof.point_table.file:
        cfg.point_table.file = prof.point_table.file
        applied.append("point_table.file")
    return applied
