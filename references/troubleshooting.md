# Stealth Scraper — 故障排查指南

## 运行错误

### `ConnectionError: 目标服务器拒绝连接`

**症状**：爬虫启动后立即报 ConnectionError，所有请求失败。

**排查步骤**：
1. 检查 `TARGET_BASE_URL` 是否正确，确保包含协议（`https://`）
2. 用浏览器手动访问目标 URL，确认站点可访问
3. 检查是否需要代理，在 `create_session()` 中添加 `proxies` 配置
4. 检查是否被目标站 IP 封禁，尝试切换网络环境

**如果确认是封禁**：
```bash
# 降低并发，增大延迟
python full-template.py --workers 1 --limit 5
```
并参考 `delay-strategies.md` 调大基础延迟。

### `HTTPError: 429 Too Many Requests`

**症状**：部分请求返回 429，限流警告。

**解决方案**：
1. 减少 Worker 数：`--workers 1`
2. 增大延迟：参考 `delay-strategies.md`，将基础延迟调到 8~15s
3. 增大批量休息频率：每 2~3 条就休息一次
4. 增大漂移访问概率到 25%

```bash
python full-template.py --workers 1 --limit 10
```

### `JSONDecodeError: 数据解析失败`

**症状**：`extract_data()` 返回的 JSON 格式错误。

**排查步骤**：
1. 检查 `extract_data()` 函数是否正确处理了空页面
2. 检查目标站 HTML 结构是否发生变化（A/B 测试）
3. 在 `extract_data()` 中增加 try/except 包裹解析逻辑

```python
def extract_data(html, url):
    try:
        soup = BeautifulSoup(html, 'html.parser')
        # ... 解析逻辑 ...
    except Exception as e:
        print(f"解析失败 {url}: {e}")
        return {"error": str(e), "url": url}
```

### Manifest 文件损坏

**症状**：`--resume` 模式下无法读取进度，报 JSON 解析错误。

**解决方案**：
1. 删除 `manifest.json` 从头开始
2. 检查 manifest 写入是否使用了原子写入（`os.replace()`）

```bash
# Windows
Remove-Item data/manifest.json
python full-template.py --workers 3

# Mac/Linux
rm data/manifest.json
python full-template.py --workers 3
```

## 性能问题

### 爬取速度过慢

**症状**：单线程爬取，速度远低于预期。

**排查**：
1. 检查网络延迟：`ping target-site.com`
2. 增大 Worker 数：`--workers 3`（注意不要超过站点承受能力）
3. 检查延迟策略是否过于保守，参考 `delay-strategies.md` 适当降低基础延迟

### 内存占用过高

**症状**：长时间运行后内存持续增长。

**原因**：HTML 原始文件未及时释放或 Session 对象未复用。

**解决方案**：
- 确保每个 Worker 使用独立 Session 并在完成后清理
- 设置 `--limit` 分批爬取，避免一次性加载全部数据

## 数据问题

### 输出的 JSON 中缺少字段

**症状**：`extract_data()` 返回的对象缺少某些字段。

**排查**：
- 检查 `extract_data()` 是否对所有字段都做了默认值处理
- 目标站 HTML 结构可能因 A/B 测试变化

```python
def extract_data(html, url):
    soup = BeautifulSoup(html, 'html.parser')
    return {
        "title": soup.find('h1').text if soup.find('h1') else "",
        "votes": int(vote.text) if (vote := soup.select_one('.votes')) else 0,
        # 始终提供默认值
    }
```

### 头像下载失败

**症状**：`fetch-avatars.py` 中部分头像下载返回 404。

**解决方案**：
- 检查目标站是否使用了外部 CDN，确认 `AVATAR_TEMPLATE` 模板正确
- 部分用户可能没有设置头像，404 是正常的（脚本已内置跳过逻辑）
- 检查是否需要登录才能获取头像

### `SSLError: 证书验证失败`

**症状**：爬虫报 `SSLError` 或 `certificate verify failed`。

**解决方案**：
1. 目标站可能使用自签名证书或 Cloudflare SSL
2. 临时方案（仅测试环境）：
```python
# 在 create_session() 中设置
session.verify = False
```
3. 推荐方案：更新系统证书或使用 `certifi` 包

### 被 Cloudflare 5 秒盾拦截

**症状**：返回 503 状态码或 JS Challenge 页面，响应内容为 "Checking your browser..."。

**解决方案**：
1. 检查 User-Agent 是否包含最新版本
2. 增大 `Accept-Language` 和 `Referer` 的多样性
3. 增大基础延迟到 15~30s
4. 考虑使用 `cloudscraper` 或 `selenium` 替代方案

### 响应内容为空白但状态码 200

**症状**：HTTP 200 但 body 为空或仅包含 "请启用 JavaScript"。

**解决方案**：
1. 目标站需要 JavaScript 渲染，`requests` 无法处理
2. 检查 `Accept` 和 `Accept-Language` 头是否完整
3. 考虑切换到 `selenium` + `undetected-chromedriver`

### 编码问题 / 乱码

**症状**：提取的中文内容显示为乱码。

**解决方案**：
1. 检测并设置正确编码：`resp.encoding = resp.apparent_encoding`
2. 在 `extract_data()` 中统一转为 UTF-8
3. **Windows 环境特别注意**：确保文件写入使用 `encoding='utf-8'`