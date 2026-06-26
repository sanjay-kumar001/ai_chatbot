# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
Audit Trail Module

Provides structured audit logging for every AI interaction, tool
invocation, and write operation.  Events are inserted asynchronously
via ``frappe.enqueue`` to avoid blocking the chat response.
"""

from __future__ import annotations

import json

import frappe


def log_audit_event(
	event_type: str,
	*,
	conversation: str | None = None,
	message: str | None = None,
	tool_name: str | None = None,
	tool_args: dict | None = None,
	tool_result_summary: str | None = None,
	provider: str | None = None,
	model: str | None = None,
	tokens: tuple[int, int] | None = None,
	cost: float | None = None,
	duration_ms: int | None = None,
	status: str = "success",
	error_message: str | None = None,
	user: str | None = None,
) -> None:
	"""Queue an audit log entry for background insertion.

	This function never raises — errors are silently logged to avoid
	disrupting the chat response flow.

	Args:
		event_type: One of llm_request, tool_call, tool_result,
			crud_operation, error, rate_limit_hit.
		conversation: Chatbot Conversation document name.
		message: Chatbot Message document name.
		tool_name: Name of the executed tool (nullable).
		tool_args: Tool arguments dict (sanitised — no passwords).
		tool_result_summary: Truncated summary of the tool result.
		provider: AI provider name (e.g. "OpenAI", "Claude", "Gemini").
		model: Model identifier string.
		tokens: Tuple of (prompt_tokens, completion_tokens).
		cost: Estimated cost in USD.
		duration_ms: Duration of the operation in milliseconds.
		status: One of success, error, timeout, rate_limited.
		error_message: Error description (nullable).
		user: User who triggered the event.  Defaults to session user.
	"""
	try:
		prompt_tokens = tokens[0] if tokens else 0
		completion_tokens = tokens[1] if tokens else 0

		# Resolve user and IP address
		resolved_user = user or getattr(frappe.session, "user", "Guest")
		ip_address = frappe.local.request.remote_addr if getattr(frappe.local, "request", None) else None

		# Sanitise tool_args — remove sensitive keys
		sanitised_args = _sanitise_args(tool_args) if tool_args else None

		# Truncate tool_result_summary to 500 chars
		if tool_result_summary and len(tool_result_summary) > 500:
			tool_result_summary = tool_result_summary[:497] + "..."

		# Truncate error_message to 1000 chars
		if error_message and len(error_message) > 1000:
			error_message = error_message[:997] + "..."

		frappe.enqueue(
			_insert_audit_log,
			queue="short",
			now=frappe.flags.in_test,
			event_type=event_type,
			conversation=conversation,
			message=message,
			tool_name=tool_name,
			tool_args=sanitised_args,
			tool_result_summary=tool_result_summary,
			provider=provider,
			model=model,
			prompt_tokens=prompt_tokens,
			completion_tokens=completion_tokens,
			cost=cost or 0.0,
			duration_ms=duration_ms or 0,
			status=status,
			error_message=error_message,
			user=resolved_user,
			ip_address=ip_address,
		)
	except Exception:
		# Never let audit logging break the main flow
		frappe.log_error("Audit log enqueue failed", "AI Chatbot Audit")


def _insert_audit_log(
	event_type: str,
	conversation: str | None,
	message: str | None,
	tool_name: str | None,
	tool_args: dict | None,
	tool_result_summary: str | None,
	provider: str | None,
	model: str | None,
	prompt_tokens: int,
	completion_tokens: int,
	cost: float,
	duration_ms: int,
	status: str,
	error_message: str | None,
	user: str,
	ip_address: str | None,
) -> None:
	"""Background worker — inserts a Chatbot Audit Log document."""
	try:
		doc = frappe.get_doc(
			{
				"doctype": "Chatbot Audit Log",
				"event_type": event_type,
				"status": status,
				"user": user,
				"ip_address": ip_address,
				"conversation": conversation,
				"message": message,
				"duration_ms": duration_ms,
				"provider": provider,
				"model": model,
				"prompt_tokens": prompt_tokens,
				"completion_tokens": completion_tokens,
				"cost": cost,
				"tool_name": tool_name,
				"tool_args": json.dumps(tool_args, default=str) if tool_args else None,
				"tool_result_summary": tool_result_summary,
				"error_message": error_message,
			}
		)
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error("Audit log insert failed", "AI Chatbot Audit")


def cleanup_old_audit_logs(days: int = 90) -> int:
	"""Delete audit log entries older than the given number of days.

	Called by a scheduled task.  Returns the number of deleted records.
	"""
	cutoff = frappe.utils.add_days(frappe.utils.today(), -days)
	old_logs = frappe.get_all(
		"Chatbot Audit Log",
		filters={"creation": ["<", cutoff]},
		pluck="name",
		limit_page_length=5000,
	)

	for name in old_logs:
		frappe.delete_doc("Chatbot Audit Log", name, force=True, ignore_permissions=True)

	if old_logs:
		frappe.db.commit()

	return len(old_logs)


def _sanitise_args(args: dict) -> dict:
	"""Remove sensitive keys from tool arguments before storing."""
	sensitive_keys = {"password", "api_key", "secret", "token", "credential", "auth"}
	sanitised = {}
	for key, value in args.items():
		if any(s in key.lower() for s in sensitive_keys):
			sanitised[key] = "***REDACTED***"
		else:
			sanitised[key] = value
	return sanitised
