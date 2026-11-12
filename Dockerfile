# IEC104 Tester —— 容器镜像（WP10b）
#
# 多阶段构建：前端在 node 阶段构建，后端只带运行时依赖，镜像内不含 node。
#
# ⚠ 安全边界（勿误解，见 SECURITY.md）：本工具是**协议调试工具**，
#   不是生产 SCADA 网关。容器化只解决「无人值守长期跑」，不改变该定位。
#
# 构建：docker build -t iec104-tester:latest .
# 运行：docker compose up -d   （见 docker-compose.yml）
# 离线：见 docs/deploy.md「离线/内网部署」

# ── 阶段 1：构建前端 ──────────────────────────────────────────────────
FROM node:20-alpine AS frontend
WORKDIR /src/webui/frontend
# 先拷依赖清单，利用层缓存（package.json 不变时不重装）
COPY webui/frontend/package.json webui/frontend/package-lock.json* ./
RUN npm ci || npm install
COPY webui/frontend/ ./
# vite 产物输出到 webui/static/app
RUN npm run build

# ── 阶段 2：运行时 ────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# tini 作为 PID 1：正确处理信号，容器 stop 时能让 aiohttp 干净退出
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    IEC104_DATA_DIR=/data

COPY pyproject.toml requirements.txt ./
# 只装运行时依赖（不含 dev/build/pdf extra；需要 PDF 报告时见 docs/deploy.md）
RUN pip install --no-cache-dir -r requirements.txt

COPY core/ core/
COPY webui/ webui/
COPY apps/ apps/
COPY configs/ configs/
COPY resources/ resources/
COPY app.py run_multi_station.py capture_tool.py sim_tool.py run_tests.py ./
# 用构建阶段的前端产物覆盖源码树里的旧产物
COPY --from=frontend /src/webui/static/app webui/static/app

# 数据目录（历史库/审计库/验收库）挂卷持久化；非 root 运行
RUN useradd --create-home --uid 10001 iec104 \
    && mkdir -p /data && chown -R iec104:iec104 /data /app
USER iec104
VOLUME ["/data"]

# 8765 = both 模式（单进程双角色、一个端口一个工作台）
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/status', timeout=3).status==200 else 1)"

# 监听 0.0.0.0 时**必须**带令牌/多用户配置，否则局域网内任何人可下发遥控。
# 默认用环境变量注入（compose 里设置 IEC104_AUTH_TOKEN 或 --auth-config）。
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "app.py", "--mode", "both", "--no-browser", "--http-host", "0.0.0.0", "--http-port", "8765"]
