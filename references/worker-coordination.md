# 多 Worker 协调

## 完整实现

```python
import math
import signal
from concurrent.futures import ThreadPoolExecutor, as_completed

def run_with_workers(topics, args):
    """多 Worker 协调入口"""
    # 分块：每个 Worker 独占一段数据，无并发冲突
    chunk_size = math.ceil(len(topics) / args.workers)
    chunks = [topics[i:i + chunk_size] for i in range(0, len(topics), chunk_size)]

    logger.info("Total: %d, Workers: %d, Chunk size: ~%d",
                 len(topics), args.workers, chunk_size)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for wid, chunk in enumerate(chunks):
            # 浮动启动：Worker 间随机延迟，避免同时触发限流
            if wid > 0:
                time.sleep(random.uniform(0, 60))
            futures[executor.submit(run_worker, wid, chunk, manifest)] = wid

        for future in as_completed(futures):
            wid = futures[future]
            try:
                future.result()
                logger.info("Worker %d finished", wid)
            except Exception as e:
                logger.error("Worker %d crashed: %s", wid, e)
            # 每个 Worker 完成后立即保存，确保进度不丢失
            save_manifest(manifest)
```

## 设计要点

1. **数据分块**：每个 Worker 独占一段，避免相互依赖和并发冲突
2. **浮动启动**：Worker 间 0~60s 随机 jitter，避免同时触发限流
3. **独立 Session**：每个 Worker 创建独立 `requests.Session`，预热首页建立 cookie
4. **即时保存**：每个 Worker 完成后立即落盘 manifest
5. **异常隔离**：单个 Worker 崩溃不影响其他 Worker

## 信号处理

Ctrl+C 时需要优雅退出，保存所有 Worker 的进度：

```python
import signal

# 全局引用
_manifest_ref = None
_executor_ref = None

def _signal_handler(signum, frame):
    """接收到中断信号时保存 manifest 并退出"""
    logger.warning("接收到中断信号，正在保存进度...")
    if _manifest_ref is not None:
        save_manifest(_manifest_ref)
    logger.warning("进度已保存，退出。使用 --resume 恢复")
    sys.exit(0)

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)  # 也处理 kill 信号
```

## Worker 数目参考

| 场景 | Workers | 最小延迟 | 说明 |
|------|---------|---------|------|
| 单 Worker | 1 | 10~30s | 最安全，适用于严格反爬站（Cloudflare 盾等） |
| 保守模式 | 2~3 | 5~15s | 行为检测站点，需要模拟真人浏览 |
| 标准模式 | 3~5 | 3~8s | 大多数场景，平衡速度和安全性 |
| 激进模式 | 5~10 | 0.5~2s | 仅限无防护站点，可能触发限流 |

```bash
# 单 Worker 模式（最安全，适用于严格反爬站）
python scraper.py --workers 1

# 标准模式（大多数场景）
python scraper.py --workers 5

# 激进模式（仅限无防护站点）
python scraper.py --workers 10
```

## 内存管理

长时间运行时需注意内存增长：

```python
def run_worker(worker_id, topics, manifest):
    """内存友好版本 — 定期清理 Session"""
    session = create_session(worker_id)
    session_refresh_interval = 200  # 每 200 条请求重建 Session

    for i, topic in enumerate(topics):
        # ... 爬取逻辑 ...

        # 每 N 条重建 Session（释放连接池和 Cookie 累积）
        if (i + 1) % session_refresh_interval == 0:
            session.close()
            session = create_session(worker_id)
            logger.info("Worker %d: Session 已刷新 (%d/%d)", worker_id, i + 1, len(topics))
```

## Worker 健康监控

```python
import threading
from collections import deque

class WorkerMonitor:
    """Worker 健康监控 — 检测卡死的 Worker"""

    def __init__(self, timeout_minutes: int = 30):
        self.timeout = timeout_minutes * 60
        self.last_progress: dict[int, float] = {}  # worker_id → 最后活跃时间
        self._lock = threading.Lock()

    def record_progress(self, worker_id: int):
        with self._lock:
            self.last_progress[worker_id] = time.time()

    def get_stalled_workers(self) -> list[int]:
        """返回超时未活动的 Worker 列表"""
        now = time.time()
        with self._lock:
            return [wid for wid, t in self.last_progress.items()
                    if now - t > self.timeout]
```

## 进度追踪

### 简易版本（日志输出）
```
[W0] 1/500 done topic=123
[W1] 1/500 done topic=456
[W2] 1/500 done topic=789
...
[W4] 500/500 done topic=3426
Worker 4 finished
```

### 增强版本（实时汇总）

```python
def print_summary(manifest: dict) -> str:
    """生成进度摘要"""
    total = len(manifest["statuses"])
    done = sum(1 for v in manifest["statuses"].values() if v == "done")
    failed = sum(1 for v in manifest["statuses"].values() if v == "failed")
    progress_pct = done / max(total, 1) * 100
    return f"Progress: {done}/{total} ({progress_pct:.1f}%) | Failed: {failed}"
```

## 伸缩性指南

| Topic 数量 | 推荐 Workers | 预计耗时 (行为检测站) | 预计耗时 (无防护站) |
|-----------|-------------|---------------------|-------------------|
| < 100 | 1 | 8~15 min | 1~2 min |
| 100 - 500 | 2~3 | 30~90 min | 5~15 min |
| 500 - 2000 | 3~5 | 2~5 h | 15~40 min |
| 2000 - 10000 | 3~5 | 8~24 h | 40 min~3 h |
| > 10000 | 分批跑 | 每 2000 条一批 | 每 5000 条一批 |

**分批策略**：对于 10000+ 条的超大规模采集，建议按 `--limit 2000` 分 5 批运行，每次用 `--resume` 接力，避免：
- 单次运行时间过长导致网络环境变化
- manifest 文件过大影响写入性能
- 内存累积增长