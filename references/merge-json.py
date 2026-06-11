#!/usr/bin/env python3
"""合并散落的 JSON 文件为统一 projects 数组，供下游评分引擎消费。

用法：
    python merge-json.py --input data/raw/json/ --output merged.json
    python merge-json.py --input data/raw/json/ --output merged.json --pattern "*.json"
    python merge-json.py --input data/raw/json/ --dry-run
    python merge-json.py --input data/raw/json/ --output merged.json --validate
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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
    root = logging.getLogger("merge")
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)


# =============================================================================
# 核心逻辑
# =============================================================================

def collect_json_files(input_dir: str, pattern: str = "*.json") -> List[Path]:
    """收集目录下所有 JSON 文件，排除 manifest.json"""
    input_path = Path(input_dir)
    if not input_path.exists():
        raise FileNotFoundError(f"目录不存在: {input_dir}")

    files = sorted([
        p for p in input_path.glob(pattern)
        if p.name != "manifest.json"
    ])
    return files


def load_json_file(filepath: Path) -> Optional[Dict[str, Any]]:
    """加载单个 JSON 文件，返回解析后的 dict 或 None"""
    logger = logging.getLogger("merge")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.warning("跳过格式错误文件: %s — %s", filepath.name, e)
        return None
    except Exception as e:
        logger.warning("跳过无法读取文件: %s — %s", filepath.name, e)
        return None


def merge_json_files(files: List[Path]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """合并所有 JSON 文件为 projects 数组，按 topicId 去重"""
    logger = logging.getLogger("merge")
    projects: List[Dict[str, Any]] = []
    seen_ids: Dict[str, bool] = {}  # topicId 去重
    stats: Dict[str, int] = {"total": 0, "loaded": 0, "skipped": 0, "duplicates": 0}

    def _add_project(p: Dict[str, Any]) -> None:
        """添加单个 project，按 topicId 去重"""
        tid = str(p.get("topicId", ""))
        if not tid:
            projects.append(p)
            stats["loaded"] += 1
            return
        if tid in seen_ids:
            stats["duplicates"] += 1
            logger.debug("跳过重复 topicId: %s", tid)
            return
        seen_ids[tid] = True
        projects.append(p)
        stats["loaded"] += 1

    for filepath in files:
        stats["total"] += 1
        data = load_json_file(filepath)

        if data is None:
            stats["skipped"] += 1
            continue

        # 如果数据已经是 project 格式（含 topicId），直接添加
        if isinstance(data, dict) and "topicId" in data:
            _add_project(data)
        # 如果数据包含 projects 数组，展开添加
        elif isinstance(data, dict) and "projects" in data:
            for p in data["projects"]:
                if isinstance(p, dict) and "topicId" in p:
                    _add_project(p)
        # 如果是纯数组，逐个添加
        elif isinstance(data, list):
            for p in data:
                if isinstance(p, dict) and "topicId" in p:
                    _add_project(p)
        else:
            logger.warning("跳过未知格式: %s", filepath.name)
            stats["skipped"] += 1

    return projects, stats


def validate_projects(projects: List[Dict[str, Any]]) -> List[str]:
    """验证 projects 数据完整性，返回问题列表"""
    logger = logging.getLogger("merge")
    issues: List[str] = []

    if not projects:
        issues.append("projects 数组为空")
        return issues

    # 检查必填字段
    required_fields = ["topicId", "title", "url"]
    for i, p in enumerate(projects):
        for field in required_fields:
            if field not in p or not p[field]:
                issues.append(f"projects[{i}] 缺少必填字段 '{field}'")

    # 检查 topicId 重复
    id_counts: Dict[str, int] = {}
    for p in projects:
        tid = str(p.get("topicId", ""))
        if tid:
            id_counts[tid] = id_counts.get(tid, 0) + 1
    dupes = {k: v for k, v in id_counts.items() if v > 1}
    if dupes:
        issues.append(f"发现 {len(dupes)} 个重复 topicId，共 {sum(dupes.values()) - len(dupes)} 条冗余")

    # 检查空字段比例
    empty_counts: Dict[str, int] = {}
    for p in projects:
        for k, v in p.items():
            if not v and v != 0:
                empty_counts[k] = empty_counts.get(k, 0) + 1
    for field, count in empty_counts.items():
        ratio = count / len(projects)
        if ratio > 0.5:
            issues.append(f"字段 '{field}' 在 {count}/{len(projects)} ({ratio:.0%}) 条记录中为空")

    logger.info("验证完成：%d 条记录，%d 个问题", len(projects), len(issues))
    return issues


def run(args: argparse.Namespace) -> None:
    """主合并流程"""
    logger = logging.getLogger("merge")

    try:
        # 收集文件
        files = collect_json_files(args.input, args.pattern)
        if not files:
            logger.error("目录 %s 中未找到 JSON 文件", args.input)
            sys.exit(1)

        logger.info("找到 %d 个 JSON 文件", len(files))

        # 合并
        projects, stats = merge_json_files(files)

        logger.info("合并结果: 加载 %d 条, 跳过 %d 文件, 去重 %d 条, 总计 %d 个文件",
                     stats["loaded"], stats["skipped"], stats["duplicates"], stats["total"])

        # 验证（可选）
        if args.validate:
            issues = validate_projects(projects)
            if issues:
                logger.warning("数据验证发现问题：")
                for issue in issues:
                    logger.warning("  - %s", issue)
            else:
                logger.info("数据验证通过，无问题")

        # 构建输出
        output: Dict[str, Any] = {
            "projects": projects,
            "meta": {
                "totalProjects": len(projects),
                "sourceFiles": stats["total"],
                "loadedFiles": stats["total"] - stats["skipped"],
                "duplicatesRemoved": stats["duplicates"],
                "generatedAt": datetime.now().isoformat(),
            }
        }

        if args.dry_run:
            logger.info("[Dry Run] 预览前 3 条:")
            for p in projects[:3]:
                logger.info("  - [%s] %s", p.get("topicId", "?"), p.get("title", "无标题")[:50])
            logger.info("总计 %d 条记录，未写入文件", len(projects))
            return

        # 写入输出
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        logger.info("已写入 %s (%d 条记录)", output_path, len(projects))

    except FileNotFoundError as e:
        logger.error("错误：%s", e)
        sys.exit(1)
    except PermissionError as e:
        logger.error("错误：无法写入输出文件 - %s", e)
        sys.exit(1)
    except Exception as e:
        logger.error("合并过程出错：%s", e)
        sys.exit(1)


def main() -> None:
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="合并散落 JSON 文件为统一 projects 数组",
        epilog="示例: python merge-json.py --input data/raw/json/ --output merged.json"
    )
    parser.add_argument("--input", "-i", required=True, help="JSON 文件所在目录")
    parser.add_argument("--output", "-o", default="merged.json", help="合并输出文件 (默认: merged.json)")
    parser.add_argument("--pattern", default="*.json", help="文件匹配模式 (默认: *.json)")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入文件")
    parser.add_argument("--validate", action="store_true", help="合并后验证数据完整性")
    parser.add_argument("--verbose", action="store_true", help="详细日志输出 (DEBUG 级别)")

    args = parser.parse_args()
    setup_logging(verbose=args.verbose)
    run(args)


if __name__ == "__main__":
    main()