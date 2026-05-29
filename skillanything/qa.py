"""Knowledge-base Q&A over collected profile evidence."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from skillanything.config import Settings
from skillanything.storage.repository import Repository
from skillanything.utils import truncate


class KnowledgeQA:
    def __init__(self, settings: Settings, repo: Repository) -> None:
        self.settings = settings
        self.repo = repo

    def ask(self, profile_id: str, question: str, limit: int = 8) -> dict[str, Any]:
        if self.repo.count_search_documents(profile_id) == 0:
            self.repo.rebuild_search_index(profile_id)
        docs = self.repo.search_documents(profile_id, question, limit=limit)
        if not docs:
            return {
                "answer": (
                    "知识库里没有检索到足够相关的证据。"
                    "请换一个更具体的问题，或先完成蒸馏/索引。"
                ),
                "sources": [],
                "model": "local",
            }
        if self.settings.llm_api_key and self.settings.llm_base_url:
            try:
                return self._ask_with_compatible_chat(question, docs)
            except Exception as exc:
                fallback = self._local_answer(question, docs)
                fallback["model_error"] = f"{type(exc).__name__}: {exc}"
                return fallback
        return self._local_answer(question, docs)

    def _ask_with_compatible_chat(
        self,
        question: str,
        docs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        model = self.settings.llm_model or self.settings.model or "qwen3-vl-plus"
        evidence = _evidence_block(docs)
        prompt = (
            "你是 SkillAnything 的知识库问答模块。只能基于给定证据回答，"
            "不要冒充原作者，不要编造未出现的私密观点、仓位或身份。"
            "如果证据不足，明确说明不足，并给出还需要哪些资料。\n\n"
            f"用户问题：{question}\n\n"
            f"证据：\n{evidence}\n\n"
            "请用中文回答，结构为：结论、依据、引用。"
        )
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }
        data = _post_json(
            f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
            payload,
            self.settings.llm_api_key or "",
        )
        return {
            "answer": _chat_text(data),
            "sources": _sources(docs),
            "model": model,
        }

    @staticmethod
    def _local_answer(question: str, docs: list[dict[str, Any]]) -> dict[str, Any]:
        lines = [
            f"问题：{question}",
            "",
            "当前未配置可用 LLM，以下是按知识库检索到的证据摘要：",
        ]
        for index, doc in enumerate(docs[:5], 1):
            lines.append(
                f"{index}. {doc.get('title') or doc.get('kind')}："
                f"{truncate(str(doc.get('body') or ''), 260)}"
            )
        return {
            "answer": "\n".join(lines),
            "sources": _sources(docs),
            "model": "local",
        }


def _evidence_block(docs: list[dict[str, Any]]) -> str:
    blocks = []
    for index, doc in enumerate(docs, 1):
        blocks.append(
            "\n".join(
                [
                    f"[{index}] kind={doc.get('kind')}",
                    f"title={doc.get('title')}",
                    f"url={doc.get('source_url')}",
                    f"text={truncate(str(doc.get('body') or ''), 1200)}",
                ]
            )
        )
    return "\n\n".join(blocks)


def _sources(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": doc.get("id"),
            "item_id": doc.get("item_id"),
            "kind": doc.get("kind"),
            "title": doc.get("title"),
            "url": doc.get("source_url"),
            "snippet": truncate(str(doc.get("body") or ""), 240),
        }
        for doc in docs
    ]


def _post_json(url: str, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _chat_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(str(part.get("text", part)) for part in content)
    return json.dumps(data, ensure_ascii=False)
