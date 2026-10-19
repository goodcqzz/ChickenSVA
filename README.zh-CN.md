> 中文版说明：本文件为原内部文档存档。面向开源用户的完整文档请见 [README.md](README.md)（英文）。

# ProjectAi3 / ChickenSV — 鸡基因组结构变异智能体

基于 Agent + MCP 的鸡基因组 SV 查询、品种表型、关联分析、基因型填充与文献知识库平台。

高校现网：学校反代 → 本机 **80**（系统 Nginx）→ 静态前端 + `/api` `/ws` → `127.0.0.1:9801` → MCP `127.0.0.1:9802`。  
同机 Dify 仅绑本机 `127.0.0.1:8080/8443`，不对外。

---

## 端口规划

| 端口 | 服务 | 监听 | 说明 |
|------|------|------|------|
| **80** | 系统 Nginx | `0.0.0.0` | 现网对外入口；学校反代指这里。`start.sh` / `stop.sh` **永不停止** |
| **9800** | 备用入口 | `0.0.0.0` | 开发 Vite / 无 Nginx 时的 `serve-proxy` |
| **9801** | FastAPI 后端 | `127.0.0.1` | Agent、WebSocket、限速；不对外 |
| **9802** | MCP | `127.0.0.1` | 生信工具与 Beagle 填充；不对外 |
| 8080/8443 | Dify | `127.0.0.1` | 文献知识库，仅本机 |

端口默认值见 [`deploy/lib/ports.sh`](deploy/lib/ports.sh)。

---

## 智能体能力（能做什么 / 不能做什么）

**能做（须走工具拿数据，禁止编造）：**

- 鸡基因组 SV 查询（基因 / 区域 / SV ID / 品种频率）
- 品种表型库（特征、产地、经纬度等已收录字段）
- 基因注释、品种层表型-基因型关联、全基因组候选扫描
- SV 基因型填充工作区（VCF/PLINK → Beagle）
- 用户明确要求时的文献知识库背景补充

**不能做：** 个体/家系 GWAS、亲子鉴定、非鸡物种、行情/养殖经营建议、未收录品种的精确数值。  
工具返回空结果时，代码会硬拦截为「未找到记录」，不让模型续写特征。

默认模型：`deepseek-v4-pro`（`max_tokens=8192`）。提示词：`agent_framework/frontend/src/prompts/Agent_prompt.md`。

---

## 一键启动

```bash
bash start.sh --status     # 只看状态，不重启
bash start.sh              # 智能默认：Nginx 已对外则只重启 MCP+后端
bash start.sh --backend    # 学校反代场景：只重启 MCP+后端，不碰 Nginx
bash start.sh --prod       # 生产：MCP+后端；保留系统 Nginx
bash start.sh --dev        # 开发：MCP+后端(热重载)+Vite（仅本机 127.0.0.1）
bash stop.sh               # 停 MCP/后端/Vite/proxy，不杀 Nginx
```

现网更新（不断学校反代）：

```bash
bash start.sh --backend
```

进程用 `nohup` 挂到 PID 1，断开 SSH 不会退出。systemd unit（`chickensv-mcp` / `chickensv-backend`）已启用，**机器重启后由 systemd 拉起**。

---

## 快速开始（开发机）

```bash
cp config/chickensv.env.example config/chickensv.env
chmod 600 config/chickensv.env
vim config/chickensv.env          # 填 DEEPSEEK_API_KEY、DIFY_API_KEY
bash setup-env.sh
bash start.sh --dev
# 浏览器: http://127.0.0.1:9800
```

---

## 生产部署（安置机）

```bash
vim config/chickensv.env
bash setup-production.sh          # 环境 + systemd + 前端构建 + Nginx
# 学校要求对外 80 时:
CHICKENSV_PUBLIC_PORT=80 bash deploy/install-nginx.sh
```

常用选项：

```bash
bash setup-production.sh --skip-nginx   # 无 sudo 时用 serve-proxy 占 9800
bash setup-production.sh --skip-build   # 已有 dist/ 时跳过 npm build
```

---

## 脚本一览

| 脚本 | 用途 |
|------|------|
| [`start.sh`](start.sh) | 一键启动 / 安全重启；`--status` `--backend` `--prod` `--dev` |
| [`stop.sh`](stop.sh) | 停止 MCP/后端/Vite/proxy（不杀系统 Nginx） |
| [`setup-env.sh`](setup-env.sh) | 创建/更新 Conda 环境 `gaoai` |
| [`setup-dev.sh`](setup-dev.sh) | 开发机：环境 + `npm ci` |
| [`setup-production.sh`](setup-production.sh) | 安置机一键生产部署 |
| [`publish.sh`](publish.sh) | rsync 发布到远程 |
| [`verify.sh`](verify.sh) | 检查 beagle、数据目录、配置文件 |
| [`deploy/install-nginx.sh`](deploy/install-nginx.sh) | 系统 Nginx 反代 |
| [`deploy/bin/diagnose-runtime.sh`](deploy/bin/diagnose-runtime.sh) | systemd 失败时诊断 |

---

## 配置

唯一运行时配置：**[`config/chickensv.env`](config/chickensv.env)**（勿提交 Git）

```bash
PORT=9801
MCP_SERVER_URL=http://127.0.0.1:9802
DEEPSEEK_MODEL=deepseek-v4-pro
PLATFORM_DEFAULT_MAX_TOKENS=8192
DIFY_API_BASE=http://127.0.0.1:8080/v1   # 以本机实际 Dify 为准
RATE_LIMIT_ENABLED=true
PERSIST_USER_API_KEYS=false
TRUSTED_PROXY_HOPS=1
```

文献检索 REST：`GET/POST /api/v1/rag/retrieve`。

---

## 健康检查

```bash
curl -s http://127.0.0.1:9802/health
curl -s http://127.0.0.1:9801/api/v1/health
curl -s http://127.0.0.1/api/v1/health          # 现网 Nginx :80
bash start.sh --status
```

---

## 数据目录（勿删）

- `data/` — SV CSV、表型
- `refpanel/` — Beagle JAR、参考 VCF
- `annotation/` — GFF3
- `agent_framework/data/` — 用户工作区
- `agent_framework/backend/data/sessions.db` — 会话历史（不含 API Key）
