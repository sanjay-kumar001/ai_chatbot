# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
Headless AI Execution Engine for Automation

Runs an AI prompt with tool-calling in a non-interactive context
(no conversation, no user session, no streaming). Used by scheduled
reports.

Replicates the multi-round tool loop from chat.py's generate_ai_response()
but operates headlessly with Administrator permissions.
"""

from __future__ import annotations

import json

import frappe

from ai_chatbot.core.ai_utils import extract_response, extract_tool_info
from ai_chatbot.core.constants import AUTOMATION_MAX_TOOL_ROUNDS
from ai_chatbot.core.prompts import build_system_prompt
from ai_chatbot.core.token_tracker import track_token_usage
from ai_chatbot.tools.base import BaseTool, get_all_tools_schema
from ai_chatbot.utils.ai_providers import get_ai_provider


def execute_prompt(
	prompt: str,
	company: str,
	max_tool_rounds: int = AUTOMATION_MAX_TOOL_ROUNDS,
	tools_enabled: bool = True,
) -> dict:
	"""Execute an AI prompt with tools and return the response.

	Runs the same multi-round tool-calling loop as the chat API, but
	without a conversation context. Executes as Administrator for
	full data access. The AI provider is resolved from Chatbot Settings.

	Args:
		prompt: The prompt to execute (e.g. "Generate a weekly sales summary").
		company: Company context for tools and system prompt.
		max_tool_rounds: Maximum number of tool call rounds (default 5).
		tools_enabled: Whether to include tools in the AI call.

	Returns:
		dict with keys:
			content (str): The AI's final text response.
			tool_calls (list): All tool calls made during execution.
			tool_results (list): All tool results from executed tools.
			tokens_used (int): Total tokens consumed (prompt + completion).
	"""
	original_user = frappe.session.user

	try:
		# Run as Administrator for full data access
		frappe.set_user("Administrator")

		# Resolve AI provider from Chatbot Settings
		settings = frappe.get_single("Chatbot Settings")
		ai_provider = getattr(settings, "ai_provider", "OpenAI") or "OpenAI"

		# Build system prompt with company override
		system_prompt = build_system_prompt(company=company)

		# Prepend date context to the user prompt
		today = frappe.utils.nowdate()
		enriched_prompt = f"Today is {today}. You are generating a report for company: {company}.\n\n{prompt}"

		# Get AI provider and tools
		provider = get_ai_provider(ai_provider)
		tools = get_all_tools_schema() if tools_enabled else None

		# Build initial message history
		history = [
			{"role": "system", "content": system_prompt},
			{"role": "user", "content": enriched_prompt},
		]

		# Multi-round tool call loop
		content = ""
		all_tool_calls = []
		all_tool_results = []
		total_prompt_tokens = 0
		total_completion_tokens = 0

		for _round in range(max_tool_rounds):
			response = provider.chat_completion(history, tools=tools, stream=False)

			round_content, tool_calls, round_prompt, round_completion = extract_response(
				ai_provider, response
			)
			content = round_content
			total_prompt_tokens += round_prompt
			total_completion_tokens += round_completion

			if not tool_calls:
				# No tool calls — we have the final response
				break

			# Record tool calls
			all_tool_calls.extend(tool_calls)

			# Add assistant message with tool calls to history
			history.append(
				{
					"role": "assistant",
					"content": round_content,
					"tool_calls": tool_calls,
				}
			)

			# Execute each tool and add results to history
			for i, tool_call in enumerate(tool_calls):
				func_name, func_args = extract_tool_info(ai_provider, tool_call)

				# Inject company context if the tool accepts it and it's not set
				if "company" not in func_args:
					func_args["company"] = company

				result = BaseTool.execute_tool(func_name, func_args)
				all_tool_results.append(result)

				history.append(
					{
						"role": "tool",
						"content": json.dumps(result, default=str),
						"tool_call_id": tool_call.get("id", f"tool_{i}"),
					}
				)

		tokens_used = total_prompt_tokens + total_completion_tokens

		# Track token usage
		track_token_usage(
			provider=ai_provider,
			model=provider.model,
			prompt_tokens=total_prompt_tokens,
			completion_tokens=total_completion_tokens,
			user="Administrator",
		)

		return {
			"content": content,
			"tool_calls": all_tool_calls,
			"tool_results": all_tool_results,
			"tokens_used": tokens_used,
		}

	finally:
		frappe.set_user(original_user)
