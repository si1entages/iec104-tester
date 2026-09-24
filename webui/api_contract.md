# Web API 契约

错误与成功：HTTP **200** + JSON `{"ok": true|false, ...}`；失败含 `error` 字符串。

| 方法 | 路径 | Body | 说明 |
|------|------|------|------|
| GET | `/api/status` | — | role/running/vs/vr/points/dropped/… |
| GET | `/api/points` | — | `{points: [{ioa,type,name,group,enabled,value,quality?}]}` |
| GET | `/api/recent` | — | 最近 frames/events |
| POST | `/api/master/start` | host,port,addr,reconnect? | |
| POST | `/api/master/stop` | — | |
| POST | `/api/master/gi` | qoi? (int 1–23\|20) | 默认 20 总召 |
| POST | `/api/master/clock` / `ci` / `reset` / `test` | — | |
| POST | `/api/master/read` | ioa:int | |
| POST | `/api/master/yk` | ioa,state,select?,double? | |
| POST | `/api/master/setpoint` | ioa,value | 短浮点 |
| POST | `/api/master/param` | kind,ioa,value,qualifier? | kind: float\|normalized\|scaled\|activation |
| POST | `/api/master/file` | action,ioa,file_name:int | action: directory\|select\|request |
| POST | `/api/slave/start` | host,port,addr | |
| POST | `/api/slave/stop` | — | |
| POST | `/api/slave/yx` | ioa,value:bool | 自发上送 |
| POST | `/api/slave/yc` | ioa,value:float | 自发上送 |
| POST | `/api/slave/response` | ResponseBehavior 字典 | 未启动可暂存 |
| POST | `/api/slave/sim` | enabled, yx_interval?… | |
| POST | `/api/points/batch` | type,ioas,action,group? | action: enable\|disable\|group |
| GET | `/api/points/yaml` | — | text/yaml |
| POST | `/api/points/yaml` | raw yaml text | |
| GET | `/api/export/points.csv` | — | text/csv |
| GET | `/api/export/session.json` | — | frames+events+status |
| WS | `/ws` | — | snapshot / frame / event |

前端常量表：`static/js/api.js`。
