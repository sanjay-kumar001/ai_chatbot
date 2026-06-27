# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
AI Provider Integration Module
Handles OpenAI, Claude, Gemini, Azure OpenAI, and local OpenAI-compatible
(Ollama / LM Studio / vLLM) API integrations with streaming support.

Provider configuration uses the unified Chatbot Settings fields:
  ai_provider, api_key, model, temperature, max_tokens
"""

import json

import frappe
import requests

from ai_chatbot.core.exceptions import ProviderAPIError
from ai_chatbot.core.logger import log_provider_error

# Default models per provider
DEFAULT_MODELS = {
	"OpenAI": "gpt-4o",
	"Claude": "claude-sonnet-4-5-20250929",
	"Gemini": "gemini-2.5-flash",
}

# Cheap/fast models used for auxiliary tasks (conversation summarisation)
SUMMARY_MODELS = {
	"OpenAI": "gpt-4o-mini",
	"Claude": "claude-haiku-4-5-20251001",
	"Gemini": "gemini-2.0-flash-lite",
}

# User-friendly error messages for common API errors
RATE_LIMIT_MESSAGE = (
	"The AI service is temporarily unavailable due to rate limiting. "
	"This usually means too many requests were sent in a short period. "
	"Please wait a moment and try again."
)

QUOTA_EXCEEDED_MESSAGE = (
	"Your AI API quota has been exceeded. Please check your API plan "
	"and billing details with your AI provider, or try again later."
)

AUTH_ERROR_MESSAGE = (
	"Authentication failed with the AI provider. Please check that your API key is valid in Chatbot Settings."
)

ENDPOINT_NOT_FOUND_MESSAGE = (
	"The AI provider endpoint was not found (404). This usually means the configured "
	"Base URL or model name in Chatbot Settings is incorrect. "
	"Please verify the provider's API endpoint and model name."
)

SERVER_ERROR_MESSAGE = (
	"The AI provider returned a server error. Please try again in a few moments."
)

CONNECTION_ERROR_MESSAGE = (
	"Could not reach the AI provider. Please check your network connection and "
	"the Base URL configured in Chatbot Settings."
)

GENERIC_PROVIDER_MESSAGE = (
	"The AI provider returned an unexpected error. Check the Error Log in the desk for details."
)


def classify_api_error(error: requests.exceptions.RequestException) -> str:
	"""Classify an API error and return a user-friendly message.

	Maps known HTTP status codes (429, 401/403, 404, 5xx) and network errors
	to short, actionable messages. The raw error is always preserved in the
	server-side Error Log via ``log_provider_error`` — the string returned
	here is what the user sees in the UI, so it must stay safe to display.
	"""
	status_code = None
	response_body = ""

	if hasattr(error, "response") and error.response is not None:
		status_code = error.response.status_code
		try:
			response_body = error.response.text or ""
		except Exception:
			pass

	body_lower = response_body.lower()

	# Billing / credit / quota issues — Anthropic returns 400, OpenAI returns 429
	if "credit balance" in body_lower or "billing" in body_lower or "purchase credits" in body_lower:
		return QUOTA_EXCEEDED_MESSAGE

	if status_code == 429:
		if "quota" in body_lower or "exceeded" in body_lower:
			return QUOTA_EXCEEDED_MESSAGE
		return RATE_LIMIT_MESSAGE

	if status_code in (401, 403):
		return AUTH_ERROR_MESSAGE

	if status_code == 404:
		return ENDPOINT_NOT_FOUND_MESSAGE

	if status_code and 500 <= status_code < 600:
		return SERVER_ERROR_MESSAGE

	# Network failures (DNS, refused, timeout) have no response attached.
	if isinstance(error, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
		return CONNECTION_ERROR_MESSAGE

	# Unknown error — don't leak the raw URL/stack to the UI.
	return GENERIC_PROVIDER_MESSAGE


def _extract_error_details(error: requests.exceptions.RequestException) -> tuple[int, float | None]:
	"""Extract HTTP status code and Retry-After value from a request error.

	Returns:
		Tuple of (status_code, retry_after_seconds). status_code is 0 if
		not available, retry_after is None if not present.
	"""
	status_code = 0
	retry_after = None

	if hasattr(error, "response") and error.response is not None:
		status_code = error.response.status_code
		header = error.response.headers.get("Retry-After")
		if header:
			try:
				retry_after = float(header)
			except (ValueError, TypeError):
				pass

	return status_code, retry_after


def _raise_provider_api_error(provider_name: str, error: requests.exceptions.RequestException):
	"""Raise a ProviderAPIError with status code and retry-after extracted from the response.

	This replaces frappe.throw() in provider chat_completion() methods so the
	resilience layer can catch, classify, and potentially retry the call.
	"""
	status_code, retry_after = _extract_error_details(error)
	raise ProviderAPIError(
		provider_name,
		status_code=status_code,
		message=classify_api_error(error),
		retry_after=retry_after,
		original_error=error,
	)


class AIProvider:
	"""Base class for AI providers"""

	def __init__(self, settings):
		self.settings = settings

	def chat_completion(self, messages, tools=None, stream=False):
		raise NotImplementedError

	def chat_completion_stream(self, messages, tools=None):
		"""Yield structured streaming events.

		Yields dicts with keys:
			type: "token" | "tool_call" | "finish"
			content: str (for token events)
			tool_call: dict (for tool_call events, contains id, name, arguments)
			finish_reason: str (for finish events)
		"""
		raise NotImplementedError

	def validate_settings(self):
		raise NotImplementedError


class OpenAIProvider(AIProvider):
	"""OpenAI API Integration"""

	provider_name = "OpenAI"

	def __init__(self, settings):
		super().__init__(settings)
		self.api_key = settings.get("api_key")
		self.model = settings.get("model") or DEFAULT_MODELS["OpenAI"]
		self.temperature = settings.get("temperature") or 0.7
		self.max_tokens = settings.get("max_tokens") or 4000
		self.base_url = "https://api.openai.com/v1"

	def validate_settings(self):
		if not self.api_key:
			frappe.throw("API Key is required for OpenAI")
		return True

	def _auth_headers(self) -> dict:
		"""Auth headers for this provider. Subclasses override for non-bearer schemes."""
		return {"Authorization": f"Bearer {self.api_key}"}

	def _endpoint_url(self) -> str:
		"""Full chat-completions URL. Subclasses override for non-standard layouts."""
		return f"{self.base_url}/chat/completions"

	def _request_kwargs(self) -> dict:
		"""Extra kwargs (e.g. query params) for requests.post. Subclasses override."""
		return {}

	def chat_completion(self, messages, tools=None, stream=False):
		"""OpenAI Chat Completion (non-streaming)"""
		self.validate_settings()

		headers = {**self._auth_headers(), "Content-Type": "application/json"}

		payload = {
			"model": self.model,
			"messages": messages,
			"temperature": self.temperature,
			"max_tokens": self.max_tokens,
			"stream": False,
		}

		if tools:
			payload["tools"] = tools
			payload["tool_choice"] = "auto"

		try:
			response = requests.post(
				self._endpoint_url(),
				headers=headers,
				json=payload,
				timeout=120,
				**self._request_kwargs(),
			)
			response.raise_for_status()
			return response.json()

		except requests.exceptions.RequestException as e:
			log_provider_error(self.provider_name, e)
			_raise_provider_api_error(self.provider_name, e)

	def chat_completion_stream(self, messages, tools=None):
		"""Yield structured streaming events from OpenAI.

		Handles both text content and tool calls during streaming.
		"""
		self.validate_settings()

		headers = {**self._auth_headers(), "Content-Type": "application/json"}

		payload = {
			"model": self.model,
			"messages": messages,
			"temperature": self.temperature,
			"max_tokens": self.max_tokens,
			"stream": True,
			"stream_options": {"include_usage": True},
		}

		if tools:
			payload["tools"] = tools
			payload["tool_choice"] = "auto"

		try:
			response = requests.post(
				self._endpoint_url(),
				headers=headers,
				json=payload,
				stream=True,
				timeout=120,
				**self._request_kwargs(),
			)
			response.raise_for_status()

			# Accumulate tool call chunks
			tool_calls_acc = {}

			for line in response.iter_lines():
				if not line:
					continue
				line = line.decode("utf-8")
				if not line.startswith("data: "):
					continue
				data = line[6:]
				if data == "[DONE]":
					break

				try:
					chunk = json.loads(data)
				except json.JSONDecodeError:
					continue

				# Usage data arrives in the final chunk (choices may be empty)
				if chunk.get("usage"):
					usage = chunk["usage"]
					yield {
						"type": "usage",
						"prompt_tokens": usage.get("prompt_tokens", 0),
						"completion_tokens": usage.get("completion_tokens", 0),
					}

				choice = chunk.get("choices", [{}])[0]
				delta = choice.get("delta", {})
				finish_reason = choice.get("finish_reason")

				# Text content
				if delta.get("content"):
					yield {"type": "token", "content": delta["content"]}

				# Tool call chunks (streamed incrementally)
				if delta.get("tool_calls"):
					for i, tc in enumerate(delta["tool_calls"]):
						idx = tc.get("index", i)
						if idx not in tool_calls_acc:
							tool_calls_acc[idx] = {
								"id": tc.get("id", ""),
								"name": "",
								"arguments": "",
							}
						if tc.get("id"):
							tool_calls_acc[idx]["id"] = tc["id"]
						if tc.get("function", {}).get("name"):
							tool_calls_acc[idx]["name"] = tc["function"]["name"]
						if tc.get("function", {}).get("arguments"):
							tool_calls_acc[idx]["arguments"] += tc["function"]["arguments"]

				# Stream finished
				if finish_reason:
					# Emit accumulated tool calls
					if finish_reason in ("tool_calls", "stop") and tool_calls_acc:
						for _idx, tc_data in sorted(tool_calls_acc.items()):
							try:
								args = json.loads(tc_data["arguments"])
							except json.JSONDecodeError:
								args = {}
							yield {
								"type": "tool_call",
								"tool_call": {
									"id": tc_data["id"],
									"name": tc_data["name"],
									"arguments": args,
								},
							}

					yield {"type": "finish", "finish_reason": finish_reason}

		except requests.exceptions.RequestException as e:
			log_provider_error(self.provider_name, e)
			status_code, retry_after = _extract_error_details(e)
			yield {
				"type": "error",
				"content": classify_api_error(e),
				"status_code": status_code,
				"retry_after": retry_after,
			}


class GeminiProvider(OpenAIProvider):
	"""Google Gemini provider via OpenAI-compatible endpoint.

	Gemini exposes an OpenAI-compatible /chat/completions API at
	generativelanguage.googleapis.com, so we extend OpenAIProvider
	and only override the base URL and defaults.

	Known Gemini differences from OpenAI:
	- Tool call streaming chunks may omit ``index`` field (handled by
	  OpenAIProvider with fallback ``tc.get("index", i)``).
	- After tool results are sent back, Gemini may occasionally return
	  another tool call instead of text content — the multi-round loop
	  in streaming.py handles this with ``max_tool_rounds``.
	"""

	provider_name = "Gemini"

	def __init__(self, settings):
		# Skip OpenAIProvider.__init__ — set fields directly
		AIProvider.__init__(self, settings)
		self.api_key = settings.get("api_key")
		self.model = settings.get("model") or DEFAULT_MODELS["Gemini"]
		self.temperature = settings.get("temperature") or 1.0
		self.max_tokens = settings.get("max_tokens") or 8192
		self.base_url = "https://generativelanguage.googleapis.com/v1beta/openai"

	def validate_settings(self):
		if not self.api_key:
			frappe.throw("API Key is required for Gemini")
		return True

	def chat_completion_stream(self, messages, tools=None):
		"""Yield streaming events from Gemini (OpenAI-compatible).

		Wraps parent with diagnostic logging so empty responses are visible
		in the log file for debugging.
		"""
		from ai_chatbot.core.logger import log_error, log_info

		has_content = False
		has_tool_calls = False
		has_error = False

		for event in super().chat_completion_stream(messages, tools=tools):
			etype = event.get("type")
			if etype == "token":
				has_content = True
			elif etype == "tool_call":
				has_tool_calls = True
			elif etype == "error":
				has_error = True
				log_error(
					f"Gemini stream error: {event.get('content', '')}",
					title="Gemini Streaming",
				)
			yield event

		if not has_content and not has_tool_calls and not has_error:
			log_error(
				"Gemini stream returned no content and no tool calls. "
				f"Model={self.model}, messages={len(messages)}, "
				f"tools={'yes' if tools else 'no'}",
				title="Gemini Empty Stream",
			)


AZURE_OPENAI_DEFAULT_API_VERSION = "2024-08-01-preview"


class AzureOpenAIProvider(OpenAIProvider):
	"""Azure OpenAI Service provider.

	Uses the OpenAI Chat Completions wire format but with three differences:
	- Endpoint URL is per-deployment: https://{resource}.openai.azure.com/openai/deployments/{deployment}
	- Auth header is ``api-key: <key>`` (not bearer)
	- An ``api-version`` query parameter is required on every request

	The deployment name takes the place of the model identifier — Azure routes by
	deployment, not by model. If the user leaves the ``model`` field blank, we
	send the deployment name as the model in the body for compatibility.
	"""

	provider_name = "Azure OpenAI"

	def __init__(self, settings):
		# Skip OpenAIProvider.__init__ — we set fields ourselves
		AIProvider.__init__(self, settings)
		self.api_key = settings.get("api_key")
		self.resource = settings.get("azure_resource_name")
		self.deployment = settings.get("azure_deployment_name")
		self.api_version = settings.get("azure_api_version") or AZURE_OPENAI_DEFAULT_API_VERSION
		# Azure routes by deployment in the URL; model in body is informational only.
		self.model = settings.get("model") or self.deployment
		self.temperature = settings.get("temperature") or 0.7
		self.max_tokens = settings.get("max_tokens") or 4000
		self.base_url = (
			f"https://{self.resource}.openai.azure.com/openai/deployments/{self.deployment}"
			if self.resource and self.deployment
			else ""
		)

	def validate_settings(self):
		if not self.api_key:
			frappe.throw("API Key is required for Azure OpenAI")
		if not self.resource:
			frappe.throw("Azure Resource Name is required (the prefix in https://<resource>.openai.azure.com).")
		if not self.deployment:
			frappe.throw("Azure Deployment Name is required (the deployment you created in Azure OpenAI Studio).")
		return True

	def _auth_headers(self) -> dict:
		return {"api-key": self.api_key}

	def _request_kwargs(self) -> dict:
		return {"params": {"api-version": self.api_version}}


LOCAL_LLM_PROVIDER = "Local LLM (OpenAI-compatible)"
DEFAULT_LOCAL_LLM_BASE_URL = "http://localhost:11434/v1"


class LocalLLMProvider(OpenAIProvider):
	"""Local / self-hosted OpenAI-compatible LLM provider.

	Works with any server that speaks the OpenAI Chat Completions wire format on
	a configurable base URL — Ollama (http://localhost:11434/v1), LM Studio,
	vLLM, llama.cpp's server, LiteLLM, etc.

	Differences from the cloud OpenAI provider:
	- base_url is user-configured (no fixed default endpoint)
	- the API key is optional; the Authorization header is only sent when a key
	  is provided (Ollama needs none; secured proxies may require one)
	"""

	provider_name = LOCAL_LLM_PROVIDER

	def __init__(self, settings):
		# Skip OpenAIProvider.__init__ — we set fields ourselves
		AIProvider.__init__(self, settings)
		self.api_key = settings.get("api_key")
		self.model = settings.get("model")
		self.temperature = settings.get("temperature") or 0.7
		self.max_tokens = settings.get("max_tokens") or 4000
		self.base_url = (settings.get("local_llm_base_url") or DEFAULT_LOCAL_LLM_BASE_URL).rstrip("/")

	def validate_settings(self):
		if not self.base_url:
			frappe.throw("Base URL is required for a Local LLM (e.g. http://localhost:11434/v1).")
		if not self.model:
			frappe.throw("Model is required for a Local LLM (the model you pulled, e.g. 'llama3.1').")
		return True

	def _auth_headers(self) -> dict:
		# Local servers (e.g. Ollama) need no auth; only send a bearer token if one is set.
		return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}


class ClaudeProvider(AIProvider):
	"""Anthropic Claude API Integration"""

	def __init__(self, settings):
		super().__init__(settings)
		self.api_key = settings.get("api_key")
		self.model = settings.get("model") or DEFAULT_MODELS["Claude"]
		self.temperature = settings.get("temperature") or 0.7
		self.max_tokens = settings.get("max_tokens") or 4000
		self.base_url = "https://api.anthropic.com/v1"
		self.api_version = "2023-06-01"

	def validate_settings(self):
		if not self.api_key:
			frappe.throw("API Key is required for Claude")
		return True

	def chat_completion(self, messages, tools=None, stream=False):
		"""Claude Messages API (non-streaming)"""
		self.validate_settings()

		headers = {
			"x-api-key": self.api_key,
			"anthropic-version": self.api_version,
			"Content-Type": "application/json",
		}

		claude_messages = self._convert_messages_to_claude(messages)
		system_message = self._extract_system_message(messages)

		# Enable prompt caching when system message uses content blocks
		if isinstance(system_message, list):
			headers["anthropic-beta"] = "prompt-caching-2024-07-31"

		payload = {
			"model": self.model,
			"messages": claude_messages,
			"max_tokens": self.max_tokens,
			"temperature": self.temperature,
			"stream": False,
		}

		if system_message:
			payload["system"] = system_message

		if tools:
			payload["tools"] = self._convert_tools_to_claude(tools)

		try:
			response = requests.post(
				f"{self.base_url}/messages",
				headers=headers,
				json=payload,
				timeout=120,
			)
			response.raise_for_status()
			return response.json()

		except requests.exceptions.RequestException as e:
			log_provider_error("Claude", e)
			_raise_provider_api_error("Claude", e)

	def chat_completion_stream(self, messages, tools=None):
		"""Yield structured streaming events from Claude.

		Claude SSE event types:
			message_start, content_block_start, content_block_delta,
			content_block_stop, message_delta, message_stop
		"""
		self.validate_settings()

		headers = {
			"x-api-key": self.api_key,
			"anthropic-version": self.api_version,
			"Content-Type": "application/json",
		}

		claude_messages = self._convert_messages_to_claude(messages)
		system_message = self._extract_system_message(messages)

		# Enable prompt caching when system message uses content blocks
		if isinstance(system_message, list):
			headers["anthropic-beta"] = "prompt-caching-2024-07-31"

		payload = {
			"model": self.model,
			"messages": claude_messages,
			"max_tokens": self.max_tokens,
			"temperature": self.temperature,
			"stream": True,
		}

		if system_message:
			payload["system"] = system_message

		if tools:
			payload["tools"] = self._convert_tools_to_claude(tools)

		try:
			response = requests.post(
				f"{self.base_url}/messages",
				headers=headers,
				json=payload,
				stream=True,
				timeout=120,
			)
			response.raise_for_status()

			# Track content blocks for tool calls
			current_block_type = None
			current_tool_name = None
			current_tool_id = None
			tool_input_json = ""

			# Accumulate usage across message_start and message_delta
			usage_prompt = 0
			usage_completion = 0

			for line in response.iter_lines():
				if not line:
					continue
				line = line.decode("utf-8")
				if not line.startswith("data: "):
					continue
				data = line[6:]

				try:
					event = json.loads(data)
				except json.JSONDecodeError:
					continue

				event_type = event.get("type")

				if event_type == "message_start":
					# message_start contains input token count
					msg_usage = event.get("message", {}).get("usage", {})
					usage_prompt = msg_usage.get("input_tokens", 0)

				elif event_type == "content_block_start":
					block = event.get("content_block", {})
					current_block_type = block.get("type")
					if current_block_type == "tool_use":
						current_tool_name = block.get("name", "")
						current_tool_id = block.get("id", "")
						tool_input_json = ""

				elif event_type == "content_block_delta":
					delta = event.get("delta", {})
					delta_type = delta.get("type")

					if delta_type == "text_delta":
						yield {"type": "token", "content": delta.get("text", "")}

					elif delta_type == "input_json_delta":
						tool_input_json += delta.get("partial_json", "")

				elif event_type == "content_block_stop":
					if current_block_type == "tool_use" and current_tool_name:
						try:
							args = json.loads(tool_input_json) if tool_input_json else {}
						except json.JSONDecodeError:
							args = {}
						yield {
							"type": "tool_call",
							"tool_call": {
								"id": current_tool_id,
								"name": current_tool_name,
								"arguments": args,
							},
						}
					current_block_type = None
					current_tool_name = None
					current_tool_id = None
					tool_input_json = ""

				elif event_type == "message_delta":
					# message_delta contains output token count
					delta_usage = event.get("usage", {})
					usage_completion = delta_usage.get("output_tokens", 0)

					stop_reason = event.get("delta", {}).get("stop_reason")
					if stop_reason:
						yield {
							"type": "usage",
							"prompt_tokens": usage_prompt,
							"completion_tokens": usage_completion,
						}
						yield {"type": "finish", "finish_reason": stop_reason}

				elif event_type == "message_stop":
					pass  # Already handled via message_delta

		except requests.exceptions.RequestException as e:
			log_provider_error("Claude", e)
			status_code, retry_after = _extract_error_details(e)
			yield {
				"type": "error",
				"content": classify_api_error(e),
				"status_code": status_code,
				"retry_after": retry_after,
			}

	def _convert_messages_to_claude(self, messages):
		"""Convert OpenAI message format to Claude format"""
		claude_messages = []
		for msg in messages:
			if msg["role"] == "system":
				continue
			if msg["role"] == "tool":
				# Claude expects tool results as user messages with tool_result content
				claude_messages.append(
					{
						"role": "user",
						"content": [
							{
								"type": "tool_result",
								"tool_use_id": msg.get("tool_call_id", ""),
								"content": msg.get("content", ""),
							}
						],
					}
				)
			elif msg["role"] == "assistant" and msg.get("tool_calls"):
				# Convert assistant tool_calls to Claude format
				content = []
				if msg.get("content"):
					content.append({"type": "text", "text": msg["content"]})
				for tc in msg["tool_calls"]:
					func = tc.get("function", tc)
					try:
						args = (
							json.loads(func["arguments"])
							if isinstance(func.get("arguments"), str)
							else func.get("arguments", {})
						)
					except json.JSONDecodeError:
						args = {}
					content.append(
						{
							"type": "tool_use",
							"id": tc.get("id", ""),
							"name": func.get("name", ""),
							"input": args,
						}
					)
				claude_messages.append({"role": "assistant", "content": content})
			else:
				content = msg.get("content", "")
				if isinstance(content, list):
					# Multi-modal content (vision) — convert from OpenAI to Claude format
					claude_content = []
					for part in content:
						if part.get("type") == "text":
							claude_content.append({"type": "text", "text": part["text"]})
						elif part.get("type") == "image_url":
							# Extract base64 from data URL: "data:image/jpeg;base64,/9j/..."
							data_url = part["image_url"]["url"]
							header, b64_data = data_url.split(",", 1)
							media_type = header.split(":")[1].split(";")[0]
							claude_content.append(
								{
									"type": "image",
									"source": {
										"type": "base64",
										"media_type": media_type,
										"data": b64_data,
									},
								}
							)
					claude_messages.append({"role": "user", "content": claude_content})
				else:
					claude_messages.append({"role": msg["role"], "content": content})
		return claude_messages

	def _extract_system_message(self, messages):
		"""Extract system message from messages list.

		If the system message carries _prompt_blocks metadata (from structured
		prompting), builds an array of Claude content blocks with cache_control
		markers on static blocks. Otherwise returns a plain string.
		"""
		for msg in messages:
			if msg["role"] == "system":
				blocks = msg.get("_prompt_blocks")
				if blocks:
					return self._build_cached_system_blocks(blocks)
				return msg["content"]
		return ""

	def _build_cached_system_blocks(self, blocks: list[dict]) -> list[dict]:
		"""Convert prompt blocks into Claude content blocks with cache_control.

		Static blocks (cacheable=True) get cache_control markers. Claude caches
		all content up to the last block that has cache_control, so we place the
		marker on the last cacheable block.

		Args:
			blocks: List of dicts with tag, content, cacheable keys.

		Returns:
			List of Claude system content blocks.
		"""
		content_blocks = []

		# Find the last cacheable block index
		last_cacheable_idx = -1
		for i, block in enumerate(blocks):
			if block.get("cacheable", False):
				last_cacheable_idx = i

		for i, block in enumerate(blocks):
			tag = block["tag"]
			text = f"<{tag}>\n{block['content']}\n</{tag}>"
			cb = {"type": "text", "text": text}
			if i == last_cacheable_idx:
				cb["cache_control"] = {"type": "ephemeral"}
			content_blocks.append(cb)

		return content_blocks

	def _convert_tools_to_claude(self, tools):
		"""Convert OpenAI tool format to Claude format.

		Adds cache_control on the last tool so Claude caches the entire
		tool schema prefix (~8K-12K tokens saved per request).
		"""
		claude_tools = []
		for tool in tools:
			if tool.get("type") == "function":
				func = tool["function"]
				claude_tools.append(
					{
						"name": func["name"],
						"description": func.get("description", ""),
						"input_schema": func.get("parameters", {}),
					}
				)

		# Mark the last tool for caching (Claude caches everything up to the marker)
		if claude_tools:
			claude_tools[-1]["cache_control"] = {"type": "ephemeral"}

		return claude_tools


def _resolve_settings(provider_name: str) -> dict:
	"""Build a unified settings dict for the given provider."""
	settings = frappe.get_single("Chatbot Settings")
	sd = settings.as_dict()

	api_key = settings.get_password("api_key") if sd.get("api_key") else None

	resolved = {
		"api_key": api_key,
		"model": sd.get("model") or DEFAULT_MODELS.get(provider_name),
		"temperature": sd.get("temperature") or 0.7,
		"max_tokens": sd.get("max_tokens") or 4000,
	}

	if provider_name == "Azure OpenAI":
		resolved["azure_resource_name"] = sd.get("azure_resource_name")
		resolved["azure_deployment_name"] = sd.get("azure_deployment_name")
		resolved["azure_api_version"] = sd.get("azure_api_version")

	if provider_name == LOCAL_LLM_PROVIDER:
		resolved["local_llm_base_url"] = sd.get("local_llm_base_url")

	return resolved


def get_ai_provider(provider_name: str) -> AIProvider:
	"""Factory function to get AI provider instance."""
	resolved = _resolve_settings(provider_name)

	if provider_name == "OpenAI":
		return OpenAIProvider(resolved)
	elif provider_name == "Claude":
		return ClaudeProvider(resolved)
	elif provider_name == "Gemini":
		return GeminiProvider(resolved)
	elif provider_name == "Azure OpenAI":
		return AzureOpenAIProvider(resolved)
	elif provider_name == LOCAL_LLM_PROVIDER:
		return LocalLLMProvider(resolved)
	else:
		frappe.throw(f"Unknown AI provider: {provider_name}")


def get_summary_provider(provider_name: str) -> AIProvider:
	"""Get a cheap/fast AI provider for auxiliary tasks (conversation summarisation).

	Uses the same provider family as the conversation but picks the cheapest
	model to minimise cost. Short max_tokens and low temperature for factual summaries.

	Args:
		provider_name: The conversation's AI provider (OpenAI/Claude/Gemini).

	Returns:
		AIProvider instance configured for summarisation.
	"""
	resolved = _resolve_settings(provider_name)
	# For Azure there's no separate "cheap" deployment — fall through to the configured one.
	summary_model = SUMMARY_MODELS.get(provider_name)
	if summary_model:
		resolved["model"] = summary_model
	resolved["max_tokens"] = 500
	resolved["temperature"] = 0.3

	if provider_name == "OpenAI":
		return OpenAIProvider(resolved)
	elif provider_name == "Claude":
		return ClaudeProvider(resolved)
	elif provider_name == "Gemini":
		return GeminiProvider(resolved)
	elif provider_name == "Azure OpenAI":
		return AzureOpenAIProvider(resolved)
	elif provider_name == LOCAL_LLM_PROVIDER:
		return LocalLLMProvider(resolved)
	else:
		frappe.throw(f"Unknown provider for summarisation: {provider_name}")


def get_fallback_provider(primary_provider_name: str) -> AIProvider | None:
	"""Get the fallback AI provider, if configured in Chatbot Settings.

	Returns None if no fallback is configured or if the fallback provider
	is the same as the primary.

	Args:
		primary_provider_name: The primary provider name (OpenAI/Claude/Gemini).

	Returns:
		AIProvider instance or None.
	"""
	try:
		settings = frappe.get_single("Chatbot Settings")
		fallback_name = getattr(settings, "fallback_provider", None)
		if not fallback_name or fallback_name == primary_provider_name:
			return None

		fallback_api_key = (
			settings.get_password("fallback_api_key") if getattr(settings, "fallback_api_key", None) else None
		)
		# A Local LLM fallback may run without an API key; all others require one.
		if not fallback_api_key and fallback_name != LOCAL_LLM_PROVIDER:
			return None

		resolved = {
			"api_key": fallback_api_key,
			"model": getattr(settings, "fallback_model", None) or DEFAULT_MODELS.get(fallback_name),
			"temperature": settings.as_dict().get("temperature") or 0.7,
			"max_tokens": settings.as_dict().get("max_tokens") or 4000,
		}

		if fallback_name == "Azure OpenAI":
			resolved["azure_resource_name"] = getattr(settings, "fallback_azure_resource_name", None)
			resolved["azure_deployment_name"] = getattr(settings, "fallback_azure_deployment_name", None)
			resolved["azure_api_version"] = getattr(settings, "fallback_azure_api_version", None)

		if fallback_name == LOCAL_LLM_PROVIDER:
			resolved["local_llm_base_url"] = getattr(settings, "fallback_local_llm_base_url", None)

		if fallback_name == "OpenAI":
			return OpenAIProvider(resolved)
		elif fallback_name == "Claude":
			return ClaudeProvider(resolved)
		elif fallback_name == "Gemini":
			return GeminiProvider(resolved)
		elif fallback_name == "Azure OpenAI":
			return AzureOpenAIProvider(resolved)
		elif fallback_name == LOCAL_LLM_PROVIDER:
			return LocalLLMProvider(resolved)
	except Exception:
		pass

	return None
