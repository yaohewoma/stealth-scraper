# 指纹轮换策略

## 核心原则

指纹三元组（UA + Accept-Language + Referer）各自独立索引轮换，确保每条请求的指纹组合不同。

**为什么独立索引？** 如果 UA/Lang/Referer 三者在同一条记录里固定绑定，一旦某个指纹被标记，整条记录都会失效。独立轮换使得即使检测到某个 UA，也无法预测下一条请求的 Language 和 Referer。

## UA 池设计

### 覆盖维度
- **操作系统**：Windows 10/11, macOS 14/15, Linux (Ubuntu/Arch), iOS 17, Android 14
- **浏览器**：Chrome 123-126, Firefox 124-127, Safari 17.4-17.5, Edge 126
- **设备**：Desktop, Mobile (iPhone 15), Tablet (iPad Pro)

### 关键技巧
- 版本号要"活"：用当前季度最新版本，不要用过期版本
- Chrome 用户占多数：15 个 UA 中 Chrome 族占 8-10 个
- 避免极端值：不要用 IE 11、Chrome 80 等明显过时的版本
- **移动端比例不超 20%**：3/15 为移动设备，太多 mobile UA 会触发异常检测

### 维护指南：如何更新指纹池

每季度检查一次浏览器版本更新：

```python
# 检查步骤：
# 1. 打开 https://www.whatismybrowser.com/guides/the-latest-version/
# 2. 获取最新 Chrome/Firefox/Safari 主版本号
# 3. 替换 USER_AGENTS 中对应浏览器的版本号（保持 OS 和设备分布不变）
# 4. 在版本号相近的 2-3 个之间做微小差异（e.g. Chrome 126, 125, 124）
```

**自动检测脚本（可选）：**

```python
"""检查 UA 池中是否存在过期版本"""
import requests
from packaging import version

LATEST_CHROME = 126  # 手动维护，来源：Chrome 发布页面

def check_ua_freshness(user_agents: list[str]) -> list[str]:
    """扫描 UA 池，返回版本过旧的条目"""
    stale = []
    import re
    for ua in user_agents:
        match = re.search(r'Chrome/(\d+)\.', ua)
        if match and int(match[1]) < LATEST_CHROME - 2:
            stale.append(ua)
    return stale
```

## Accept-Language 设计

与目标站点受众匹配：

| 目标站点受众 | 语言池 |
|-------------|--------|
| 中文站点 | zh-CN 为主 (60%)，少量 en-US (20%)，日韩/繁体 (20%) |
| 国际站点 | en-US 为主 (60%)，少量 zh-CN/de/fr/es (40%) |
| 日本站点 | ja-JP 为主 (70%)，少量 en-US (30%) |

### 自定义语言池模板

```python
# 根据目标站受众，选择以下模板之一
LANG_CN_SITE = [
    "zh-CN,zh;q=0.9,en;q=0.8",  * 9,   # 60% 中文为主
    "en-US,en;q=0.9,zh-CN;q=0.7", * 3,  # 20% 英文
    "ja-JP,ja;q=0.9,en;q=0.8",         # 20% 日韩繁体
    "ko-KR,ko;q=0.9,en;q=0.8",
    "zh-TW,zh;q=0.9,en;q=0.8",
]

LANG_INTL_SITE = [
    "en-US,en;q=0.9",           * 4,   # 60% 英文
    "en-GB,en;q=0.9",           * 3,
    "en-US,en;q=0.9,zh-CN;q=0.7", * 2,
    "zh-CN,zh;q=0.9,en;q=0.8",         # 40% 其他
    "de-DE,de;q=0.9,en;q=0.8",
    "fr-FR,fr;q=0.9,en;q=0.8",
    "es-ES,es;q=0.9,en;q=0.8",
    "pt-BR,pt;q=0.9,en;q=0.8",
]
```

## Referer 设计

- **空 referer (40%)**：模拟直接访问、书签打开
- **搜索引擎 (40%)**：Google, Bing, DuckDuckGo, Baidu
- **技术站点 (20%)**：GitHub, Stack Overflow 等

**为什么空 referer 比例不能太高？** 超过 60% 的直接访问会被某些反爬系统识别为自动化工具，因为真人用户很少全部通过书签/直接输入访问。

## 反检测评分 (Detection Score)

以下模式会提高被检测的概率，按风险排序：

| 风险等级 | 模式 | 检测原因 | 修复 |
|---------|------|---------|------|
| 🔴 高 | 所有请求固定 UA | 流量模式单一 | 用指纹池轮换 |
| 🔴 高 | UA / Lang / Referer 固定绑定 | 可被指纹识别 | 各自独立索引 |
| 🟠 中 | 100% 请求带 Referer | 不像真人浏览 | 40% 空 referer |
| 🟠 中 | UA 版本号过旧 (>2 个大版本) | 明显不是最新浏览器 | 每季度更新 |
| 🟡 低 | 顺序轮换 (0→1→2→…) | 模式可预测 | 加 jitter 打乱 |
| 🟡 低 | 移动端 UA 占比 >50% | 不符合桌面端爬虫场景 | 保持 15-20% |

## 反检测指标速查

避免以下模式：
- 固定 UA 但不同 Accept-Language → 不自然
- 所有请求都带 Referer → 不自然
- 指纹轮换有规律（如按顺序轮换）→ 用 `idx % len(pool)` 看似随机实则固定，配合 jitter 进一步打乱
- Chrome 126 UA 配 Firefox-only 的 Accept header → header 与 UA 不一致
- Windows UA 却声称 `Accept-Language: ja-JP` 且占比过高 → 语言分布与 OS 不匹配