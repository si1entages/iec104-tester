# Web API 契约

错误与成功：HTTP **200** + JSON `{"ok": true|false, ...}`；失败含 `error` 字符串。

| 方法 | 路径 | Body | 说明 |
|------|------|------|------|
| GET | `/api/status` | — | role/running/vs/vr/points/dropped/… |
| GET | `/api/points` | — | `{points: [{ioa,type,name,group,enabled,value,quality?}]}` |
| GET | `/api/recent` | — | 最近 frames/events |
| POST | `/api/master/start` | host,port,addr,reconnect? | |
| POST | `/api/master/stop` | — | |
| POST | `/api/master/gi` | qoi? (int 1–16=组召唤 \| 20=站召唤) | 默认 20 站召唤；组召唤帧上 QOI=20+组号(21–36) |
| POST | `/api/master/clock` / `ci` / `reset` / `test` | — | |
| POST | `/api/master/read` | ioa:int | |
| POST | `/api/master/yk` | ioa,state,select?,double?,with_time? | with_time=true → C_SC_TA_1 / C_DC_TA_1 |
| POST | `/api/master/setpoint` | ioa,value,kind?,with_time? | kind: short_float\|normalized\|scaled |
| POST | `/api/master/step` | ioa,state(1=降,2=升),select? | 升降命令 C_RC_NA_1 |
| POST | `/api/master/bitstring` | ioa,value:int(32bit) | 比特串命令 C_BO_NA_1 |
| POST | `/api/master/delay` | delay_ms (0-60000) | 延时获得 C_CD_NA_1 |
| POST | `/api/master/param` | kind,ioa,value,qualifier? | kind: float\|normalized\|scaled\|activation |
| POST | `/api/master/file` | action,ioa,file_name:int | action: directory\|select\|request |
| POST | `/api/slave/start` | host,port,addr | |
| POST | `/api/slave/stop` | — | |
| POST | `/api/slave/yx` | ioa,value:bool | 自发上送（双点声明自动转 M_DP_TB_1） |
| POST | `/api/slave/yc` | ioa,value:float | 自发上送 |
| POST | `/api/slave/ym` | ioa,value:int | 累计量置数并上送 (M_IT_TB_1) |
| POST | `/api/slave/ep` | ioa,event_value,with_time? | 继保事件模拟 (M_EP_TD_1/TA_1) |
| POST | `/api/slave/ps` | ioa,states:[0/1×1-8] | 成组单点模拟 (M_PS_NA_1) |
| POST | `/api/slave/response` | ResponseBehavior 字典 | 未启动可暂存 |
| POST | `/api/slave/sim` | enabled, yx_interval?… | |
| POST | `/api/points/batch` | type,ioas,action,group? | action: enable\|disable\|group |
| GET | `/api/points/yaml` | — | text/yaml |
| POST | `/api/points/yaml` | raw yaml text | |
| GET | `/api/export/points.csv` | — | text/csv |
| GET | `/api/export/session.json` | — | frames+events+status |
| GET | `/api/logs` | — | 结构化日志查询：`?level_min=&category=&source=&q=&limit=` |
| GET | `/api/logs/export` | — | 下载 JSONL 日志 |
| WS | `/ws` | — | snapshot（含 logs）/ frame / event / log；客户端可发 `"refresh"` |

前端 API 封装：`static/js/app.js` 内的 `api()`（经 `window.IEC104` 暴露）。
