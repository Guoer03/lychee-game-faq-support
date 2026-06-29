#!/usr/bin/env python3
"""只搜索白名单内的荔枝游戏 FAQ、任务书和通信协议资料。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
DOC_ROOT = SKILL_ROOT / "references"
SOURCES = [
    DOC_ROOT / "一骑红尘：荔枝争运战 FAQ.md",
    DOC_ROOT / "一骑红尘：荔枝争运战 参赛选手任务书.md",
    DOC_ROOT / "一骑红尘：荔枝争运战 通信协议.md",
]


class ChineseArgumentParser(argparse.ArgumentParser):
    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "用法:")

    def format_help(self) -> str:
        return super().format_help().replace("usage:", "用法:")


def parse_args() -> argparse.Namespace:
    parser = ChineseArgumentParser(description="搜索荔枝游戏客服白名单资料。", add_help=False)
    parser._positionals.title = "位置参数"
    parser._optionals.title = "选项"
    parser.add_argument("-h", "--help", action="help", help="显示帮助信息并退出。")
    parser.add_argument("terms", nargs="*", help="字面关键词。")
    parser.add_argument(
        "--context",
        type=int,
        default=2,
        help="每个命中点前后输出的上下文行数。",
    )
    parser.add_argument(
        "--list-sources",
        action="store_true",
        help="打印白名单资料文件后退出。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.list_sources:
        for source in SOURCES:
            print(source)
        return 0

    terms = [term.strip() for term in args.terms if term.strip()]
    if not terms:
        print("未提供搜索关键词。", file=sys.stderr)
        return 2

    missing = [source for source in SOURCES if not source.exists()]
    if missing:
        print("缺少资料文件：", file=sys.stderr)
        for source in missing:
            print(source, file=sys.stderr)
        return 2

    lower_terms = [term.casefold() for term in terms]
    hit_count = 0
    printed_blocks: set[tuple[Path, int, int]] = set()
    for source in SOURCES:
        lines = source.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not any(term in line.casefold() for term in lower_terms):
                continue
            start = max(0, index - args.context)
            end = min(len(lines), index + args.context + 1)
            block_key = (source, start, end)
            if block_key in printed_blocks:
                continue
            printed_blocks.add(block_key)
            hit_count += 1
            print(f"\n## {source.name}:{index + 1}")
            for line_number in range(start, end):
                print(f"{line_number + 1}: {lines[line_number]}")

    if hit_count == 0:
        print("白名单资料中没有命中。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
