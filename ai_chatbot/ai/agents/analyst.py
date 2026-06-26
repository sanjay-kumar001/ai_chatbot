# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
Analyst Agent

Executes a single step of the orchestration plan. Makes LLM calls with
tool-calling support, runs a mini tool loop, and returns the step with results.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import frappe

from ai_chatbot.ai.agents.context import AgentContext, AgentStep
from ai_chatbot.ai.agents.prompts import get_analyst_prompt
from ai_chatbot.core.ai_utils import extract_response, extract_tool_info
from ai_chatbot.tools.base import BaseTool

# Analyst gets fewer tool rounds than the main flow (3 vs 5)
MAX_TOOL_ROUNDS = 3


def execute_step(
	provider,
	step: AgentStep,
	context: AgentContext,
	tools: list[dict],
	system_prompt: str,
	ai_provider: str,
) -> AgentStep:
	"""Execute a single plan step using tool calls (non-streaming).

	Args:
		provider: The AI provider instance.
		step: The step to execute.
		context: Shared agent context with prior results.
		tools: Available tool schemas.
		system_prompt: Base system prompt from build_system_prompt().
		ai_provider: Provider name (e.g. "OpenAI", "Claude").

	Returns:
		The same step object, mutated with results/error.
	"""
	step.status = "running"

	try:
		prior_results = context.get_dependency_results(step)
		analyst_prompt = get_analyst_prompt(step.description, prior_results, system_prompt)

		messages = [
			{"role": "system", "content": analyst_prompt},
			{"role": "user", "content": step.description},
		]

		# Mini tool-calling loop
		content = ""
		for _round in range(MAX_TOOL_ROUNDS):
			response = provider.chat_completion(messages, tools=tools, stream=False)

			round_content, tool_calls, prompt_tokens, completion_tokens = extract_response(
				ai_provider, response
			)
			content = round_content
			step.tokens_used += prompt_tokens + completion_tokens

			if not tool_calls:
				break

			# Execute tool calls
			messages.append(
				{
					"role": "assistant",
					"content": round_content,
					"tool_calls": tool_calls,
				}
			)

			for i, tool_call in enumerate(tool_calls):
				func_name, func_args = extract_tool_info(ai_provider, tool_call)
				result = BaseTool.execute_tool(func_name, func_args)

				step.tool_calls.append({"name": func_name, "arguments": func_args})
				step.tool_results.append(result)

				messages.append(
					{
						"role": "tool",
						"content": json.dumps(result, default=str),
						"tool_call_id": tool_call.get("id", f"tool_{i}"),
					}
				)

		step.status = "completed"
		step.result = _build_step_result(step)
		step.result_summary = content[:500] if content else ""

	except Exception as e:
		frappe.log_error(f"Agent analyst error (step {step.step_id}): {e!s}", "AI Chatbot Agent")
		step.status = "failed"
		step.error = str(e)

	return step


def execute_step_streaming(
	provider,
	step: AgentStep,
	context: AgentContext,
	tools: list[dict],
	system_prompt: str,
	ai_provider: str,
	publish_fn: Callable,
	conversation_id: str,
	stream_id: str,
	user: str,
) -> AgentStep:
	"""Execute a single plan step with streaming tool call events.

	Same logic as execute_step but publishes tool_call and tool_result
	events via the publish_fn callback for real-time frontend updates.

	Args:
		provider: The AI provider instance.
		step: The step to execute.
		context: Shared agent context.
		tools: Available tool schemas.
		system_prompt: Base system prompt.
		ai_provider: Provider name.
		publish_fn: Function to publish realtime events.
		conversation_id: For event routing.
		stream_id: For event routing.
		user: For event routing.

	Returns:
		The same step object, mutated with results/error.
	"""
	step.status = "running"

	try:
		prior_results = context.get_dependency_results(step)
		analyst_prompt = get_analyst_prompt(step.description, prior_results, system_prompt)

		messages = [
			{"role": "system", "content": analyst_prompt},
			{"role": "user", "content": step.description},
		]

		content = ""
		for _round in range(MAX_TOOL_ROUNDS):
			response = provider.chat_completion(messages, tools=tools, stream=False)

			round_content, tool_calls, prompt_tokens, completion_tokens = extract_response(
				ai_provider, response
			)
			content = round_content
			step.tokens_used += prompt_tokens + completion_tokens

			if not tool_calls:
				break

			messages.append(
				{
					"role": "assistant",
					"content": round_content,
					"tool_calls": tool_calls,
				}
			)

			for i, tool_call in enumerate(tool_calls):
				func_name, func_args = extract_tool_info(ai_provider, tool_call)

				# Publish tool call event
				tool_display = func_name.replace("_", " ").title()
				publish_fn(
					"ai_chat_process_step",
					{
						"conversation_id": conversation_id,
						"stream_id": stream_id,
						"step": f"Step {step.step_id}: Executing {tool_display}...",
					},
					user=user,
				)

				publish_fn(
					"ai_chat_tool_call",
					{
						"conversation_id": conversation_id,
						"stream_id": stream_id,
						"tool_name": func_name,
						"tool_arguments": func_args,
					},
					user=user,
				)

				try:
					result = BaseTool.execute_tool(func_name, func_args)
				except Exception as e:
					result = {"error": str(e)}

				step.tool_calls.append({"name": func_name, "arguments": func_args})
				step.tool_results.append(result)

				# Publish tool result event
				publish_fn(
					"ai_chat_tool_result",
					{
						"conversation_id": conversation_id,
						"stream_id": stream_id,
						"tool_name": func_name,
						"result": result,
					},
					user=user,
				)

				messages.append(
					{
						"role": "tool",
						"content": json.dumps(result, default=str),
						"tool_call_id": tool_call.get("id", f"tool_{i}"),
					}
				)

		step.status = "completed"
		step.result = _build_step_result(step)
		step.result_summary = content[:500] if content else ""

	except Exception as e:
		frappe.log_error(f"Agent analyst error (step {step.step_id}): {e!s}", "AI Chatbot Agent")
		step.status = "failed"
		step.error = str(e)

	return step


def _build_step_result(step: AgentStep) -> dict:
	"""Build a consolidated result dict for a completed step.

	Merges data from all tool results in the step.
	"""
	if not step.tool_results:
		return {}

	# If there's a single tool result, use it directly
	if len(step.tool_results) == 1:
		result = step.tool_results[0]
		if isinstance(result, dict):
			return result.get("data", result)
		return result

	# Multiple tool results — combine into a list
	combined = []
	for r in step.tool_results:
		if isinstance(r, dict):
			combined.append(r.get("data", r))
		else:
			combined.append(r)
	return {"combined_results": combined}
