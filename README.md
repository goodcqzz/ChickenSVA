# ChickenSVA
Chicken SV Knowlegde Agent/Atlas/Analysis (ChickenSVA)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0-3178C6?logo=typescript)](https://www.typescriptlang.org/)
[![Vite](https://img.shields.io/badge/Vite-5.0-646CFF?logo=vite)](https://vitejs.dev/)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.0-000000?logo=flask)](https://flask.palletsprojects.com/)
[![Docker](https://img.shields.io/badge/Docker-Supported-2496ED?logo=docker)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> 基于前端页面 + Python Flask 的鸡基因组结构变异(SV)数据库分析平台

![Platform Preview](https://via.placeholder.com/800x400/4F46E5/FFFFFF?text=Chicken+SV+Platform)

---

## ✨ 核心功能

### 🎯 基因型填充工作台
- **参考面板管理**: 自动加载已索引的参考面板（2063样本GRCg7b等）
- **VCF文件上传**: 支持 `.vcf` / `.vcf.gz` / `.bcf` 格式，最大 500MB
- **参数配置**: 线程数、窗口大小、重叠区域等高级参数
- **任务执行**: 基于 **Beagle** 算法的高精度基因型填充
- **实时监控**: 任务状态轮询、进度显示、执行日志
- **结果下载**: 一键下载填充结果文件

### 🔍 SV 查询探索器
- **基因查询**: 按基因名称查询相关 SV（BRCA1、TP53等）
- **区域查询**: 按染色体位置范围查询
- **ID查询**: 精确查询特定 SV ID
- **统计概览**: SV类型分布、染色体分布、样本统计可视化
- **结果导出**: CSV 格式导出查询结果

### 📊 任务管理中心
- **任务列表**: 查看所有历史任务
- **状态筛选**: 排队中 / 运行中 / 已完成 / 失败
- **操作功能**: 重试失败任务、取消运行中任务、下载结果
- **详情查看**: 任务执行详情和实时日志

---

## 🚀 快速开始

### 方式一：一键启动（推荐）

```bash
# 克隆项目
git clone <repository-url>
cd ChickenSVA

# 一键启动开发环境
./deploy.sh start
```

访问 http://localhost:8080 即可使用！

### 方式二：Docker 生产部署

```bash
# 一键部署生产环境
./deploy.sh prod
```

访问 http://localhost 即可使用！

---

## 📋 环境要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | 3.11+ | 后端运行 |
| Node.js | 18+ | 前端开发 |
| npm | 9+ | 包管理 |
| Docker | 20+ | 生产部署（可选）|
| BCFtools | 最新 | VCF处理（可选）|

---
