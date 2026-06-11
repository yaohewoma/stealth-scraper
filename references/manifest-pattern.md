# 断点续传 (Manifest)

## 设计目标

在数千条批量爬取场景中，进程可能因以下原因中断：
- 用户主动 Ctrl+C
- 网络断开
- 目标站临时限流导致大量失败需要重跑
- 系统重启 / 笔记本合盖

Manifest 机制确保无论何种中断，已完成的进度不会丢失。

## 数据结构

```json
{
  "version": 1,
  "startedAt": "2026-06-11T12:00:00",
  "updatedAt": "2026-06-11T14:30:00",
  "stats": {
    "total": 3400,
    "done": 3120,
    "failed": 15,
    "skipped": 7,
    "pending": 258
  },
  "statuses": {
    "123": "done",
    "456": "failed",
    "789": "skipped"
  }
}
```

**design note**：`stats` 字段是可选的快捷统计，运行时通过遍历 `statuses` 即可实时计算，但它避免了每次保存 manifest 时都要 O(n) 遍历 3000+ 条记录。

## 实现

```python
def load_manifest() -> dict:
    """加载状态文件，不存在则创建新的"""
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "version": 1,
        "startedAt": datetime.now().isoformat(),
        "statuses": {},
    }


def save_manifest(manifest: dict) -> None:
    """原子写入，防止写入中断导致 manifest 损坏"""
    tmp = MANIFEST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    os.replace(tmp, MANIFEST_PATH)  # 原子操作


def needs_crawl(topic_id: str, manifest: dict) -> bool:
    """检查指定 topic 是否需要爬取"""
    return manifest["statuses"].get(str(topic_id)) != "done"


def resume_from_manifest(manifest: dict) -> list[str]:
    """从 manifest 中提取未完成的任务列表"""
    return [tid for tid, status in manifest["statuses"].items() if status != "done"]
```

## 关键设计

1. **原子写入**：`os.replace(temp, target)` 在 POSIX 和 Windows 上都是原子操作，进程崩溃时不会出现半写入的损坏文件
2. **及时标记**：每个 topic 完成后**立即**写入 manifest，不是批量完成后才写
3. **状态枚举**：`done` / `failed` / `skipped`
   - `done`：跳过不重试
   - `failed`：默认重试（可配合 `--retry-failed` 参数）
   - `skipped`：手动跳过，不重试
4. **Worker 安全**：每条记录由唯一 Worker 负责，不存在并发写冲突
5. **恢复模式**：`--resume` 参数跳过已完成 topic，只爬未完成的

## 边界情况

### 1. Manifest 文件损坏

如果 `load_manifest()` 遇到 `JSONDecodeError`：

```python
def load_manifest() -> dict:
    try:
        if os.path.exists(MANIFEST_PATH):
            with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning("Manifest 损坏 (%s)，从备份恢复...", e)
        backup = MANIFEST_PATH + ".backup"
        if os.path.exists(backup):
            os.replace(backup, MANIFEST_PATH)
            return load_manifest()
        logger.warning("无备份可用，创建新 manifest")

    return {"version": 1, "startedAt": datetime.now().isoformat(), "statuses": {}}
```

### 2. 磁盘空间不足

写入 manifest 前检查磁盘空间：

```python
import shutil

def save_manifest(manifest: dict) -> None:
    # 检查磁盘空间（至少保留 10MB）
    free = shutil.disk_usage(os.path.dirname(MANIFEST_PATH)).free
    if free < 10 * 1024 * 1024:
        logger.critical("磁盘空间不足 (%d MB)，停止爬取", free // (1024 * 1024))
        raise RuntimeError("磁盘空间不足")

    tmp = MANIFEST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    os.replace(tmp, MANIFEST_PATH)
```

### 3. 大量 topic 的性能优化

当 topic 数量超过 10000 时，`json.dump` 的 manifest 文件可能达到数 MB。优化策略：

- **增量字段**：仅保存 `statuses`，去掉每个 topic 的附加信息
- **定时快照**：每 5 分钟做一次完整备份（`manifest.{timestamp}.backup`）
- **压缩存储**：使用 `gzip` 压缩 manifest 文件（对于 3400 条记录约节省 80% 空间）

```python
import gzip

def save_manifest_compressed(manifest: dict) -> None:
    """压缩写入（适用于大量记录场景）"""
    tmp = MANIFEST_PATH + ".tmp.gz"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    os.replace(tmp, MANIFEST_PATH + ".gz")
```

### 4. 多进程安全

虽然当前设计使用 `ThreadPoolExecutor`（共享进程空间，无并发写入问题），但如果升级到多进程：

```python
import fcntl  # Linux only
# 或使用 portalocker (跨平台): pip install portalocker

def save_manifest_multiprocess(manifest: dict) -> None:
    """多进程安全的 manifest 写入"""
    import portalocker
    tmp = MANIFEST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        portalocker.lock(f, portalocker.LOCK_EX)
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    os.replace(tmp, MANIFEST_PATH)
```

## 恢复流程

```bash
# 首次运行
python scraper.py --workers 3
# → 爬取 1500/3400 条后被 Ctrl+C 中断

# 断点续传（只爬剩余 1900 条）
python scraper.py --workers 3 --resume

# 重试失败的任务 + 继续
python scraper.py --workers 3 --resume --retry-failed

# 查看当前进度
python -c "import json; m=json.load(open('data/manifest.json')); \
  done=sum(1 for v in m['statuses'].values() if v=='done'); \
  print(f'{done}/{len(m[\"statuses\"])} completed')"
```

## Manifest 迁移 (v1 → v2)

如果需要变更 manifest 数据结构：

```python
def migrate_manifest_v1_to_v2(old: dict) -> dict:
    """从 v1 迁移到 v2 格式"""
    if old.get("version") == 1:
        return {
            "version": 2,
            "startedAt": old["startedAt"],
            "stats": {
                "total": len(old["statuses"]),
                "done": sum(1 for v in old["statuses"].values() if v == "done"),
                "failed": sum(1 for v in old["statuses"].values() if v == "failed"),
            },
            "statuses": old["statuses"],
        }
    return old
```