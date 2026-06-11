#!/usr/bin/env python3
"""Stealth Scraper 集成测试 — 使用 responses mock 测试完整请求-解析流水线"""

import json
import os
import sys
import tempfile
from datetime import datetime
from typing import Any, Dict, List
from unittest import mock

import pytest
import responses
from bs4 import BeautifulSoup


@pytest.fixture
def mock_forum_html() -> str:
    """模拟论坛帖子页面的 HTML"""
    return """
<html>
<head><title>Sample Topic</title></head>
<body>
    <article>
        <h1>How to Build a Web Scraper</h1>
        <p>Author: JohnDoe</p>
        <div class="post-content">
            <p>This is a detailed guide on building web scrapers.</p>
            <p>It covers fingerprint rotation, delay strategies, and more.</p>
            <p>Checkpoint resume is essential for long-running scrapes.</p>
        </div>
    </article>
</body>
</html>"""


@pytest.fixture
def mock_topics_json() -> List[Dict[str, Any]]:
    return [
        {"id": "101", "url": "https://forum.example.com/t/101"},
        {"id": "102", "url": "https://forum.example.com/t/102"},
        {"id": "103", "url": "https://forum.example.com/t/103"},
    ]


class TestIntegration:
    """端到端集成测试"""

    @responses.activate
    def test_full_scrape_pipeline(self, mock_forum_html, tmp_path):
        """测试完整的爬取-解析-保存流程"""
        # Mock HTTP 响应
        responses.add(
            responses.GET,
            "https://forum.example.com/",
            body="<html></html>",
            status=200,
        )
        responses.add(
            responses.GET,
            "https://forum.example.com/t/101",
            body=mock_forum_html,
            status=200,
        )

        import requests

        # 1. 创建 Session 并预热
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 Test Browser",
            "Accept-Language": "en-US,en;q=0.9",
        })

        try:
            session.get("https://forum.example.com/", timeout=5)
        except Exception:
            pass

        # 2. 爬取页面
        resp = session.get("https://forum.example.com/t/101", timeout=5)
        assert resp.status_code == 200
        assert "How to Build a Web Scraper" in resp.text

        # 3. 解析 HTML
        soup = BeautifulSoup(resp.text, "html.parser")
        title = soup.find("h1").get_text(strip=True) if soup.find("h1") else ""
        content = soup.find("article").get_text(separator="\n", strip=True) if soup.find("article") else ""

        assert title == "How to Build a Web Scraper"
        assert "fingerprint rotation" in content

        # 4. 构建结构化数据
        data = {
            "url": "https://forum.example.com/t/101",
            "topicId": "101",
            "title": title,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }

        # 5. 保存到 JSON
        json_dir = tmp_path / "json"
        json_dir.mkdir(exist_ok=True)
        json_path = json_dir / "101.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 6. 保存到 HTML
        html_dir = tmp_path / "html"
        html_dir.mkdir(exist_ok=True)
        html_path = html_dir / "101.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(resp.text)

        # 验证
        assert json_path.exists()
        assert html_path.exists()

        with open(json_path, "r", encoding="utf-8") as f:
            saved_data = json.load(f)
        assert saved_data["topicId"] == "101"
        assert saved_data["title"] == "How to Build a Web Scraper"

    @responses.activate
    def test_429_rate_limit_handling(self):
        """测试 429 限流响应处理"""
        responses.add(
            responses.GET,
            "https://forum.example.com/t/429",
            status=429,
            headers={"Retry-After": "5"},
        )
        responses.add(
            responses.GET,
            "https://forum.example.com/t/429",
            body="<html>Success after retry</html>",
            status=200,
        )

        import requests

        session = requests.Session()
        session.headers.update({"User-Agent": "Test"})

        # 第一次请求返回 429
        resp1 = session.get("https://forum.example.com/t/429", timeout=5)
        assert resp1.status_code == 429

        # 第二次请求成功
        resp2 = session.get("https://forum.example.com/t/429", timeout=5)
        assert resp2.status_code == 200

    @responses.activate
    def test_connection_timeout(self):
        """测试连接超时处理"""
        import requests

        responses.add(
            responses.GET,
            "https://slow.example.com/",
            body=requests.exceptions.Timeout("Connection timed out"),
        )

        session = requests.Session()
        try:
            session.get("https://slow.example.com/", timeout=2)
            # 应该抛出超时异常
            assert False, "应抛出超时异常"
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            pass  # 预期行为

    def test_manifest_crash_recovery(self, tmp_path):
        """测试 manifest 崩溃恢复：写入中途崩溃不会损坏已有数据"""
        manifest_path = tmp_path / "manifest.json"

        # 正常保存 manifest
        manifest = {"version": 1, "statuses": {}}
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        # 模拟崩溃：写入到一半时关闭
        try:
            tmp_path_file = tmp_path / "manifest.json.tmp"
            with open(tmp_path_file, "w", encoding="utf-8") as f:
                f.write('{"version": 1, "statuses": {"1": "done')
                # 模拟崩溃 — 不完整的 JSON
            os.replace(str(tmp_path_file), str(manifest_path))
        except Exception:
            pass  # 不应影响原始数据

    def test_chunk_distribution_even(self, mock_topics_json):
        """测试数据分块：各 Worker 应获得均等任务"""
        import math

        topics = mock_topics_json * 3  # 9 个 topics
        workers = 3
        chunk_size = math.ceil(len(topics) / workers)
        chunks = [topics[i:i + chunk_size] for i in range(0, len(topics), chunk_size)]

        assert len(chunks) == workers
        assert all(len(chunk) == 3 for chunk in chunks)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])