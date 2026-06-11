#!/usr/bin/env python3
"""
通用头像爬取器 —— 从论坛 API 提取用户头像并下载
适用于 Discourse 类论坛系统

用法:
    python fetch_avatars.py
    python fetch_avatars.py --input projects.json --output avatars/
    python fetch_avatars.py --size 240 --workers 3

依赖: pip install requests tqdm
"""
import json, os, sys, time, random, re, logging, argparse
from typing import Any, Dict, List, Optional, Tuple
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# Optional tqdm import
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

# =============================================================================
# 配置
# =============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 目标论坛配置
FORUM_BASE = "https://forum.example.com"
AVATAR_SIZE = 120  # 头像尺寸（默认值）

# 重试与超时
RETRY_MAX = 3
RETRY_BASE = 5
API_TIMEOUT = 15
DOWNLOAD_TIMEOUT = 10

# 浏览器指纹（5 套）
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]

# =============================================================================
# Logging 配置
# =============================================================================

def setup_logging(verbose: bool = False) -> None:
    """配置日志系统"""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%H:%M:%S"
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    root = logging.getLogger("avatars")
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)


def get_worker_logger(worker_id: int) -> logging.Logger:
    """为指定 Worker 创建独立 logger"""
    logger = logging.getLogger(f"avatars.W{worker_id}")
    logger.propagate = True
    return logger


# =============================================================================
# 文件名清理
# =============================================================================

def sanitize_filename(name: str) -> str:
    """清理文件名中的特殊字符，保留字母、数字、中文、下划线、连字符"""
    # 替换路径分隔符和非法字符
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', name)
    # 去除首尾空格和点
    sanitized = sanitized.strip(' .')
    # 如果清理后为空，使用默认名
    if not sanitized:
        sanitized = "unknown"
    return sanitized


# =============================================================================
# Session 管理
# =============================================================================

def get_session() -> requests.Session:
    """创建带随机指纹的 requests session"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": FORUM_BASE + "/",
    })
    return s


# =============================================================================
# 头像 URL 提取
# =============================================================================

def fetch_avatar_url(session: requests.Session, topic_id: int,
                     author_name: str, avatar_size: int = AVATAR_SIZE) -> str:
    """
    从 Discourse topic JSON API 提取用户头像 URL。

    Discourse 的 /t/{topic_id}.json 接口会返回帖子作者的头像信息，
    通常位于 post_stream.posts[0].avatar_template 字段。
    """
    logger = logging.getLogger("avatars")
    api_url = f"{FORUM_BASE}/t/{topic_id}.json"
    size_str = str(avatar_size)

    for attempt in range(RETRY_MAX):
        try:
            resp = session.get(api_url, timeout=API_TIMEOUT)
            if resp.status_code == 429:
                wait = RETRY_BASE * (2 ** attempt) + random.uniform(0, 3)
                logger.warning("429 限流 topic=%d，等待 %.0fs (attempt %d/%d)",
                               topic_id, wait, attempt + 1, RETRY_MAX)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()

            # Discourse avatar template 格式: "/user_avatar/{host}/{username}/{size}/{hash}.png"
            posts = data.get("post_stream", {}).get("posts", [])
            if posts:
                avatar_template = posts[0].get("avatar_template", "")
                if avatar_template:
                    avatar_url = avatar_template.replace("{size}", size_str)
                    if avatar_url.startswith("/"):
                        avatar_url = FORUM_BASE + avatar_url
                    return avatar_url

            # 兼容其他论坛系统
            participants = data.get("details", {}).get("participants", [])
            for user in participants:
                if user.get("username") == author_name:
                    avatar = user.get("avatar_template", "")
                    if avatar:
                        return FORUM_BASE + avatar.replace("{size}", size_str)

            return ""  # API 返回成功但无头像信息

        except Exception as e:
            if attempt < RETRY_MAX - 1:
                wait = RETRY_BASE * (2 ** attempt) + random.uniform(0, 2)
                logger.debug("topic=%d avatar fetch attempt %d/%d failed: %s",
                             topic_id, attempt + 1, RETRY_MAX, e)
                time.sleep(wait)
            else:
                logger.error("topic=%d avatar fetch failed after %d attempts: %s",
                             topic_id, RETRY_MAX, e)

    return ""


# =============================================================================
# 头像下载
# =============================================================================

def download_avatar(session: requests.Session, avatar_url: str,
                    output_path: str, author_name: str) -> bool:
    """下载头像到本地，验证 Content-Type"""
    logger = logging.getLogger("avatars")
    if not avatar_url:
        return False

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    for attempt in range(RETRY_MAX):
        try:
            resp = session.get(avatar_url, timeout=DOWNLOAD_TIMEOUT)
            if resp.status_code == 200:
                # 验证 Content-Type 是否为 image/*
                content_type = resp.headers.get("Content-Type", "")
                if not content_type.startswith("image/"):
                    logger.warning("非图片响应 for %s: Content-Type=%s", author_name, content_type)
                    return False

                with open(output_path, "wb") as f:
                    f.write(resp.content)
                return True
            elif resp.status_code == 429:
                wait = RETRY_BASE * (2 ** attempt) + random.uniform(0, 3)
                logger.warning("429 限流 download %s，等待 %.0fs (attempt %d/%d)",
                               author_name, wait, attempt + 1, RETRY_MAX)
                time.sleep(wait)
            else:
                logger.debug("download %s HTTP %d (attempt %d/%d)",
                             author_name, resp.status_code, attempt + 1, RETRY_MAX)
                if attempt < RETRY_MAX - 1:
                    wait = RETRY_BASE * (2 ** attempt)
                    time.sleep(wait)
        except Exception as e:
            if attempt < RETRY_MAX - 1:
                wait = RETRY_BASE * (2 ** attempt) + random.uniform(0, 2)
                time.sleep(wait)
            else:
                logger.error("download failed for %s after %d attempts: %s",
                             author_name, RETRY_MAX, e)

    return False


# =============================================================================
# 作者提取
# =============================================================================

def get_unique_authors(projects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """提取唯一作者列表（去重）"""
    seen: Dict[str, bool] = {}
    result: List[Dict[str, Any]] = []
    for p in projects:
        author = p.get("author", "")
        if not author or author in seen:
            continue
        seen[author] = True
        result.append({
            "name": author,
            "topicId": p["topicId"],
        })
    return result


# =============================================================================
# Worker
# =============================================================================

def process_author(author: Dict[str, Any], output_dir: str,
                   avatar_size: int) -> Dict[str, str]:
    """处理单个作者的头像"""
    sess = get_session()
    name = author["name"]
    tid = author["topicId"]

    avatar_url = fetch_avatar_url(sess, tid, name, avatar_size)
    if avatar_url:
        safe_name = sanitize_filename(name)
        filename = f"{safe_name}.png"
        filepath = os.path.join(output_dir, filename)
        if download_avatar(sess, avatar_url, filepath, name):
            return {"author": name, "avatarUrl": f"avatars/{filename}", "topicId": str(tid)}
    return {"author": name, "avatarUrl": "", "topicId": str(tid)}


# =============================================================================
# 主函数
# =============================================================================

def main() -> None:
    """主入口"""
    parser = argparse.ArgumentParser(
        description="Stealth Scraper / Fetch Avatars - 从 Discourse 论坛 API 提取用户头像并下载",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python %(prog)s --input projects.json --output avatars/
  python %(prog)s --input projects.json --output avatars/ --size 240 --workers 3
        """.strip()
    )
    parser.add_argument("--input", help="Path to input JSON file with projects (auto-detected if omitted)")
    parser.add_argument("--output", default="avatars", help="Output directory for avatars (default: avatars)")
    parser.add_argument("--size", type=int, default=AVATAR_SIZE, help="Avatar size in pixels (default: 120)")
    parser.add_argument("--workers", type=int, default=3, help="Number of download workers (default: 3)")
    parser.add_argument("--verbose", action="store_true", help="详细日志输出 (DEBUG 级别)")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    logger = logging.getLogger("avatars")

    avatar_size = args.size  # 使用命令行参数

    # 加载项目
    input_file = args.input or os.path.join(BASE_DIR, "..", "analyzer", "public", "data", "top300_merged.json")
    logger.info("Reading: %s", input_file)
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    projects = data.get("projects", data if isinstance(data, list) else [])

    authors = get_unique_authors(projects)
    logger.info("Authors: %d unique from %d projects", len(authors), len(projects))

    # 下载
    output_dir = os.path.join(BASE_DIR, args.output)
    os.makedirs(output_dir, exist_ok=True)
    logger.info("Downloading avatars (size=%d, workers=%d)...", avatar_size, args.workers)

    results: Dict[str, str] = {}
    success = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_author, a, output_dir, avatar_size): a for a in authors}

        # 进度条
        iterator = as_completed(futures)
        if TQDM_AVAILABLE:
            iterator = tqdm(iterator, total=len(authors), desc="Avatars", unit="author")

        for future in iterator:
            result = future.result()
            author_name = result["author"]
            if result["avatarUrl"]:
                results[author_name] = result["avatarUrl"]
                success += 1
                logger.info("%s %s: %s", "OK", author_name, result["avatarUrl"])
            else:
                results[author_name] = ""
                logger.warning("%s %s: no avatar", "SKIP", author_name)

    # 保存映射
    output_json = os.path.join(BASE_DIR, "author-avatars.json")
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    logger.info("Done: %d/%d avatars", success, len(authors))
    logger.info("Output: %s/", output_dir)
    logger.info("Mapping: %s", output_json)


if __name__ == "__main__":
    main()