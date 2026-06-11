# 数据契约：Stealth Scraper

## 输入格式

本 Skill 为数据入口，无上游数据输入。

### 输入来源

| 来源 | 格式 | 说明 |
|------|------|------|
| `topics.json` | JSON 数组 | 待爬取 URL 列表 |
| 命令行参数 | `--workers` / `--limit` / `--resume` | 运行配置 |

### topics.json 格式

```json
[
  { "id": "123", "url": "https://target.com/t/123" },
  { "id": "456", "url": "https://target.com/t/456" }
]
```

**字段约束：**
- `id`：唯一标识符，支持字符串或数字
- `url`：完整 URL，必须包含协议（`https://`）

## 输出格式

### 1. 原始 HTML 存档

```
data/raw/html/{topicId}.html
```

- 编码：UTF-8
- 内容：完整 HTTP 响应 body（未经任何修改）
- 用途：保留原始数据，供后续重新解析或审计

### 2. 结构化 JSON（单条记录）

```
data/raw/json/{topicId}.json
```

```json
{
  "url": "https://target.com/t/123",
  "title": "项目标题",
  "content": "提取的文本内容（纯文本）",
  "topicId": "123",
  "timestamp": "2026-06-11T12:00:00"
}
```

### 3. Manifest 状态文件

```
data/manifest.json
```

```json
{
  "version": 1,
  "startedAt": "2026-06-11T12:00:00",
  "statuses": {
    "123": "done",
    "456": "failed"
  }
}
```

**状态枚举：**
- `done`：爬取成功，数据已保存
- `failed`：爬取失败，可重新尝试
- `skipped`：手动跳过

## 合并输出（供下游消费）

使用 `merge-json.py` 将散落的 `data/raw/json/*.json` 合并为统一 `merged.json`：

```json
{
  "projects": [
    {
      "url": "https://target.com/t/123",
      "title": "项目标题",
      "content": "提取的文本内容",
      "topicId": "123",
      "timestamp": "2026-06-11T12:00:00"
    }
  ],
  "meta": {
    "totalProjects": 3400,
    "sourceFiles": 3400,
    "loadedFiles": 3393,
    "duplicatesRemoved": 0,
    "generatedAt": "2026-06-11T14:00:00"
  }
}
```

下游 `rule-scoring-engine` 消费此 `merged.json`，期望字段包括：`topicId`、`title`、`content`（纯文本）、`url`。