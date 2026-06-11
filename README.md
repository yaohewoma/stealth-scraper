# stealth-scraper

> **一句话**：500+ 项目采集零封禁，断点续传不怕崩

反检测爬虫框架，专为竞品分析场景设计。通过 15 套浏览器指纹轮换、人类行为模拟和断点续传机制，实现大规模论坛数据零封禁采集。

## 快速开始

```bash
# 查看示例
python examples/basic-scraper.py

# 查看完整参考实现
cat references/full-template.py
```

## 模块地图

| 目录/文件 | 说明 |
|-----------|------|
| `SKILL.md` | Skill 主文档 |
| `examples/` | 使用示例 |
| `references/` | 参考实现和设计文档 |
| `tests/` | 测试固件 |
| `CHANGELOG.md` | 变更日志 |

## 核心能力

- 15 套浏览器指纹自动轮换
- 人类行为模拟（滚动、停留、点击间隔）
- Cookie + 代理池管理
- 断点续传（checkpoint 机制）
- 429/503 退避重试策略

## 适用场景

- 论坛 / 社区帖子批量采集
- 竞品数据自动化收集
- 需要反反爬的场景

## GitHub

https://github.com/yaohewoma/stealth-scraper