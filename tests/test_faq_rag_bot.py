from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import faq_rag_bot
import search_sources


class FaqRagBotTest(unittest.TestCase):
    def test_mechanism_question_retrieves_supported_chunks(self) -> None:
        index = faq_rag_bot.build_index()

        result = faq_rag_bot.answer_from_index("最后怎么算分？", index=index, dry_run=True)

        self.assertNotEqual(result["answer"], "不回复")
        self.assertTrue(result["gate"]["allowed"])
        self.assertTrue(result["chunks"])
        self.assertTrue(any("得分" in chunk["content"] or "计分" in chunk["content"] for chunk in result["chunks"]))

    def test_platform_issue_does_not_reply(self) -> None:
        index = faq_rag_bot.build_index()

        result = faq_rag_bot.answer_from_index("平台上游戏回放很卡怎么办？", index=index, dry_run=True)

        self.assertEqual(result["answer"], "不回复")
        self.assertEqual(result["gate"]["reason"], "out_of_scope")

    def test_unknown_supported_by_no_material_does_not_reply(self) -> None:
        index = faq_rag_bot.build_index()

        result = faq_rag_bot.answer_from_index("冠军奖金什么时候发？", index=index, dry_run=True)

        self.assertEqual(result["answer"], "不回复")
        self.assertFalse(result["gate"]["allowed"])

    def test_faq_sources_are_searched_before_task_book_and_protocol(self) -> None:
        index = faq_rag_bot.build_index()

        result = faq_rag_bot.answer_from_index("过所和官凭有没有隐藏效果差异？", index=index, dry_run=True)

        self.assertTrue(result["gate"]["allowed"])
        self.assertEqual(result["gate"]["sourceGroup"], "faq")
        self.assertTrue(result["chunks"])
        self.assertTrue(all(chunk["sourceGroup"] == "faq" for chunk in result["chunks"]))

    def test_falls_back_to_reference_sources_when_faq_has_no_support(self) -> None:
        index = faq_rag_bot.build_index()

        result = faq_rag_bot.answer_from_index("最后怎么算分？", index=index, dry_run=True)

        self.assertTrue(result["gate"]["allowed"])
        self.assertEqual(result["gate"]["sourceGroup"], "reference")
        self.assertTrue(result["chunks"])
        self.assertTrue(any(chunk["sourceGroup"] == "reference" for chunk in result["chunks"]))

    def test_question_is_summarized_before_retrieval(self) -> None:
        index = faq_rag_bot.build_index()

        result = faq_rag_bot.answer_from_index("@客服 我想问一下，最后到底怎么算分呀？谢谢", index=index, dry_run=True)

        self.assertEqual(result["normalizedQuestion"], "最后怎么算分")
        self.assertTrue(result["gate"]["allowed"])

    def test_scripts_only_read_bundled_references(self) -> None:
        reference_root = SKILL_ROOT / "references"

        self.assertEqual(faq_rag_bot.DOC_ROOT, reference_root)
        self.assertEqual(search_sources.DOC_ROOT, reference_root)
        self.assertTrue(all(source.parent == reference_root for source in faq_rag_bot.SOURCES))
        self.assertTrue(all(source.parent == reference_root for source in search_sources.SOURCES))

    def test_only_required_reference_documents_are_loaded(self) -> None:
        expected_source_names = {
            "一骑红尘：荔枝争运战 FAQ.md",
            "一骑红尘：荔枝争运战 参赛选手任务书.md",
            "一骑红尘：荔枝争运战 通信协议.md",
        }

        self.assertEqual({source.name for source in faq_rag_bot.SOURCES}, expected_source_names)
        self.assertEqual({source.name for source in search_sources.SOURCES}, expected_source_names)

    def test_saved_index_uses_portable_reference_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "faq_chunks.json"

            faq_rag_bot.save_index(index_path)
            payload = json.loads(index_path.read_text(encoding="utf-8"))

        self.assertEqual(
            payload["sources"],
            [
                "references/一骑红尘：荔枝争运战 FAQ.md",
                "references/一骑红尘：荔枝争运战 参赛选手任务书.md",
                "references/一骑红尘：荔枝争运战 通信协议.md",
            ],
        )


if __name__ == "__main__":
    unittest.main()
