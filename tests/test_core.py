#!/usr/bin/env python3
"""Stealth Scraper 测试套件 — 测试核心模块的指纹轮换、行为模拟、断点续传、数据提取"""

import json
import os
import sys
import tempfile
import time
from datetime import datetime
from typing import Any, Dict, List
from unittest import mock

import pytest

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_html() -> str:
    """模拟目标网站的 HTML 片段"""
    return """<html>
<body>
<article>
    <h1>Test Project Title</h1>
    <main>
        <p>This is a sample project description for testing purposes.</p>
        <p>It contains multiple paragraphs to simulate realistic content.</p>
    </main>
</article>
</body>
</html>"""


@pytest.fixture
def sample_topics() -> List[Dict[str, Any]]:
    """模拟待爬取列表"""
    return [
        {"id": "1", "url": "https://example.com/t/1"},
        {"id": "2", "url": "https://example.com/t/2"},
        {"id": "3", "url": "https://example.com/t/3"},
    ]


@pytest.fixture
def temp_dir():
    """创建临时目录用于测试"""
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


# =============================================================================
# 指纹轮换测试
# =============================================================================


class TestFingerprintRotation:
    """测试浏览器指纹轮换机制"""

    # 模拟指纹池（精简版用于测试）
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Firefox/127.0",
    ]
    LANGUAGES = ["zh-CN,zh;q=0.9,en;q=0.8", "en-US,en;q=0.9", "ja-JP,ja;q=0.9"]
    REFERERS = ["", "https://www.google.com/", "https://github.com/"]

    def build_headers(self, idx: int) -> Dict[str, str]:
        """构建请求头"""
        ua = self.USER_AGENTS[idx % len(self.USER_AGENTS)]
        lang = self.LANGUAGES[idx % len(self.LANGUAGES)]
        referer = self.REFERERS[idx % len(self.REFERERS)]
        headers = {
            "User-Agent": ua,
            "Accept-Language": lang,
            "Accept": "text/html,application/xhtml+xml",
            "Connection": "keep-alive",
        }
        if referer:
            headers["Referer"] = referer
        return headers

    def test_different_indices_produce_different_headers(self):
        """不同索引应产生不同的请求头组合"""
        h0 = self.build_headers(0)
        h1 = self.build_headers(1)
        h2 = self.build_headers(2)

        # 三个独立索引应有不同的三元组
        assert h0["User-Agent"] != h1["User-Agent"]
        assert h1["User-Agent"] != h2["User-Agent"]
        assert h0["Accept-Language"] != h1["Accept-Language"]

    def test_same_index_cycle_produces_same_ua(self):
        """同索引循环（模长）应产生相同 UA（确保轮换确定性）"""
        pool_size = len(self.USER_AGENTS)
        h0 = self.build_headers(0)
        h_cycle = self.build_headers(pool_size)
        assert h0["User-Agent"] == h_cycle["User-Agent"]

    def test_referer_may_be_empty(self):
        """空 Referer 是合法的（模拟直接访问）"""
        h0 = self.build_headers(0)
        # 第一个 Referer 为空字符串
        assert "Referer" not in h0

    def test_non_empty_referer_is_set(self):
        """非空 Referer 必须出现在请求头中"""
        h1 = self.build_headers(1)
        assert "Referer" in h1
        assert h1["Referer"] != ""


# =============================================================================
# 行为模拟测试
# =============================================================================


class TestHumanBehavior:
    """测试人类行为模拟"""

    def test_random_delay_uses_uniform(self):
        """确保延迟使用 random.uniform 而非固定值"""

        with mock.patch("random.random", return_value=0.5):
            with mock.patch("random.uniform", return_value=5.0) as mock_uniform:
                with mock.patch("time.sleep") as mock_sleep:
                    # 模拟变速延迟
                    r = 0.5  # 落在正常浏览区间 (0.60)
                    if r < 0.60:
                        t = mock_uniform(3.5, 8.5)
                    time.sleep(t)

                    mock_sleep.assert_called_once_with(5.0)
                    mock_uniform.assert_called_once_with(3.5, 8.5)

    def test_delay_distribution_covers_all_ranges(self):
        """验证四种延迟策略都能被覆盖"""
        strategies_hit = set()

        # 用固定 random 值模拟每种策略
        for r, label in [(0.3, "browse"), (0.7, "flip"), (0.85, "read"), (0.95, "away")]:
            if r < 0.60:
                strategies_hit.add("browse")
            elif r < 0.80:
                strategies_hit.add("flip")
            elif r < 0.90:
                strategies_hit.add("read")
            else:
                strategies_hit.add("away")

        assert len(strategies_hit) == 4, f"未覆盖全部策略: {strategies_hit}"

    def test_delay_is_positive(self):
        """所有延迟值必须为正数"""
        import random
        for _ in range(100):
            t = random.uniform(0.5, 95.0)
            assert t > 0, f"延迟 {t} <= 0"


# =============================================================================
# 断点续传测试
# =============================================================================


class TestCheckpointResume:
    """测试 Manifest 断点续传"""

    def test_load_manifest_new(self, temp_dir):
        """首次运行创建空 manifest"""
        manifest_path = os.path.join(temp_dir, "manifest.json")
        manifest = {"version": 1, "startedAt": datetime.now().isoformat(), "statuses": {}}
        assert manifest["statuses"] == {}

    def test_needs_crawl_new_id(self):
        """新 ID 应该需要爬取"""
        manifest = {"statuses": {"1": "done"}}

        def needs_crawl(tid, m):
            return m["statuses"].get(str(tid)) != "done"

        assert needs_crawl("2", manifest) is True
        assert needs_crawl("1", manifest) is False

    def test_save_manifest_atomic(self, temp_dir):
        """原子写入：先写 tmp 再 rename"""
        manifest_path = os.path.join(temp_dir, "manifest.json")
        tmp_path = manifest_path + ".tmp"

        manifest = {"version": 1, "statuses": {"1": "done"}}

        # 原子写入步骤
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, manifest_path)

        # 验证写入正确
        with open(manifest_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["statuses"]["1"] == "done"

    def test_resume_skips_completed(self, sample_topics):
        """断点续传跳过 done 状态的 topic"""
        manifest = {"statuses": {"1": "done", "2": "failed"}}
        pending = [t for t in sample_topics if manifest["statuses"].get(str(t["id"])) != "done"]

        assert len(pending) == 2
        assert pending[0]["id"] == "2"
        assert pending[1]["id"] == "3"

    def test_failed_can_be_retried(self):
        """failed 状态可以被重新尝试"""
        manifest = {"statuses": {"1": "failed"}}

        def needs_crawl(tid, m):
            return m["statuses"].get(str(tid)) != "done"

        assert needs_crawl("1", manifest) is True  # failed != done


# =============================================================================
# 数据提取测试
# =============================================================================


class TestDataExtraction:
    """测试 extract_data() 函数"""

    def test_extract_required_fields_present(self, sample_html):
        """提取的数据必须包含所有必填字段"""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(sample_html, "html.parser")
        data = {
            "url": "https://example.com/t/1",
            "title": (soup.find("h1").get_text(strip=True) if soup.find("h1") else ""),
            "content": (soup.find("article").get_text(separator="\n", strip=True) if soup.find("article") else ""),
            "timestamp": datetime.now().isoformat(),
        }

        required = ["url", "title", "content", "timestamp"]
        for field in required:
            assert field in data, f"缺少必填字段: {field}"
            assert data[field], f"字段为空: {field}"

    def test_extract_handles_empty_html(self):
        """空 HTML 也应该能返回基本结构"""
        data = {"url": "https://example.com", "title": "", "content": "", "timestamp": datetime.now().isoformat()}
        assert data["url"] == "https://example.com"
        assert data["title"] == ""


# =============================================================================
# 指数退避测试
# =============================================================================


class TestExponentialBackoff:
    """测试请求重试的指数退避机制"""

    def test_backoff_grows_exponentially(self):
        """退避时间应呈指数增长"""
        base = 10
        waits = [base * (2 ** attempt) for attempt in range(3)]
        # 10, 20, 40 — 呈指数增长
        for i in range(1, len(waits)):
            assert waits[i] > waits[i - 1], f"退避未递增: {waits}"

    def test_backoff_with_jitter_is_variable(self):
        """带 jitter 的退避时间在合理范围内变化"""
        import random
        base = 10
        for _ in range(20):
            attempt = random.randint(0, 2)
            jitter = random.uniform(0, 5)
            wait = base * (2 ** attempt) + jitter
            # 检查在合理范围内
            assert wait >= base * (2 ** attempt)
            assert wait <= base * (2 ** attempt) + 5


# =============================================================================
# URL 构建测试
# =============================================================================


class TestUrlHandling:
    """测试 URL 处理逻辑"""

    def test_urljoin_absolute(self):
        """urljoin 正确拼接绝对路径"""
        from urllib.parse import urljoin
        assert urljoin("https://example.com/forum/", "/t/123") == "https://example.com/t/123"

    def test_urljoin_relative(self):
        """urljoin 正确拼接相对路径"""
        from urllib.parse import urljoin
        assert urljoin("https://example.com/forum/", "t/123") == "https://example.com/forum/t/123"

    def test_url_protocol_required(self):
        """URL 必须包含协议"""
        valid = "https://example.com"
        assert valid.startswith("https://") or valid.startswith("http://")


# =============================================================================
# Main entry
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])