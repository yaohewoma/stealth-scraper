#!/usr/bin/env python3
"""
Stealth Scraper — 基础爬虫示例
演示反检测爬虫框架的核心能力：指纹轮换、人类行为模拟、断点续传

用法:
    python basic-scraper.py                         # 爬取所有页面
    python basic-scraper.py --workers 1 --limit 5   # 测试 5 条
    python basic-scraper.py --resume                # 从断点恢复

目标: https://quotes.toscrape.com/ (练习用，无反爬)
"""

import requests
from bs4 import BeautifulSoup
import random
import time
import json
import os
import argparse
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

# =============================================================================
# 配置区
# =============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "output")
MANIFEST_PATH = os.path.join(DATA_DIR, "manifest.json")

TARGET_BASE_URL = "https://quotes.toscrape.com"

# 重试与超时
RETRY_MAX = 3
RETRY_BASE = 10
DEFAULT_TIMEOUT = 25

# 人类行为延迟参数（因为目标站无反爬，缩短至演示级别）
HUMAN_BROWSE_MIN = 1.0
HUMAN_BROWSE_MAX = 2.5
HUMAN_FLIP_MIN = 0.5
HUMAN_FLIP_MAX = 1.2
HUMAN_READ_MIN = 3.0
HUMAN_READ_MAX = 6.0
HUMAN_AWAY_MIN = 8.0
HUMAN_AWAY_MAX = 15.0

# =============================================================================
# 指纹池（15 套独立浏览器指纹）
# =============================================================================

USER_AGENTS = [
    # Chrome (Win/Mac/Linux)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Firefox (Win/Mac/Linux)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    # Safari (Mac/iOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    # Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0",
]

ACCEPT_LANGUAGES = [
    "zh-CN,zh;q=0.9,en;q=0.8",
    "en-US,en;q=0.9,zh-CN;q=0.7",
    "ja-JP,ja;q=0.9,en;q=0.8",
    "ko-KR,ko;q=0.9,en;q=0.8",
    "zh-TW,zh;q=0.9,en;q=0.8",
    "en-GB,en;q=0.9,zh-CN;q=0.6",
    "fr-FR,fr;q=0.9,en;q=0.7",
    "de-DE,de;q=0.9,en;q=0.7",
    "zh-CN,zh;q=0.8,en;q=0.9",
    "en-US,en;q=0.8,zh-CN;q=0.9",
    "es-ES,es;q=0.9,en;q=0.7",
    "pt-BR,pt;q=0.9,en;q=0.7",
    "zh-CN,zh;q=0.95,en;q=0.5",
    "en-US,en;q=0.95",
    "en-US,en;q=0.9,ja;q=0.6",
]

REFERERS = [
    "", "",
    "https://www.google.com/",
    "https://www.bing.com/",
    "https://github.com/",
    "https://duckduckgo.com/",
    "https://www.baidu.com/",
    "",
    "https://www.google.com/",
    "",
    "https://www.bing.com/",
    "https://www.google.com/",
    "",
    "https://duckduckgo.com/",
    "https://github.com/",
]

# =============================================================================
# Logging 配置
# =============================================================================

def setup_logging(verbose: bool = False) -> None:
    """配置日志系统：控制台输出带时间戳和级别"""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    datefmt = "%H:%M:%S"
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    root = logging.getLogger("scraper")
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)


# =============================================================================
# 人类行为模拟
# =============================================================================

def human_delay() -> None:
    """
    变速延迟策略：60% 正常浏览、20% 快速翻页、10% 仔细阅读、10% 离开，
    模拟真实人类的行为模式，避免固定延迟模式被反爬系统识别。
    """
    r = random.random()
    if r < 0.60:
        t = random.uniform(HUMAN_BROWSE_MIN, HUMAN_BROWSE_MAX)      # 正常浏览
    elif r < 0.80:
        t = random.uniform(HUMAN_FLIP_MIN, HUMAN_FLIP_MAX)          # 快速翻页
    elif r < 0.90:
        t = random.uniform(HUMAN_READ_MIN, HUMAN_READ_MAX)          # 仔细阅读
    else:
        t = random.uniform(HUMAN_AWAY_MIN, HUMAN_AWAY_MAX)          # 离开
    time.sleep(t)


# =============================================================================
# 请求基础设施
# =============================================================================

def build_headers(idx: int) -> Dict[str, str]:
    """
    构建请求头，指纹三元组（UA + Accept-Language + Referer）各自独立索引轮换，
    确保每条请求的指纹组合不同，避免固定模式。
    """
    ua = USER_AGENTS[idx % len(USER_AGENTS)]
    lang = ACCEPT_LANGUAGES[idx % len(ACCEPT_LANGUAGES)]
    referer = REFERERS[idx % len(REFERERS)]

    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": lang,
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def safe_get(session: requests.Session, url: str, idx: int,
             timeout: int = DEFAULT_TIMEOUT) -> Optional[requests.Response]:
    """
    带指数退避重试的 GET 请求。遇到 429 限流自动等待更长间隔；
    所有重试耗尽后返回 None，不抛异常。
    """
    logger = logging.getLogger("scraper")
    for attempt in range(RETRY_MAX):
        try:
            headers = build_headers(idx)
            resp = session.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 429:
                wait = RETRY_BASE * (3 ** attempt) + random.uniform(0, 5)
                logger.warning("429 限流，等待 %.0fs (attempt %d/%d)", wait, attempt + 1, RETRY_MAX)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt < RETRY_MAX - 1:
                wait = RETRY_BASE * (2 ** attempt) + random.uniform(0, 3)
                logger.debug("请求失败 (attempt %d/%d): %s，等待 %.1fs", attempt + 1, RETRY_MAX, e, wait)
                time.sleep(wait)
            else:
                logger.error("请求最终失败 (attempt %d/%d): %s", attempt + 1, RETRY_MAX, e)
    return None


def create_session(idx: int) -> requests.Session:
    """
    创建独立 Session，预热首页建立初始 Cookie 指纹，
    避免第一个业务请求就带异常行为标记。
    """
    sess = requests.Session()
    headers = build_headers(idx)
    try:
        sess.get(TARGET_BASE_URL, headers=headers, timeout=15)
    except Exception:
        pass  # 预热失败不影响后续爬取
    human_delay()
    return sess


# =============================================================================
# 断点续传 (Manifest)
# =============================================================================

def load_manifest() -> Dict[str, Any]:
    """加载 manifest 状态文件，不存在则创建空状态"""
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "version": 1,
        "startedAt": datetime.now().isoformat(),
        "statuses": {},
    }


def save_manifest(manifest: Dict[str, Any]) -> None:
    """
    原子写入 manifest：先写临时文件再 os.replace，
    防止写入中断导致 manifest 损坏。
    """
    tmp = MANIFEST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    os.replace(tmp, MANIFEST_PATH)


def needs_crawl(page_id: str, manifest: Dict[str, Any]) -> bool:
    """检查指定页面是否需要爬取（断点续传判断）"""
    return manifest["statuses"].get(str(page_id)) != "done"


# =============================================================================
# 数据提取（用户自定义核心函数）
# =============================================================================

def extract_data(html: str, url: str, page_index: int) -> Dict[str, Any]:
    """
    从 HTML 中提取结构化数据。
    这是用户需要自定义的核心函数——针对不同网站重写此函数即可。

    Args:
        html: 原始 HTML 字符串
        url: 页面 URL
        page_index: 页面序号（用于分页跟踪）

    Returns:
        dict: 提取的数据，至少包含 url、title、quotes、timestamp
    """
    soup = BeautifulSoup(html, "html.parser")

    # 提取名言
    quotes = []
    for quote_div in soup.find_all("div", class_="quote"):
        text_tag = quote_div.find("span", class_="text")
        author_tag = quote_div.find("small", class_="author")
        tags_tags = quote_div.find_all("a", class_="tag")

        if text_tag and author_tag:
            quotes.append({
                "text": text_tag.get_text(strip=True),
                "author": author_tag.get_text(strip=True),
                "tags": [t.get_text(strip=True) for t in tags_tags],
            })

    return {
        "url": url,
        "pageIndex": page_index,
        "quoteCount": len(quotes),
        "quotes": quotes,
        "timestamp": datetime.now().isoformat(),
    }


# =============================================================================
# 主函数
# =============================================================================

def load_urls() -> List[Dict[str, Any]]:
    """
    加载待爬取 URL 列表。
    生产环境中从 topics.json 或数据库加载。
    """
    # 本示例目标站共 10 页
    return [
        {"id": str(i), "url": f"{TARGET_BASE_URL}/page/{i}/"}
        for i in range(1, 11)
    ]


def run(args: argparse.Namespace) -> None:
    """主爬取流程"""
    logger = logging.getLogger("scraper")

    # 加载 manifest（支持断点续传）
    manifest = load_manifest()
    pages = load_urls()

    if args.limit:
        pages = pages[:args.limit]

    # 断点续传：过滤已完成页面
    if args.resume:
        original_count = len(pages)
        pages = [p for p in pages
                 if manifest["statuses"].get(str(p["id"])) != "done"]
        logger.info("Resume 模式：跳过 %d 个已完成，剩余 %d 个",
                     original_count - len(pages), len(pages))

    if not pages:
        logger.info("所有页面已完成，无需爬取")
        return

    logger.info("目标：%d 页 | Workers：%d | URL：%s",
                 len(pages), args.workers, TARGET_BASE_URL)

    # 创建 Session
    session = create_session(0)

    total_quotes = 0
    success_count = 0
    fail_count = 0

    # 逐页爬取
    for i, page in enumerate(pages):
        pid = str(page["id"])
        url = page["url"]

        if not needs_crawl(pid, manifest):
            logger.info("[%d/%d] 跳过已完成: %s", i + 1, len(pages), pid)
            continue

        logger.info("[%d/%d] 正在爬取: %s", i + 1, len(pages), url)

        # 爬取页面
        resp = safe_get(session, url, i)
        if resp is None:
            logger.warning("[%d/%d] 失败: %s", i + 1, len(pages), url)
            manifest["statuses"][pid] = "failed"
            fail_count += 1
            save_manifest(manifest)
            continue

        # 提取数据
        data = extract_data(resp.text, url, i + 1)
        data["pageId"] = pid
        total_quotes += data["quoteCount"]
        logger.info("[%d/%d] 提取到 %d 条名言", i + 1, len(pages), data["quoteCount"])

        # 保存结构化 JSON
        json_dir = os.path.join(DATA_DIR, "json")
        os.makedirs(json_dir, exist_ok=True)
        json_path = os.path.join(json_dir, f"{pid}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 保存原始 HTML
        html_dir = os.path.join(DATA_DIR, "html")
        os.makedirs(html_dir, exist_ok=True)
        html_path = os.path.join(html_dir, f"{pid}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(resp.text)

        # 标记完成
        manifest["statuses"][pid] = "done"
        success_count += 1
        save_manifest(manifest)

        # 人类行为模拟
        human_delay()

    # 汇总
    logger.info("=" * 50)
    logger.info("爬取完成！成功: %d | 失败: %d | 名言总数: %d",
                 success_count, fail_count, total_quotes)
    logger.info("数据目录: %s", DATA_DIR)
    logger.info("状态文件: %s", MANIFEST_PATH)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stealth Scraper 示例 — 爬取 quotes.toscrape.com",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python %(prog)s                        # 爬取全部 10 页
  python %(prog)s --limit 3              # 仅爬取前 3 页
  python %(prog)s --resume               # 从断点恢复
  python %(prog)s --verbose              # 详细日志
        """.strip()
    )
    parser.add_argument("--workers", type=int, default=1, help="Worker 数（本示例为顺序爬取，保留参数兼容）")
    parser.add_argument("--limit", type=int, default=0, help="限制爬取页数，0=全量")
    parser.add_argument("--resume", action="store_true", help="从 manifest 断点恢复")
    parser.add_argument("--verbose", action="store_true", help="详细日志 (DEBUG 级别)")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    run(args)