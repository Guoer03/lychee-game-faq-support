#!/usr/bin/env python3
"""荔枝游戏群聊 FAQ 客服的非向量检索与证据门禁。"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
DOC_ROOT = SKILL_ROOT / "references"
INDEX_PATH = SKILL_ROOT / "index" / "faq_chunks.json"
SOURCES = [
    DOC_ROOT / "一骑红尘：荔枝争运战 FAQ.md",
    DOC_ROOT / "一骑红尘：荔枝争运战 参赛选手任务书.md",
    DOC_ROOT / "一骑红尘：荔枝争运战 通信协议.md",
]
FAQ_SOURCE_NAMES = {
    "一骑红尘：荔枝争运战 FAQ.md",
}

NO_REPLY = "不回复"
REPLY_MARKER_RE = re.compile(r"[\[【]\s*(?:已回复|未回复)\s*[\]】]")
ANSWER_STYLE_GUIDE = (
    "回答要求：中文；详略得当；简单问题用 1 句；复杂规则、流程、计分或字段问题可用 2 到 4 句；仍需清晰干练。\n"
    "可以基于材料做归纳总结、合并多条规则并给出直接推论；不要逐字复述材料。\n"
    "直接推论必须能由材料一步推出，不能引入材料外的新设定、常识、经验或猜测。\n"
)

DOMAIN_TERMS = [
    "MOVE",
    "PROCESS",
    "VERIFY_GATE",
    "DELIVER",
    "CLAIM_RESOURCE",
    "USE_RESOURCE",
    "SET_GUARD",
    "BREAK_GUARD",
    "FORCED_PASS",
    "WINDOW_CARD",
    "WAIT",
    "PASS_TOKEN",
    "OFFICIAL_PERMIT",
    "YAN_DIE",
    "inquire",
    "start",
    "action",
    "replay",
    "over",
    "actionResults",
    "targetNodeId",
    "remainRound",
    "remainingRound",
    "matchId",
    "teamId",
    "playerId",
    "resources",
    "buffs",
    "freshness",
    "goodFruit",
    "badFruit",
    "taskScore",
    "游戏机制",
    "通信协议",
    "结算",
    "算分",
    "计分",
    "得分",
    "总分",
    "交付",
    "验核",
    "鲜度",
    "好果",
    "坏果",
    "地图",
    "节点",
    "路线",
    "道路",
    "移动",
    "相邻节点",
    "资源",
    "天气",
    "设卡",
    "攻坚",
    "强制通行",
    "窗口",
    "三拍",
    "回合",
    "Tick",
    "任务",
    "皇榜",
    "过所",
    "官凭",
    "验牒",
]

SYNONYMS = {
    "硬闯": ["FORCED_PASS", "强制通行"],
    "强通": ["FORCED_PASS", "强制通行"],
    "拦路": ["SET_GUARD", "设卡"],
    "卡人": ["SET_GUARD", "设卡"],
    "破卡": ["BREAK_GUARD", "攻坚"],
    "打牌": ["WINDOW_CARD", "窗口"],
    "三回合": ["三拍", "窗口"],
    "荔枝坏了": ["坏果", "badFruit"],
    "坏了": ["坏果", "badFruit"],
    "保鲜": ["鲜度", "ICE_BOX"],
    "冰鉴": ["ICE_BOX", "鲜度"],
    "怎么算分": ["得分", "计分", "总分", "结算"],
    "怎么算": ["得分", "计分", "结算"],
    "最后怎么算分": ["得分", "计分", "总分", "结算"],
    "结算": ["结算", "得分", "总分"],
    "分数": ["得分", "计分", "总分"],
    "终点": ["交付", "DELIVER"],
    "宫门": ["验核", "VERIFY_GATE"],
    "注册": ["register", "ready", "start"],
    "通行文书": ["PASS_TOKEN", "OFFICIAL_PERMIT", "过所", "官凭"],
}

OUT_OF_SCOPE_PATTERNS = [
    "平台",
    "回放很卡",
    "网页",
    "页面",
    "登录",
    "账号",
    "报名",
    "奖金",
    "奖品",
    "证书",
    "群",
    "客服",
    "投诉",
    "编译不过",
    "编译失败",
    "maven",
    "gradle",
    "jar包",
    "什么时候结束",
    "几点结束",
    "赛程",
]

MECHANISM_HINTS = set(DOMAIN_TERMS) | {
    "规则",
    "玩法",
    "怎么结算",
    "怎么算分",
    "怎么得分",
    "最后怎么算分",
    "游戏怎么结算",
    "协议",
    "字段",
    "动作",
    "状态",
    "合法",
}


class ChineseArgumentParser(argparse.ArgumentParser):
    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "用法:")

    def format_help(self) -> str:
        return super().format_help().replace("usage:", "用法:")


@dataclass(frozen=True)
class Chunk:
    id: str
    source: str
    headingPath: list[str]
    lineStart: int
    lineEnd: int
    content: str
    keywords: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "sourceGroup": source_group(self.source, self.headingPath),
            "headingPath": self.headingPath,
            "lineStart": self.lineStart,
            "lineEnd": self.lineEnd,
            "content": self.content,
            "keywords": self.keywords,
        }


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?", text):
        raw = match.group(0)
        tokens.append(raw if raw.isupper() or "_" in raw else raw.casefold())
    for term in DOMAIN_TERMS:
        if term in text:
            tokens.append(term if re.search(r"[A-Z_]", term) else term.casefold())
    for char in re.findall(r"[\u4e00-\u9fff]", text):
        tokens.append(char)
    return tokens


def expand_query(question: str) -> list[str]:
    expanded = [question]
    for phrase, replacements in SYNONYMS.items():
        if phrase in question:
            expanded.extend(replacements)
    for term in DOMAIN_TERMS:
        if term in question:
            expanded.append(term)
    return expanded


def classify_question(question: str) -> tuple[str, str]:
    normalized = question.strip()
    if not normalized:
        return "out_of_scope", "empty"
    if any(pattern in normalized for pattern in OUT_OF_SCOPE_PATTERNS):
        if not any(hint in normalized for hint in MECHANISM_HINTS):
            return "out_of_scope", "out_of_scope"
        if "平台" in normalized or "编译" in normalized or "奖金" in normalized:
            return "out_of_scope", "out_of_scope"
    if any(hint in normalized for hint in MECHANISM_HINTS):
        return "mechanism", "mechanism_hint"
    if re.search(r"[A-Z_]{3,}|[a-z]+[A-Z][A-Za-z]+", normalized):
        return "mechanism", "protocol_like"
    return "out_of_scope", "out_of_scope"


def summarize_question(question: str) -> str:
    text = re.sub(r"@\S+", "", question or "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"[？?！!。,.，、~～]+", " ", text).strip()
    if "过所" in text and "官凭" in text and ("隐藏" in text or "差异" in text):
        return "过所和官凭有没有隐藏效果差异"
    if "最后" in text and ("算分" in text or "得分" in text or "结算" in text):
        return "最后怎么算分"
    if "游戏" in text and "结算" in text:
        return "游戏怎么结算"
    if "怎么算分" in text or "怎么得分" in text:
        return "怎么算分"
    for prefix in ("我想问一下", "请问", "问一下", "想问下", "想问一下"):
        text = text.replace(prefix, "")
    for suffix in ("谢谢", "多谢", "呀", "啊", "呢", "哈"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text.strip() or question.strip()


def source_group(source_name: str, heading_path: list[str] | None = None) -> str:
    if source_name == "一骑红尘：荔枝争运战 FAQ.md":
        return "faq"
    return "reference"


def source_files() -> list[Path]:
    return SOURCES


def build_index() -> dict[str, Any]:
    missing = [str(source) for source in SOURCES if not source.exists()]
    if missing:
        raise FileNotFoundError("Missing source file(s): " + ", ".join(missing))

    chunks: list[Chunk] = []
    for source in SOURCES:
        chunks.extend(_chunks_from_markdown(source))
    return _prepare_index([chunk.as_dict() for chunk in chunks])


def save_index(path: Path = INDEX_PATH) -> dict[str, Any]:
    index = build_index()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "sources": [source.relative_to(SKILL_ROOT).as_posix() for source in SOURCES],
        "chunks": [
            {key: value for key, value in chunk.items() if key not in {"tokens", "tokenCounts"}}
            for chunk in index["chunks"]
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def load_index(path: Path = INDEX_PATH) -> dict[str, Any]:
    if not path.exists():
        return build_index()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _prepare_index(payload["chunks"])


def answer_from_index(
    question: str,
    *,
    index: dict[str, Any] | None = None,
    dry_run: bool = False,
    top_k: int = 5,
) -> dict[str, Any]:
    active_index = index or load_index()
    context = _answer_context(question, active_index, top_k=top_k)
    if not context["gate"]["allowed"]:
        return {
            "answer": NO_REPLY,
            "gate": context["gate"],
            "gateAttempts": context.get("gateAttempts", []),
            "chunks": context["chunks"],
            "prompt": "",
            "normalizedQuestion": context["normalizedQuestion"],
        }

    prompt = build_prompt(context["normalizedQuestion"], context["chunks"])
    if dry_run:
        return {
            "answer": "__DRY_RUN_MINIMAX_PROMPT__",
            "gate": context["gate"],
            "gateAttempts": context["gateAttempts"],
            "chunks": context["chunks"],
            "prompt": prompt,
            "normalizedQuestion": context["normalizedQuestion"],
        }

    answer = call_minimax(prompt)
    if not answer.strip() or _is_no_reply_answer(answer):
        answer = NO_REPLY
    return {
        "answer": answer.strip(),
        "gate": context["gate"],
        "gateAttempts": context["gateAttempts"],
        "chunks": context["chunks"],
        "prompt": prompt,
        "normalizedQuestion": context["normalizedQuestion"],
    }


def answer_chat_payload(
    payload: dict[str, Any],
    *,
    index: dict[str, Any] | None = None,
    dry_run: bool = False,
    top_k: int = 5,
) -> list[str]:
    active_index = index or load_index()
    contexts: list[dict[str, Any]] = []
    for record in _chat_messages(payload)[-30:]:
        content = _message_content(record)
        if not content:
            continue
        if _is_replied_record(record, content):
            continue
        content = _strip_reply_marker(content)
        for question in _candidate_questions(content):
            context = _answer_context(question, active_index, top_k=min(top_k, 3))
            if context["gate"]["allowed"]:
                contexts.append(context)

    if not contexts:
        return []
    if dry_run:
        return [_format_batch_reply(context, "__DRY_RUN_MINIMAX_PROMPT__") for context in contexts]

    answers = _parse_reply_array(call_minimax(build_batch_prompt(contexts)), expected_count=len(contexts))
    replies: list[str] = []
    for context, answer in zip(contexts, answers):
        if answer and not _is_no_reply_answer(answer):
            replies.append(_format_batch_reply(context, answer))
    return replies


def _answer_context(question: str, index: dict[str, Any], *, top_k: int = 5) -> dict[str, Any]:
    normalized_question = summarize_question(question)
    category, reason = classify_question(normalized_question)
    if category != "mechanism":
        return {
            "gate": {"allowed": False, "reason": reason},
            "gateAttempts": [],
            "chunks": [],
            "normalizedQuestion": normalized_question,
        }

    attempts = []
    ranked: list[dict[str, Any]] = []
    gate: dict[str, Any] = {"allowed": False, "reason": "no_retrieval", "sourceGroup": "reference"}
    for group in ("faq", "reference"):
        ranked = retrieve(normalized_question, index, top_k=top_k, source_group_filter=group)
        gate = evidence_gate(normalized_question, ranked)
        gate["sourceGroup"] = group
        attempts.append(gate)
        if gate["allowed"]:
            break
    return {
        "gate": gate,
        "gateAttempts": attempts,
        "chunks": ranked,
        "normalizedQuestion": normalized_question,
    }


def retrieve(question: str, index: dict[str, Any], *, top_k: int = 5,
             source_group_filter: str | None = None) -> list[dict[str, Any]]:
    query_text = "\n".join(expand_query(question))
    query_tokens = tokenize(query_text)
    if not query_tokens:
        return []

    query_counts = Counter(query_tokens)
    scored: list[dict[str, Any]] = []
    for chunk in index["chunks"]:
        if source_group_filter and chunk.get("sourceGroup") != source_group_filter:
            continue
        score = _score_chunk(question, query_counts, chunk, index)
        if score <= 0:
            continue
        item = {key: value for key, value in chunk.items() if key not in {"tokens", "tokenCounts"}}
        item["score"] = round(score, 4)
        item["matchedKeywords"] = _matched_keywords(question, chunk)
        scored.append(item)
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:top_k]


def evidence_gate(question: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    if not chunks:
        return {"allowed": False, "reason": "no_retrieval"}
    top = chunks[0]
    top_score = float(top.get("score", 0))
    matched_keywords = set(top.get("matchedKeywords") or [])
    direct_support = _has_direct_support(question, chunks)
    if top_score < 5.0:
        return {"allowed": False, "reason": "low_score", "topScore": top_score}
    if top_score < 8.0 and not matched_keywords:
        return {"allowed": False, "reason": "weak_keyword_support", "topScore": top_score}
    if not direct_support:
        return {"allowed": False, "reason": "no_direct_support", "topScore": top_score}
    return {"allowed": True, "reason": "supported", "topScore": top_score}


def build_prompt(question: str, chunks: list[dict[str, Any]]) -> str:
    materials = []
    for index, chunk in enumerate(chunks, start=1):
        heading = " / ".join(chunk.get("headingPath") or [])
        materials.append(
            f"[材料{index}]\n"
            f"来源：{chunk['source']}:{chunk['lineStart']}-{chunk['lineEnd']}\n"
            f"标题：{heading}\n"
            f"{chunk['content']}"
        )
    return (
        "你是“一骑红尘：荔枝争运战”的群聊 FAQ 客服。\n"
        "只能根据【参考材料】回答，不能使用常识、推测、旧记忆或外部信息。\n"
        "如果参考材料不足以回答，必须只输出：不回复\n"
        "如果问题不属于游戏机制或通信协议，必须只输出：不回复\n"
        f"{ANSWER_STYLE_GUIDE}"
        "不要解释检索过程；不要引用材料名，除非用户问出处。\n\n"
        "【参考材料】\n"
        + "\n\n".join(materials)
        + "\n\n【用户问题】\n"
        + question
    )


def build_batch_prompt(contexts: list[dict[str, Any]]) -> str:
    cases = []
    for case_index, context in enumerate(contexts, start=1):
        materials = []
        for material_index, chunk in enumerate(context["chunks"], start=1):
            heading = " / ".join(chunk.get("headingPath") or [])
            materials.append(
                f"[材料{case_index}-{material_index}]\n"
                f"来源：{chunk['source']}:{chunk['lineStart']}-{chunk['lineEnd']}\n"
                f"标题：{heading}\n"
                f"{chunk['content']}"
            )
        cases.append(
            f"【问题{case_index}】\n"
            f"{context['normalizedQuestion']}\n\n"
            f"【问题{case_index}参考材料】\n"
            + "\n\n".join(materials)
        )
    return (
        "你是“一骑红尘：荔枝争运战”的群聊 FAQ 客服。\n"
        "下面每个问题都已经通过本地资料门禁；只能根据每个问题自己的参考材料回答。\n"
        "必须只输出 JSON 字符串数组，不要输出 Markdown、解释、对象或额外文字。\n"
        "数组元素只填写答案本身，不要重复问题；程序会自动加上“问题”引用前缀。\n"
        "数组长度必须等于问题数量，顺序必须与问题顺序一致。\n"
        "如果某个问题的材料仍不足以回答，该位置输出空字符串，不要输出“不回复”。\n"
        f"{ANSWER_STYLE_GUIDE}"
        "不要解释检索过程；不要引用材料名，除非用户问出处。\n\n"
        + "\n\n---\n\n".join(cases)
    )


def call_minimax(prompt: str) -> str:
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        raise RuntimeError("除非使用 --dry-run，否则必须配置 MINIMAX_API_KEY。")
    base_url = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io/v1").rstrip("/")
    model = os.environ.get("MINIMAX_MODEL", "MiniMax-M2.7")
    url = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是基于材料做归纳回答的中文 FAQ 客服。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"MiniMax HTTP {exc.code}: {body}") from exc
    choices = data.get("choices") or []
    if not choices:
        return NO_REPLY
    message = choices[0].get("message") or {}
    return str(message.get("content") or "").strip()


def _chunks_from_markdown(source: Path) -> list[Chunk]:
    lines = source.read_text(encoding="utf-8").splitlines()
    chunks: list[Chunk] = []
    heading_stack: list[tuple[int, str]] = []
    block_lines: list[str] = []
    block_start = 1
    block_index = 1

    def flush(end_line: int) -> None:
        nonlocal block_lines, block_start, block_index
        content = "\n".join(block_lines).strip()
        if not content:
            block_lines = []
            return
        heading_path = [heading for _, heading in heading_stack]
        for piece, start, end in _split_large_block(content, block_start, end_line):
            keywords = _extract_keywords(piece, heading_path)
            chunk_id = f"{source.stem}-{block_index:04d}"
            block_index += 1
            chunks.append(
                Chunk(
                    id=chunk_id,
                    source=source.name,
                    headingPath=heading_path,
                    lineStart=start,
                    lineEnd=end,
                    content=piece,
                    keywords=keywords,
                )
            )
        block_lines = []

    for line_number, line in enumerate(lines, start=1):
        heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading_match:
            flush(line_number - 1)
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            block_start = line_number
            block_lines = [line]
            continue
        if not block_lines:
            block_start = line_number
        block_lines.append(line)
    flush(len(lines))
    return chunks


def _split_large_block(content: str, start_line: int, end_line: int) -> list[tuple[str, int, int]]:
    if len(content) <= 1800:
        return [(content, start_line, end_line)]
    lines = content.splitlines()
    pieces: list[tuple[str, int, int]] = []
    current: list[str] = []
    piece_start = start_line
    for offset, line in enumerate(lines):
        current.append(line)
        current_text = "\n".join(current)
        is_table = line.lstrip().startswith("|")
        if len(current_text) >= 1200 and not is_table and not _next_line_is_table(lines, offset):
            piece_end = start_line + offset
            pieces.append((current_text.strip(), piece_start, piece_end))
            current = []
            piece_start = piece_end + 1
    if current:
        pieces.append(("\n".join(current).strip(), piece_start, end_line))
    return pieces


def _next_line_is_table(lines: list[str], offset: int) -> bool:
    if offset + 1 >= len(lines):
        return False
    return lines[offset + 1].lstrip().startswith("|")


def _extract_keywords(content: str, heading_path: list[str]) -> list[str]:
    text = "\n".join(heading_path) + "\n" + content
    keywords = []
    for term in DOMAIN_TERMS:
        if term in text:
            keywords.append(term)
    return sorted(set(keywords))


def _prepare_index(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    prepared = []
    document_frequency: Counter[str] = Counter()
    for chunk in chunks:
        text = "\n".join(chunk.get("headingPath") or []) + "\n" + chunk["content"]
        tokens = tokenize(text)
        token_counts = Counter(tokens)
        chunk = dict(chunk)
        chunk["sourceGroup"] = chunk.get("sourceGroup") or source_group(
            chunk.get("source", ""), chunk.get("headingPath") or []
        )
        chunk["tokens"] = tokens
        chunk["tokenCounts"] = dict(token_counts)
        chunk["length"] = max(1, len(tokens))
        prepared.append(chunk)
        document_frequency.update(set(tokens))
    avg_len = sum(chunk["length"] for chunk in prepared) / max(1, len(prepared))
    return {"chunks": prepared, "df": dict(document_frequency), "avgLen": avg_len, "count": len(prepared)}


def _score_chunk(question: str, query_counts: Counter[str], chunk: dict[str, Any], index: dict[str, Any]) -> float:
    score = 0.0
    token_counts = Counter(chunk["tokenCounts"])
    total_docs = max(1, int(index["count"]))
    avg_len = max(1.0, float(index["avgLen"]))
    chunk_len = max(1.0, float(chunk["length"]))
    k1 = 1.5
    b = 0.75
    for token, query_count in query_counts.items():
        frequency = token_counts.get(token, 0)
        if frequency <= 0:
            continue
        df = int(index["df"].get(token, 0))
        idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
        score += idf * frequency * (k1 + 1) / (frequency + k1 * (1 - b + b * chunk_len / avg_len))
        score += min(query_count, 3) * 0.15
    text = "\n".join(chunk.get("headingPath") or []) + "\n" + chunk["content"]
    for phrase in expand_query(question):
        if len(phrase) >= 2 and phrase in text:
            score += 4.0
    score += len(_matched_keywords(question, chunk)) * 2.5
    return score


def _matched_keywords(question: str, chunk: dict[str, Any]) -> list[str]:
    expanded = set(expand_query(question))
    question_tokens = set(tokenize("\n".join(expanded)))
    matches = []
    for keyword in chunk.get("keywords") or []:
        normalized = keyword if re.search(r"[A-Z_]", keyword) else keyword.casefold()
        if keyword in expanded or normalized in question_tokens or keyword in question:
            matches.append(keyword)
    return sorted(set(matches))


def _has_direct_support(question: str, chunks: list[dict[str, Any]]) -> bool:
    expanded = expand_query(question)
    combined = "\n".join(
        "\n".join(chunk.get("headingPath") or []) + "\n" + chunk.get("content", "")
        for chunk in chunks[:3]
    )
    if _asks_score_overview(question):
        return "最终总分" in combined and (
            "分项" in combined or "公式" in combined or "六类正向得分" in combined
        )
    if any(phrase in combined for phrase in expanded if len(phrase) >= 2):
        return True
    query_tokens = set(tokenize("\n".join(expanded)))
    content_tokens = set(tokenize(combined))
    strong_terms = {token for token in query_tokens if len(token) > 1 or re.search(r"[A-Z_]", token)}
    return len(strong_terms & content_tokens) >= 2


def _asks_score_overview(question: str) -> bool:
    return ("算分" in question or "怎么得分" in question or "得分" in question) and (
        "最后" in question or "总分" in question or "结算" in question
    )


def _chat_messages(payload: dict[str, Any]) -> list[Any]:
    for key in ("messages", "latestMessages", "chatRecords", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _message_content(record: Any) -> str:
    if isinstance(record, str):
        return record.strip()
    if not isinstance(record, dict):
        return ""
    for key in ("content", "text", "message", "body"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _is_replied_record(record: Any, content: str) -> bool:
    if isinstance(record, dict):
        for key in ("replyStatus", "reply_status", "status"):
            value = record.get(key)
            if isinstance(value, str):
                if "已回复" in value:
                    return True
                if "未回复" in value:
                    return False
        for key in ("replied", "isReplied"):
            value = record.get(key)
            if isinstance(value, bool):
                return value
    return bool(re.search(r"[\[【]\s*已回复\s*[\]】]", content))


def _strip_reply_marker(content: str) -> str:
    return REPLY_MARKER_RE.sub("", content).strip()


def _candidate_questions(content: str) -> list[str]:
    pieces = [
        piece.strip()
        for piece in re.split(r"(?<=[？?。！!；;])\s*|\n+", content)
        if piece.strip()
    ]
    return pieces or [content.strip()]


def _is_no_reply_answer(answer: str) -> bool:
    normalized = re.sub(r"[\s\"'`“”‘’\[\]（）()。.!！?？，,、：:；;]+", "", answer)
    return normalized == NO_REPLY


def _format_batch_reply(context: dict[str, Any], answer: str) -> str:
    question = str(context.get("normalizedQuestion") or "").strip()
    question = question.strip("“”\"'`")
    return f"“{question}” ---- {answer.strip()}"


def _parse_reply_array(raw: str, *, expected_count: int) -> list[str]:
    text = (raw or "").strip()
    if not text or _is_no_reply_answer(text):
        return []

    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S | re.I)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    bracketed = re.search(r"\[.*\]", text, flags=re.S)
    if bracketed:
        candidates.append(bracketed.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return _clean_reply_items(parsed)
        if isinstance(parsed, str) and expected_count == 1:
            return _clean_reply_items([parsed])

    if expected_count == 1:
        return _clean_reply_items([text])
    return []


def _clean_reply_items(items: list[Any]) -> list[str]:
    replies: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        answer = item.strip()
        if answer and not _is_no_reply_answer(answer):
            replies.append(answer)
    return replies


def _read_json_payload(path: str) -> dict[str, Any]:
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("群聊输入 JSON 必须是对象。")
    return payload


def parse_args() -> argparse.Namespace:
    parser = ChineseArgumentParser(description="运行荔枝游戏 FAQ 的严格非向量检索和证据门禁。", add_help=False)
    parser._positionals.title = "位置参数"
    parser._optionals.title = "选项"
    parser.add_argument("-h", "--help", action="help", help="显示帮助信息并退出。")
    parser.add_argument("question", nargs="?", help="群聊问题。")
    parser.add_argument("--build-index", action="store_true", help="构建并保存本地 JSON 索引。")
    parser.add_argument("--chat-json", help="读取群聊批量输入 JSON 文件；使用 - 表示从 stdin 读取。")
    parser.add_argument("--index", default=str(INDEX_PATH), help="JSON 索引路径。")
    parser.add_argument("--dry-run", action="store_true", help="不调用 MiniMax，只返回检索资料块和 prompt。")
    parser.add_argument("--json", action="store_true", help="输出结构化 JSON。")
    parser.add_argument("--top-k", type=int, default=5, help="传给模型的资料块数量。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    index_path = Path(args.index)
    if args.build_index:
        index = save_index(index_path)
        print(json.dumps({"chunks": index["count"], "index": str(index_path)}, ensure_ascii=False))
        return 0
    if args.chat_json:
        index = load_index(index_path)
        replies = answer_chat_payload(
            _read_json_payload(args.chat_json),
            index=index,
            dry_run=args.dry_run,
            top_k=args.top_k,
        )
        print(json.dumps(replies, ensure_ascii=False))
        return 0
    if not args.question:
        print("除非使用 --build-index 或 --chat-json，否则必须提供问题。", file=sys.stderr)
        return 2
    index = load_index(index_path)
    result = answer_from_index(args.question, index=index, dry_run=args.dry_run, top_k=args.top_k)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["answer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
