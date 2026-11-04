<div align="center">

# 学生信息管理系统

**面向学院的班费账本 + 学籍名册 + 学院任务协同：公开、透明、可追溯。**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/Python-3.13-blue.svg)](server-py/)
[![Vue 3](https://img.shields.io/badge/Vue-3.5-42b883.svg)](web/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688.svg)](server-py/)

</div>

---

## 目录结构

```
classfee-manager/
├─ server-py/              后端（FastAPI，:8080）
│  ├─ app/                 routers（HTTP 层）· services（业务/事务）· models / security / seed
│  ├─ db/schema.sql        15 张表（启动时幂等执行）
│  └─ tests/api_regression.py   契约回归（零依赖，1263 项）
├─ web/                    前端（Vue 3 + Vite + Element Plus，:5173）
│  └─ src/                 api · views · components · stores · router
├─ assets/screenshots/     README 截图（演示数据）
├─ docs/                   部署指南 · 账号与权限 · 设计要点（GitHub 上仅这三份）
├─ log/                    运行日志（backend / frontend / database，不入库）
├─ docker-compose.yml                 一键部署（自带 MariaDB）
├─ docker-compose.use-existing-db.yml 复用服务器已有数据库
└─ .env.example            部署变量模板
```

**规模**：15 张表｜110 个 REST 端点｜前端 17 个页面｜Vue 3 + Element Plus · FastAPI + SQLAlchemy 2.0

---

## 这是什么

一个面向**单个学院**的系统，同时管三件事：

| 模块 | 一句话 |
|------|--------|
| **班费账本** | 按班记收支，批次逐人收班费、生成流水，记错作废红冲，全账可回溯（小票可挂、可查看） |
| **学籍名册** | 班主任逐人维护学生字段，学院侧按「申请 → 授权」看非管辖班数据 |
| **学院任务协同** | 院长发全学院任务，各班班主任逐人接龙回收；班主任可给自己班发班级任务 |

**没有注册页，只有登录页**：账号由部署方声明或运营在页面创建，代码里不写死任何默认口令。

![任务总览 — 院长视角](assets/screenshots/任务总览.jpeg)

![学院任务 — 院长发布/跟进](assets/screenshots/学院任务.jpeg)

> 截图为本地演示实例（合成数据），能看到：学院任务由院长发布、按「已填班数」回收；任务总览一眼看清开放中任务与回收率。

---

## 快速开始

需要 Python 3.13+、Node 22+、一个 MySQL 8 / MariaDB 库。前后端启动时**自动建表、自动补种子数据**：

```bash
mysql -uroot -p -e "CREATE DATABASE classfee DEFAULT CHARSET utf8mb4;"

cd server-py && python -m venv .venv && .venv/bin/pip install -r requirements.txt \
  && .venv/bin/python -m uvicorn app.main:app --port 8080
cd web && npm install && npm run dev
```

登录账号由部署时声明（`CLASSFEE_TEACHER_USERNAME` / `PASSWORD`），或运营登录后在「成员管理」「学院 → 院长账号」里创建。

详细部署（手动 / Docker Compose / 排障 / 日志）见 **[`docs/部署-Linux.md`](docs/部署-Linux.md)**。

---

## 文档

| 文档 | 内容 |
|------|------|
| [`docs/部署-Linux.md`](docs/部署-Linux.md) | Linux 部署（systemd + nginx / Docker Compose）、验证清单、排障、运行日志配置 |
| [`docs/账号权限.md`](docs/账号权限.md) | 功能模块总表 · 角色六档与 `ROLE_LEVEL` · 账号来源与特性 · 跨班数据授权 |
| [`docs/设计要点.md`](docs/设计要点.md) | 记账/余额/金额/小票口径 · 任务回收率算法 · 15 张表 DDL |
| [`log/README.md`](log/README.md) | 运行日志：backend / frontend / database 三类分离、隐私底线 |

---

## License

[MIT](LICENSE) © 2026 Student Info Manager contributors
