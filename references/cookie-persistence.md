# Cookie 持久化模块

## 概述

Cookie 持久化模块将爬虫获取的 Cookie 保存到本地文件，支持跨会话复用，减少重复登录和验证。

## 配置

```python
# Cookie 持久化配置
COOKIE_CONFIG = {
    "enabled": True,  # 是否启用 Cookie 持久化
    "storage": "file",  # 存储方式: file, sqlite
    "cookie_dir": "cookies",  # Cookie 文件存储目录
    "file_format": "json",  # 文件格式: json, netscape
    "expire_check": True,  # 是否检查 Cookie 过期
    "auto_save": True,  # 请求后自动保存
    "domain_filter": [],  # 域名过滤（为空则保存所有）
    "max_age": 86400 * 7,  # Cookie 最大存活时间（秒）
}
```

## 存储格式

### JSON 格式

```json
{
  "version": 1,
  "domain": "example.com",
  "created_at": "2024-01-01T00:00:00",
  "updated_at": "2024-01-01T12:00:00",
  "cookies": [
    {
      "name": "session_id",
      "value": "abc123",
      "domain": ".example.com",
      "path": "/",
      "expires": 1706745600,
      "httpOnly": true,
      "secure": true,
      "sameSite": "Lax"
    }
  ]
}
```

### Netscape 格式

```
# Netscape HTTP Cookie File
# https://curl.se/rfc/cookie_spec.html
# This is a generated file! Do not edit.

.example.com	TRUE	/	TRUE	1706745600	session_id	abc123
.example.com	TRUE	/	FALSE	0	preference	theme=dark
```

## 实现

```python
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from http.cookiejar import MozillaCookieJar, Cookie


class CookieManager:
    """Cookie 管理器"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.cookie_dir = config["cookie_dir"]
        os.makedirs(self.cookie_dir, exist_ok=True)
    
    def _get_cookie_path(self, domain: str) -> str:
        """获取 Cookie 文件路径"""
        safe_domain = domain.replace(".", "_").replace("/", "_")
        return os.path.join(self.cookie_dir, f"{safe_domain}.json")
    
    def load_cookies(self, domain: str) -> List[Dict[str, Any]]:
        """加载指定域名的 Cookie"""
        path = self._get_cookie_path(domain)
        if not os.path.exists(path):
            return []
        
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # 检查过期
        if self.config["expire_check"]:
            now = datetime.now().timestamp()
            valid_cookies = []
            for cookie in data.get("cookies", []):
                expires = cookie.get("expires", 0)
                if expires == 0 or expires > now:
                    valid_cookies.append(cookie)
            return valid_cookies
        
        return data.get("cookies", [])
    
    def save_cookies(self, domain: str, cookies: List[Dict[str, Any]]) -> None:
        """保存 Cookie 到文件"""
        path = self._get_cookie_path(domain)
        
        # 过滤域名
        if self.config["domain_filter"]:
            if not any(d in domain for d in self.config["domain_filter"]):
                return
        
        # 加载现有数据
        existing = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        
        # 合并 Cookie（新值覆盖旧值）
        cookie_map = {}
        for cookie in existing.get("cookies", []):
            key = (cookie["name"], cookie.get("domain", ""), cookie.get("path", "/"))
            cookie_map[key] = cookie
        
        for cookie in cookies:
            key = (cookie["name"], cookie.get("domain", ""), cookie.get("path", "/"))
            cookie_map[key] = cookie
        
        # 构建保存数据
        save_data = {
            "version": 1,
            "domain": domain,
            "created_at": existing.get("created_at", datetime.now().isoformat()),
            "updated_at": datetime.now().isoformat(),
            "cookies": list(cookie_map.values())
        }
        
        # 原子写入
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    
    def get_cookies_for_domain(self, domain: str) -> Dict[str, str]:
        """获取域名的 Cookie 字典"""
        cookies = self.load_cookies(domain)
        return {c["name"]: c["value"] for c in cookies}
    
    def clear_expired(self, domain: Optional[str] = None) -> int:
        """清理过期 Cookie"""
        cleared = 0
        domains = [domain] if domain else self._get_all_domains()
        
        for d in domains:
            path = self._get_cookie_path(d)
            if not os.path.exists(path):
                continue
            
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            now = datetime.now().timestamp()
            valid_cookies = []
            for cookie in data.get("cookies", []):
                expires = cookie.get("expires", 0)
                if expires == 0 or expires > now:
                    valid_cookies.append(cookie)
                else:
                    cleared += 1
            
            if len(valid_cookies) != len(data.get("cookies", [])):
                data["cookies"] = valid_cookies
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        
        return cleared
    
    def _get_all_domains(self) -> List[str]:
        """获取所有已保存的域名"""
        domains = []
        for filename in os.listdir(self.cookie_dir):
            if filename.endswith(".json"):
                domain = filename[:-5].replace("_", ".")
                domains.append(domain)
        return domains


class SessionWithCookies:
    """带 Cookie 持久化的 Session"""
    
    def __init__(self, cookie_manager: CookieManager, domain: str):
        self.cookie_manager = cookie_manager
        self.domain = domain
        self.session = requests.Session()
        
        # 加载已有 Cookie
        self._load_cookies()
    
    def _load_cookies(self):
        """加载 Cookie 到 Session"""
        cookies = self.cookie_manager.load_cookies(self.domain)
        for cookie in cookies:
            self.session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain", ""),
                path=cookie.get("path", "/")
            )
    
    def _save_cookies(self):
        """保存 Session 中的 Cookie"""
        cookies = []
        for cookie in self.session.cookies:
            cookies.append({
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
                "expires": cookie.expires,
                "secure": cookie.secure,
            })
        self.cookie_manager.save_cookies(self.domain, cookies)
    
    def get(self, url: str, **kwargs) -> requests.Response:
        """发送 GET 请求并自动保存 Cookie"""
        response = self.session.get(url, **kwargs)
        if self.cookie_manager.config["auto_save"]:
            self._save_cookies()
        return response
    
    def post(self, url: str, **kwargs) -> requests.Response:
        """发送 POST 请求并自动保存 Cookie"""
        response = self.session.post(url, **kwargs)
        if self.cookie_manager.config["auto_save"]:
            self._save_cookies()
        return response
```

## 使用示例

### 基本用法

```python
# 初始化 Cookie 管理器
cookie_manager = CookieManager(COOKIE_CONFIG)

# 创建带 Cookie 的 Session
session = SessionWithCookies(cookie_manager, "example.com")

# 发送请求（自动加载和保存 Cookie）
response = session.get("https://example.com/page1")
response = session.get("https://example.com/page2")
```

### 手动管理

```python
# 手动加载 Cookie
cookies = cookie_manager.load_cookies("example.com")

# 手动保存 Cookie
new_cookies = [
    {"name": "token", "value": "xyz789", "domain": ".example.com", "path": "/"}
]
cookie_manager.save_cookies("example.com", new_cookies)

# 清理过期 Cookie
cleared = cookie_manager.clear_expired()
print(f"Cleared {cleared} expired cookies")
```

## 集成到爬虫模板

```python
# 在配置区添加
COOKIE_CONFIG = {
    "enabled": True,
    "storage": "file",
    "cookie_dir": os.path.join(DATA_DIR, "cookies"),
    "file_format": "json",
    "expire_check": True,
    "auto_save": True,
    "domain_filter": [],
    "max_age": 86400 * 7,
}

# 修改 create_session 函数
def create_session(idx: int, cookie_manager: Optional[CookieManager] = None) -> requests.Session:
    """创建独立 Session，支持 Cookie 持久化"""
    sess = requests.Session()
    headers, _, _, _ = build_headers(idx)
    
    # 加载已有 Cookie
    if cookie_manager and cookie_manager.config["enabled"]:
        domain = TARGET_BASE_URL.split("//")[-1].split("/")[0]
        cookies = cookie_manager.load_cookies(domain)
        for cookie in cookies:
            sess.cookies.set(cookie["name"], cookie["value"])
    
    # 预热首页
    try:
        resp = sess.get(TARGET_BASE_URL, headers=headers, timeout=SESSION_WARMUP_TIMEOUT)
        # 保存新 Cookie
        if cookie_manager and cookie_manager.config["enabled"]:
            domain = TARGET_BASE_URL.split("//")[-1].split("/")[0]
            new_cookies = [
                {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path, "expires": c.expires}
                for c in sess.cookies
            ]
            cookie_manager.save_cookies(domain, new_cookies)
    except Exception:
        pass
    
    human_delay()
    return sess
```

## 注意事项

1. **敏感信息**：Cookie 可能包含敏感信息，注意文件权限
2. **过期处理**：定期清理过期 Cookie，避免文件膨胀
3. **并发安全**：多线程写入同一域名的 Cookie 时需要加锁
4. **域名匹配**：注意区分 `.example.com` 和 `example.com`
5. **Secure 属性**：HTTPS 站点的 Cookie 应设置 `secure=True`
