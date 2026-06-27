# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
Planner Agent

Decomposes a complex user query into a sequence of executable steps.
Each step maps to one or more tool calls that the analyst agent will execute.
"""

from __future__ import annotations

import json
import re

import frappe

from ai_chatbot.ai.agents.context import AgentStep
from ai_chatbot.ai.agents.prompts import get_planner_prompt
from ai_chatbot.core.logger import log_error

MAX_STEPS = 6


def create_plan(
	provider,
	query: str,
	available_tools: list[dict],
	history: list[dict],
) -> list[AgentStep]:
	"""Decompose a complex query into executable steps.

	Calls the LLM with the planner prompt to produce a JSON plan.
	Returns an empty list on failure (caller should fall back to simple path).

	Args:
		provider: The AI provider instance.
		query: The user's query to decompose.
		available_tools: Tool schemas (used to extract tool names for the prompt).
		history: Recent conversation history for context.

	Returns:
		List of AgentStep objects, or empty list on failure.
	"""
	try:
		# Extract tool names from schemas
		tool_names = _extract_tool_names(available_tools)

		# Build messages
		messages = [{"role": "system", "content": get_planner_prompt(tool_names)}]

		# Include last 2 exchanges for conversational context
		recent = [m for m in history if m.get("role") in ("user", "assistant")][-4:]
		for msg in recent:
			content = msg.get("content", "")
			if isinstance(content, list):
				content = " ".join(p.get("text", "") for p in content if p.get("type") == "text")
			if content:
				messages.append({"role": msg["role"], "content": content[:300]})

		# The user's query is the last message
		if not messages or messages[-1].get("content") != query:
			messages.append({"role": "user", "content": query})

		# Call LLM — no tools needed, just planning
		response = provider.chat_completion(messages, tools=None, stream=False)

		# Parse the plan
		return _parse_plan(provider, response)

	except Exception as e:
		log_error(f"Agent planner error: {e!s}", title="Agent")
		return []


def _extract_tool_names(tools: list[dict]) -> list[str]:
	"""Extract tool names from OpenAI function calling schemas."""
	names = []
	for tool in tools:
		func = tool.get("function", {})
		name = func.get("name", "")
		if name:
			names.append(name)
	return names


def _parse_plan(provider, response: dict) -> list[AgentStep]:
	"""Parse the LLM response into AgentStep objects.

	Handles both OpenAI/Gemini and Claude response formats.
	Returns empty list on parse failure.
	"""
	try:
		# Extract text content
		if "choices" in response:
			content = response["choices"][0]["message"].get("content", "")
		else:
			content = ""
			for block in response.get("content", []):
				if block.get("type") == "text":
					content += block.get("text", "")

		if not content:
			return []

		# Extract JSON — may be wrapped in ```json ... ```
		json_match = re.search(r"\{[\s\S]*\}", content)
		if not json_match:
			return []

		plan_data = json.loads(json_match.group())
		steps_raw = plan_data.get("steps", [])

		if not isinstance(steps_raw, list) or not steps_raw:
			return []

		# Convert to AgentStep objects, capped at MAX_STEPS
		steps = []
		seen_ids = set()
		for i, step_raw in enumerate(steps_raw[:MAX_STEPS]):
			step_id = step_raw.get("step_id", f"step_{i + 1}")
			description = step_raw.get("description", "")

			if not description:
				continue
			if step_id in seen_ids:
				step_id = f"step_{i + 1}"
			seen_ids.add(step_id)

			# Validate depends_on references
			depends_on = step_raw.get("depends_on", [])
			if not isinstance(depends_on, list):
				depends_on = []
			depends_on = [d for d in depends_on if d in seen_ids]

			steps.append(
				AgentStep(
					step_id=step_id,
					description=description,
					tool_hint=step_raw.get("tool_hint"),
					depends_on=depends_on,
				)
			)

		return _validate_plan(steps)

	except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
		log_error(f"Agent planner parse error: {e!s}", title="Agent")
		return []


def _validate_plan(steps: list[AgentStep]) -> list[AgentStep]:
	"""Validate and clean up the plan.

	- Ensures at least 2 steps (otherwise not worth orchestrating)
	- Removes orphan dependencies
	- Returns the validated steps or empty list
	"""
	if len(steps) < 2:
		return []

	# Verify all dependency references are valid
	valid_ids = {s.step_id for s in steps}
	for step in steps:
		step.depends_on = [d for d in step.depends_on if d in valid_ids]

	return steps
