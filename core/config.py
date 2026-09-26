"""配置管理 — YAML 配置文件加载/保存."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


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
    auto_clock_sync: bool = False


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
                'auto_clock_sync': self.master.auto_clock_sync,
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
    cfg.master.auto_clock_sync = master.get('auto_clock_sync', cfg.master.auto_clock_sync)

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

    return cfg
