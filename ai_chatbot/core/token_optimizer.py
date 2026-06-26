# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
Token Optimization Module

Strategies to reduce token usage and stay within context limits:
1. Conversation history trimming — keep only the last N messages
2. Conversation summarisation — summarise dropped messages via cheap LLM
3. Tool result compression — strip metadata, round numbers, remove zeros
4. Progressive compression — older tool results reduced to scalar summaries
5. Result deduplication — identical tool calls reference earlier results
"""

import json

import frappe

# ── Constants ──

# Frappe-internal metadata keys that the AI never needs
_METADATA_KEYS = frozenset(
	{
		"_meta",
		"modified",
		"creation",
		"owner",
		"modified_by",
		"docstatus",
		"doctype",
		"idx",
		"parent",
		"parenttype",
		"parentfield",
		"_user_tags",
		"_comments",
		"_assign",
		"_liked_by",
	}
)

# Top-level tool result keys where a zero value is meaningful
_KEEP_ZERO_KEYS = frozenset(
	{
		"invoice_count",
		"order_count",
		"count",
		"total_count",
		"success",
		"message_count",
		"chunk_count",
	}
)

# Prompt used to summarise dropped conversation messages (Phase 14B enhanced)
_SUMMARISATION_PROMPT = (
	"Summarise the following conversation history. Return a JSON object with exactly "
	"two keys:\n"
	'1. "summary" — a concise paragraph (under 200 words) covering: key topics discussed, '
	"specific data points or numbers mentioned, decisions made, and the user's preferences "
	"or requests.\n"
	'2. "topics" — an array of 1-5 short topic labels (2-4 words each) that describe what '
	'the conversation was about. Example: ["Q3 sales analytics", "North region revenue", '
	'"leave balance"].\n\n'
	"Return ONLY the JSON object, no other text."
)


# ═══════════════════════════════════════════════════════════════════════
# Compression helpers (applied to individual tool results)
# ═══════════════════════════════════════════════════════════════════════


def round_numeric_values(obj, precision: int = 2):
	"""Recursively round all float values in a nested dict/list.

	Args:
		obj: The object to process (dict, list, or scalar).
		precision: Decimal places to round to.

	Returns:
		Processed object with rounded floats.
	"""
	if isinstance(obj, dict):
		return {k: round_numeric_values(v, precision) for k, v in obj.items()}
	if isinstance(obj, list):
		return [round_numeric_values(item, precision) for item in obj]
	if isinstance(obj, float):
		return round(obj, precision)
	return obj


def strip_zero_values(obj, *, _top_level: bool = True):
	"""Remove keys with zero/empty values from nested dicts.

	At the top level, preserves keys in _KEEP_ZERO_KEYS where zero is
	meaningful (e.g. counts). In nested data rows, strips all zeros.

	Args:
		obj: The object to process.
		_top_level: Internal flag — True for the root dict, False for nested.

	Returns:
		Processed object with zero/empty values removed.
	"""
	if isinstance(obj, dict):
		result = {}
		for k, v in obj.items():
			if _top_level and k in _KEEP_ZERO_KEYS:
				result[k] = strip_zero_values(v, _top_level=False)
			elif v in (0, 0.0, None, ""):
				continue
			else:
				result[k] = strip_zero_values(v, _top_level=False)
		return result
	if isinstance(obj, list):
		return [strip_zero_values(item, _top_level=False) for item in obj]
	return obj


def strip_metadata_fields(obj):
	"""Recursively strip Frappe-internal metadata fields from dicts.

	Acts as a safety net — most tool results are already clean, but this
	catches any tool that inadvertently includes raw Frappe document fields.

	Args:
		obj: The object to process.

	Returns:
		Processed object with metadata fields removed.
	"""
	if isinstance(obj, dict):
		return {k: strip_metadata_fields(v) for k, v in obj.items() if k not in _METADATA_KEYS}
	if isinstance(obj, list):
		return [strip_metadata_fields(item) for item in obj]
	return obj


# ═══════════════════════════════════════════════════════════════════════
# Tool result compression (applied to role="tool" messages)
# ═══════════════════════════════════════════════════════════════════════


def compress_tool_result(result: dict, max_rows: int = 20) -> dict:
	"""Compress a tool result dict to reduce token usage.

	- Removes frontend-only rendering data (echart_option, etc.)
	- Strips Frappe metadata fields
	- Truncates large data arrays to max_rows
	- Rounds floats to 2 decimal places
	- Strips zero/empty values

	Args:
		result: Tool result dict (typically from BaseTool.execute_tool).
		max_rows: Maximum rows to keep in data arrays.

	Returns:
		Compressed result dict.
	"""
	if not isinstance(result, dict):
		return result

	compressed = dict(result)

	# Remove frontend-only rendering data — AI doesn't need these
	compressed.pop("echart_option", None)
	compressed.pop("hierarchical_table", None)
	compressed.pop("bi_cards", None)

	# Strip Frappe metadata fields
	compressed = strip_metadata_fields(compressed)

	# Truncate large data arrays
	if isinstance(compressed.get("data"), list) and len(compressed["data"]) > max_rows:
		total = len(compressed["data"])
		compressed["data"] = compressed["data"][:max_rows]
		compressed["_truncated"] = True
		compressed["_total_rows"] = total

	# Round numeric values and strip zeros
	compressed = round_numeric_values(compressed)
	compressed = strip_zero_values(compressed)

	return compressed


def compress_tool_results_in_history(history: list[dict], max_rows: int = 20) -> list[dict]:
	"""Compress tool result messages in conversation history.

	Finds messages with role="tool" and compresses their JSON content.

	Args:
		history: Message list to process.
		max_rows: Maximum data rows per tool result.

	Returns:
		History with compressed tool results.
	"""
	compressed = []
	for msg in history:
		if msg.get("role") == "tool" and msg.get("content"):
			try:
				content = json.loads(msg["content"]) if isinstance(msg["content"], str) else msg["content"]
				if isinstance(content, dict):
					content = compress_tool_result(content, max_rows)
					compressed.append({**msg, "content": json.dumps(content, default=str)})
					continue
			except (json.JSONDecodeError, TypeError):
				pass
		compressed.append(msg)
	return compressed


# ═══════════════════════════════════════════════════════════════════════
# Progressive compression (older tool results → scalar summaries)
# ═══════════════════════════════════════════════════════════════════════


def progressively_compress_history(messages: list[dict]) -> list[dict]:
	"""Apply progressive compression: older tool results get more aggressively compressed.

	Strategy:
	- Last 3 tool results: full detail (already compressed by compress_tool_result)
	- Older tool results: keep only scalar/small fields, strip data arrays entirely

	This ensures the AI has full detail for recent tool calls while retaining
	a lightweight summary of older results for context.

	Args:
		messages: Message list (already compressed by compress_tool_results_in_history).

	Returns:
		Messages with older tool results aggressively compressed.
	"""
	# Find indices of all tool messages
	tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]

	if len(tool_indices) <= 3:
		return messages  # Nothing to compress further

	# Tool messages to aggressively compress (all except the last 3)
	aggressive_indices = set(tool_indices[:-3])

	result = []
	for i, msg in enumerate(messages):
		if i in aggressive_indices:
			try:
				content = json.loads(msg["content"]) if isinstance(msg["content"], str) else msg["content"]
				if isinstance(content, dict):
					# Keep only scalar fields + small structural fields
					summary = {}
					for k, v in content.items():
						if isinstance(v, list):
							summary[f"_{k}_count"] = len(v)
						elif isinstance(v, dict) and k in ("period",):
							summary[k] = v
						elif not isinstance(v, (list, dict)):
							summary[k] = v
					result.append({**msg, "content": json.dumps(summary, default=str)})
					continue
			except (json.JSONDecodeError, TypeError):
				pass
		result.append(msg)
	return result


# ═══════════════════════════════════════════════════════════════════════
# Tool result deduplication
# ═══════════════════════════════════════════════════════════════════════


def _find_tool_call_info(messages: list[dict], tool_call_id: str) -> tuple[str, dict]:
	"""Find the tool name and arguments for a given tool_call_id.

	Searches backward through assistant messages' tool_calls arrays
	to find the matching tool call.

	Returns:
		Tuple of (tool_name, arguments_dict). Returns ("", {}) if not found.
	"""
	for msg in reversed(messages):
		if msg.get("role") == "assistant" and msg.get("tool_calls"):
			for tc in msg["tool_calls"]:
				tc_id = tc.get("id", "")
				if tc_id == tool_call_id:
					func = tc.get("function", tc)
					name = func.get("name", tc.get("name", ""))
					args = func.get("arguments", tc.get("arguments", {}))
					if isinstance(args, str):
						try:
							args = json.loads(args)
						except (json.JSONDecodeError, TypeError):
							args = {}
					return name, args
	return "", {}


def _tool_dedup_key(name: str, args: dict) -> tuple:
	"""Create a hashable deduplication key from tool name and arguments."""
	try:
		# Sort args for consistent hashing
		args_str = json.dumps(args, sort_keys=True)
	except (TypeError, ValueError):
		args_str = str(args)
	return (name, args_str)


def deduplicate_tool_results(messages: list[dict]) -> list[dict]:
	"""Replace duplicate tool result contents with a back-reference.

	Scans for tool calls with identical (name, arguments) pairs. If the same
	tool was called with the same args multiple times, keeps the LAST result
	in full and replaces earlier ones with a short reference.

	Args:
		messages: Message list to process.

	Returns:
		Messages with duplicate tool results replaced by references.
	"""
	# Build map: dedup_key -> list of (message_index, tool_name) pairs
	tool_call_map: dict[tuple, list[tuple[int, str]]] = {}

	for i, msg in enumerate(messages):
		if msg.get("role") == "tool" and msg.get("tool_call_id"):
			name, args = _find_tool_call_info(messages, msg["tool_call_id"])
			if name:
				key = _tool_dedup_key(name, args)
				tool_call_map.setdefault(key, []).append((i, name))

	# For groups with >1 call, replace all but the last with a reference
	deduped = list(messages)
	for _key, entries in tool_call_map.items():
		if len(entries) <= 1:
			continue
		# Keep the last one, replace earlier ones
		for idx, tool_name in entries[:-1]:
			deduped[idx] = {
				**deduped[idx],
				"content": json.dumps({"_ref": f"Same as later {tool_name} result"}),
			}

	return deduped


# ═══════════════════════════════════════════════════════════════════════
# Conversation trimming
# ═══════════════════════════════════════════════════════════════════════


def trim_conversation_history(messages: list[dict], max_messages: int = 20) -> tuple[list[dict], list[dict]]:
	"""Keep system prompt + last N messages. Return dropped messages separately.

	Preserves system messages (always first) and trims older messages
	from the conversation history to reduce token usage.

	Args:
		messages: Full message list (system + user/assistant/tool).
		max_messages: Maximum non-system messages to keep. 0 = unlimited.

	Returns:
		Tuple of (trimmed_messages, dropped_messages).
		dropped_messages is empty if no trimming occurred.
	"""
	if max_messages <= 0:
		return messages, []

	system = [m for m in messages if m.get("role") == "system"]
	history = [m for m in messages if m.get("role") != "system"]

	if len(history) <= max_messages:
		return messages, []

	dropped = history[:-max_messages]
	kept = history[-max_messages:]
	return system + kept, dropped


def get_max_context_messages() -> int:
	"""Get the max_context_messages setting, with fallback to default 20."""
	try:
		settings = frappe.get_single("Chatbot Settings")
		return getattr(settings, "max_context_messages", 20) or 20
	except Exception:
		return 20


# ═══════════════════════════════════════════════════════════════════════
# Conversation summarisation
# ═══════════════════════════════════════════════════════════════════════


def _format_messages_for_summary(messages: list[dict]) -> str:
	"""Format dropped messages into readable text for the summarisation LLM.

	Truncates long content and simplifies tool results to keep the
	summarisation input small.

	Args:
		messages: Messages that were dropped from the context window.

	Returns:
		Formatted text string.
	"""
	parts = []
	for msg in messages:
		role = msg.get("role", "unknown")
		content = msg.get("content", "")

		if role == "tool":
			# Summarise tool results very briefly
			try:
				data = json.loads(content) if isinstance(content, str) else content
				if isinstance(data, dict):
					brief = {k: v for k, v in data.items() if not isinstance(v, (list, dict))}
					content = json.dumps(brief, default=str)[:200]
			except (json.JSONDecodeError, TypeError):
				content = str(content)[:200]
		elif isinstance(content, list):
			# Multimodal content: extract text parts only
			content = " ".join(p.get("text", "") for p in content if p.get("type") == "text")

		parts.append(f"[{role}]: {str(content)[:300]}")

	return "\n".join(parts)


def generate_conversation_summary(
	dropped_messages: list[dict],
	conversation_id: str,
	provider_name: str,
) -> str:
	"""Generate a summary of dropped messages using a cheap/fast model.

	Phase 14B enhanced: the summarisation prompt returns structured JSON with
	both a summary paragraph and topic labels. Topics are cached separately
	for cross-conversation recall (14B.3).

	Checks the cached summary in session_context first. Only re-summarises
	when new messages push beyond the context window again.

	Args:
		dropped_messages: Messages being dropped from the context window.
		conversation_id: For caching the summary in session_context.
		provider_name: The conversation's AI provider (OpenAI/Claude/Gemini).

	Returns:
		Summary string, or empty string on failure.
	"""
	from ai_chatbot.core.session_context import get_session_context, set_session_context
	from ai_chatbot.utils.ai_providers import get_summary_provider

	# Check cache first
	ctx = get_session_context(conversation_id)
	cached_summary = ctx.get("conversation_summary", "")
	cached_msg_count = ctx.get("summary_through_message_count", 0)

	# Count total messages that should be summarised
	current_total = cached_msg_count + len(dropped_messages)

	if cached_summary and cached_msg_count >= current_total:
		# Cached summary is still valid (no new messages to incorporate)
		return cached_summary

	# Build the text to summarise
	text_to_summarise = ""
	if cached_summary:
		text_to_summarise = f"Previous summary: {cached_summary}\n\nNew messages to incorporate:\n"
	text_to_summarise += _format_messages_for_summary(dropped_messages)

	# Call the cheap model
	try:
		provider = get_summary_provider(provider_name)
		messages = [
			{"role": "system", "content": _SUMMARISATION_PROMPT},
			{"role": "user", "content": text_to_summarise},
		]

		response = provider.chat_completion(messages, tools=None, stream=False)

		# Extract text from response (provider-agnostic)
		from ai_chatbot.core.ai_utils import extract_response

		raw_text, _, _, _ = extract_response(provider_name, response)

		# Phase 14B: Parse structured JSON response (summary + topics)
		summary_text, topics = _parse_summary_response(raw_text)

		# Cache in session_context
		set_session_context(conversation_id, "conversation_summary", summary_text)
		set_session_context(conversation_id, "summary_through_message_count", current_total)

		# Phase 14B: Cache topics for cross-conversation recall
		if topics:
			existing_topics = ctx.get("conversation_topics", [])
			# Merge and deduplicate topics (keep latest at front)
			merged = list(dict.fromkeys(topics + existing_topics))[:10]
			set_session_context(conversation_id, "conversation_topics", merged)

			# Also record topics in user preferences for cross-conversation learning
			try:
				from ai_chatbot.core.user_preferences import record_topic

				for topic in topics:
					record_topic(topic)
			except Exception:
				pass  # Non-critical

		return summary_text

	except Exception as e:
		frappe.log_error(f"Summarisation error: {e}", "AI Chatbot")
		return cached_summary or ""


def _parse_summary_response(raw_text: str) -> tuple[str, list[str]]:
	"""Parse the structured JSON response from the summarisation LLM.

	Expected format: {"summary": "...", "topics": ["...", "..."]}
	Falls back to treating the entire response as the summary if JSON
	parsing fails (backward compatible with non-JSON responses).

	Args:
		raw_text: Raw LLM response text.

	Returns:
		Tuple of (summary_text, topics_list).
	"""
	try:
		# Try to parse as JSON first
		parsed = json.loads(raw_text.strip())
		if isinstance(parsed, dict):
			summary = parsed.get("summary", "")
			topics = parsed.get("topics", [])
			if isinstance(summary, str) and summary:
				if isinstance(topics, list):
					topics = [t for t in topics if isinstance(t, str)]
				return summary, topics
	except (json.JSONDecodeError, TypeError):
		pass

	# Fallback: treat entire response as summary, no topics
	return raw_text.strip(), []


# ═══════════════════════════════════════════════════════════════════════
# Main orchestrator
# ═══════════════════════════════════════════════════════════════════════


def optimize_history(
	messages: list[dict],
	conversation_id: str | None = None,
	provider_name: str | None = None,
) -> list[dict]:
	"""Apply all optimization strategies to a message history.

	Pipeline:
	1. Trim to max_context_messages (returns dropped messages)
	2. Summarise dropped messages (if conversation context provided)
	3. Compress tool results (strip frontend data, truncate, round, strip zeros)
	4. Progressive compression (older tool results → scalar summaries)
	5. Deduplicate identical tool calls

	Args:
		messages: Full message list including system prompt.
		conversation_id: Optional conversation ID for summarisation caching.
		provider_name: Optional AI provider name for summarisation model selection.

	Returns:
		Optimized message list.
	"""
	max_msgs = get_max_context_messages()
	optimized, dropped = trim_conversation_history(messages, max_msgs)

	# Generate summary of dropped messages
	if dropped and conversation_id and provider_name:
		summary = generate_conversation_summary(dropped, conversation_id, provider_name)
		if summary:
			# Insert summary as a system-level note after the main system prompt
			summary_msg = {
				"role": "system",
				"content": f"[Conversation summary of earlier messages: {summary}]",
			}
			# Find insertion point: after all existing system messages
			insert_pos = 0
			for i, m in enumerate(optimized):
				if m.get("role") == "system":
					insert_pos = i + 1
				else:
					break
			optimized.insert(insert_pos, summary_msg)

	optimized = compress_tool_results_in_history(optimized)
	optimized = progressively_compress_history(optimized)
	optimized = deduplicate_tool_results(optimized)

	return optimized
