---
name: "stealth-scraper"
version: "1.1.0"
description: "Builds anti-detection Python web scrapers with rotating browser fingerprints, human-like delays, checkpoint resume, and multi-worker coordination. Invoke when user needs to scrape websites with anti-bot protection at scale."
---

# Stealth Scraper — 反检测爬虫框架

> **核心原则：** 绝不用 Selenium/Playwright 开场。先用 requests，只有 JS 渲染必需时才降级。
> **执行前必做：** 生成任何爬虫代码前，必须先阅读 [`references/full-template.py`](references/full-template.py) 获取完整模板。

## 0. 概览

| 项目 | 说明 |
|------|------|
| **定位** | 数据采集流水线入口，产出原始 HTML + 结构化 JSON |
| **上游** | 无（数据入口） |
| **下游** | [rule-scoring-engine](../rule-scoring-engine/SKILL.md) — 对爬取结果做六维度自动评分 |
| **产出** | `data/raw/html/{id}.html` + `data/raw/json/{id}.json` + `data/manifest.json` |
| **实战验证** | 3400+ 页面，99.8% 成功率，零封禁 |

## 1. 触发条件

### 应使用本 Skill
- 用户提到"爬虫"、"采集"、"批量抓取"、"数据采集"、"网页抓取"
- 需要从有反爬机制的网站批量获取数据
- 需要多线程并行爬取且不能触发封禁
- 爬取过程需要断点续传（随时中断后恢复）
- 需要下载图片/头像等二进制资源到本地

### 不应使用本 Skill
- 简单的一次性 API 调用 → 直接用 `requests.get()`
- 需要 JS 渲染的 SPA 页面 → 用 Playwright/Selenium
- 需要登录认证（可扩展但模板不含）
- 目标站 `robots.txt` 明确 Disallow → 先提醒用户

## 2. 生成爬虫的标准流程

```
确认目标 → 读取模板 → 定制指纹池 → 实现 extract_data() → 调参 → 输出并运行
```

1. **确认目标** — 与用户确认 URL 模式、期望提取的字段、是否需要解析 HTML
2. **读取模板** — 阅读 [`references/full-template.py`](references/full-template.py)
3. **定制指纹池** — 根据目标站受众区域，参考 [`references/fingerprint-strategies.md`](references/fingerprint-strategies.md) 调整 UA/语言池
4. **实现 extract_data()** — 用户只需定义 `extract_data(html: str, url: str) -> dict` 函数
5. **调参** — 根据站点反爬强度，参考 [`references/delay-strategies.md`](references/delay-strategies.md) 选择延迟参数
6. **输出** — 生成完整的 `.py` 脚本，用户直接 `python scraper.py` 运行

### 前置约束（生成代码时必须遵守）

- **绝不用固定 sleep** — 必须用 `random.uniform(a, b)`
- **输出必须存档** — 同时保存原始 HTML、纯文本、结构化 JSON
- **manifest 原子写入** — 用 `os.replace(temp, target)`，禁止 `json.dump` 直接覆盖
- **指纹独立轮换** — UA、Accept-Language、Referer 三元组各自独立索引
- **数据源为 Excel** — 使用 `openpyxl` 读取

## 3. 模块导航

| 模块 | 问题 | 参考文件 |
|------|------|---------|
| **主模板** | 完整可运行的爬虫框架 | [`references/full-template.py`](references/full-template.py) |
| 指纹轮换 | 15 套 UA/语言/Referer 独立轮换 | [`references/fingerprint-strategies.md`](references/fingerprint-strategies.md) |
| 延迟策略 | 变速延迟 + 批量休息 + 漂移访问 | [`references/delay-strategies.md`](references/delay-strategies.md) |
| 断点续传 | Manifest 状态管理 + 原子写入 | [`references/manifest-pattern.md`](references/manifest-pattern.md) |
| 多 Worker | ThreadPoolExecutor + 浮动启动 | [`references/worker-coordination.md`](references/worker-coordination.md) |
| 数据契约 | 输入/输出格式 + 下游交接 | [`references/data-contract.md`](references/data-contract.md) |
| 头像爬取 | Discourse 论坛头像下载 | [`references/fetch-avatars.py`](references/fetch-avatars.py) |
| JSON 合并 | 散落 JSON → 统一 projects 数组 | [`references/merge-json.py`](references/merge-json.py) |
| 代理池（可选）| IP 代理轮换 + 健康检测 | [`references/proxy-pool.md`](references/proxy-pool.md) |
| Cookie（可选）| Cookie 持久化跨会话复用 | [`references/cookie-persistence.md`](references/cookie-persistence.md) |
| 故障排查 | 15 个常见问题的解决方案 | [`references/troubleshooting.md`](references/troubleshooting.md) |
| 测试套件 | 单元测试 + 集成测试 (pytest) | [`tests/`](tests/) |
| CI/CD | GitHub Actions 自动 lint + test | [`.github/workflows/ci.yml`](.github/workflows/ci.yml) |

## 4. 参数调优速查

| 站点防护等级 | workers | 基础延迟 | 批量间隔 | 漂移概率 |
|------------|---------|---------|---------|---------|
| 无防护 | 5~10 | 0.5~2s | 每 10 条 | 0% |
| 基础限流 | 3~5 | 1~5s | 每 8 条 | 5% |
| 行为检测 | 3~5 | 3~8s | 每 3~7 条 | 15% |
| Cloudflare | 1~2 | 5~15s | 每 2~4 条 | 20% |
| 严格反爬 | 1 | 10~30s | 每 1~3 条 | 25% |

## 5. 常见错误（生成代码时避免）

| 错误写法 | 后果 | 正确写法 |
|---------|------|---------|
| `time.sleep(3)` 固定延迟 | 行为模式被识别，触发封禁 | `time.sleep(random.uniform(a, b))` |
| 不预热 Session | 首个请求携带异常行为标记 | `create_session()` 先 GET 首页 |
| `json.dump(obj, f)` 直接写 manifest | 进程崩溃时 manifest 损坏 | 写临时文件 → `os.replace(tmp, target)` |
| 用 Selenium/Playwright 开场 | 重 10 倍，慢且易检测 | 先用 requests，只有 JS 渲染必要才降级 |
| 所有 Worker 同时启动 | 瞬时流量尖峰触发限流 | `time.sleep(random.uniform(0, 60))` 浮动启动 |
| 不存档原始 HTML | 重新解析时无数据源 | 每次请求都保存到 `raw/html/{id}.html` |
| 硬编码指纹组合 | 单点失效，模式可识别 | UA/Lang/Referer 独立索引轮换 |

## 6. Quick Start

```bash
pip install requests beautifulsoup4 tqdm

# 修改 full-template.py: TARGET_BASE_URL = "https://your-site.com"
# 实现 extract_data() 和 load_topics()

python full-template.py --workers 1 --limit 10    # 先测试 10 条
python full-template.py --workers 3                # 全量运行
python full-template.py --resume                   # 断点续传
python full-template.py --dry-run                  # 预览不爬取

# 爬完后:
python merge-json.py --input data/raw/json/ --output merged.json
python fetch-avatars.py --input merged.json --output avatars/
```