# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
Agent Orchestrator

Main entry point for multi-agent orchestration. Decides whether to use
the multi-agent pipeline or the standard single-pass tool-calling flow,
then coordinates the planner → analyst → synthesis pipeline.
"""

from __future__ import annotations

import json

import frappe

from ai_chatbot.ai.agents.analyst import execute_step, execute_step_streaming
from ai_chatbot.ai.agents.classifier import classify_query
from ai_chatbot.ai.agents.context import AgentContext
from ai_chatbot.ai.agents.planner import create_plan
from ai_chatbot.ai.agents.prompts import get_synthesis_prompt
from ai_chatbot.core.logger import log_error
from ai_chatbot.core.token_optimizer import compress_tool_result
from ai_chatbot.core.token_tracker import track_token_usage

# If more than half the data steps fail, abort and fall back to simple path
FAILURE_THRESHOLD = 0.5

# Token buffer size for streaming synthesis (matches streaming.py)
TOKEN_BUFFER_SIZE = 20


def should_orchestrate(
	provider,
	user_message: str,
	history: list[dict],
	tools: list[dict],
) -> bool:
	"""Check whether multi-agent orchestration should be used.

	Checks the settings toggle first, then calls the classifier.

	Args:
		provider: The AI provider instance.
		user_message: The user's latest message.
		history: Conversation history.
		tools: Available tool schemas.

	Returns:
		True if orchestration should be used.
	"""
	# Check settings toggle
	try:
		settings = frappe.get_single("Chatbot Settings")
		if not getattr(settings, "enable_agent_orchestration", False):
			return False
	except Exception:
		return False

	# No tools available — orchestration is pointless
	if not tools:
		return False

	return classify_query(provider, user_message, history, tools)


def run_orchestrated(
	conversation,
	provider,
	history: list[dict],
	tools: list[dict],
) -> dict:
	"""Run the multi-agent orchestration pipeline (non-streaming).

	Returns the same dict format as generate_ai_response() in chat.py:
	{success: bool, message: str, tokens_used: int}

	Falls back to None on failure (caller should proceed with simple path).
	"""
	ai_provider = conversation.ai_provider
	conversation_id = conversation.name

	# Extract user query from history
	user_query = _extract_user_query(history)
	if not user_query:
		return None

	# Create the agent context
	context = AgentContext(
		query=user_query,
		conversation_id=conversation_id,
	)

	# --- Phase 1: Planning ---
	plan = create_plan(provider, user_query, tools, history)
	if not plan:
		return None  # Fall back to simple path

	context.plan = plan

	# --- Phase 2: Execute steps ---
	system_prompt = _get_system_prompt(history)

	for step in context.plan:
		# Check dependencies
		if not _dependencies_met(step, context):
			step.status = "skipped"
			step.error = "Dependency failed"
			continue

		execute_step(
			provider=provider,
			step=step,
			context=context,
			tools=tools,
			system_prompt=system_prompt,
			ai_provider=ai_provider,
		)

		# Aggregate into context
		context.all_tool_calls.extend(step.tool_calls)
		context.all_tool_results.extend(step.tool_results)
		context.total_tokens += step.tokens_used

		if step.status == "failed":
			context.errors.append(f"Step '{step.description}': {step.error}")

	# Check failure threshold
	if _should_abort(context):
		return None  # Fall back to simple path

	# --- Phase 3: Synthesis ---
	try:
		synthesis_content, synthesis_tokens = _run_synthesis(
			provider=provider,
			context=context,
			ai_provider=ai_provider,
		)
		context.total_tokens += synthesis_tokens
	except Exception as e:
		log_error(f"Agent synthesis error: {e!s}", title="Agent")
		return None  # Fall back to simple path

	# Fallback: if synthesis returned empty, build basic response from step data
	if not synthesis_content.strip():
		synthesis_content = _build_fallback_response(context)

	# Track token usage
	track_token_usage(
		provider=ai_provider,
		model=provider.model,
		prompt_tokens=0,
		completion_tokens=context.total_tokens,
		conversation_id=conversation_id,
	)

	# Save assistant message
	frappe.get_doc(
		{
			"doctype": "Chatbot Message",
			"conversation": conversation_id,
			"role": "assistant",
			"content": synthesis_content,
			"timestamp": frappe.utils.now(),
			"tokens_used": context.total_tokens,
			"tool_calls": json.dumps(context.all_tool_calls, default=str) if context.all_tool_calls else None,
			"tool_results": json.dumps(context.all_tool_results, default=str) if context.all_tool_results else None,
		}
	).insert()

	# Update conversation
	conversation.reload()
	conversation.message_count = frappe.db.count("Chatbot Message", {"conversation": conversation_id})
	conversation.total_tokens += context.total_tokens
	conversation.updated_at = frappe.utils.now()

	# Auto-generate title from first message if still "New Chat"
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

	return {
		"success": True,
		"message": synthesis_content,
		"tokens_used": context.total_tokens,
	}


def run_orchestrated_streaming(
	ai_provider: str,
	provider,
	history: list[dict],
	tools: list[dict],
	conversation_id: str,
	stream_id: str,
	user: str,
) -> tuple:
	"""Run the multi-agent orchestration pipeline with streaming.

	Returns the same tuple format as _stream_with_tools() in streaming.py:
	(full_content, all_tool_calls, all_tool_results, tokens_used,
	 prompt_tokens, completion_tokens)

	Returns None on failure (caller should proceed with simple path).
	"""
	from ai_chatbot.api.streaming import _publish

	user_query = _extract_user_query(history)
	if not user_query:
		return None

	context = AgentContext(
		query=user_query,
		conversation_id=conversation_id,
		stream_id=stream_id,
		user=user,
	)

	# --- Phase 1: Planning ---
	_publish(
		"ai_chat_process_step",
		{"conversation_id": conversation_id, "stream_id": stream_id, "step": "Planning analysis..."},
		user=user,
	)

	plan = create_plan(provider, user_query, tools, history)
	if not plan:
		return None

	context.plan = plan

	# Publish the plan to the frontend
	plan_data = [
		{"step_id": s.step_id, "description": s.description, "tool_hint": s.tool_hint} for s in context.plan
	]
	_publish(
		"ai_chat_agent_plan",
		{"conversation_id": conversation_id, "stream_id": stream_id, "plan": plan_data},
		user=user,
	)

	# --- Phase 2: Execute steps ---
	system_prompt = _get_system_prompt(history)
	total_steps = len(context.plan)

	for i, step in enumerate(context.plan, 1):
		# Check dependencies
		if not _dependencies_met(step, context):
			step.status = "skipped"
			step.error = "Dependency failed"
			_publish(
				"ai_chat_agent_step_result",
				{
					"conversation_id": conversation_id,
					"stream_id": stream_id,
					"step_id": step.step_id,
					"status": "skipped",
					"summary": "Skipped — dependency failed",
				},
				user=user,
			)
			continue

		# Notify step start
		_publish(
			"ai_chat_agent_step_start",
			{
				"conversation_id": conversation_id,
				"stream_id": stream_id,
				"step_id": step.step_id,
				"description": step.description,
				"step_number": i,
				"total_steps": total_steps,
			},
			user=user,
		)

		execute_step_streaming(
			provider=provider,
			step=step,
			context=context,
			tools=tools,
			system_prompt=system_prompt,
			ai_provider=ai_provider,
			publish_fn=_publish,
			conversation_id=conversation_id,
			stream_id=stream_id,
			user=user,
		)

		# Aggregate
		context.all_tool_calls.extend(step.tool_calls)
		context.all_tool_results.extend(step.tool_results)
		context.total_tokens += step.tokens_used

		# Notify step result
		_publish(
			"ai_chat_agent_step_result",
			{
				"conversation_id": conversation_id,
				"stream_id": stream_id,
				"step_id": step.step_id,
				"status": step.status,
				"summary": step.result_summary[:200] if step.result_summary else "",
			},
			user=user,
		)

		if step.status == "failed":
			context.errors.append(f"Step '{step.description}': {step.error}")

	# Check failure threshold
	if _should_abort(context):
		return None

	# --- Phase 3: Synthesis (streamed) ---
	_publish(
		"ai_chat_process_step",
		{"conversation_id": conversation_id, "stream_id": stream_id, "step": "Synthesizing results..."},
		user=user,
	)

	try:
		full_content = ""
		buffer = ""

		synthesis_messages = _build_synthesis_messages(context)
		for event in provider.chat_completion_stream(synthesis_messages, tools=None):
			event_type = event.get("type")

			if event_type == "token":
				token_text = event.get("content", "")
				full_content += token_text
				buffer += token_text

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

			elif event_type == "finish":
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
				_publish(
					"ai_chat_error",
					{
						"conversation_id": conversation_id,
						"stream_id": stream_id,
						"error": event.get("content", "Synthesis error"),
					},
					user=user,
				)
				break

		# Flush remaining buffer
		if buffer:
			_publish(
				"ai_chat_token",
				{"conversation_id": conversation_id, "stream_id": stream_id, "content": buffer},
				user=user,
			)

		# Estimate synthesis tokens
		synthesis_tokens = len(full_content) // 4
		context.total_tokens += synthesis_tokens

	except Exception as e:
		log_error(f"Agent streaming synthesis error: {e!s}", title="Agent")
		return None

	# Fallback: if synthesis returned empty content, build a basic response
	# from step results so the user at least sees the gathered data.
	if not full_content.strip():
		full_content = _build_fallback_response(context)
		if full_content:
			# Stream the fallback content to the frontend
			_publish(
				"ai_chat_token",
				{"conversation_id": conversation_id, "stream_id": stream_id, "content": full_content},
				user=user,
			)

	# Return the same 6-tuple as _stream_with_tools in streaming.py.
	# The orchestrator doesn't have real per-round usage from the provider,
	# so prompt_tokens=0 and completion_tokens=total_tokens (estimated).
	return (
		full_content,
		context.all_tool_calls,
		context.all_tool_results,
		context.total_tokens,
		0,
		context.total_tokens,
	)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_user_query(history: list[dict]) -> str:
	"""Extract the last user message from conversation history."""
	for msg in reversed(history):
		if msg.get("role") == "user":
			content = msg.get("content", "")
			if isinstance(content, list):
				# Multimodal — extract text parts
				return " ".join(p.get("text", "") for p in content if p.get("type") == "text")
			return content
	return ""


def _get_system_prompt(history: list[dict]) -> str:
	"""Extract the system prompt from the conversation history."""
	for msg in history:
		if msg.get("role") == "system":
			return msg.get("content", "")
	return ""


def _dependencies_met(step, context: AgentContext) -> bool:
	"""Check if all dependencies for a step have completed successfully."""
	for dep_id in step.depends_on:
		dep_step = context.get_step(dep_id)
		if not dep_step or dep_step.status != "completed":
			return False
	return True


def _should_abort(context: AgentContext) -> bool:
	"""Check if too many steps failed, warranting an abort."""
	data_steps = context.total_data_steps()
	if data_steps == 0:
		return True
	return context.failed_count() / data_steps > FAILURE_THRESHOLD


def _build_fallback_response(context: AgentContext) -> str:
	"""Build a basic response from step results when synthesis returns empty.

	This is a safety net — it formats the raw step summaries into a readable
	response so the user at least sees the data that was gathered.
	"""
	parts = []
	for step in context.plan:
		if step.status == "completed" and step.result_summary:
			parts.append(f"**{step.description}**\n{step.result_summary}")
		elif step.status == "failed":
			parts.append(f"**{step.description}** — _{step.error or 'Failed'}_")

	if not parts:
		return ""

	return "Here are the results from the analysis:\n\n" + "\n\n".join(parts)


def _run_synthesis(provider, context: AgentContext, ai_provider: str) -> tuple[str, int]:
	"""Run the synthesis LLM call (non-streaming).

	Returns (content, tokens_used).
	"""
	messages = _build_synthesis_messages(context)
	response = provider.chat_completion(messages, tools=None, stream=False)

	# Extract content and tokens
	if "choices" in response:
		content = response["choices"][0]["message"].get("content", "")
		usage = response.get("usage", {})
		tokens = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
	else:
		content = ""
		for block in response.get("content", []):
			if block.get("type") == "text":
				content += block.get("text", "")
		usage = response.get("usage", {})
		tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

	return content, tokens


def _build_synthesis_messages(context: AgentContext) -> list[dict]:
	"""Build the message list for the synthesis LLM call."""
	steps_data = []
	for step in context.plan:
		step_info = {
			"description": step.description,
			"status": step.status,
			"summary": step.result_summary,
		}
		if step.status == "completed" and step.result:
			step_info["result"] = compress_tool_result(step.result)
		if step.status == "failed":
			step_info["error"] = step.error
		steps_data.append(step_info)

	synthesis_prompt = get_synthesis_prompt(steps_data)

	return [
		{"role": "system", "content": synthesis_prompt},
		{"role": "user", "content": context.query},
	]


def _build_agent_metadata(context: AgentContext) -> dict:
	"""Build metadata about the agent execution for debugging/display."""
	return {
		"agent_orchestrated": True,
		"plan": [
			{
				"step_id": s.step_id,
				"description": s.description,
				"status": s.status,
				"summary": s.result_summary[:200] if s.result_summary else "",
			}
			for s in context.plan
		],
		"total_steps": len(context.plan),
		"completed_steps": sum(1 for s in context.plan if s.status == "completed"),
		"failed_steps": sum(1 for s in context.plan if s.status == "failed"),
	}
