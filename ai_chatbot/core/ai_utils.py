# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
Shared AI Response Parsing Utilities

Provider-agnostic helpers for extracting content, tool calls, and token
usage from AI provider responses. Used by the chat API, streaming module,
and automation executor.
"""

import json


#: Providers whose wire format is OpenAI Chat Completions. Azure OpenAI, the
#: Gemini OpenAI-compatible endpoint, and any user-configured Local LLM
#: (Ollama / LM Studio / vLLM / DashScope's compatible-mode) all parse and
#: format tool calls identically to OpenAI itself. Claude has its own wire
#: format and is the only provider that returns False here.
_OPENAI_FORMAT_PROVIDERS = frozenset(
	{
		"OpenAI",
		"Gemini",
		"Azure OpenAI",
		"Local LLM (OpenAI-compatible)",
	}
)


def is_openai_format(provider_name: str) -> bool:
	"""Return True if the provider uses OpenAI-compatible response format."""
	return provider_name in _OPENAI_FORMAT_PROVIDERS


def extract_response(provider_name: str, response: dict) -> tuple:
	"""Extract content, tool_calls, prompt_tokens, completion_tokens from a provider response.

	Handles both OpenAI/Gemini format and Claude format.

	Args:
		provider_name: The AI provider name ("OpenAI", "Claude", or "Gemini").
		response: The raw API response dict from the provider.

	Returns:
		Tuple of (content: str, tool_calls: list, prompt_tokens: int, completion_tokens: int).
	"""
	if is_openai_format(provider_name):
		msg = response["choices"][0]["message"]
		content = msg.get("content") or ""
		tool_calls = msg.get("tool_calls", [])
		usage = response.get("usage", {})
		prompt_tokens = usage.get("prompt_tokens", 0)
		completion_tokens = usage.get("completion_tokens", 0)
	else:  # Claude
		content = ""
		tool_calls = []
		for block in response.get("content", []):
			if block.get("type") == "text":
				content += block.get("text", "")
			elif block.get("type") == "tool_use":
				tool_calls.append(block)
		usage = response.get("usage", {})
		prompt_tokens = usage.get("input_tokens", 0)
		completion_tokens = usage.get("output_tokens", 0)

	return content, tool_calls, prompt_tokens, completion_tokens


def extract_tool_info(provider_name: str, tool_call: dict) -> tuple:
	"""Extract (func_name, func_args) from a tool_call dict.

	Args:
		provider_name: The AI provider name ("OpenAI", "Claude", or "Gemini").
		tool_call: A single tool call dict from the provider response.

	Returns:
		Tuple of (func_name: str, func_args: dict).
	"""
	if is_openai_format(provider_name):
		func_name = tool_call["function"]["name"]
		func_args = json.loads(tool_call["function"]["arguments"])
	else:  # Claude
		func_name = tool_call["name"]
		func_args = tool_call.get("input", {})
	return func_name, func_args

def safe_json(obj) -> str:
	return json.dumps(obj, default=str)