"""Stealth Scraper 测试配置 — conftest.py"""

import pytest


def pytest_configure(config):
    """注册自定义标记"""
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')")
    config.addinivalue_line("markers", "network: marks tests that require network access")