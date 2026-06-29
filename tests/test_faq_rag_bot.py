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

    def test_chat_payload_returns_reply_array_for_supported_messages_only(self) -> None:
        index = faq_rag_bot.build_index()
        payload = {
            "memory": "群里最近在讨论一骑红尘比赛规则。",
            "messages": [
                {"id": "m1", "sender": "A", "content": "平台上游戏回放很卡怎么办？"},
                {"id": "m2", "sender": "B", "content": "过所和官凭有没有隐藏效果差异？"},
                {"id": "m3", "sender": "C", "content": "冠军奖金什么时候发？"},
            ],
        }

        replies = faq_rag_bot.answer_chat_payload(payload, index=index, dry_run=True)

        self.assertEqual(replies, ["“过所和官凭有没有隐藏效果差异” ---- __DRY_RUN_MINIMAX_PROMPT__"])

    def test_chat_payload_only_considers_latest_30_messages(self) -> None:
        index = faq_rag_bot.build_index()
        messages = [{"content": "最后怎么算分？"}]
        messages.extend({"content": f"普通聊天 {i}"} for i in range(30))

        replies = faq_rag_bot.answer_chat_payload({"memory": "", "messages": messages}, index=index, dry_run=True)

        self.assertEqual(replies, [])

    def test_chat_payload_accepts_common_message_record_fields(self) -> None:
        index = faq_rag_bot.build_index()
        payload = {
            "memory": {},
            "messages": [
                "过所和官凭有没有隐藏效果差异？",
                {"text": "最后怎么算分？"},
                {"message": "平台什么时候结束？"},
            ],
        }

        replies = faq_rag_bot.answer_chat_payload(payload, index=index, dry_run=True)

        self.assertEqual(
            replies,
            [
                "“过所和官凭有没有隐藏效果差异” ---- __DRY_RUN_MINIMAX_PROMPT__",
                "“最后怎么算分” ---- __DRY_RUN_MINIMAX_PROMPT__",
            ],
        )

    def test_chat_payload_skips_messages_marked_as_already_replied(self) -> None:
        index = faq_rag_bot.build_index()
        payload = {
            "messages": [
                {"content": "【已回复】最后怎么算分？"},
                {"content": "【未回复】过所和官凭有没有隐藏效果差异？"},
            ],
        }

        replies = faq_rag_bot.answer_chat_payload(payload, index=index, dry_run=True)

        self.assertEqual(
            replies,
            ["“过所和官凭有没有隐藏效果差异” ---- __DRY_RUN_MINIMAX_PROMPT__"],
        )

    def test_chat_payload_uses_structured_reply_status_fields(self) -> None:
        index = faq_rag_bot.build_index()
        payload = {
            "messages": [
                {"replyStatus": "已回复", "content": "最后怎么算分？"},
                {"status": "未回复", "content": "MOVE 动作怎么发？"},
            ],
        }

        replies = faq_rag_bot.answer_chat_payload(payload, index=index, dry_run=True)

        self.assertEqual(replies, ["“MOVE 动作怎么发” ---- __DRY_RUN_MINIMAX_PROMPT__"])

    def test_chat_payload_splits_consecutive_questions_and_skips_unsupported_parts(self) -> None:
        index = faq_rag_bot.build_index()
        payload = {
            "memory": "用户连续问了两个问题。",
            "messages": [
                {"content": "平台上游戏回放很卡怎么办？MOVE 动作怎么发？"},
            ],
        }

        replies = faq_rag_bot.answer_chat_payload(payload, index=index, dry_run=True)

        self.assertEqual(replies, ["“MOVE 动作怎么发” ---- __DRY_RUN_MINIMAX_PROMPT__"])

    def test_no_reply_variants_are_never_included_in_batch_output(self) -> None:
        original_call_minimax = faq_rag_bot.call_minimax
        try:
            faq_rag_bot.call_minimax = lambda prompt: " “不回复”。 "

            replies = faq_rag_bot.answer_chat_payload(
                {"messages": [{"content": "最后怎么算分？"}]},
                index=faq_rag_bot.build_index(),
            )

            self.assertEqual(replies, [])
        finally:
            faq_rag_bot.call_minimax = original_call_minimax

    def test_prompt_requires_answer_length_to_match_question_complexity(self) -> None:
        prompt = faq_rag_bot.build_prompt("最后怎么算分？", [])

        self.assertIn("详略得当", prompt)
        self.assertIn("简单问题", prompt)
        self.assertIn("复杂规则", prompt)
        self.assertIn("清晰干练", prompt)
        self.assertNotIn("简洁干练", prompt)

    def test_batch_generation_calls_minimax_once_for_multiple_supported_replies(self) -> None:
        calls = []
        original_call_minimax = faq_rag_bot.call_minimax
        try:
            def fake_call_minimax(prompt: str) -> str:
                calls.append(prompt)
                return '["过所和官凭没有隐藏效果差异。", "MOVE 动作需要提交目标节点。"]'

            faq_rag_bot.call_minimax = fake_call_minimax
            replies = faq_rag_bot.answer_chat_payload(
                {
                    "messages": [
                        {"content": "过所和官凭有没有隐藏效果差异？"},
                        {"content": "MOVE 动作怎么发？"},
                    ]
                },
                index=faq_rag_bot.build_index(),
            )

            self.assertEqual(len(calls), 1)
            self.assertEqual(
                replies,
                [
                    "“过所和官凭有没有隐藏效果差异” ---- 过所和官凭没有隐藏效果差异。",
                    "“MOVE 动作怎么发” ---- MOVE 动作需要提交目标节点。",
                ],
            )
            self.assertIn("JSON 字符串数组", calls[0])
        finally:
            faq_rag_bot.call_minimax = original_call_minimax

    def test_batch_replies_quote_the_normalized_user_question(self) -> None:
        original_call_minimax = faq_rag_bot.call_minimax
        try:
            faq_rag_bot.call_minimax = lambda prompt: '["按最终总分结算。"]'

            replies = faq_rag_bot.answer_chat_payload(
                {"messages": [{"content": "@客服 我想问一下，最后到底怎么算分呀？谢谢"}]},
                index=faq_rag_bot.build_index(),
            )

            self.assertEqual(replies, ["“最后怎么算分” ---- 按最终总分结算。"])
        finally:
            faq_rag_bot.call_minimax = original_call_minimax

    def test_batch_generation_skips_minimax_when_no_message_is_supported(self) -> None:
        original_call_minimax = faq_rag_bot.call_minimax
        try:
            faq_rag_bot.call_minimax = lambda prompt: self.fail("不应调用 MiniMax")

            replies = faq_rag_bot.answer_chat_payload(
                {"messages": [{"content": "平台上游戏回放很卡怎么办？"}]},
                index=faq_rag_bot.build_index(),
            )

            self.assertEqual(replies, [])
        finally:
            faq_rag_bot.call_minimax = original_call_minimax


if __name__ == "__main__":
    unittest.main()
