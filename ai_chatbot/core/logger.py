# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
Structured Logging for AI Chatbot

Provides Python `logging` module-based loggers that write to dedicated log
files under ``{bench_path}/logs/``, following Frappe's convention.

Two loggers are configured:
- **ai_chatbot** → ``logs/ai_chatbot.log``  (general app logging)
- **ai_chatbot.tools** → ``logs/ai_chatbot_tools.log``  (tool execution)

Log levels: DEBUG for tool args/results, INFO for requests, WARNING for
fallbacks, ERROR for failures.

Critical errors are *also* written to Frappe's Error Log DocType via
``frappe.log_error()`` so they remain visible in the Frappe desk.
"""

from __future__ import annotations

import json
import logging
import os
import time
from logging.handlers import RotatingFileHandler

import frappe

from ai_chatbot.core.constants import LOG_TITLE

# ── Module-level singletons (lazy-initialised) ───────────────────────

_app_logger: logging.Logger | None = None
_tool_logger: logging.Logger | None = None

# Rotate at 10 MB, keep 5 backups
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5


def _get_bench_log_dir() -> str:
	"""Return ``{bench_path}/logs``, creating the directory if needed."""
	bench_path = frappe.utils.get_bench_path()
	log_dir = os.path.join(bench_path, "logs")
	os.makedirs(log_dir, exist_ok=True)
	return log_dir


def _make_handler(filepath: str) -> RotatingFileHandler:
	"""Create a rotating file handler with a structured formatter."""
	handler = RotatingFileHandler(filepath, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT)
	formatter = logging.Formatter(
		fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
		datefmt="%Y-%m-%d %H:%M:%S",
	)
	handler.setFormatter(formatter)
	return handler


def _get_app_logger() -> logging.Logger:
	"""Return (and lazily initialise) the main app logger."""
	global _app_logger
	if _app_logger is not None:
		return _app_logger

	_app_logger = logging.getLogger("ai_chatbot")
	_app_logger.setLevel(logging.DEBUG)
	_app_logger.propagate = False

	if not _app_logger.handlers:
		log_dir = _get_bench_log_dir()
		_app_logger.addHandler(_make_handler(os.path.join(log_dir, "ai_chatbot.log")))

	return _app_logger


def _get_tool_logger() -> logging.Logger:
	"""Return (and lazily initialise) the tool-specific logger."""
	global _tool_logger
	if _tool_logger is not None:
		return _tool_logger

	_tool_logger = logging.getLogger("ai_chatbot.tools")
	_tool_logger.setLevel(logging.DEBUG)
	_tool_logger.propagate = False

	if not _tool_logger.handlers:
		log_dir = _get_bench_log_dir()
		_tool_logger.addHandler(_make_handler(os.path.join(log_dir, "ai_chatbot_tools.log")))

	return _tool_logger


# ── Structured field helpers ──────────────────────────────────────────


def _fmt_fields(**fields) -> str:
	"""Format structured key=value fields for log messages.

	Drops keys whose values are ``None`` so log lines stay compact.
	"""
	parts = []
	for key, value in fields.items():
		if value is None:
			continue
		parts.append(f"{key}={value}")
	return " | ".join(parts) if parts else ""


# ── Public API ────────────────────────────────────────────────────────


def get_logger() -> logging.Logger:
	"""Return the main AI Chatbot logger for direct use."""
	return _get_app_logger()


def log_info(message: str, **fields) -> None:
	"""Log an INFO-level message with optional structured fields.

	Args:
		message: Human-readable log message.
		**fields: Optional structured fields (conversation_id, provider, etc.).
	"""
	extra = _fmt_fields(**fields)
	full = f"{message} | {extra}" if extra else message
	_get_app_logger().info(full)


def log_warning(message: str, **fields) -> None:
	"""Log a WARNING-level message with optional structured fields."""
	extra = _fmt_fields(**fields)
	full = f"{message} | {extra}" if extra else message
	_get_app_logger().warning(full)


def log_debug(message: str, **fields) -> None:
	"""Log a DEBUG-level message with optional structured fields."""
	extra = _fmt_fields(**fields)
	full = f"{message} | {extra}" if extra else message
	_get_app_logger().debug(full)


#: Frappe's Error Log `method` (title) field is Data(140). Leave a small margin
#: so we never trigger Frappe's CharacterLengthExceededError. Keep the leading
#: characters — those are the most informative for scanning the desk.
_MAX_ERROR_TITLE_LEN = 130


def log_error(message, title=None, reference_doctype=None, reference_name=None):
	"""Log an error to both the file logger and Frappe's Error Log.

	Critical errors should still appear in the Frappe desk for admin
	visibility, so this function writes to both destinations.

	Args:
		message: Error message or exception.
		title: Optional sub-title (appended to LOG_TITLE).
		reference_doctype: Optional linked doctype.
		reference_name: Optional linked document name.
	"""
	full_title = f"{LOG_TITLE} - {title}" if title else LOG_TITLE
	# Guard against the 140-char limit on Error Log's title field. The full
	# detail still lands in the `message` body, so nothing is lost.
	if len(full_title) > _MAX_ERROR_TITLE_LEN:
		full_title = full_title[: _MAX_ERROR_TITLE_LEN - 1] + "…"

	log_line = f"{full_title} | {message}"
	_get_app_logger().error(log_line)

	# Also persist to Frappe Error Log for desk visibility
	try:
		frappe.log_error(
			message=str(message),
			title=full_title,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
		)
	except Exception:
		pass  # Don't let Frappe DB issues break the caller


def log_tool_error(tool_name: str, error, arguments=None) -> None:
	"""Log a tool execution error to the tool log file and Frappe Error Log.

	Args:
		tool_name: Name of the tool that failed.
		error: The exception or error message.
		arguments: The arguments passed to the tool.
	"""
	args_str = _safe_json(arguments) if arguments else ""
	_get_tool_logger().error(f"TOOL_ERROR | tool={tool_name} | error={error} | args={args_str}")

	# Also write to Frappe Error Log
	msg = f"Tool: {tool_name}\nError: {error}"
	if arguments:
		msg += f"\nArguments: {arguments}"
	log_error(msg, title="Tool Execution")


def log_tool_call(
	tool_name: str,
	arguments: dict | None = None,
	result: dict | None = None,
	duration_ms: float | None = None,
	conversation_id: str | None = None,
) -> None:
	"""Log a successful tool invocation at DEBUG level.

	Args:
		tool_name: Name of the tool that was called.
		arguments: The arguments passed to the tool.
		result: Abbreviated result data (caller should truncate large payloads).
		duration_ms: Execution time in milliseconds.
		conversation_id: The active conversation ID.
	"""
	args_str = _safe_json(arguments) if arguments else ""
	_get_tool_logger().debug(
		_fmt_fields(
			tool=tool_name,
			args=args_str,
			duration_ms=f"{duration_ms:.0f}" if duration_ms is not None else None,
			conversation_id=conversation_id,
		)
	)


def log_provider_error(provider_name: str, error) -> None:
	"""Log an AI provider error to both file and Frappe Error Log.

	Args:
		provider_name: Name of the provider (OpenAI, Claude, Gemini).
		error: The exception or error message.
	"""
	_get_app_logger().error(f"PROVIDER_ERROR | provider={provider_name} | error={error}")
	log_error(f"Provider: {provider_name}\nError: {error}", title="AI Provider")


def log_request(
	provider: str,
	model: str | None = None,
	conversation_id: str | None = None,
	prompt_tokens: int | None = None,
	completion_tokens: int | None = None,
	duration_ms: float | None = None,
	stream: bool = False,
) -> None:
	"""Log an AI provider request at INFO level.

	Args:
		provider: Provider name (OpenAI, Claude, Gemini).
		model: Model name/ID used.
		conversation_id: The active conversation ID.
		prompt_tokens: Number of prompt tokens consumed.
		completion_tokens: Number of completion tokens consumed.
		duration_ms: Total request time in milliseconds.
		stream: Whether this was a streaming request.
	"""
	_get_app_logger().info(
		_fmt_fields(
			event="ai_request",
			provider=provider,
			model=model,
			conversation_id=conversation_id,
			prompt_tokens=prompt_tokens,
			completion_tokens=completion_tokens,
			duration_ms=f"{duration_ms:.0f}" if duration_ms is not None else None,
			stream=stream,
		)
	)


# ── Timer context manager ────────────────────────────────────────────


class timer:
	"""Simple context manager to measure elapsed wall-clock time.

	Usage::

	        with timer() as t:
	            do_work()
	        print(t.duration_ms)  # float, milliseconds
	"""

	__slots__ = ("_start", "duration_ms")

	def __enter__(self):
		self._start = time.perf_counter()
		self.duration_ms = 0.0
		return self

	def __exit__(self, *_exc):
		self.duration_ms = (time.perf_counter() - self._start) * 1000
		return False


# ── Helpers ───────────────────────────────────────────────────────────


def _safe_json(obj) -> str:
	"""JSON-encode ``obj`` safely, falling back to ``str()``."""
	try:
		return json.dumps(obj, default=str, ensure_ascii=False)
	except Exception:
		return str(obj)
