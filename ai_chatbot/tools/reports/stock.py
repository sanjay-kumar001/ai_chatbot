# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
Stock Report Tools (Phase 12B)

Thin wrappers around ERPNext's standard stock report execute() functions.

Reports covered:
1. Stock Ledger
2. Stock Balance
3. Stock Ageing
"""

from __future__ import annotations

from frappe.utils import nowdate

from ai_chatbot.core.config import get_default_company, get_fiscal_year_dates
from ai_chatbot.tools.registry import register_tool
from ai_chatbot.tools.reports._base import build_report_response, run_report

# ═══════════════════════════════════════════════════════════════════
# 1. Stock Ledger
# ═══════════════════════════════════════════════════════════════════


@register_tool(
	name="report_stock_ledger",
	category="inventory",
	description=(
		"Run ERPNext Stock Ledger report — a detailed record of all stock movements. "
		"Shows inward/outward transactions related to manufacturing, purchasing, selling, "
		"and stock transfers with quantity and value for each movement. "
		"Use for a granular view of stock transaction history."
	),
	parameters={
		"company": {
			"type": "string",
			"description": "Company name. Optional — omit to use user's default company.",
		},
		"from_date": {
			"type": "string",
			"description": "Start date (YYYY-MM-DD). Optional — defaults to fiscal year start.",
		},
		"to_date": {
			"type": "string",
			"description": "End date (YYYY-MM-DD). Optional — defaults to fiscal year end.",
		},
		"warehouse": {
			"type": "string",
			"description": "Filter by warehouse name.",
		},
		"item_code": {
			"type": "string",
			"description": "Filter by specific item code.",
		},
		"item_group": {
			"type": "string",
			"description": "Filter by item group.",
		},
	},
	doctypes=["Stock Ledger Entry"],
)
def report_stock_ledger(
	company=None,
	from_date=None,
	to_date=None,
	warehouse=None,
	item_code=None,
	item_group=None,
):
	"""Run ERPNext Stock Ledger report."""
	company = get_default_company(company)

	if not from_date or not to_date:
		fy_from, fy_to = get_fiscal_year_dates(company)
		from_date = from_date or fy_from
		to_date = to_date or fy_to

	filters = {
		"company": company,
		"from_date": from_date,
		"to_date": to_date,
	}

	if warehouse:
		filters["warehouse"] = warehouse
	if item_code:
		filters["item_code"] = item_code
	if item_group:
		filters["item_group"] = item_group

	from erpnext.stock.report.stock_ledger.stock_ledger import execute

	result = run_report(execute, filters)
	result["period"] = {"from": from_date, "to": to_date}
	return build_report_response(result, company)


# ═══════════════════════════════════════════════════════════════════
# 2. Stock Balance
# ═══════════════════════════════════════════════════════════════════


@register_tool(
	name="report_stock_balance",
	category="inventory",
	description=(
		"Run ERPNext Stock Balance report — provides a real-time summary of current "
		"inventory quantities, valuation rates, and total stock value broken down by "
		"item and warehouse. Calculates: Opening Stock + In Stock - Out Stock. "
		"Use for current inventory snapshot."
	),
	parameters={
		"company": {
			"type": "string",
			"description": "Company name. Optional — omit to use user's default company.",
		},
		"from_date": {
			"type": "string",
			"description": "Start date (YYYY-MM-DD). Optional — defaults to fiscal year start.",
		},
		"to_date": {
			"type": "string",
			"description": "End date (YYYY-MM-DD). Optional — defaults to fiscal year end.",
		},
		"warehouse": {
			"type": "string",
			"description": "Filter by warehouse name.",
		},
		"item_code": {
			"type": "string",
			"description": "Filter by specific item code.",
		},
		"item_group": {
			"type": "string",
			"description": "Filter by item group.",
		},
	},
	doctypes=["Stock Ledger Entry"],
)
def report_stock_balance(
	company=None,
	from_date=None,
	to_date=None,
	warehouse=None,
	item_code=None,
	item_group=None,
):
	"""Run ERPNext Stock Balance report."""
	company = get_default_company(company)

	if not from_date or not to_date:
		fy_from, fy_to = get_fiscal_year_dates(company)
		from_date = from_date or fy_from
		to_date = to_date or fy_to

	filters = {
		"company": company,
		"from_date": from_date,
		"to_date": to_date,
	}

	if warehouse:
		filters["warehouse"] = warehouse
	if item_code:
		filters["item_code"] = item_code
	if item_group:
		filters["item_group"] = item_group

	if item_code:
		# ERPNext stock_balance report uses isin() which expects a list, not a bare string
		filters["item_code"] = [item_code] if isinstance(item_code, str) else item_code

	from erpnext.stock.report.stock_balance.stock_balance import execute

	result = run_report(execute, filters)
	result["period"] = {"from": from_date, "to": to_date}
	return build_report_response(result, company)


# ═══════════════════════════════════════════════════════════════════
# 3. Stock Ageing
# ═══════════════════════════════════════════════════════════════════


@register_tool(
	name="report_stock_ageing",
	category="inventory",
	description=(
		"Run ERPNext Stock Ageing report — monitors how long inventory has been in "
		"warehouses, helping identify slow-moving or obsolete items to reduce dead stock. "
		"Calculates item age based on entry date. Use for warehouse optimization and "
		"improving stock turnover."
	),
	parameters={
		"company": {
			"type": "string",
			"description": "Company name. Optional — omit to use user's default company.",
		},
		"to_date": {
			"type": "string",
			"description": "Report date (YYYY-MM-DD). Optional — defaults to today.",
		},
		"warehouse": {
			"type": "string",
			"description": "Filter by warehouse name.",
		},
		"item_code": {
			"type": "string",
			"description": "Filter by specific item code.",
		},
		"range": {
			"type": "string",
			"description": (
				"Comma-separated ageing buckets in days, e.g. '30, 60, 90'. "
				"Optional — defaults to '30, 60, 90'."
			),
		},
	},
	doctypes=["Stock Ledger Entry"],
)
def report_stock_ageing(
	company=None,
	to_date=None,
	warehouse=None,
	item_code=None,
	range=None,
):
	"""Run ERPNext Stock Ageing report."""
	company = get_default_company(company)
	to_date = to_date or nowdate()

	filters = {
		"company": company,
		"to_date": to_date,
		# ERPNext's stock_ageing.execute() unconditionally calls
		# filters.range.split(","), so `range` must never be None.
		"range": range or "30, 60, 90",
	}

	if warehouse:
		filters["warehouse"] = warehouse
	if item_code:
		filters["item_code"] = item_code

	from erpnext.stock.report.stock_ageing.stock_ageing import execute

	result = run_report(execute, filters)
	return build_report_response(result, company)
