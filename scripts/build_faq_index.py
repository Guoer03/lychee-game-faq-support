#!/usr/bin/env python3
"""构建本地非向量 FAQ 索引。"""

from __future__ import annotations

from pathlib import Path

import faq_rag_bot


if __name__ == "__main__":
    result = faq_rag_bot.save_index(Path(faq_rag_bot.INDEX_PATH))
    print(f"已构建 {result['count']} 个资料块 -> {faq_rag_bot.INDEX_PATH}")
