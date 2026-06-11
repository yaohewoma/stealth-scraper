# 代理池模块

## 概述

代理池模块为爬虫提供 IP 代理轮换能力，支持多种代理协议和自动健康检测。

## 配置

```python
# 代理池配置
PROXY_POOL_CONFIG = {
    "enabled": False,  # 是否启用代理池
    "protocol": "http",  # 代理协议: http, https, socks5
    "source": "file",  # 代理来源: file, api, rotating
    "proxy_file": "proxies.txt",  # 代理列表文件路径
    "api_url": "",  # 代理 API 地址（动态获取代理）
    "api_format": "json",  # API 返回格式: json, text
    "api_ip_field": "ip",  # JSON 中 IP 字段名
    "api_port_field": "port",  # JSON 中端口字段名
    "max_retries": 3,  # 代理失败最大重试次数
    "health_check_url": "https://httpbin.org/ip",  # 健康检测 URL
    "health_check_timeout": 10,  # 健康检测超时（秒）
    "rotation_strategy": "round_robin",  # 轮换策略: round_robin, random, least_used
    "fail_threshold": 3,  # 连续失败次数阈值，超过则标记为不可用
    "cooldown_time": 300,  # 不可用代理冷却时间（秒）
}
```

## 代理来源

### 1. 文件来源

从文本文件加载代理列表，每行一个代理：

```
# proxies.txt 格式
http://user:pass@proxy1.example.com:8080
http://proxy2.example.com:3128
socks5://proxy3.example.com:1080
```

### 2. API 来源

从代理 API 动态获取代理：

```python
def fetch_proxies_from_api(api_url: str, count: int = 10) -> List[str]:
    """从 API 获取代理列表"""
    response = requests.get(api_url, params={"count": count})
    data = response.json()
    return [f"http://{item['ip']}:{item['port']}" for item in data]
```

## 代理轮换策略

| 策略 | 说明 | 适用场景 |
|------|------|---------|
| round_robin | 轮询使用 | 代理质量均匀 |
| random | 随机选择 | 代理质量差异大 |
| least_used | 最少使用优先 | 均衡负载 |

## 健康检测

```python
class ProxyHealthChecker:
    """代理健康检测器"""
    
    def __init__(self, check_url: str, timeout: int):
        self.check_url = check_url
        self.timeout = timeout
        self.proxy_stats: Dict[str, ProxyStats] = {}
    
    def check(self, proxy: str) -> bool:
        """检测代理是否可用"""
        try:
            response = requests.get(
                self.check_url,
                proxies={"http": proxy, "https": proxy},
                timeout=self.timeout
            )
            return response.status_code == 200
        except Exception:
            return False
    
    def mark_failed(self, proxy: str):
        """标记代理失败"""
        if proxy not in self.proxy_stats:
            self.proxy_stats[proxy] = ProxyStats()
        stats = self.proxy_stats[proxy]
        stats.fail_count += 1
        stats.last_fail_time = time.time()
    
    def mark_success(self, proxy: str):
        """标记代理成功"""
        if proxy not in self.proxy_stats:
            self.proxy_stats[proxy] = ProxyStats()
        self.proxy_stats[proxy].fail_count = 0
    
    def is_available(self, proxy: str, threshold: int, cooldown: int) -> bool:
        """检查代理是否可用"""
        if proxy not in self.proxy_stats:
            return True
        stats = self.proxy_stats[proxy]
        if stats.fail_count < threshold:
            return True
        # 检查冷却时间
        if time.time() - stats.last_fail_time > cooldown:
            stats.fail_count = 0
            return True
        return False
```

## 集成到爬虫

```python
class ProxyPool:
    """代理池管理器"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.proxies: List[str] = []
        self.health_checker = ProxyHealthChecker(
            config["health_check_url"],
            config["health_check_timeout"]
        )
        self.current_index = 0
        
        # 加载代理
        if config["source"] == "file":
            self._load_from_file(config["proxy_file"])
        elif config["source"] == "api":
            self._refresh_from_api()
    
    def get_proxy(self) -> Optional[str]:
        """获取一个可用代理"""
        if not self.config["enabled"] or not self.proxies:
            return None
        
        strategy = self.config["rotation_strategy"]
        max_attempts = len(self.proxies)
        
        for _ in range(max_attempts):
            if strategy == "round_robin":
                proxy = self.proxies[self.current_index % len(self.proxies)]
                self.current_index += 1
            elif strategy == "random":
                proxy = random.choice(self.proxies)
            elif strategy == "least_used":
                proxy = min(self.proxies, key=lambda p: self.health_checker.proxy_stats.get(p, ProxyStats()).use_count)
            else:
                proxy = self.proxies[0]
            
            # 检查代理是否可用
            if self.health_checker.is_available(
                proxy,
                self.config["fail_threshold"],
                self.config["cooldown_time"]
            ):
                self.health_checker.proxy_stats[proxy].use_count += 1
                return proxy
        
        return None
    
    def report_success(self, proxy: str):
        """报告代理使用成功"""
        self.health_checker.mark_success(proxy)
    
    def report_failure(self, proxy: str):
        """报告代理使用失败"""
        self.health_checker.mark_failed(proxy)
```

## 使用示例

```python
# 初始化代理池
proxy_pool = ProxyPool(PROXY_POOL_CONFIG)

# 在请求中使用代理
def safe_get_with_proxy(session, url, idx, proxy_pool):
    proxy = proxy_pool.get_proxy()
    proxies = {"http": proxy, "https": proxy} if proxy else None
    
    try:
        response = session.get(url, proxies=proxies, timeout=DEFAULT_TIMEOUT)
        if proxy:
            proxy_pool.report_success(proxy)
        return response
    except Exception as e:
        if proxy:
            proxy_pool.report_failure(proxy)
        raise
```

## 注意事项

1. **代理质量**：建议使用付费代理服务，免费代理不稳定
2. **协议匹配**：确保代理协议与目标站点协议匹配（http/https）
3. **认证信息**：带认证的代理格式：`http://user:pass@host:port`
4. **超时设置**：使用代理时建议增加超时时间
5. **日志记录**：记录代理使用情况，便于排查问题
