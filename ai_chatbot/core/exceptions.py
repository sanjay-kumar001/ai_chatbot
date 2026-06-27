# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
Custom Exceptions for AI Chatbot
"""


class ChatbotError(Exception):
	"""Base exception for all chatbot errors"""

	def __init__(self, message="An error occurred in the AI Chatbot", error_code=None):
		self.message = message
		self.error_code = error_code
		super().__init__(self.message)


class ToolExecutionError(ChatbotError):
	"""Raised when a tool fails to execute"""

	def __init__(self, tool_name, message=None, original_error=None):
		self.tool_name = tool_name
		self.original_error = original_error
		msg = message or f"Tool '{tool_name}' failed to execute"
		if original_error:
			msg += f": {original_error}"
		super().__init__(msg, error_code="TOOL_EXECUTION_ERROR")


class ProviderError(ChatbotError):
	"""Raised when an AI provider fails.

	``message`` is the user-facing summary (already classified — safe to
	surface in the UI). ``original_error`` is kept on the instance for
	server-side logging only; it is NOT appended to the user message,
	so raw provider URLs and stack details do not leak to the chat UI.
	"""

	def __init__(self, provider_name, message=None, original_error=None):
		self.provider_name = provider_name
		self.original_error = original_error
		if message:
			msg = message
		elif original_error:
			msg = f"AI provider '{provider_name}' failed: {original_error}"
		else:
			msg = f"AI provider '{provider_name}' failed"
		super().__init__(msg, error_code="PROVIDER_ERROR")


class CompanyRequiredError(ChatbotError):
	"""Raised when a company is required but not provided or configured"""

	def __init__(self):
		super().__init__(
			"No company specified and no default company set for the current user. "
			"Please specify a company or set a default company in your user settings.",
			error_code="COMPANY_REQUIRED",
		)


class ToolNotFoundError(ChatbotError):
	"""Raised when a requested tool does not exist in the registry"""

	def __init__(self, tool_name):
		self.tool_name = tool_name
		super().__init__(f"Tool '{tool_name}' not found in the registry", error_code="TOOL_NOT_FOUND")


class DocumentValidationError(ChatbotError):
	"""Raised when document validation fails (missing fields, invalid links, etc.)"""

	def __init__(self, doctype, errors):
		self.doctype = doctype
		self.errors = errors
		msg = f"Validation failed for {doctype}: {', '.join(errors)}"
		super().__init__(msg, error_code="DOCUMENT_VALIDATION_ERROR")


class InsufficientDataError(ChatbotError):
	"""Raised when there is not enough historical data for forecasting"""

	def __init__(self, required_months, available_months):
		self.required_months = required_months
		self.available_months = available_months
		super().__init__(
			f"Insufficient historical data for forecasting. "
			f"Need at least {required_months} months, but only {available_months} available.",
			error_code="INSUFFICIENT_DATA",
		)


class ProviderAPIError(ProviderError):
	"""Raised when an AI provider API call fails with a classifiable HTTP error.

	Carries the HTTP status code and optional Retry-After value so the
	resilience layer can decide whether to retry.
	"""

	def __init__(self, provider_name, status_code, message=None, retry_after=None, original_error=None):
		self.status_code = status_code
		self.retry_after = retry_after  # seconds (from Retry-After header)
		super().__init__(provider_name, message=message, original_error=original_error)


class CircuitBreakerOpenError(ChatbotError):
	"""Raised when the circuit breaker is open for a provider."""

	def __init__(self, provider_name):
		self.provider_name = provider_name
		super().__init__(
			"The AI service is temporarily unavailable. Please try again in a few minutes.",
			error_code="CIRCUIT_BREAKER_OPEN",
		)
