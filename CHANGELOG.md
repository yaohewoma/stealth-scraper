# Changelog

All notable changes to the Stealth Scraper Skill will be documented in this file.

## [1.2.0] — 2026-06-11

### Added
- `LICENSE` — MIT 开源协议
- `CONTRIBUTING.md` — 贡献指南（开发环境、代码规范、PR 流程、模块模板）
- `pyproject.toml` — 项目元数据、black/isort/mypy/pytest 工具配置
- `.pre-commit-config.yaml` — pre-commit 钩子（black, isort, flake8, 通用检查）
- `tests/` 测试套件：
  - `test_core.py` — 12 个单元测试覆盖指纹轮换、行为模拟、断点续传、数据提取、指数退避、URL 处理
  - `test_integration.py` — 4 个集成测试覆盖完整流水线、429 处理、超时处理、崩溃恢复、数据分块
  - `conftest.py` — pytest 配置与自定义标记
- `.github/workflows/ci.yml` — GitHub Actions CI（lint + test，Python 3.8/3.11，ubuntu/windows 双平台）
- `references/requirements-dev.txt` — 开发依赖（black, isort, flake8, mypy, pytest, responses）

### Changed
- `references/fingerprint-strategies.md` — 新增：UA 池维护指南 + 自动检测脚本、Accept-Language 分场景模板、反检测评分表（6 种风险模式）
- `references/delay-strategies.md` — 新增：四层防护体系图、渐进式退避策略、会话级作息模拟、调参信号诊断表
- `references/manifest-pattern.md` — 新增：4 个边界情况（损坏恢复、磁盘不足、大量 topic 压缩、多进程安全）+ Manifest 迁移指南
- `references/worker-coordination.md` — 新增：信号处理、内存管理、Worker 健康监控、伸缩性指南（按 topic 量推荐参数）
- `SKILL.md` — 模块导航新增测试套件和 CI 入口
- `README.md` — 目录结构更新至 v1.2.0 完整版

## [1.1.0] — 2026-06-11

### Added
- `README.md` — GitHub 项目首页文档，包含快速开始、目录结构、参数调优表
- `.gitignore` — 排除 `__pycache__`、虚拟环境、临时数据文件
- `CHANGELOG.md` — 版本变更记录

### Changed
- `SKILL.md` — 重写为更精简的 LLM 指令格式（212→112 行），优化触发条件和流程描述，新增概览表、7 条常见错误
- `examples/basic-scraper.py` — 对齐完整模板的指纹池规模（5→15 套），增加断点续传、指数退避、Session 预热、结构化日志
- `references/troubleshooting.md` — 修复 Windows 平台命令兼容性（`rm` → `Remove-Item`），新增 3 个排查用例
- `references/data-contract.md` — 内联下游交接格式，移除对外部索引的硬依赖

### Fixed
- 修复 SKILL.md 中跨 Skill 路径引用在独立部署时可能断裂的问题
- 修复 troubleshooting.md 中 Linux-only 命令的跨平台兼容问题

## [1.0.0] — 2026-06-04

### Added
- 初始版本：完整的反检测爬虫框架
- 15 套浏览器指纹轮换（UA + Accept-Language + Referer）
- 变速延迟策略（60%/20%/10%/10% 分布）
- Manifest 断点续传（原子写入 + 崩溃恢复）
- 多 Worker 协调（ThreadPoolExecutor + 浮动启动）
- 代理池模块（轮询/随机/最少使用策略）
- Cookie 持久化模块（JSON/Netscape 格式）
- 故障排查指南（15 个常见问题）
- 示例代码（basic-scraper.py）
- 头像爬取器（fetch-avatars.py）
- JSON 合并器（merge-json.py）