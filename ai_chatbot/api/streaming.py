# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
Streaming API Module
Real-time token streaming via frappe.publish_realtime (Socket.IO/WebSocket)

The streaming endpoint enqueues the AI response generation as a background
job so the HTTP response returns immediately. Tokens are delivered to the
frontend via frappe.publish_realtime → Redis Pub/Sub → Socket.IO.
"""

import json
import uuid

import frappe

from ai_chatbot.api.history import get_conversation_history as _get_conversation_history
from ai_chatbot.core.audit import log_audit_event
from ai_chatbot.core.logger import log_error, log_info, log_request, timer
from ai_chatbot.core.prompts import build_system_prompt, inject_recall_context, inject_routing_context
from ai_chatbot.core.token_optimizer import optimize_history
from ai_chatbot.core.token_tracker import estimate_cost, track_token_usage
from ai_chatbot.core.ai_utils import safe_json
from ai_chatbot.tools.base import BaseTool, get_tools_for_message
from ai_chatbot.utils.ai_providers import get_ai_provider

# Buffer threshold — batch tokens to reduce Redis Pub/Sub overhead
TOKEN_BUFFER_SIZE = 20  # characters


@frappe.whitelist()
def send_message_streaming(
	conversation_id: str,
	message: str,
	attachments: str | None = None,
	is_retry: bool | str = False,
) -> dict:
	"""Send a message and stream the AI response via frappe.publish_realtime.

	Saves the user message, then enqueues a background job that streams
	tokens via Socket.IO. Returns immediately with the stream_id so the
	frontend can start listening for realtime events.

	Args:
		conversation_id: The conversation document name.
		message: The user's message text.
		attachments: Optional JSON string of file attachment metadata.
		is_retry: If True, skip saving the user message (already persisted)
			and remove any incomplete assistant message from the previous attempt.

	Returns:
		dict with success status and stream_id.
	"""
	try:
		# Normalise is_retry (Frappe may pass "true"/"1" as a string)
		is_retry = is_retry in (True, "true", "True", "1", 1)

		# Validate conversation ownership
		conversation = frappe.get_doc("Chatbot Conversation", conversation_id)
		if conversation.user != frappe.session.user:
			frappe.throw("Unauthorized access to conversation")

		# Generate a unique stream ID for this request
		stream_id = str(uuid.uuid4())[:8]

		if is_retry:
			# Remove any incomplete assistant message from the failed attempt
			incomplete_msgs = frappe.get_all(
				"Chatbot Message",
				filters={
					"conversation": conversation_id,
					"role": "assistant",
					"status": "incomplete",
				},
				pluck="name",
			)
			for msg_name in incomplete_msgs:
				frappe.delete_doc("Chatbot Message", msg_name, force=True)
			if incomplete_msgs:
				frappe.db.commit()
		else:
			# Save user message immediately (before enqueue)
			msg_doc = {
				"doctype": "Chatbot Message",
				"conversation": conversation_id,
				"role": "user",
				"content": message,
				"timestamp": frappe.utils.now(),
			}
			if attachments:
				msg_doc["attachments"] = attachments
			frappe.get_doc(msg_doc).insert()
			frappe.db.commit()

		# Enqueue the streaming job so HTTP response returns immediately.
		# Always use now=False (even in dev mode) to ensure the HTTP response
		# returns before tokens start streaming. With now=True the job runs
		# synchronously, blocking the response and making tokens appear all at once.
		frappe.enqueue(
			"ai_chatbot.api.streaming._run_streaming_job",
			queue="default",
			timeout=300,
			now=False,
			conversation_id=conversation_id,
			stream_id=stream_id,
			ai_provider=conversation.ai_provider,
			user=frappe.session.user,
		)

		return {"success": True, "stream_id": stream_id}

	except Exception as e:
		log_error(f"Streaming error: {e!s}", title="Streaming")
		return {"success": False, "error": str(e)}


def _run_streaming_job(conversation_id: str, stream_id: str, ai_provider: str, user: str):
	"""Background job that performs the actual AI streaming.

	This runs in a background worker (or inline in dev mode via now=True).
	Publishes tokens via frappe.publish_realtime as they arrive.
	"""
	try:
		# Set conversation context for session tools
		frappe.flags.current_conversation_id = conversation_id

		log_info("Streaming job started", conversation_id=conversation_id, provider=ai_provider)

		# Notify frontend: stream started
		_publish(
			"ai_chat_stream_start",
			{
				"conversation_id": conversation_id,
				"stream_id": stream_id,
			},
			user=user,
		)

		_publish_process_step(conversation_id, stream_id, "Preparing context...", user)

		# Get conversation history and provider
		history = _get_conversation_history(conversation_id)

		# Prepend system prompt (pass conversation_id for session context)
		system_prompt = build_system_prompt(conversation_id=conversation_id)
		system_msg = {"role": "system", "content": system_prompt}

		# Attach prompt blocks for Claude prompt caching
		if ai_provider == "Claude":
			from ai_chatbot.core.prompts import build_system_prompt_blocks

			system_msg["_prompt_blocks"] = build_system_prompt_blocks(conversation_id=conversation_id)

		history = [system_msg, *history]

		# Optimize history (trim, summarise, compress, deduplicate)
		history = optimize_history(
			history,
			conversation_id=conversation_id,
			provider_name=ai_provider,
		)

		_publish_process_step(conversation_id, stream_id, "Communicating with LLM...", user)

		provider = get_ai_provider(ai_provider)

		# Route to relevant tool subset (Phase 12A)
		user_msg = next(
			(m.get("content", "") for m in reversed(history) if m.get("role") == "user"),
			"",
		)
		if isinstance(user_msg, list):
			user_msg = " ".join(p.get("text", "") for p in user_msg if p.get("type") == "text")

		tools, routing = get_tools_for_message(user_msg, history)
		log_info(
			"Tool routing (stream)",
			conversation_id=conversation_id,
			categories=",".join(routing.intent.categories),
			tool_count=routing.tool_count,
			is_fallback=routing.is_fallback,
			query_type=routing.intent.query_type,
			is_write=routing.intent.is_write_request,
			is_ambiguous=routing.intent.is_ambiguous,
			complexity=routing.intent.complexity,
		)

		# Phase 14A: Inject routing context hint into system prompt
		inject_routing_context(history[0], routing.routing_hint)

		# Phase 14B.3: Cross-conversation recall
		try:
			from ai_chatbot.core.recall import (
				build_recall_context,
				detect_recall_intent,
				find_relevant_conversations,
			)

			if detect_recall_intent(user_msg):
				matches = find_relevant_conversations(user_msg, conversation_id)
				recall_ctx = build_recall_context(matches)
				if recall_ctx:
					inject_recall_context(history[0], recall_ctx)
					log_info(
						"Cross-conversation recall (stream)",
						conversation_id=conversation_id,
						matches=len(matches),
					)
		except Exception:
			pass  # Non-critical

		# Run the streaming loop
		with timer() as t:
			(
				full_content,
				tool_calls_data,
				tool_results_data,
				tokens_used,
				prompt_tokens,
				completion_tokens,
			) = _stream_with_tools(
				ai_provider=ai_provider,
				provider=provider,
				history=history,
				tools=tools,
				conversation_id=conversation_id,
				stream_id=stream_id,
				user=user,
			)

		log_request(
			provider=ai_provider,
			model=provider.model,
			conversation_id=conversation_id,
			prompt_tokens=prompt_tokens,
			completion_tokens=completion_tokens,
			duration_ms=t.duration_ms,
			stream=True,
		)

		# Phase 13F: Audit the overall LLM streaming request
		log_audit_event(
			"llm_request",
			conversation=conversation_id,
			provider=ai_provider,
			model=provider.model,
			tokens=(prompt_tokens, completion_tokens),
			cost=estimate_cost(provider.model, prompt_tokens, completion_tokens),
			duration_ms=t.duration_ms,
			status="success",
			user=user,
		)

		_publish_process_step(conversation_id, stream_id, "Saving response...", user)

		# Guard: if content is empty, provide a fallback message
		if not full_content.strip():
			if tool_calls_data:
				# Check if any tool returned a confirmation card — if so, the
				# card itself IS the response; a missing text summary is harmless.
				has_confirmation = any(
					isinstance(tr, dict) and tr.get("confirmation_required") for tr in tool_results_data
				)
				if has_confirmation:
					full_content = (
						"A confirmation card has been generated for your review. "
						"Please check the details and click Save Draft or Submit to proceed."
					)
				else:
					log_error(
						f"Empty content after tool execution. Provider={ai_provider}, "
						f"tools={[tc.get('name') for tc in tool_calls_data]}",
						title="Streaming Empty After Tools",
					)
					full_content = (
						"I processed your request and executed the required tools, but was "
						"unable to generate a summary. Please try rephrasing your question."
					)
			else:
				log_error(
					f"Empty stream response. Provider={ai_provider}, model={provider.model}, "
					f"prompt_tokens={prompt_tokens}, completion_tokens={completion_tokens}",
					title="Streaming Empty Response",
				)
				full_content = (
					"I was unable to generate a response. This may be a temporary issue "
					"with the AI provider. Please try again."
				)
			_publish(
				"ai_chat_token",
				{"conversation_id": conversation_id, "stream_id": stream_id, "content": full_content},
				user=user,
			)

		# Save assistant message to database
		frappe.get_doc(
			{
				"doctype": "Chatbot Message",
				"conversation": conversation_id,
				"role": "assistant",
				"content": full_content,
				"timestamp": frappe.utils.now(),
				"tokens_used": tokens_used,
				"tool_calls": safe_json(tool_calls_data) if tool_calls_data else None,
				"tool_results": safe_json(tool_results_data) if tool_results_data else None,
			}
		).insert()

		# Track token usage with real prompt/completion split from the provider
		track_token_usage(
			provider=ai_provider,
			model=provider.model,
			prompt_tokens=prompt_tokens,
			completion_tokens=completion_tokens,
			user=user,
			conversation_id=conversation_id,
		)

		# Update conversation metadata
		conversation = frappe.get_doc("Chatbot Conversation", conversation_id)
		conversation.message_count = frappe.db.count("Chatbot Message", {"conversation": conversation_id})
		conversation.total_tokens += tokens_used
		conversation.updated_at = frappe.utils.now()

		# Auto-generate title from first user message
		if conversation.title == "New Chat" and conversation.message_count == 2:
			first_msg = frappe.get_all(
				"Chatbot Message",
				filters={"conversation": conversation_id, "role": "user"},
				fields=["content"],
				order_by="timestamp asc",
				limit=1,
			)
			if first_msg:
				title = first_msg[0].content[:50].strip()
				if len(first_msg[0].content) > 50:
					title += "..."
				conversation.title = title

		conversation.save(ignore_version=True)
		frappe.db.commit()

		# Notify frontend: stream ended
		_publish(
			"ai_chat_stream_end",
			{
				"conversation_id": conversation_id,
				"stream_id": stream_id,
				"content": full_content,
				"tokens_used": tokens_used,
				"tool_calls": tool_calls_data,
			},
			user=user,
		)

	except Exception as e:
		log_error(f"Streaming job error: {e!s}", title="Streaming")

		# Phase 13F: Audit the error
		error_status = "rate_limited" if "rate" in str(e).lower() and "limit" in str(e).lower() else "error"
		log_audit_event(
			"error",
			conversation=conversation_id,
			provider=ai_provider,
			model=provider.model if provider else None,
			status=error_status,
			error_message=str(e),
			user=user,
		)

		# Phase 13A.3: Save partial response as incomplete message
		# so the user can see what was generated before the error.
		_save_partial_response(conversation_id, e)

		# Publish a user-friendly error message (avoid raw tracebacks)
		friendly = _friendly_error_message(e)
		_publish(
			"ai_chat_error",
			{
				"conversation_id": conversation_id,
				"stream_id": stream_id,
				"error": friendly,
			},
			user=user,
		)


def _save_partial_response(conversation_id: str, error: Exception) -> None:
	"""Save any partial streamed content as an incomplete assistant message.

	Currently a no-op because partial content lives in the background job's
	local variables and is not accessible here.  The frontend error banner
	(``ai_chat_error`` realtime event) is the sole channel for communicating
	errors to the user — saving a placeholder message would result in a
	confusing duplicate display (one message bubble + one error banner).

	If partial-content capture is implemented in the future (e.g. via a
	shared cache key), this function should save the real partial content
	with ``status='incomplete'`` and skip saving when content is empty.
	"""


def _friendly_error_message(error: Exception) -> str:
	"""Convert a raw exception into a user-facing error string.

	Avoids leaking stack traces or internal details to the frontend.
	"""
	# ChatbotError subclasses (e.g. ProviderAPIError) already carry a
	# classified, sanitized message via ``classify_api_error``. Trust them
	# instead of re-running heuristics over their text.
	from ai_chatbot.core.exceptions import ChatbotError

	if isinstance(error, ChatbotError):
		return str(error)

	msg = str(error).lower()

	# Rate limit / throttling (various provider phrasings)
	if ("rate" in msg and "limit" in msg) or "too many requests" in msg or "429" in msg:
		return "The AI provider's rate limit was exceeded. Please wait a moment and try again."
	# Quota / billing / credit exhaustion
	if "quota" in msg or ("exceeded" in msg and ("api" in msg or "credit" in msg or "billing" in msg)):
		return (
			"Your AI API quota has been exceeded. Please check your API plan "
			"and billing details with your AI provider, or try again later."
		)
	if "credit" in msg and ("balance" in msg or "billing" in msg or "purchase" in msg):
		return (
			"Your AI API quota has been exceeded. Please check your API plan "
			"and billing details with your AI provider, or try again later."
		)
	if "timeout" in msg or "timed out" in msg:
		return "The request timed out. Try a simpler question or a shorter conversation."
	if "404" in msg and ("not found" in msg or "client error" in msg):
		return (
			"The AI provider endpoint was not found. Please check the Base URL "
			"and model name in Chatbot Settings."
		)
	if "401" in msg or "auth" in msg or "api key" in msg:
		return "Authentication with the AI provider failed. Please check the API key in Chatbot Settings."
	if "connection" in msg or "connect" in msg:
		return "Unable to connect to the AI provider. Please try again shortly."
	if "context" in msg and "length" in msg:
		return "The conversation is too long for the AI model's context window. Start a new chat or ask a shorter question."

	# Generic fallback — do NOT include the raw error text (it may carry
	# provider URLs or internal paths). The full detail is in the Error Log.
	return "Something went wrong while generating the response. Please try again."


def _stream_with_tools(
	ai_provider, provider, history, tools, conversation_id, stream_id, user, max_tool_rounds=5
):
	"""Stream AI response with tool call support.

	Handles the loop: stream tokens → tool call detected → execute tool →
	add results to history → stream again with tool results.

	Returns:
		tuple of (full_content, tool_calls_data, tool_results_data,
		          tokens_used, prompt_tokens, completion_tokens)
	"""
	# Check if agent orchestration should handle this query
	from ai_chatbot.ai.agents.orchestrator import run_orchestrated_streaming, should_orchestrate

	user_msg = next((m.get("content", "") for m in reversed(history) if m.get("role") == "user"), "")
	if isinstance(user_msg, list):
		user_msg = " ".join(p.get("text", "") for p in user_msg if p.get("type") == "text")

	if should_orchestrate(provider, user_msg, history, tools):
		result = run_orchestrated_streaming(
			ai_provider=ai_provider,
			provider=provider,
			history=history,
			tools=tools,
			conversation_id=conversation_id,
			stream_id=stream_id,
			user=user,
		)
		if result is not None:
			return result
		# Fall through to standard flow if orchestration returned None

	# Phase 13D: Wrap provider with retry/fallback and loop guard
	from ai_chatbot.core.resilience import LLMCallWithRetry, ToolCallLoopGuard
	from ai_chatbot.utils.ai_providers import get_fallback_provider

	fallback = get_fallback_provider(ai_provider)
	retry_wrapper = LLMCallWithRetry(provider, fallback_provider=fallback)
	loop_guard = ToolCallLoopGuard()

	full_content = ""
	all_tool_calls = []
	all_tool_results = []
	total_prompt_tokens = 0
	total_completion_tokens = 0

	for _round in range(max_tool_rounds):
		round_content, round_tool_calls, _needs_followup, round_usage = _stream_single_round(
			retry_wrapper=retry_wrapper,
			history=history,
			tools=tools,
			conversation_id=conversation_id,
			stream_id=stream_id,
			user=user,
		)

		log_info(
			"Streaming round completed",
			conversation_id=conversation_id,
			round=_round,
			provider=ai_provider,
			content_length=len(round_content),
			tool_calls=len(round_tool_calls),
			usage=round_usage,
		)

		# Accumulate real usage data from the provider
		if round_usage:
			total_prompt_tokens += round_usage.get("prompt_tokens", 0)
			total_completion_tokens += round_usage.get("completion_tokens", 0)

		full_content += round_content

		if not round_tool_calls:
			# No tool calls — we're done
			break

		# Execute tool calls and add results to history
		all_tool_calls.extend(round_tool_calls)

		# Add assistant message with tool calls to history. The OpenAI wire
		# format is shared by OpenAI itself, Gemini's compat endpoint, Azure
		# OpenAI, and any Local LLM gateway (Ollama / LM Studio / vLLM /
		# DashScope compatible-mode) — all of which require the
		# {id, type, function:{name, arguments:"<json>"}} envelope on the
		# assistant turn.
		from ai_chatbot.core.ai_utils import is_openai_format

		if is_openai_format(ai_provider):
			openai_tool_calls = []
			for tc in round_tool_calls:
				try:
					args_str = json.dumps(tc["arguments"])
				except TypeError:
					log_error(f"Non-serializable tool args for {tc['name']}: {tc['arguments']!r}",
						title="Streaming Tool Args")
					args_str = safe_json(tc["arguments"])

				openai_tool_calls.append(
					{
						"id": tc["id"],
						"type": "function",
						"function": {
							"name": tc["name"],
							"arguments": args_str,
						},
					}
				)
			history.append(
				{
					"role": "assistant",
					"content": round_content or None,
					"tool_calls": openai_tool_calls,
				}
			)
		else:
			history.append(
				{
					"role": "assistant",
					"content": round_content or None,
					"tool_calls": round_tool_calls,
				}
			)

		# Execute each tool and add results
		for tc in round_tool_calls:
			# Phase 13D: Detect duplicate tool calls
			if loop_guard.is_stuck(tc["name"], tc["arguments"]):
				from ai_chatbot.core.logger import log_warning

				log_warning(
					f"Tool call loop detected: {tc['name']} called "
					f"{loop_guard.MAX_DUPLICATE_CALLS}+ times with same args",
					conversation_id=conversation_id,
				)
				loop_error = {
					"error": True,
					"error_type": "loop_detected",
					"message": f"Tool '{tc['name']}' has failed multiple times with the same arguments. Do not retry.",
					"suggestion": "Stop calling this tool and tell the user what went wrong.",
				}
				all_tool_results.append(loop_error)

				_publish(
					"ai_chat_tool_result",
					{
						"conversation_id": conversation_id,
						"stream_id": stream_id,
						"tool_name": tc["name"],
						"result": loop_error,
					},
					user=user,
				)

				history.append(
					{
						"role": "tool",
						"content": safe_json(loop_error),
						"tool_call_id": tc["id"],
					}
				)
				# Phase 13F: Audit loop-detected error
				log_audit_event(
					"error",
					conversation=conversation_id,
					tool_name=tc["name"],
					tool_args=tc["arguments"],
					status="error",
					error_message=f"Tool call loop detected: {tc['name']}",
					user=user,
				)
				continue

			tool_display = tc["name"].replace("_", " ").title()
			_publish_process_step(conversation_id, stream_id, f"Executing {tool_display}...", user)

			_publish(
				"ai_chat_tool_call",
				{
					"conversation_id": conversation_id,
					"stream_id": stream_id,
					"tool_name": tc["name"],
					"tool_arguments": tc["arguments"],
				},
				user=user,
			)

			try:
				result = BaseTool.execute_tool(tc["name"], tc["arguments"])
			except Exception as e:
				log_error(
					f"Tool execution failed: {tc['name']}: {e!s}",
					title="Streaming Tool Error",
				)
				result = {"error": str(e)}

			loop_guard.record_call(tc["name"], tc["arguments"])
			all_tool_results.append(result)

			_publish(
				"ai_chat_tool_result",
				{
					"conversation_id": conversation_id,
					"stream_id": stream_id,
					"tool_name": tc["name"],
					"result": result,
				},
				user=user,
			)

			history.append(
				{
					"role": "tool",
					"content": safe_json(result),
					"tool_call_id": tc["id"],
				}
			)

			# Check if the tool signaled to stop processing (e.g., file not found)
			if isinstance(result, dict) and result.get("stop_processing"):
				full_content = result.get("error", "An error occurred. Please check and try again.")
				# Publish error as final content
				_publish(
					"ai_chat_token",
					{
						"conversation_id": conversation_id,
						"stream_id": stream_id,
						"token": full_content,
					},
					user=user,
				)
				# Break out of both loops
				break
		else:
			_publish_process_step(conversation_id, stream_id, "Processing results...", user)
			# Continue to next round
			continue
		# Inner for-loop was broken — break the outer round loop too
		break
	else:
		# Max tool rounds reached — log and notify user
		from ai_chatbot.core.logger import log_warning

		log_warning(
			f"Max tool rounds ({max_tool_rounds}) reached",
			conversation_id=conversation_id,
		)
		_publish_process_step(
			conversation_id,
			stream_id,
			"Reached maximum processing rounds. Finalizing response...",
			user,
		)

	# Use real usage data from the provider when available; fall back to estimate
	if total_prompt_tokens or total_completion_tokens:
		tokens_used = total_prompt_tokens + total_completion_tokens
	else:
		tokens_used = _estimate_tokens(full_content, history)
		total_completion_tokens = tokens_used

	return (
		full_content,
		all_tool_calls,
		all_tool_results,
		tokens_used,
		total_prompt_tokens,
		total_completion_tokens,
	)


def _stream_single_round(retry_wrapper, history, tools, conversation_id, stream_id, user):
	"""Stream a single round of AI response.

	Args:
		retry_wrapper: LLMCallWithRetry instance (or provider for backward compat).
		history: Conversation history.
		tools: Tool schemas.
		conversation_id: Conversation ID.
		stream_id: Stream ID.
		user: User for realtime publishing.

	Returns:
		tuple of (content, tool_calls, needs_followup, usage)
		where tool_calls is a list of dicts with id, name, arguments
		and usage is a dict with prompt_tokens and completion_tokens (or None)
	"""
	content = ""
	tool_calls = []
	buffer = ""
	usage = None

	# Phase 13D: Use retry wrapper's call_stream for retry/fallback support.
	# Fall back to direct provider call for backward compatibility.
	from ai_chatbot.core.resilience import LLMCallWithRetry

	if isinstance(retry_wrapper, LLMCallWithRetry):
		stream_iter = retry_wrapper.call_stream(history, tools=tools)
	else:
		stream_iter = retry_wrapper.chat_completion_stream(history, tools=tools)

	for event in stream_iter:
		event_type = event.get("type")

		if event_type == "token":
			token_text = event.get("content", "")
			content += token_text
			buffer += token_text

			# Flush buffer when it reaches threshold
			if len(buffer) >= TOKEN_BUFFER_SIZE:
				_publish(
					"ai_chat_token",
					{
						"conversation_id": conversation_id,
						"stream_id": stream_id,
						"content": buffer,
					},
					user=user,
				)
				buffer = ""

		elif event_type == "usage":
			usage = {
				"prompt_tokens": event.get("prompt_tokens", 0),
				"completion_tokens": event.get("completion_tokens", 0),
			}

		elif event_type == "tool_call":
			tc = event.get("tool_call", {})
			tool_calls.append(
				{
					"id": tc.get("id", f"tool_{len(tool_calls)}"),
					"name": tc.get("name", ""),
					"arguments": tc.get("arguments", {}),
				}
			)

		elif event_type == "finish":
			# Flush remaining buffer
			if buffer:
				_publish(
					"ai_chat_token",
					{
						"conversation_id": conversation_id,
						"stream_id": stream_id,
						"content": buffer,
					},
					user=user,
				)
				buffer = ""

		elif event_type == "error":
			raw_error = event.get("content", "Unknown error")
			# Raise so the caller's except block publishes the error and
			# saves a partial response instead of falling through to the
			# empty-content fallback.
			raise Exception(raw_error)

	# Flush any remaining buffer
	if buffer:
		_publish(
			"ai_chat_token",
			{
				"conversation_id": conversation_id,
				"stream_id": stream_id,
				"content": buffer,
			},
			user=user,
		)

	return content, tool_calls, bool(tool_calls), usage


def _publish(event, message, user=None):
	"""Publish a realtime event to the specified user."""
	frappe.publish_realtime(
		event,
		message=message,
		user=user or frappe.session.user,
	)


def _publish_process_step(conversation_id, stream_id, step, user):
	"""Publish a process step indicator to the frontend."""
	_publish(
		"ai_chat_process_step",
		{
			"conversation_id": conversation_id,
			"stream_id": stream_id,
			"step": step,
		},
		user=user,
	)


def _estimate_tokens(content: str, history: list[dict]) -> int:
	"""Rough token estimation (1 token ~ 4 chars).

	This is an approximation. For accurate counts, the provider response
	would need to include usage data, which streaming doesn't always provide.
	"""
	total_chars = len(content)
	for msg in history:
		total_chars += len(msg.get("content") or "")
	return total_chars // 4
