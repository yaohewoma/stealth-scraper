# 延迟策略

## 设计哲学

反爬系统的核心检测手段之一是**时间模式分析**。机器人倾向于均匀、快速的请求间隔，而真人用户表现出高度不规则的时间分布。本 Skill 的延迟策略通过多层随机化来模拟这种不规则性。

**四层防护**（从微观到宏观）：

```
请求间延迟 (变速) → 批量休息 → 漂移访问 → 浮动启动
   秒级             分钟级        随机穿插      会话级
```

## 变速延迟

```python
def human_delay():
    """变速延迟：60%正常浏览，20%快速翻页，10%仔细阅读，10%离开"""
    r = random.random()
    if r < 0.60:
        t = random.uniform(3.5, 8.5)
    elif r < 0.80:
        t = random.uniform(1.2, 3.0)
    elif r < 0.90:
        t = random.uniform(10, 28)
    else:
        t = random.uniform(30, 95)
    time.sleep(t)
```

### 行为模式解释

| 策略 | 占比 | 延迟范围 | 模拟场景 |
|------|------|---------|---------|
| 正常浏览 | 60% | 3.5-8.5s | 正常阅读标题和摘要后点击下一页 |
| 快速翻页 | 20% | 1.2-3.0s | 快速扫过不感兴趣的内容 |
| 仔细阅读 | 10% | 10-28s | 认真阅读长篇文章 |
| 离开 | 10% | 30-95s | 起身倒水、接电话、查其他资料 |

**为什么不用固定 sleep？** 固定间隔 `time.sleep(3)` 会在服务器端形成整齐的时间间隔分布——这是机器人的典型特征。真人行为的间隔是高度分散的。

## 批量休息

每完成一批任务后，模拟人类需要休息：

```python
def batch_rest():
    r = random.random()
    if r < 0.50:
        t = random.uniform(25, 85)       # 50% 短休（喝水）
    elif r < 0.80:
        t = random.uniform(85, 175)      # 30% 中休（去洗手间）
    else:
        t = random.uniform(175, 410)    # 20% 长休（吃饭/开会）
    time.sleep(t)
```

### 触发时机

```python
# 每 3~7 条后有一定概率触发批量休息
if (i + 1) % random.randint(3, 7) == 0:
    batch_rest()
```

## 漂移访问

```python
def drift_visit(session, idx):
    """15% 概率随机访问其他页面，破坏固定行为模式"""
    if random.random() < 0.15:
        drift_urls = [
            f"{TARGET_BASE_URL}/",
            f"{TARGET_BASE_URL}/category/1",
            f"{TARGET_BASE_URL}/about",
        ]
        headers, _, _, _ = build_headers(idx)
        try:
            session.get(random.choice(drift_urls), headers=headers, timeout=10)
        except Exception:
            pass  # 漂移访问失败不影响主流程
        time.sleep(random.uniform(1, 3))
```

**为什么需要漂移访问？** 如果是纯粹的数据采集，请求序列会是 `page/1 → page/2 → page/3 → ...`，这种线性模式极易被检测。而真人会随机点击首页、分类页、关于页等，形成网状浏览模式。

## 浮动启动

Worker 线程非同时启动，避免瞬时流量尖峰：

```python
for wid, chunk in enumerate(chunks):
    if wid > 0:
        time.sleep(random.uniform(0, 60))  # 0~60s 随机 jitter
    executor.submit(run_worker, wid, chunk, manifest)
```

## 渐进式退避 (Progressive Backoff)

当检测到 429/503 响应时，应该逐步增大延迟而非立即停止：

```python
def progressive_backoff(consecutive_errors: int) -> float:
    """渐进式退避：连续错误越多，等待越久"""
    base = 30  # 基础等待 30s
    multiplier = 2 ** min(consecutive_errors, 5)  # 上限 32x
    jitter = random.uniform(0, base)
    return base * multiplier + jitter
    # 1st error: ~60s
    # 2nd error: ~120s
    # 3rd error: ~240s
    # ...
    # 5th+: ~960s (16min)
```

## 会话级时间管理

对于长时间运行的爬虫（数小时以上），需要在**会话级别**引入作息模式：

```python
def should_be_active(hour: int) -> bool:
    """模拟人类作息：深夜降低活跃度"""
    if 2 <= hour < 7:
        return random.random() < 0.3  # 凌晨仅 30% 概率活跃
    elif 7 <= hour < 9:
        return random.random() < 0.7  # 早晨 70%
    else:
        return True  # 白天全活跃

# 使用:
import datetime
if not should_be_active(datetime.datetime.now().hour):
    time.sleep(random.uniform(600, 1800))  # 10-30min 睡眠
```

## 调参建议

| 站点防护等级 | 基础延迟 | 批量间隔 | 漂移概率 | Workers |
|-------------|---------|---------|---------|---------|
| 无防护 | 0.5~2s | 不需要 | 0% | 5~10 |
| 基础限流 | 1~5s | 每 10 条 | 5% | 3~5 |
| 行为检测 | 3~8s | 每 3~7 条 | 15% | 3~5 |
| Cloudflare | 5~15s | 每 2~4 条 | 20% | 1~2 |
| 严格反爬 | 10~30s | 每 1~3 条 | 25% | 1 |

### 调参信号

| 症状 | 原因 | 调整 |
|------|------|------|
| 前 100 条正常，之后全 429 | 速率检测触发 | 增大基础延迟 50%，增大批量休息频率 |
| 第 1 条就 429 | IP 已被标记 | 切换 IP，降低 Workers 到 1 |
| HTTP 200 但内容为空 | JS 挑战页面（检测通过但需 JS） | requests 无法处理，需降级到 Selenium |
| 随机丢包（成功率 80%） | 网络不稳定 + 反爬 | 增大重试次数到 5，增大超时到 45s |