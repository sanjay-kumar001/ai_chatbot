# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
Conversation History Reconstruction

Loads stored Chatbot Message records and rebuilds an LLM-ready history list,
including multimodal attachments and tool call/result exchanges.
"""

import json

import frappe


def _normalize_tool_call(tc: dict) -> dict:
	"""Normalize a stored tool call to OpenAI format.

	Handles three stored formats:
	- Streaming normalized: {id, name, arguments} (arguments is dict)
	- Non-streaming OpenAI: {id, type, function: {name, arguments}} (arguments is JSON string)
	- Non-streaming Claude: {type: "tool_use", id, name, input}
	"""
	if "function" in tc:
		# Already OpenAI format
		return tc
	name = tc.get("name", "")
	args = tc.get("arguments") or tc.get("input") or {}
	if isinstance(args, str):
		args = json.loads(args)
	return {
		"id": tc.get("id", ""),
		"type": "function",
		"function": {
			"name": name,
			"arguments": json.dumps(args, default=str) if isinstance(args, dict) else args,
		},
	}


def get_conversation_history(conversation_id: str) -> list[dict]:
	"""Get conversation history in AI message format.

	For messages with image attachments, builds multimodal content arrays
	using the OpenAI Vision format (converted to Claude format by the provider).

	For assistant messages with tool_calls, reconstructs the full tool call/result
	exchange so the LLM sees the correct conversation structure on subsequent turns.

	File Alias System:
		Attachments are assigned short aliases (file_1, file_2, ...) so the LLM
		passes a simple, unforgeable identifier to IDP tools instead of a full
		file path. The alias→URL mapping is stored in frappe.flags.file_alias_registry
		for resolution by tool functions.
	"""
	messages = frappe.get_all(
		"Chatbot Message",
		filters={"conversation": conversation_id},
		fields=["role", "content", "tool_calls", "tool_results", "attachments"],
		order_by="timestamp asc",
	)

	# Build file alias registry: short id → real file_url
	file_alias_registry = {}
	alias_counter = 0

	history = []
	for msg in messages:
		# Check if user message has attachments — build appropriate content
		if msg.role == "user" and msg.attachments:
			try:
				atts = json.loads(msg.attachments) if isinstance(msg.attachments, str) else msg.attachments
			except (json.JSONDecodeError, TypeError):
				atts = None

			if atts:
				# Assign aliases to all attachments in this message
				for att in atts:
					file_url = att.get("file_url", "")
					if file_url and file_url not in file_alias_registry.values():
						alias_counter += 1
						att["_file_id"] = f"file_{alias_counter}"
						file_alias_registry[f"file_{alias_counter}"] = file_url
					elif file_url:
						# Re-use existing alias for the same URL
						for alias, url in file_alias_registry.items():
							if url == file_url:
								att["_file_id"] = alias
								break

				has_images = any(a.get("is_image") for a in atts)
				if has_images:
					# Image attachments: use multimodal Vision content
					from ai_chatbot.api.files import build_vision_content

					content = build_vision_content(msg.content or "", atts)
					history.append({"role": msg.role, "content": content})
				else:
					# Non-image attachments (PDF, Excel, etc.): append file refs
					# with short alias IDs instead of full file_url paths
					text = msg.content or ""
					for att in atts:
						file_url = att.get("file_url", "")
						file_name = att.get("file_name", "unknown")
						file_id = att.get("_file_id", "")
						mime_type = att.get("mime_type", "")
						text += f"\n[Attached file: {file_name} ({mime_type}), file_id: {file_id}]"
						# Inline raw text extraction so LLM sees actual content
						inline_text = _extract_inline_text(file_url, mime_type)
						if inline_text:
							text += (
								f"\n\n--- Document Content ({file_name}) ---\n"
								f"{inline_text}\n"
								f"--- End Document Content ---"
							)
					history.append({"role": msg.role, "content": text})
				continue

		# Reconstruct tool call/result exchange for assistant messages
		if msg.role == "assistant" and msg.tool_calls:
			try:
				raw_tcs = json.loads(msg.tool_calls) if isinstance(msg.tool_calls, str) else msg.tool_calls
			except (json.JSONDecodeError, TypeError):
				raw_tcs = None

			if raw_tcs:
				openai_tcs = [_normalize_tool_call(tc) for tc in raw_tcs]
				history.append(
					{
						"role": "assistant",
						"content": msg.content or None,
						"tool_calls": openai_tcs,
					}
				)

				# Inject tool result messages
				try:
					raw_results = (
						json.loads(msg.tool_results)
						if isinstance(msg.tool_results, str)
						else msg.tool_results
					) or []
				except (json.JSONDecodeError, TypeError):
					raw_results = []

				for i, tc in enumerate(openai_tcs):
					result_content = json.dumps(raw_results[i], default=str) if i < len(raw_results) else "{}"
					history.append(
						{
							"role": "tool",
							"content": result_content,
							"tool_call_id": tc["id"],
						}
					)
				continue

		message_dict = {"role": msg.role, "content": msg.content}
		history.append(message_dict)

	# Store file alias registry so IDP tools can resolve file_id → file_url
	frappe.flags.file_alias_registry = file_alias_registry

	return history


# Maximum characters of inline document text to include in the message.
# Keeps context window usage reasonable for large documents.
_MAX_INLINE_TEXT_CHARS = 15000


def _extract_inline_text(file_url: str, mime_type: str) -> str:
	"""Extract raw text from a file attachment for inline inclusion.

	Reads the file and extracts selectable text using the IDP extractors.
	Returns empty string on any failure (non-critical — the LLM can still
	use the file_url with IDP tools as a fallback).

	Args:
		file_url: Frappe file URL (e.g., "/private/files/invoice.pdf").
		mime_type: MIME type of the file.

	Returns:
		Extracted text (truncated to _MAX_INLINE_TEXT_CHARS), or empty string.
	"""
	try:
		from ai_chatbot.idp.extractors.base import extract_content

		result = extract_content(file_url)
		if result.get("content_type") == "text" and result.get("text"):
			text = result["text"].strip()
			if len(text) > _MAX_INLINE_TEXT_CHARS:
				text = text[:_MAX_INLINE_TEXT_CHARS] + "\n\n[... truncated ...]"
			return text
	except Exception:
		pass
	return ""
