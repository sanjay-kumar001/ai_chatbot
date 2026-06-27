# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
PDF Generation Utility

Uses WeasyPrint for HTML → PDF conversion. Falls back to Frappe's
built-in ``get_pdf()`` (wkhtmltopdf) if WeasyPrint is not available.

WeasyPrint advantages over wkhtmltopdf:
  - Actively maintained
  - Full CSS Grid/Flexbox support
  - No heading-centering bug at page breaks
  - Better SVG rendering

System requirements for WeasyPrint:
  - libpango1.0-dev, libcairo2-dev, libgdk-pixbuf2.0-dev
  - On Debian/Ubuntu: ``apt install libpango1.0-dev libcairo2-dev``
"""

from __future__ import annotations

import frappe

from ai_chatbot.core.logger import log_error


def html_to_pdf(html: str) -> bytes:
	"""Convert an HTML string to PDF bytes.

	Uses WeasyPrint when available, otherwise falls back to
	``frappe.utils.pdf.get_pdf()`` (wkhtmltopdf).

	Args:
		html: Complete HTML document string.

	Returns:
		PDF file content as bytes.
	"""
	try:
		from weasyprint import HTML

		return HTML(string=html).write_pdf()
	except ImportError:
		log_error(
			"WeasyPrint not installed — falling back to wkhtmltopdf. Install with: pip install weasyprint",
			title="PDF",
		)
		from frappe.utils.pdf import get_pdf

		return get_pdf(html)
	except Exception as e:
		# WeasyPrint installed but failed (e.g. missing system libs) — fallback
		log_error(
			f"WeasyPrint rendering failed, falling back to wkhtmltopdf: {e!s}",
			title="PDF",
		)
		from frappe.utils.pdf import get_pdf

		return get_pdf(html)
