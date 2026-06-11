"""
通用反检测爬虫模板
基于 3400+ 页面实战验证的策略

用法:
    python scraper.py                           # 默认 5 workers, 全量
    python scraper.py --workers 3               # 3 线程
    python scraper.py --limit 50                # 先跑 50 个测试
    python scraper.py --resume                  # 从 manifest 断点续传
    python scraper.py --dry-run                 # 仅预览，不爬取

依赖: pip install requests beautifulsoup4 tqdm
"""
import re, json, os, sys, time, random, math, signal, logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin
import argparse

import requests
from bs4 import BeautifulSoup

# Optional tqdm import
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

# =============================================================================
# 配置区
# =============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
RAW_HTML_DIR = os.path.join(DATA_DIR, "raw", "html")
RAW_JSON_DIR = os.path.join(DATA_DIR, "raw", "json")
MANIFEST_PATH = os.path.join(DATA_DIR, "manifest.json")

TARGET_BASE_URL = "https://example.com"  # 目标站点

# 重试与超时常量
RETRY_MAX = 3
RETRY_BASE = 10
DEFAULT_TIMEOUT = 25
SESSION_WARMUP_TIMEOUT = 15
DRIFT_TIMEOUT = 10

# manifest 批量保存间隔（每 N 个 topic 保存一次，减少磁盘 I/O）
BATCH_SAVE_INTERVAL = 10

# 人类行为延时参数
HUMAN_BROWSE_MIN = 3.5
HUMAN_BROWSE_MAX = 8.5
HUMAN_FLIP_MIN = 1.2
HUMAN_FLIP_MAX = 3.0
HUMAN_READ_MIN = 10
HUMAN_READ_MAX = 28
HUMAN_AWAY_MIN = 30
HUMAN_AWAY_MAX = 95

# 批量休息参数
BATCH_REST_SHORT_MIN = 25
BATCH_REST_SHORT_MAX = 85
BATCH_REST_MEDIUM_MIN = 85
BATCH_REST_MEDIUM_MAX = 175
BATCH_REST_LONG_MIN = 175
BATCH_REST_LONG_MAX = 410

# 漂移访问概率
DRIFT_PROBABILITY = 0.15

# Worker 启动间隔最大值（秒）
WORKER_START_DELAY_MAX = 60

# 提取数据的必填字段
EXTRACT_REQUIRED_FIELDS = ["url", "title", "content", "timestamp"]

# =============================================================================
# 指纹池（15 套独立浏览器指纹）
# =============================================================================

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
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
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%H:%M:%S"
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    root = logging.getLogger("scraper")
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

def get_worker_logger(worker_id: int) -> logging.Logger:
    """为指定 Worker 创建独立 logger"""
    logger = logging.getLogger(f"scraper.W{worker_id}")
    logger.propagate = True  # 继承 root handler
    return logger

# =============================================================================
# Signal 处理（Ctrl+C 保存 manifest）
# =============================================================================

# 全局 manifest 引用，供 signal handler 使用
_manifest_ref: Optional[Dict[str, Any]] = None

def _signal_handler(signum: int, frame: Any) -> None:
    """接收到中断信号时保存 manifest 并退出"""
    logger = logging.getLogger("scraper")
    logger.warning("接收到中断信号 (Ctrl+C)，正在保存 manifest ...")
    if _manifest_ref is not None:
        save_manifest(_manifest_ref)
    logger.warning("Manifest 已保存，退出。")
    sys.exit(1)

signal.signal(signal.SIGINT, _signal_handler)

# =============================================================================
# 人类行为模拟
# =============================================================================

def human_delay() -> None:
    """变速延迟：60%正常浏览，20%快速翻页，10%仔细阅读，10%离开"""
    r = random.random()
    if r < 0.60:
        t = random.uniform(HUMAN_BROWSE_MIN, HUMAN_BROWSE_MAX)
    elif r < 0.80:
        t = random.uniform(HUMAN_FLIP_MIN, HUMAN_FLIP_MAX)
    elif r < 0.90:
        t = random.uniform(HUMAN_READ_MIN, HUMAN_READ_MAX)
    else:
        t = random.uniform(HUMAN_AWAY_MIN, HUMAN_AWAY_MAX)
    time.sleep(t)


def batch_rest() -> None:
    """每完成一批任务后的休息"""
    r = random.random()
    if r < 0.50:
        t = random.uniform(BATCH_REST_SHORT_MIN, BATCH_REST_SHORT_MAX)
    elif r < 0.80:
        t = random.uniform(BATCH_REST_MEDIUM_MIN, BATCH_REST_MEDIUM_MAX)
    else:
        t = random.uniform(BATCH_REST_LONG_MIN, BATCH_REST_LONG_MAX)
    time.sleep(t)


def drift_visit(session: requests.Session, idx: int) -> None:
    """15% 概率随机访问其他页面，破坏固定行为模式"""
    if random.random() < DRIFT_PROBABILITY:
        urls = [
            f"{TARGET_BASE_URL}/",
            f"{TARGET_BASE_URL}/category/1",
            f"{TARGET_BASE_URL}/category/2",
        ]
        headers, _, _, _ = build_headers(idx)
        try:
            session.get(random.choice(urls), headers=headers, timeout=DRIFT_TIMEOUT)
        except Exception:
            pass
        time.sleep(random.uniform(1, 3))


# =============================================================================
# 请求基础设施
# =============================================================================

def build_headers(idx: int) -> Tuple[Dict[str, str], str, str, str]:
    """构建请求头，指纹索引独立轮换"""
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
    return headers, ua, lang, referer


def safe_get(session: requests.Session, url: str, idx: int,
             timeout: int = DEFAULT_TIMEOUT) -> Optional[requests.Response]:
    """带指数退避重试的 GET 请求，所有重试耗尽后返回 None"""
    logger = get_worker_logger(idx)
    for attempt in range(RETRY_MAX):
        try:
            headers, _, _, _ = build_headers(idx)
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
                logger.debug("请求失败 (attempt %d/%d): %s，等待 %.1fs 重试", attempt + 1, RETRY_MAX, e, wait)
                time.sleep(wait)
            else:
                logger.error("请求最终失败 (attempt %d/%d): %s", attempt + 1, RETRY_MAX, e)
    return None


def create_session(idx: int) -> requests.Session:
    """创建独立 Session，预热首页建立 cookie"""
    sess = requests.Session()
    headers, _, _, _ = build_headers(idx)
    try:
        sess.get(TARGET_BASE_URL, headers=headers, timeout=SESSION_WARMUP_TIMEOUT)
    except Exception:
        pass
    human_delay()
    return sess


# =============================================================================
# 断点续传 (Manifest)
# =============================================================================

def load_manifest() -> Dict[str, Any]:
    """加载 manifest 状态文件"""
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "version": 1,
        "startedAt": datetime.now().isoformat(),
        "statuses": {},
    }


def save_manifest(manifest: Dict[str, Any]) -> None:
    """原子写入，防止写入中断导致 manifest 损坏"""
    tmp = MANIFEST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    os.replace(tmp, MANIFEST_PATH)


def needs_crawl(topic_id: str, manifest: Dict[str, Any]) -> bool:
    """检查指定 topic 是否需要爬取"""
    return manifest["statuses"].get(str(topic_id)) != "done"


# =============================================================================
# 数据提取（用户自定义）
# =============================================================================

def extract_data(html_content: str, url: str) -> Dict[str, Any]:
    """
    从 HTML 中提取结构化数据。
    这是用户需要自定义的核心函数。

    Args:
        html_content: 原始 HTML 字符串
        url: 页面 URL

    Returns:
        dict: 提取的数据字段，保证包含所有 EXTRACT_REQUIRED_FIELDS
    """
    soup = BeautifulSoup(html_content, "html.parser")

    data: Dict[str, Any] = {
        "url": url,
        "title": "",
        "content": "",
        "timestamp": datetime.now().isoformat(),
    }

    # 示例：提取标题
    title_tag = soup.find("h1")
    if title_tag:
        data["title"] = title_tag.get_text(strip=True)

    # 示例：提取文本内容
    content_tag = soup.find("article") or soup.find("main") or soup.find("body")
    if content_tag:
        data["content"] = content_tag.get_text(separator="\n", strip=True)

    # 结构化输出约束：确保所有必填字段存在
    for field in EXTRACT_REQUIRED_FIELDS:
        if field not in data:
            data[field] = ""
    if not data.get("timestamp"):
        data["timestamp"] = datetime.now().isoformat()

    return data


# =============================================================================
# Worker 线程
# =============================================================================

def run_worker(worker_id: int, topics: List[Dict[str, Any]],
               manifest: Dict[str, Any]) -> int:
    """单个 Worker 线程的主循环"""
    logger = get_worker_logger(worker_id)
    total = len(topics)
    session = create_session(worker_id)

    # 进度条（tqdm 可用时）
    iterator = enumerate(topics)
    if TQDM_AVAILABLE:
        iterator = tqdm(enumerate(topics), total=total, desc=f"W{worker_id}",
                        position=worker_id, leave=False, unit="topic")

    counter = 0  # 本地计数器，用于批量保存
    for i, topic in iterator:
        tid = str(topic["id"])

        # 检查是否需要爬取
        if not needs_crawl(tid, manifest):
            logger.info("%d/%d skip topic=%s (already done)", i + 1, total, tid)
            continue

        try:
            # 爬取页面
            url = topic["url"]
            resp = safe_get(session, url, worker_id)
            if resp is None:
                manifest["statuses"][tid] = "failed"
                logger.warning("%d/%d failed topic=%s (request returned None)", i + 1, total, tid)
                counter += 1
                continue

            html = resp.text

            # 保存原始 HTML
            html_path = os.path.join(RAW_HTML_DIR, f"{tid}.html")
            os.makedirs(RAW_HTML_DIR, exist_ok=True)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)

            # 提取数据
            data = extract_data(html, url)
            data["topicId"] = tid

            # 保存结构化 JSON
            json_path = os.path.join(RAW_JSON_DIR, f"{tid}.json")
            os.makedirs(RAW_JSON_DIR, exist_ok=True)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # 标记完成
            manifest["statuses"][tid] = "done"
            logger.info("%d/%d done topic=%s", i + 1, total, tid)

        except Exception as e:
            logger.error("%d/%d error topic=%s: %s", i + 1, total, tid, e)
            manifest["statuses"][tid] = "failed"

        counter += 1

        # 批量保存 manifest（每 BATCH_SAVE_INTERVAL 条，降低磁盘 I/O）
        if counter % BATCH_SAVE_INTERVAL == 0:
            save_manifest(manifest)

        # 人类行为：延迟 + 漂移 + 批量休息
        human_delay()
        if i % random.randint(3, 7) == 0:
            drift_visit(session, worker_id)
        if (i + 1) % random.randint(3, 7) == 0:
            batch_rest()

    # 最后再保存一次，确保数据不丢失
    save_manifest(manifest)
    return worker_id


# =============================================================================
# 主函数
# =============================================================================

def run(args: argparse.Namespace) -> None:
    """主爬取流程"""
    global _manifest_ref

    manifest = load_manifest()
    _manifest_ref = manifest  # 注册给 signal handler

    logger = logging.getLogger("scraper")

    # 加载待爬取列表
    topics = load_topics()
    if args.limit:
        topics = topics[:args.limit]

    # 断点续传：过滤已完成 topic
    if args.resume:
        original_count = len(topics)
        topics = [t for t in topics
                  if manifest["statuses"].get(str(t["id"])) != "done"]
        skipped = original_count - len(topics)
        logger.info("Resume 模式：跳过 %d 个已完成 topic，剩余 %d 个",
                     skipped, len(topics))

    logger.info("Total topics: %d, Workers: %d", len(topics), args.workers)

    # 分块
    chunk_size = math.ceil(len(topics) / args.workers)
    chunks = [topics[i:i + chunk_size] for i in range(0, len(topics), chunk_size)]

    # 浮动启动：Worker 间随机延迟，避免同时触发限流
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for wid, chunk in enumerate(chunks):
            if wid > 0:
                time.sleep(random.uniform(0, WORKER_START_DELAY_MAX))
            futures[executor.submit(run_worker, wid, chunk, manifest)] = wid

        # 总进度条
        total_topics = len(topics)
        pbar = None
        if TQDM_AVAILABLE:
            pbar = tqdm(total=total_topics, desc="Total", unit="topic")

        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logger.error("Worker %d crashed: %s", futures[future], e)
            # 每个 worker 完成后保存 manifest
            save_manifest(manifest)
            if pbar is not None:
                done_count = sum(1 for v in manifest["statuses"].values() if v == "done")
                failed_count = sum(1 for v in manifest["statuses"].values() if v == "failed")
                pbar.n = done_count + failed_count
                pbar.refresh()

        if pbar is not None:
            pbar.close()

    done_count = sum(1 for v in manifest["statuses"].values() if v == "done")
    failed_count = sum(1 for v in manifest["statuses"].values() if v == "failed")
    logger.info("Done! Success: %d, Failed: %d", done_count, failed_count)


def load_topics() -> List[Dict[str, Any]]:
    """用户自定义：从数据源加载待爬取列表"""
    with open("topics.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return [{"id": t["id"], "url": t["url"]} for t in data]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stealth Scraper - 通用反检测爬虫模板，支持多线程、指纹轮换、断点续传",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python %(prog)s --workers 3 --limit 100
  python %(prog)s --workers 5 --resume
  python %(prog)s --dry-run
        """.strip()
    )
    parser.add_argument("--workers", type=int, default=5, help="Worker 线程数 (default: 5)")
    parser.add_argument("--limit", type=int, default=0, help="限制爬取条数，0=全量 (default: 0)")
    parser.add_argument("--resume", action="store_true", help="从 manifest 断点恢复")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际爬取")
    parser.add_argument("--verbose", action="store_true", help="详细日志输出 (DEBUG 级别)")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    if args.dry_run:
        logging.getLogger("scraper").info("Dry run - no actual crawling")
    else:
        run(args)