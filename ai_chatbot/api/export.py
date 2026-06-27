# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
PDF Export API

Generates downloadable PDFs from chat messages and conversations
using WeasyPrint (with wkhtmltopdf fallback).

Reuses the HTML formatters from ``automation/formatters.py`` so that
tables and charts render identically to scheduled-report PDFs.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import nowdate

from ai_chatbot.automation.formatters import (
	_render_charts,
	_style_html_headings,
	_style_html_tables,
	format_html_email,
)
from ai_chatbot.core.logger import log_error

# ---------------------------------------------------------------------------
# Single message export
# ---------------------------------------------------------------------------


@frappe.whitelist()
def export_message_pdf(message_name: str) -> dict:
	"""Generate a PDF from a single Chatbot Message and return the file URL.

	Args:
		message_name: The Chatbot Message document name (e.g. ``MSG-00042``).

	Returns:
		``{"success": True, "file_url": "/files/...pdf"}`` on success,
		``{"success": False, "error": "..."}`` on failure.
	"""
	try:
		msg = frappe.get_doc("Chatbot Message", message_name)

		# Only the owning user may export their own messages
		conversation = frappe.get_doc("Chatbot Conversation", msg.conversation)
		if conversation.user != frappe.session.user:
			frappe.throw("You do not have permission to export this message.", frappe.PermissionError)

		# Build HTML for the single message
		tool_results = _parse_json_field(msg.tool_results)
		html = _build_message_html(
			content=msg.content or "",
			tool_results=tool_results,
			title=conversation.title or "Chat Export",
			company=_resolve_company(conversation),
		)

		# Generate PDF
		from ai_chatbot.utils.pdf import html_to_pdf

		pdf_bytes = html_to_pdf(html)

		# Save as a Frappe File so it can be downloaded
		safe_title = _safe_filename(conversation.title or "chat")
		fname = f"{safe_title}_{message_name}_{nowdate()}.pdf"

		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": fname,
				"content": pdf_bytes,
				"is_private": 1,
				"attached_to_doctype": "Chatbot Message",
				"attached_to_name": message_name,
			}
		)
		file_doc.save(ignore_permissions=True)
		frappe.db.commit()

		return {"success": True, "file_url": file_doc.file_url}

	except frappe.PermissionError:
		raise
	except Exception as e:
		log_error(
			f"PDF export failed for message {message_name}: {e!s}",
			title="PDF Export",
		)
		return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Full conversation export
# ---------------------------------------------------------------------------


@frappe.whitelist()
def export_conversation_pdf(conversation_id: str) -> dict:
	"""Generate a PDF containing all messages in a conversation.

	Args:
		conversation_id: The Chatbot Conversation document name.

	Returns:
		``{"success": True, "file_url": "/files/...pdf"}`` on success,
		``{"success": False, "error": "..."}`` on failure.
	"""
	try:
		conversation = frappe.get_doc("Chatbot Conversation", conversation_id)
		if conversation.user != frappe.session.user:
			frappe.throw("You do not have permission to export this conversation.", frappe.PermissionError)

		messages = frappe.get_all(
			"Chatbot Message",
			filters={"conversation": conversation_id, "role": ["in", ["user", "assistant"]]},
			fields=["role", "content", "tool_results", "timestamp"],
			order_by="timestamp asc",
		)

		if not messages:
			return {"success": False, "error": "No messages to export."}

		company = _resolve_company(conversation)
		html = _build_conversation_html(
			messages=messages,
			title=conversation.title or "Chat Export",
			company=company,
		)

		from ai_chatbot.utils.pdf import html_to_pdf

		pdf_bytes = html_to_pdf(html)

		safe_title = _safe_filename(conversation.title or "conversation")
		fname = f"{safe_title}_{conversation_id}_{nowdate()}.pdf"

		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": fname,
				"content": pdf_bytes,
				"is_private": 1,
				"attached_to_doctype": "Chatbot Conversation",
				"attached_to_name": conversation_id,
			}
		)
		file_doc.save(ignore_permissions=True)
		frappe.db.commit()

		return {"success": True, "file_url": file_doc.file_url}

	except frappe.PermissionError:
		raise
	except Exception as e:
		log_error(
			f"PDF export failed for conversation {conversation_id}: {e!s}",
			title="PDF Export",
		)
		return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_message_html(
	content: str,
	tool_results: list | None,
	title: str,
	company: str,
) -> str:
	"""Render a single assistant message as a complete HTML page for PDF.

	Delegates to the shared ``format_html_email`` formatter with
	``for_pdf=True`` so that ECharts are rendered as inline SVG.
	"""
	return format_html_email(
		content=content,
		tool_results=tool_results,
		report_name=title,
		company=company,
		for_pdf=True,
	)


def _build_conversation_html(
	messages: list[dict],
	title: str,
	company: str,
) -> str:
	"""Render a full conversation thread as HTML for PDF.

	Each message is rendered in a visually distinct block (user vs assistant)
	so the exported PDF reads like a chat transcript.
	"""
	from ai_chatbot.automation.formatters import (
		_fix_markdown_lists,
		_fix_markdown_structure,
		_markdown_to_html,
		_replace_hr_tags,
	)

	body_parts: list[str] = []

	for msg in messages:
		role = msg.get("role", "user")
		content = msg.get("content") or ""
		timestamp = msg.get("timestamp") or ""

		if role == "user":
			body_parts.append(_user_block(content, timestamp))
		else:
			# Assistant — render markdown + charts
			tool_results = _parse_json_field(msg.get("tool_results"))
			content = _fix_markdown_structure(content)
			content = _fix_markdown_lists(content)
			html_body = _markdown_to_html(content)
			html_body = _replace_hr_tags(html_body)
			html_body = _style_html_tables(html_body)
			html_body = _style_html_headings(html_body)

			charts_html = _render_charts(tool_results, as_svg=True)
			if charts_html:
				html_body += charts_html

			body_parts.append(_assistant_block(html_body, timestamp))

	body_html = "\n".join(body_parts)
	subtitle = f" — {company}" if company else ""
	today = nowdate()

	from ai_chatbot.automation.formatters import _PDF_STYLE_BLOCK

	return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{_PDF_STYLE_BLOCK}
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; \
font-size: 14px; line-height: 1.6; color: #333; text-align: left; max-width: 800px; margin: 0 auto; padding: 20px;">

<div style="background-color: #f8f9fa; border-bottom: 3px solid #4a90d9; padding: 20px; \
margin-bottom: 20px; border-radius: 4px 4px 0 0;">
<h2 style="margin: 0 0 5px; color: #2c3e50; text-align: left;">{title}</h2>
<p style="margin: 0; color: #7f8c8d; font-size: 14px;">{today}{subtitle}</p>
</div>

{body_html}

<div style="margin-top: 30px; padding-top: 15px; border-top: 1px solid #eee; \
color: #95a5a6; font-size: 12px;">
<p>Exported from AI Chatbot. Data reflects the state at the time of the original conversation.</p>
</div>

</body>
</html>"""


def _user_block(content: str, timestamp: str) -> str:
	"""Render a user message block for the conversation PDF."""
	ts_html = (
		f"<span style='font-size: 11px; color: #95a5a6; margin-left: 10px;'>{timestamp}</span>"
		if timestamp
		else ""
	)
	return (
		f"<div style='margin-bottom: 16px; padding: 12px 16px; "
		f"background-color: #f0f4f8; border-radius: 8px; border-left: 3px solid #a0aec0;'>"
		f"<div style='font-size: 12px; font-weight: 600; color: #4a5568; margin-bottom: 4px;'>"
		f"You{ts_html}</div>"
		f"<div style='color: #2d3748;'>{_escape_html(content)}</div>"
		f"</div>"
	)


def _assistant_block(html_content: str, timestamp: str) -> str:
	"""Render an assistant message block for the conversation PDF."""
	ts_html = (
		f"<span style='font-size: 11px; color: #95a5a6; margin-left: 10px;'>{timestamp}</span>"
		if timestamp
		else ""
	)
	return (
		f"<div style='margin-bottom: 16px; padding: 12px 16px; "
		f"background-color: #ffffff; border-radius: 8px; border-left: 3px solid #4a90d9;'>"
		f"<div style='font-size: 12px; font-weight: 600; color: #2b6cb0; margin-bottom: 4px;'>"
		f"AI Assistant{ts_html}</div>"
		f"<div>{html_content}</div>"
		f"</div>"
	)


def _parse_json_field(value) -> list | None:
	"""Parse a JSON string field into a list, returning None on failure."""
	if not value:
		return None
	if isinstance(value, list):
		return value
	if isinstance(value, str):
		try:
			parsed = json.loads(value)
			return parsed if isinstance(parsed, list) else [parsed]
		except Exception:
			return None
	return None


def _resolve_company(conversation) -> str:
	"""Extract the company from conversation session_context, or fall back to user default."""
	ctx = conversation.session_context
	if ctx:
		if isinstance(ctx, str):
			try:
				ctx = json.loads(ctx)
			except Exception:
				ctx = {}
		if isinstance(ctx, dict) and ctx.get("company"):
			return ctx["company"]
	return frappe.defaults.get_user_default("Company") or ""


def _safe_filename(text: str, max_len: int = 30) -> str:
	"""Sanitise text for use in a filename, truncated to max_len characters."""
	import re

	return re.sub(r"[^a-zA-Z0-9_-]", "_", text.strip())[:max_len].rstrip("_")


def _escape_html(text: str) -> str:
	"""Minimal HTML escaping for user content in the PDF."""
	return (
		text.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
		.replace("\n", "<br>")
	)
