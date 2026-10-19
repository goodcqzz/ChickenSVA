# Release notes — ChickenSVA open-source package (2026-10-17)

面向 iMetaOmics 重投准备的开源发布包。**状态：待作者最终审阅后推送 GitHub。**

## 本包内容

在已提交的代码基线（git 7713188）之上，本包新增/修改：

| 项 | 文件 | 状态 |
|---|---|---|
| 英文 README（安装/配置/quickstart） | `README.md`（原中文版存为 `README.zh-CN.md`） | ✅ 已写 |
| MIT 许可证 | `LICENSE` | ⚠️ 证种待作者确认（当前默认 MIT） |
| 引用元数据 | `CITATION.cff` | ✅ DOI 待论文录用后补 |
| 示例数据集 | `examples/data/`（chr5:5-7Mb，100 样本，1.4 MB） | ✅ 真实数据子集 |
| 示例脚本 | `examples/make_example_data.py`、`run_demo.sh/.py` | ✅ **已实测跑通** |
| Docker 三镜像 | `deploy/docker/Dockerfile.{mcp,backend,web}`、`docker-compose.yml` | ⚠️ 已撰写、**未构建验证**（见下） |
| 脱敏 | Dify dataset UUID 默认值清空、env.example 占位符化 | ✅ 已做并复扫 |

## 已验证（2026-10-17，部署服务器上实测）

- `examples/run_demo.sh` 端到端：SV 查询（chr5 68 个 DEL，含基因注释）→ Beagle 填充
  迷你基准（9,486 常见位点，60 参考/40 目标样本，80% mask，等位基因一致性 0.838）。
- 脱敏复扫：无 API 密钥、无内网 IP、无 dataset UUID 残留。

## 已知限制 / 待办

1. **Docker 未构建验证**：制作本包的服务器无外网（docker.io / npm / pypi 均不可达），
   `docker compose build` 需在有网机器上首次验证；如遇问题优先检查：
   `Dockerfile.web` 的 `npm ci`（需 package-lock.json，已包含）、
   `Dockerfile.mcp` 的 apt 源（bcftools/tabible/JRE）。
2. `beagle.jar` 不随包分发（第三方许可）：`run_demo.sh` 会自动从官网下载，
   或手动放置（README/examples 均有说明）。
3. Zenodo 数据存放与 DOI、`scripts/download_ccrp.sh`：待上传全量 CCRP 后补。
4. 教程视频 + README 视频链接：待录制。
5. GitHub 仓库 `goodcqzz/ChickenSVA`：目前为私有/空，推送前需作者确认许可证与作者名单
   （CITATION.cff 目前只写了第一作者 + "and co-authors" 占位）。
6. 手稿的 Data and Code availability 一节需按回复信中的新表述替换。

## 与线上服务的差异（重要）

本包 `config.py` 中三个 Dify dataset 默认值已清空（原为实验室内部 ID）；
线上服务用 `config/chickensv.env` 里的显式配置，不受影响。
若要把本包改动同步回生产仓库，`git diff` 仅涉及 `config.py` 三处默认值与
`config/chickensv.env.example` 占位符，可安全合并。

7. 在线平台 URL 在同行评审期间不公开（仅向期刊审稿人披露），录用后随正式版恢复到 README/CITATION。
