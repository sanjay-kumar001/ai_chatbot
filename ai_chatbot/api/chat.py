# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
Chat API Module
RESTful API endpoints for AI chatbot
"""

import json

import frappe

from ai_chatbot.api.history import get_conversation_history
from ai_chatbot.core.ai_utils import extract_response, extract_tool_info, safe_json
from ai_chatbot.core.audit import log_audit_event
from ai_chatbot.core.exceptions import ChatbotError
from ai_chatbot.core.logger import log_error, log_info, log_warning
from ai_chatbot.core.prompts import build_system_prompt, inject_recall_context, inject_routing_context
from ai_chatbot.core.token_optimizer import optimize_history
from ai_chatbot.core.token_tracker import estimate_cost, track_token_usage
from ai_chatbot.tools.base import BaseTool, get_tools_for_message
from ai_chatbot.utils.ai_providers import get_ai_provider

# Generic fallback shown to the user when an unexpected exception escapes the
# chat pipeline. The full traceback is captured in the Frappe Error Log via
# ``log_error``, so users see a clean message instead of an internal stack/URL.
_FALLBACK_USER_ERROR = (
	"Something went wrong while processing your message. "
	"An administrator has been notified — please check the Error Log for details."
)


def _user_facing_error(error: Exception) -> str:
	"""Return a message safe to surface in the chat UI.

	``ChatbotError`` subclasses already carry classified, friendly messages
	(see ``ai_providers.classify_api_error``). Everything else collapses to
	a generic notice — the original exception is logged separately, so no
	information is lost; it just doesn't get rendered to the end user.
	"""
	if isinstance(error, ChatbotError):
		return str(error)
	return _FALLBACK_USER_ERROR


@frappe.whitelist()
def create_conversation(title: str, ai_provider: str = "OpenAI") -> dict:
	"""Create a new chat conversation"""
	try:
		conversation = frappe.get_doc(
			{
				"doctype": "Chatbot Conversation",
				"title": title,
				"user": frappe.session.user,
				"ai_provider": ai_provider,
				"status": "Active",
				"created_at": frappe.utils.now(),
				"updated_at": frappe.utils.now(),
			}
		)
		conversation.insert()
		frappe.db.commit()

		return {
			"success": True,
			"conversation_id": conversation.name,
			"data": conversation.as_dict(),
		}
	except Exception as e:
		log_error(f"Error creating conversation: {e!s}", title="Chat API")
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_conversations(limit: int = 20) -> dict:
	"""Get user's conversations"""
	try:
		conversations = frappe.get_all(
			"Chatbot Conversation",
			filters={"user": frappe.session.user},
			fields=["name", "title", "ai_provider", "status", "created_at", "updated_at", "message_count"],
			order_by="updated_at desc",
			limit=limit,
		)

		return {
			"success": True,
			"conversations": conversations,
		}
	except Exception as e:
		log_error(f"Error getting conversations: {e!s}", title="Chat API")
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_conversation_messages(conversation_id: str) -> dict:
	"""Get messages for a conversation"""
	try:
		messages = frappe.get_all(
			"Chatbot Message",
			filters={"conversation": conversation_id},
			fields=[
				"name",
				"role",
				"content",
				"timestamp",
				"tokens_used",
				"tool_calls",
				"tool_results",
				"attachments",
				"confirmation_state",
			],
			order_by="timestamp asc",
		)

		# Parse JSON string fields
		for msg in messages:
			if msg.get("tool_calls"):
				try:
					msg["tool_calls"] = (
						json.loads(msg["tool_calls"])
						if isinstance(msg["tool_calls"], str)
						else msg["tool_calls"]
					)
				except (json.JSONDecodeError, TypeError):
					msg["tool_calls"] = None
			if msg.get("tool_results"):
				try:
					msg["tool_results"] = (
						json.loads(msg["tool_results"])
						if isinstance(msg["tool_results"], str)
						else msg["tool_results"]
					)
				except (json.JSONDecodeError, TypeError):
					msg["tool_results"] = None
			if msg.get("attachments"):
				try:
					msg["attachments"] = (
						json.loads(msg["attachments"])
						if isinstance(msg["attachments"], str)
						else msg["attachments"]
					)
				except (json.JSONDecodeError, TypeError):
					msg["attachments"] = None
			if msg.get("confirmation_state"):
				try:
					msg["confirmation_state"] = (
						json.loads(msg["confirmation_state"])
						if isinstance(msg["confirmation_state"], str)
						else msg["confirmation_state"]
					)
				except (json.JSONDecodeError, TypeError):
					msg["confirmation_state"] = None

		# Load session context for conversation-level preferences
		session_context = {}
		try:
			raw_ctx = frappe.db.get_value("Chatbot Conversation", conversation_id, "session_context")
			if raw_ctx:
				session_context = json.loads(raw_ctx) if isinstance(raw_ctx, str) else raw_ctx
		except (json.JSONDecodeError, TypeError):
			pass

		return {
			"success": True,
			"messages": messages,
			"session_context": session_context,
		}
	except Exception as e:
		log_error(f"Error getting messages: {e!s}", title="Chat API")
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def send_message(
	conversation_id: str,
	message: str,
	stream: bool = False,
	attachments: str | None = None,
	is_retry: bool | str = False,
) -> dict:
	"""Send a message and get AI response.

	When stream=True, delegates to the streaming API which delivers tokens
	via frappe.publish_realtime. The HTTP response returns immediately with
	the stream_id. When stream=False, returns the complete response.

	Args:
		conversation_id: The conversation document name.
		message: The user's message text.
		stream: Whether to use streaming mode.
		attachments: Optional JSON string of file attachment metadata.
		is_retry: If True, skip saving the user message (already persisted).
	"""
	try:
		log_info("Incoming message", conversation_id=conversation_id, stream=stream)

		if stream:
			from ai_chatbot.api.streaming import send_message_streaming

			return send_message_streaming(
				conversation_id, message, attachments=attachments, is_retry=is_retry
			)

		# Validate conversation
		conversation = frappe.get_doc("Chatbot Conversation", conversation_id)
		if conversation.user != frappe.session.user:
			frappe.throw("Unauthorized access to conversation")

		# Set conversation context for session tools
		frappe.flags.current_conversation_id = conversation_id

		# Normalise is_retry (Frappe may pass "true"/"1" as a string)
		is_retry = is_retry in (True, "true", "True", "1", 1)

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
			# Save user message
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

		# Get conversation history
		history = get_conversation_history(conversation_id)

		# Prepend system prompt (pass conversation_id for session context)
		system_prompt = build_system_prompt(conversation_id=conversation_id)
		system_msg = {"role": "system", "content": system_prompt}

		# Attach prompt blocks for Claude prompt caching
		if conversation.ai_provider == "Claude":
			from ai_chatbot.core.prompts import build_system_prompt_blocks

			system_msg["_prompt_blocks"] = build_system_prompt_blocks(conversation_id=conversation_id)

		history = [system_msg, *history]

		# Optimize history (trim, summarise, compress, deduplicate)
		history = optimize_history(
			history,
			conversation_id=conversation_id,
			provider_name=conversation.ai_provider,
		)

		# Get AI provider
		provider = get_ai_provider(conversation.ai_provider)

		# Route to relevant tool subset (Phase 12A)
		tools, routing = get_tools_for_message(message, history)
		log_info(
			"Tool routing",
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

			if detect_recall_intent(message):
				matches = find_relevant_conversations(message, conversation_id)
				recall_ctx = build_recall_context(matches)
				if recall_ctx:
					inject_recall_context(history[0], recall_ctx)
					log_info(
						"Cross-conversation recall",
						conversation_id=conversation_id,
						matches=len(matches),
					)
		except Exception:
			pass  # Non-critical

		# Generate non-streaming response
		return generate_ai_response(conversation, provider, history, tools)

	except Exception as e:
		log_error(f"Error sending message: {e!s}", title="Chat API")
		return {"success": False, "error": _user_facing_error(e)}


def generate_ai_response(conversation, provider, history, tools) -> dict:
	"""Generate non-streaming AI response with provider-agnostic parsing."""
	try:
		ai_provider = conversation.ai_provider

		# Check if agent orchestration should handle this query
		from ai_chatbot.ai.agents.orchestrator import run_orchestrated, should_orchestrate

		user_msg = next((m.get("content", "") for m in reversed(history) if m.get("role") == "user"), "")
		if isinstance(user_msg, list):
			user_msg = " ".join(p.get("text", "") for p in user_msg if p.get("type") == "text")

		if should_orchestrate(provider, user_msg, history, tools):
			result = run_orchestrated(conversation, provider, history, tools)
			if result is not None:
				return result
			# Fall through to standard flow if orchestration returned None

		# Phase 13D: Wrap provider with retry/fallback and loop guard
		from ai_chatbot.core.resilience import LLMCallWithRetry, ToolCallLoopGuard
		from ai_chatbot.utils.ai_providers import get_fallback_provider

		fallback = get_fallback_provider(ai_provider)
		retry_wrapper = LLMCallWithRetry(provider, fallback_provider=fallback)
		loop_guard = ToolCallLoopGuard()

		max_tool_rounds = 5

		# Multi-round tool call loop
		content = ""
		all_tool_calls = []
		all_tool_results = []
		prompt_tokens = 0
		completion_tokens = 0

		for _round in range(max_tool_rounds):
			from ai_chatbot.core.logger import timer as _timer

			with _timer() as llm_t:
				response = retry_wrapper.call(history, tools=tools, stream=False)

			round_content, tool_calls, round_prompt, round_completion = extract_response(
				ai_provider, response
			)
			content = round_content
			prompt_tokens += round_prompt
			completion_tokens += round_completion

			# Phase 13F: Audit the LLM request
			log_audit_event(
				"llm_request",
				conversation=conversation.name,
				provider=ai_provider,
				model=provider.model,
				tokens=(round_prompt, round_completion),
				cost=estimate_cost(provider.model, round_prompt, round_completion),
				duration_ms=llm_t.duration_ms,
				status="success",
			)

			if not tool_calls:
				# No tool calls — we're done
				break

			# Execute tool calls
			all_tool_calls.extend(tool_calls)

			history.append(
				{
					"role": "assistant",
					"content": round_content,
					"tool_calls": tool_calls,
				}
			)

			for i, tool_call in enumerate(tool_calls):
				func_name, func_args = extract_tool_info(ai_provider, tool_call)

				# Phase 13D: Detect duplicate tool calls (same name + same args)
				if loop_guard.is_stuck(func_name, func_args):
					log_warning(
						f"Tool call loop detected: {func_name} called {loop_guard.MAX_DUPLICATE_CALLS}+ times with same args",
						conversation_id=conversation.name,
					)
					loop_error = {
						"error": True,
						"error_type": "loop_detected",
						"message": f"Tool '{func_name}' has failed multiple times with the same arguments. Do not retry.",
						"suggestion": "Stop calling this tool and tell the user what went wrong.",
					}
					all_tool_results.append(loop_error)
					history.append(
						{
							"role": "tool",
							"content": safe_json(loop_error),
							"tool_call_id": tool_call.get("id", f"tool_{i}"),
						}
					)
					# Phase 13F: Audit loop-detected error
					log_audit_event(
						"error",
						conversation=conversation.name,
						tool_name=func_name,
						tool_args=func_args,
						status="error",
						error_message=f"Tool call loop detected: {func_name}",
					)
					continue

				result = BaseTool.execute_tool(func_name, func_args)
				loop_guard.record_call(func_name, func_args)
				all_tool_results.append(result)

				history.append(
					{
						"role": "tool",
						"content": safe_json(result),
						"tool_call_id": tool_call.get("id", f"tool_{i}"),
					}
				)

				# Check if the tool signaled to stop processing (e.g., file not found)
				if isinstance(result, dict) and result.get("stop_processing"):
					content = result.get("error", "An error occurred. Please check and try again.")
					# Break out of both the tool_call loop and the round loop
					break

			else:
				# Inner for-loop completed normally — continue to next round
				continue
			# Inner for-loop was broken — break the outer round loop too
			break

		tool_calls = all_tool_calls
		tokens_used = prompt_tokens + completion_tokens

		# Track token usage
		track_token_usage(
			provider=ai_provider,
			model=provider.model,
			prompt_tokens=prompt_tokens,
			completion_tokens=completion_tokens,
			conversation_id=conversation.name,
		)

		# Save assistant message
		frappe.get_doc(
			{
				"doctype": "Chatbot Message",
				"conversation": conversation.name,
				"role": "assistant",
				"content": content,
				"timestamp": frappe.utils.now(),
				"tokens_used": tokens_used,
				"tool_calls": safe_json(tool_calls) if tool_calls else None,
				"tool_results": safe_json(all_tool_results) if all_tool_results else None,
			}
		).insert()

		# Update conversation
		conversation.reload()
		conversation.message_count = frappe.db.count("Chatbot Message", {"conversation": conversation.name})
		conversation.total_tokens += tokens_used
		conversation.updated_at = frappe.utils.now()

		# Auto-generate title from first message if still "New Chat"
		if conversation.title == "New Chat" and conversation.message_count == 2:
			first_message = frappe.get_all(
				"Chatbot Message",
				filters={"conversation": conversation.name, "role": "user"},
				fields=["content"],
				order_by="timestamp asc",
				limit=1,
			)
			if first_message:
				title = first_message[0].content[:50].strip()
				if len(first_message[0].content) > 50:
					title += "..."
				conversation.title = title

		conversation.save(ignore_version=True)
		frappe.db.commit()

		return {
			"success": True,
			"message": content,
			"tokens_used": tokens_used,
		}

	except Exception as e:
		log_error(f"Error generating response: {e!s}", title="Chat API")
		# Phase 13F: Audit the error
		log_audit_event(
			"error",
			conversation=conversation.name,
			provider=ai_provider,
			model=provider.model,
			status="error",
			error_message=str(e),
		)
		return {"success": False, "error": _user_facing_error(e)}


@frappe.whitelist()
def delete_conversation(conversation_id: str) -> dict:
	"""Delete a conversation and its messages"""
	try:
		conversation = frappe.get_doc("Chatbot Conversation", conversation_id)
		if conversation.user != frappe.session.user:
			frappe.throw("Unauthorized access to conversation")

		# Delete all messages
		messages = frappe.get_all("Chatbot Message", filters={"conversation": conversation_id})
		for msg in messages:
			frappe.delete_doc("Chatbot Message", msg.name)

		# Delete conversation
		frappe.delete_doc("Chatbot Conversation", conversation_id)
		frappe.db.commit()

		return {"success": True}
	except Exception as e:
		log_error(f"Error deleting conversation: {e!s}", title="Chat API")
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def update_conversation_title(conversation_id: str, title: str) -> dict:
	"""Update conversation title"""
	try:
		conversation = frappe.get_doc("Chatbot Conversation", conversation_id)
		if conversation.user != frappe.session.user:
			frappe.throw("Unauthorized access to conversation")

		conversation.title = title
		conversation.updated_at = frappe.utils.now()
		conversation.save()
		frappe.db.commit()

		return {"success": True}
	except Exception as e:
		log_error(f"Error updating title: {e!s}", title="Chat API")
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def set_conversation_language(conversation_id: str, language: str = "") -> dict:
	"""Set the response language for a specific conversation.

	Stores the language preference in the conversation's session_context JSON.
	Pass an empty string to reset to the global default.

	Args:
		conversation_id: The conversation document name.
		language: Language name (e.g. "Hindi", "Spanish") or empty string to reset.

	Returns:
		dict with success status.
	"""
	try:
		conversation = frappe.get_doc("Chatbot Conversation", conversation_id)
		if conversation.user != frappe.session.user:
			frappe.throw("Unauthorized access to conversation")

		from ai_chatbot.core.session_context import set_session_context

		set_session_context(conversation_id, "response_language", language or None)
		frappe.db.commit()

		return {"success": True, "language": language}
	except Exception as e:
		log_error(f"Error setting conversation language: {e!s}", title="Chat API")
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_settings() -> dict:
	"""Get chatbot settings and current user info"""
	try:
		settings = frappe.get_single("Chatbot Settings")

		# Get current user's fullname and avatar
		from frappe.utils.user import get_fullname_and_avatar

		user_info = get_fullname_and_avatar(frappe.session.user)

		# Unified provider (new) or legacy dual-provider flags
		ai_provider = getattr(settings, "ai_provider", None)

		# Language options from the Select field
		lang_options = (getattr(settings, "response_language", "") or "").strip()
		available_languages = [
			"",
			"English",
			"Hindi",
			"Spanish",
			"French",
			"German",
			"Portuguese",
			"Arabic",
			"Chinese",
			"Japanese",
			"Korean",
		]

		return {
			"success": True,
			"settings": {
				"ai_provider": ai_provider or "OpenAI",
				"enable_streaming": settings.enable_streaming if hasattr(settings, "enable_streaming") else 1,
				"response_language": lang_options,
				"available_languages": available_languages,
				"tools_enabled": {
					"crm": settings.enable_crm_tools,
					"sales": settings.enable_sales_tools,
					"purchase": settings.enable_purchase_tools,
					"finance": settings.enable_finance_tools,
					"inventory": settings.enable_inventory_tools,
					"operations": getattr(settings, "enable_write_operations", 0),
					"agent_orchestration": getattr(settings, "enable_agent_orchestration", 0),
				},
			},
			"user": {
				"fullname": user_info.get("fullname"),
				"avatar": user_info.get("avatar"),
			},
		}
	except Exception as e:
		log_error(f"Error getting settings: {e!s}", title="Chat API")
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_sample_prompts() -> dict:
	"""Parse docs/SAMPLE_USER_PROMPT.md and return structured prompt categories.

	The markdown file uses H2 headings for categories and pipe-delimited tables
	with columns: Prompt | Output | Expected Result.

	Returns:
		dict with 'categories' list and 'mentions' list.
	"""
	import os
	import re

	try:
		app_path = frappe.get_app_path("ai_chatbot")
		md_path = os.path.join(app_path, "..", "docs", "SAMPLE_USER_PROMPT.md")
		md_path = os.path.normpath(md_path)

		if not os.path.isfile(md_path):
			return {"success": False, "error": "SAMPLE_USER_PROMPT.md not found"}

		with open(md_path) as f:
			content = f.read()

		categories = []
		mentions = []
		current_category = None
		in_tips = False

		for line in content.split("\n"):
			stripped = line.strip()

			# Detect H2 category headings: ## Sales / Selling
			if stripped.startswith("## "):
				heading = stripped[3:].strip()
				in_tips = heading.lower() == "tips"
				if not in_tips:
					current_category = {"category": heading, "prompts": []}
					categories.append(current_category)
				continue

			# Skip tips section, notes, and non-table lines
			if in_tips or not current_category:
				continue

			# Detect table rows (skip header and separator rows)
			if stripped.startswith("|") and stripped.endswith("|"):
				cells = [c.strip() for c in stripped.split("|")[1:-1]]
				# Skip header row and separator row (---|---|---)
				if len(cells) >= 3 and not re.match(r"^-+$", cells[0]):
					prompt_text = cells[0]
					output_type = cells[1].lower()
					expected = cells[2] if len(cells) > 2 else ""
					if prompt_text and prompt_text.lower() != "prompt":
						current_category["prompts"].append(
							{
								"text": prompt_text,
								"type": output_type,
								"expected": expected,
							}
						)

		# Parse @mention reference from the Tips section
		mention_pattern = re.compile(r"`(@\w+)`")
		tips_section = content.split("## Tips")
		if len(tips_section) > 1:
			# Extract @mentions from the tips text
			tips_text = tips_section[1]
			for match in mention_pattern.finditer(tips_text):
				mention_val = match.group(1)
				if mention_val not in [m["mention"] for m in mentions]:
					mentions.append({"mention": mention_val})

		# Filter out empty categories
		categories = [c for c in categories if c["prompts"]]

		return {"success": True, "categories": categories, "mentions": mentions}
	except Exception as e:
		log_error(f"Error loading sample prompts: {e!s}", title="Chat API")
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def search_conversations(query: str, limit: int = 20) -> dict:
	"""Search conversations by title or message content.

	Searches the current user's conversations where the title matches
	or any message content matches the query string.

	Args:
		query: The search term.
		limit: Maximum number of results to return.

	Returns:
		dict with success and conversations list.
	"""
	try:
		query = query.strip()
		if not query or len(query) < 2:
			return {"success": True, "conversations": []}

		user = frappe.session.user
		like_pattern = f"%{query}%"

		# Search by conversation title
		title_matches = frappe.get_all(
			"Chatbot Conversation",
			filters={"user": user, "title": ["like", like_pattern]},
			fields=["name", "title", "ai_provider", "status", "created_at", "updated_at", "message_count"],
			order_by="updated_at desc",
			limit=limit,
		)

		# Search by message content (get distinct conversation IDs)
		message_conv_ids = frappe.get_all(
			"Chatbot Message",
			filters={"content": ["like", like_pattern]},
			fields=["conversation"],
			group_by="conversation",
			limit=limit * 2,
		)
		message_conv_names = [m.conversation for m in message_conv_ids]

		# Filter to user's conversations and fetch details
		content_matches = []
		if message_conv_names:
			content_matches = frappe.get_all(
				"Chatbot Conversation",
				filters={"user": user, "name": ["in", message_conv_names]},
				fields=[
					"name",
					"title",
					"ai_provider",
					"status",
					"created_at",
					"updated_at",
					"message_count",
				],
				order_by="updated_at desc",
				limit=limit,
			)

		# Deduplicate (title matches take priority)
		seen = {c.name for c in title_matches}
		for c in content_matches:
			if c.name not in seen:
				title_matches.append(c)
				seen.add(c.name)

		# Sort combined results by updated_at desc and limit
		title_matches.sort(key=lambda c: c.get("updated_at") or "", reverse=True)

		return {
			"success": True,
			"conversations": title_matches[:limit],
		}
	except Exception as e:
		log_error(f"Search conversations error: {e!s}", title="Chat API")
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_mention_values(mention_type: str, search_term: str = "", company: str | None = None) -> dict:
	"""Return values for @mention autocomplete in chat input.

	Args:
		mention_type: One of: company, period, cost_center, department, warehouse,
			customer, item, accounting_dimension
		search_term: Filter string
		company: Company context (defaults to user default)

	Returns:
		dict with success and values list
	"""
	try:
		if not company:
			company = frappe.defaults.get_user_default("Company")

		if mention_type == "company":
			filters = {}
			if search_term:
				filters["name"] = ["like", f"%{search_term}%"]
			companies = frappe.get_all(
				"Company",
				filters=filters,
				pluck="name",
				limit_page_length=50,
				order_by="name asc",
			)
			# Put the user's default company first
			if company and company in companies:
				companies.remove(company)
				companies.insert(0, company)
			return {"success": True, "values": companies}

		if mention_type == "period":
			return {"success": True, "values": _get_period_presets(company)}

		# Searchable DocType mentions
		doctype_map = {
			"cost_center": "Cost Center",
			"department": "Department",
			"warehouse": "Warehouse",
			"customer": "Customer",
			"item": "Item",
		}

		if mention_type in doctype_map:
			doctype = doctype_map[mention_type]
			filters = {}
			if search_term:
				filters["name"] = ["like", f"%{search_term}%"]
			# Company filter for company-scoped DocTypes
			if mention_type in ("cost_center", "department", "warehouse") and company:
				filters["company"] = company

			values = frappe.get_all(
				doctype,
				filters=filters,
				pluck="name",
				limit_page_length=20,
				order_by="name asc",
			)
			return {"success": True, "values": values}

		if mention_type == "accounting_dimension":
			return {"success": True, "values": _get_accounting_dimensions(company, search_term)}

		return {"success": False, "error": f"Unknown mention type: {mention_type}"}

	except Exception as e:
		log_error(f"Mention values error: {e!s}", title="Chat API")
		return {"success": False, "error": str(e)}


def _get_period_presets(company: str | None = None) -> list[dict]:
	"""Return date range presets for @period mention."""
	from datetime import timedelta

	today = frappe.utils.today()
	today_date = frappe.utils.getdate(today)

	# This Week (Monday to Sunday)
	monday = today_date - timedelta(days=today_date.weekday())
	sunday = monday + timedelta(days=6)

	# This Month
	month_start = today_date.replace(day=1)
	if today_date.month == 12:
		month_end = today_date.replace(year=today_date.year + 1, month=1, day=1) - timedelta(days=1)
	else:
		month_end = today_date.replace(month=today_date.month + 1, day=1) - timedelta(days=1)

	# Last Month
	last_month_end = month_start - timedelta(days=1)
	last_month_start = last_month_end.replace(day=1)

	presets = [
		{"label": "This Week", "value": f"{monday} to {sunday}"},
		{"label": "This Month", "value": f"{month_start} to {month_end}"},
		{"label": "Last Month", "value": f"{last_month_start} to {last_month_end}"},
	]

	# Try to get fiscal year info
	try:
		from erpnext.accounts.utils import get_fiscal_year

		fy = get_fiscal_year(today, company=company)
		if fy:
			fy_start, fy_end = str(fy[1]), str(fy[2])

			# This Quarter
			quarter_month = ((today_date.month - frappe.utils.getdate(fy_start).month) // 3) * 3
			q_start_month = frappe.utils.getdate(fy_start).month + quarter_month
			q_start_year = today_date.year if q_start_month <= 12 else today_date.year + 1
			if q_start_month > 12:
				q_start_month -= 12
			q_start = today_date.replace(year=q_start_year, month=q_start_month, day=1)
			q_end_month = q_start_month + 2
			q_end_year = q_start_year
			if q_end_month > 12:
				q_end_month -= 12
				q_end_year += 1
			if q_end_month == 12:
				q_end = today_date.replace(year=q_end_year, month=12, day=31)
			else:
				q_end = today_date.replace(year=q_end_year, month=q_end_month + 1, day=1) - timedelta(days=1)

			presets.append({"label": "This Quarter", "value": f"{q_start} to {q_end}"})
			presets.append({"label": "This FY", "value": f"{fy_start} to {fy_end}"})

			# Last FY
			try:
				prev_fy_date = frappe.utils.getdate(fy_start) - timedelta(days=1)
				prev_fy = get_fiscal_year(str(prev_fy_date), company=company)
				if prev_fy:
					presets.append({"label": "Last FY", "value": f"{prev_fy[1]} to {prev_fy[2]}"})
			except Exception:
				pass
	except Exception:
		pass

	return presets


def _get_accounting_dimensions(company: str | None = None, search_term: str = "") -> list[dict]:
	"""Return available accounting dimensions and their values.

	Uses the centralised ``core.dimensions.get_available_dimensions()``
	(which calls ERPNext's ``get_accounting_dimensions`` API) to discover
	active dimensions, then queries each dimension's document_type for values.
	"""
	try:
		from ai_chatbot.core.dimensions import get_available_dimensions

		dimensions = get_available_dimensions()

		# Optional search_term filter on label
		if search_term:
			term_lower = search_term.lower()
			dimensions = [d for d in dimensions if term_lower in (d.get("label") or "").lower()]

		results = []
		for dim in dimensions:
			doc_type = dim.get("document_type") or dim.get("fieldname")
			label = dim.get("label") or doc_type

			# Get values for this dimension's document type
			try:
				value_filters = {}
				if company and frappe.get_meta(doc_type).has_field("company"):
					value_filters["company"] = company

				values = frappe.get_all(
					doc_type,
					filters=value_filters,
					pluck="name",
					limit_page_length=20,
					order_by="name asc",
				)
			except Exception:
				values = []

			results.append(
				{
					"label": label,
					"description": f"{doc_type} ({len(values)} values)",
					"values": values,
				}
			)
		return results
	except Exception as e:
		log_warning(f"Error fetching accounting dimensions: {e}")
		return []
