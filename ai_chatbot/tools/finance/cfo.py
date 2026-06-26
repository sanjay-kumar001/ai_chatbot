# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
CFO Reporting Tools
Composite analysis tools that aggregate data from ERPNext standard reports.

Phase 12B-ext: Refactored to source all data from ERPNext report execute()
functions instead of custom frappe.qb queries, ensuring data consistency
with ERPNext's own reports.

Phase 19: When "Use Financial Report Engine" is enabled in Chatbot Settings,
CFO dashboard helpers now route through the template-engine path for data
consistency with user-facing report tools.  Extraction uses a fallback chain:
  1. report_summary (standard path — always has this)
  2. Row-level KPI extraction from report data (works for both paths)
  3. Standard path as last resort
"""

from __future__ import annotations

import frappe
from frappe.query_builder import functions as fn
from frappe.utils import add_years, flt, nowdate

from ai_chatbot.core.config import get_default_company, get_fiscal_year_dates
from ai_chatbot.core.session_context import get_company_filter
from ai_chatbot.data.charts import build_bar_chart, build_multi_series_chart
from ai_chatbot.data.currency import build_currency_response
from ai_chatbot.tools.common import primary
from ai_chatbot.tools.registry import register_tool
from ai_chatbot.tools.reports._base import (
	build_financial_filters,
	extract_kpis_from_report_data,
	get_fiscal_year_name,
	get_report_data,
	is_fre_enabled,
)

# ═══════════════════════════════════════════════════════════════════
# Internal helpers — extract values from report results
# ═══════════════════════════════════════════════════════════════════


def _pnl_totals(company: str, from_date: str, to_date: str) -> dict:
	"""Extract income, expense, net profit from P&L report.

	Fallback chain (Phase 19 — FRE consistency):
	  1. If FRE enabled → run with report_type to use template path;
	     extract KPIs from data rows (report_summary is absent on this path).
	  2. If FRE disabled OR template path returns no data → run standard path
	     and extract from report_summary.
	"""
	use_fre = is_fre_enabled()

	from erpnext.accounts.report.profit_and_loss_statement.profit_and_loss_statement import (
		execute,
	)

	# ── Attempt 1: FRE template path ──
	if use_fre:
		fre_filters = build_financial_filters(
			company=company,
			from_date=from_date,
			to_date=to_date,
			periodicity="Yearly",
			report_type="profit_and_loss",
		)
		fre_result = get_report_data(execute, fre_filters)

		# If the template path returned data, extract from rows
		if fre_result.get("data"):
			totals = _extract_pnl_from_data(fre_result["data"])
			if totals["income"] or totals["expense"] or totals["net_profit"]:
				return totals

	# ── Attempt 2: Standard path (report_summary) ──
	std_filters = build_financial_filters(
		company=company,
		from_date=from_date,
		to_date=to_date,
		periodicity="Yearly",
	)
	result = get_report_data(execute, std_filters)

	# Try report_summary first
	summary = result.get("report_summary") or []
	totals = {"income": 0, "expense": 0, "net_profit": 0}
	for item in summary:
		label = (item.get("label") or "").lower()
		value = flt(item.get("value", 0))
		if "income" in label:
			totals["income"] = value
		elif "expense" in label:
			totals["expense"] = value
		elif "profit" in label or "loss" in label:
			totals["net_profit"] = value

	if totals["income"] or totals["expense"] or totals["net_profit"]:
		return totals

	# Last resort: extract from data rows (standard path data)
	if result.get("data"):
		return _extract_pnl_from_data(result["data"])

	return totals


# Label candidates for P&L KPI extraction — matches both standard and
# template-engine row labels regardless of user customisation.
_PNL_KPI_MAP = {
	"income": [
		"total income",
		"income (total)",
		"total revenue",
		"gross income",
	],
	"expense": [
		"total expense",
		"expense (total)",
		"total expenditure",
		"gross expense",
	],
	"net_profit": [
		"net profit",
		"profit for the year",
		"net loss",
		"profit (loss)",
		"net income",
	],
}


def _extract_pnl_from_data(data: list[dict]) -> dict:
	"""Extract income, expense, net profit from P&L data rows.

	Uses label matching with multiple candidates per KPI so it works
	regardless of whether the data comes from the standard path or
	the FinancialReportEngine template path.
	"""
	return extract_kpis_from_report_data(data, _PNL_KPI_MAP)


def _ar_total(company: str) -> float:
	"""Get total outstanding receivables from AR Summary report."""
	from erpnext.accounts.report.accounts_receivable_summary.accounts_receivable_summary import (
		execute,
	)

	filters = {
		"company": company,
		"report_date": nowdate(),
		"ageing_based_on": "Due Date",
		"range1": 30,
		"range2": 60,
		"range3": 90,
		"range4": 120,
	}
	result = get_report_data(execute, filters, max_rows=500)
	return flt(sum(flt(row.get("outstanding", 0)) for row in result.get("data", [])), 2)


def _ap_total(company: str) -> float:
	"""Get total outstanding payables from AP Summary report."""
	from erpnext.accounts.report.accounts_payable_summary.accounts_payable_summary import (
		execute,
	)

	filters = {
		"company": company,
		"report_date": nowdate(),
		"ageing_based_on": "Due Date",
		"range1": 30,
		"range2": 60,
		"range3": 90,
		"range4": 120,
	}
	result = get_report_data(execute, filters, max_rows=500)
	return flt(sum(flt(row.get("outstanding", 0)) for row in result.get("data", [])), 2)


def _balance_sheet_totals(company: str, from_date: str, to_date: str) -> dict:
	"""Extract asset, liability, equity totals from Balance Sheet report.

	Fallback chain (Phase 19 — FRE consistency):
	  1. If FRE enabled → run with report_type to use template path;
	     extract KPIs from data rows.
	  2. If FRE disabled OR template path returns no data → run standard path
	     and extract from report_summary.
	"""
	use_fre = is_fre_enabled()

	from erpnext.accounts.report.balance_sheet.balance_sheet import execute

	# ── Attempt 1: FRE template path ──
	if use_fre:
		fre_filters = build_financial_filters(
			company=company,
			from_date=from_date,
			to_date=to_date,
			periodicity="Yearly",
			report_type="balance_sheet",
		)
		fre_result = get_report_data(execute, fre_filters)

		if fre_result.get("data"):
			totals = _extract_bs_from_data(fre_result["data"])
			if totals["total_asset"] or totals["total_liability"] or totals["total_equity"]:
				return totals

	# ── Attempt 2: Standard path (report_summary) ──
	std_filters = build_financial_filters(
		company=company,
		from_date=from_date,
		to_date=to_date,
		periodicity="Yearly",
	)
	result = get_report_data(execute, std_filters)

	# Try report_summary first
	summary = result.get("report_summary") or []
	totals = {"total_asset": 0, "total_liability": 0, "total_equity": 0}
	for item in summary:
		label = (item.get("label") or "").lower()
		value = flt(item.get("value", 0))
		if "asset" in label:
			totals["total_asset"] = value
		elif "liability" in label:
			totals["total_liability"] = value
		elif "equity" in label:
			totals["total_equity"] = value

	if totals["total_asset"] or totals["total_liability"] or totals["total_equity"]:
		return totals

	# Last resort: extract from data rows (standard path data)
	if result.get("data"):
		return _extract_bs_from_data(result["data"])

	return totals


# Label candidates for Balance Sheet KPI extraction.
_BS_KPI_MAP = {
	"total_asset": [
		"total asset",
		"total assets",
		"assets (total)",
	],
	"total_liability": [
		"total liability",
		"total liabilities",
		"liabilities (total)",
	],
	"total_equity": [
		"total equity",
		"equity (total)",
		"shareholder",
		"stockholder",
	],
}


def _extract_bs_from_data(data: list[dict]) -> dict:
	"""Extract asset, liability, equity from Balance Sheet data rows."""
	return extract_kpis_from_report_data(data, _BS_KPI_MAP)


def _cash_position(company: str | list) -> float:
	"""Get cash/bank position from GL entries (no standard report for this alone)."""
	acc = frappe.qb.DocType("Account")
	gle = frappe.qb.DocType("GL Entry")

	acc_q = (
		frappe.qb.from_(acc)
		.select(acc.name)
		.where(acc.account_type.isin(["Bank", "Cash"]))
		.where(acc.is_group == 0)
	)
	if isinstance(company, list):
		acc_q = acc_q.where(acc.company.isin(company))
	else:
		acc_q = acc_q.where(acc.company == company)
	cash_accounts = [a[0] for a in acc_q.run(as_list=True)]

	if not cash_accounts:
		return 0

	cash_q = (
		frappe.qb.from_(gle)
		.select((fn.Sum(gle.debit) - fn.Sum(gle.credit)).as_("balance"))
		.where(gle.account.isin(cash_accounts))
		.where(gle.is_cancelled == 0)
	)
	if isinstance(company, list):
		cash_q = cash_q.where(gle.company.isin(company))
	else:
		cash_q = cash_q.where(gle.company == company)
	cash_result = cash_q.run(as_dict=True)
	return flt(cash_result[0].balance) if cash_result else 0


def _inventory_value(company: str | list) -> float:
	"""Get total inventory value from Bin/Warehouse."""
	bin_table = frappe.qb.DocType("Bin")
	wh_table = frappe.qb.DocType("Warehouse")
	inv_q = (
		frappe.qb.from_(bin_table)
		.join(wh_table)
		.on(bin_table.warehouse == wh_table.name)
		.select(fn.Sum(bin_table.stock_value).as_("total"))
	)
	if isinstance(company, list):
		inv_q = inv_q.where(wh_table.company.isin(company))
	else:
		inv_q = inv_q.where(wh_table.company == company)
	inv_result = inv_q.run(as_dict=True)
	return flt(inv_result[0].total) if inv_result else 0


def _financial_ratios(company: str) -> dict:
	"""Get financial ratios from the Financial Ratios report."""
	fy_name = get_fiscal_year_name(company)
	from erpnext.accounts.report.financial_ratios.financial_ratios import execute

	filters = {
		"company": company,
		"from_fiscal_year": fy_name,
		"to_fiscal_year": fy_name,
		"periodicity": "Yearly",
	}
	result = get_report_data(execute, filters)
	data = result.get("data", [])

	# Parse ratio rows — each row has {"ratio": "Name", <period_key>: value}
	ratios = {}
	for row in data:
		name = row.get("ratio", "")
		if not name or name in ("Liquidity Ratios", "Solvency Ratios", "Turnover Ratios"):
			continue
		# Get the first period value (usually the only one for Yearly)
		for k, v in row.items():
			if k != "ratio" and v is not None:
				ratios[name] = flt(v, 2)
				break
	return ratios


def _cash_flow_summary(company: str, from_date: str, to_date: str) -> dict:
	"""Get cash flow summary (inflow/outflow) from Payment Entries."""
	pe = frappe.qb.DocType("Payment Entry")

	def _sum_pe(payment_type):
		q = (
			frappe.qb.from_(pe)
			.select(fn.Sum(pe.base_paid_amount).as_("total"))
			.where(pe.docstatus == 1)
			.where(pe.payment_type == payment_type)
			.where(pe.posting_date >= from_date)
			.where(pe.posting_date <= to_date)
		)
		if isinstance(company, list):
			q = q.where(pe.company.isin(company))
		else:
			q = q.where(pe.company == company)
		r = q.run(as_dict=True)
		return flt(r[0].total) if r else 0

	inflow = _sum_pe("Receive")
	outflow = _sum_pe("Pay")
	return {"inflow": flt(inflow, 2), "outflow": flt(outflow, 2), "net": flt(inflow - outflow, 2)}


def _budget_summary(company: str) -> dict:
	"""Get budget vs actual summary from Budget Variance report."""
	fy_name = get_fiscal_year_name(company)
	if not fy_name:
		return {"message": "No fiscal year configured"}

	from erpnext.accounts.report.budget_variance_report.budget_variance_report import execute

	filters = {
		"company": company,
		"fiscal_year": fy_name,
		"budget_against": "Cost Center",
		"period": "Yearly",
	}
	try:
		result = get_report_data(execute, filters)
	except Exception:
		return {"total_budget": 0, "total_actual": 0, "variance": 0, "fiscal_year": fy_name}

	data = result.get("data", [])
	if not data:
		return {"total_budget": 0, "total_actual": 0, "variance": 0, "fiscal_year": fy_name}

	# Sum budget and actual columns across all rows
	total_budget = 0
	total_actual = 0
	for row in data:
		for k, v in row.items():
			if k.startswith("total_budget") or k == "total_budget":
				total_budget += flt(v)
			elif k.startswith("total_actual") or k == "total_actual":
				total_actual += flt(v)
			elif "budget" in k and "total" not in k and "variance" not in k:
				total_budget += flt(v)
			elif "actual" in k and "total" not in k and "variance" not in k:
				total_actual += flt(v)

	variance = flt(total_budget - total_actual, 2)
	variance_pct = flt((variance / total_budget) * 100, 1) if total_budget else 0

	return {
		"total_budget": flt(total_budget, 2),
		"total_actual": flt(total_actual, 2),
		"variance": variance,
		"variance_pct": variance_pct,
		"fiscal_year": fy_name,
	}


# ═══════════════════════════════════════════════════════════════════
# Tool: Financial Overview
# ═══════════════════════════════════════════════════════════════════


@register_tool(
	name="get_financial_overview",
	category="finance",
	description=(
		"Get a high-level financial overview with key KPIs and BI metric cards: revenue, COGS, "
		"gross profit, net profit, cash position, accounts receivable, and accounts payable. "
		"Data sourced from ERPNext P&L Statement, AR/AP Summary reports. "
		"Prefer get_cfo_dashboard for comprehensive CFO-level analysis."
	),
	parameters={
		"from_date": {
			"type": "string",
			"description": "Start date (YYYY-MM-DD). Optional — omit to use current fiscal year start.",
		},
		"to_date": {
			"type": "string",
			"description": "End date (YYYY-MM-DD). Optional — omit to use current fiscal year end.",
		},
		"company": {
			"type": "string",
			"description": "Company name. Optional — omit to use user's default company.",
		},
	},
	doctypes=["GL Entry", "Account", "Sales Invoice", "Purchase Invoice"],
)
def get_financial_overview(from_date=None, to_date=None, company=None):
	"""High-level financial KPIs aggregated from ERPNext reports."""
	company = get_company_filter(company)
	comp = primary(company)

	if not from_date or not to_date:
		fy_from, fy_to = get_fiscal_year_dates(comp)
		from_date = from_date or fy_from
		to_date = to_date or fy_to

	# Source data from reports
	pnl = _pnl_totals(comp, from_date, to_date)
	revenue = flt(pnl["income"], 2)
	total_expenses = flt(pnl["expense"], 2)
	net_profit = flt(pnl["net_profit"], 2)
	net_margin_pct = flt((net_profit / revenue) * 100, 1) if revenue else 0

	receivables = _ar_total(comp)
	payables = _ap_total(comp)
	cash = flt(_cash_position(company), 2)

	# Build chart
	categories = ["Revenue", "Expenses", "Net Profit", "Cash", "AR", "AP"]
	values = [revenue, total_expenses, net_profit, cash, receivables, payables]

	bi_cards = [
		{
			"label": "Revenue",
			"value": revenue,
			"change_pct": None,
			"change_period": None,
			"trend": "up" if revenue > 0 else "flat",
			"icon": "trending-up",
		},
		{
			"label": "Net Profit",
			"value": net_profit,
			"change_pct": net_margin_pct,
			"change_period": "Margin %",
			"trend": "up" if net_profit > 0 else "down",
			"icon": "bar-chart-3",
		},
		{
			"label": "Cash Position",
			"value": cash,
			"change_pct": None,
			"change_period": None,
			"trend": "up" if cash > 0 else "down",
			"icon": "wallet",
		},
		{
			"label": "Receivables",
			"value": receivables,
			"change_pct": None,
			"change_period": None,
			"trend": "flat",
			"icon": "arrow-up-right",
		},
		{
			"label": "Payables",
			"value": payables,
			"change_pct": None,
			"change_period": None,
			"trend": "flat",
			"icon": "arrow-down-right",
		},
	]

	result = {
		"bi_cards": bi_cards,
		"revenue": revenue,
		"total_expenses": total_expenses,
		"net_profit": net_profit,
		"net_margin_pct": net_margin_pct,
		"cash_position": cash,
		"receivables": receivables,
		"payables": payables,
		"net_working_capital": flt(receivables - payables, 2),
		"period": {"from": from_date, "to": to_date},
		"echart_option": build_bar_chart(
			title="Financial Overview",
			categories=categories,
			series_data=values,
			y_axis_name="Amount",
			series_name="Amount",
		),
	}
	return build_currency_response(result, comp)


# ═══════════════════════════════════════════════════════════════════
# Tool: CFO Dashboard
# ═══════════════════════════════════════════════════════════════════


@register_tool(
	name="get_cfo_dashboard",
	category="finance",
	description=(
		"Get a comprehensive CFO dashboard with BI metric cards (Revenue, Net Profit, Cash, AR, AP "
		"with YoY comparisons), financial highlights, KPIs (margins, ratios, efficiency metrics), "
		"cash flow summary, receivables/payables aging, and budget variance. "
		"Data sourced from ERPNext P&L, Balance Sheet, Financial Ratios, AR/AP Summary, "
		"and Budget Variance reports. "
		"Use this tool when user asks for 'CFO dashboard', 'financial overview', 'financial dashboard', "
		"'show CFO dashboard', or any comprehensive financial summary request."
	),
	parameters={
		"from_date": {
			"type": "string",
			"description": "Start date (YYYY-MM-DD). Optional — omit to use current fiscal year start.",
		},
		"to_date": {
			"type": "string",
			"description": "End date (YYYY-MM-DD). Optional — omit to use current fiscal year end.",
		},
		"company": {
			"type": "string",
			"description": "Company name. Optional — omit to use user's default company.",
		},
	},
	doctypes=["GL Entry", "Account", "Sales Invoice", "Purchase Invoice", "Budget"],
)
def get_cfo_dashboard(from_date=None, to_date=None, company=None):
	"""Comprehensive CFO dashboard aggregating data from ERPNext reports."""
	company = get_company_filter(company)
	comp = primary(company)

	if not from_date or not to_date:
		fy_from, fy_to = get_fiscal_year_dates(comp)
		from_date = from_date or fy_from
		to_date = to_date or fy_to

	# ── P&L data ──
	try:
		pnl = _pnl_totals(comp, from_date, to_date)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "CFO Dashboard: P&L failed")
		pnl = {"income": 0, "expense": 0, "net_profit": 0}
	revenue = flt(pnl["income"], 2)
	total_expenses = flt(pnl["expense"], 2)
	net_profit = flt(pnl["net_profit"], 2)

	# ── AR / AP ──
	try:
		total_receivables = _ar_total(comp)
	except Exception:
		total_receivables = 0.0
	try:
		total_payables = _ap_total(comp)
	except Exception:
		total_payables = 0.0

	# ── Balance Sheet ──
	try:
		bs = _balance_sheet_totals(comp, from_date, to_date)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "CFO Dashboard: Balance Sheet failed")
		bs = {"total_asset": 0, "total_liability": 0, "total_equity": 0}
	total_assets = flt(bs["total_asset"], 2)

	# ── Cash & Inventory ──
	try:
		cash_position = flt(_cash_position(company), 2)
	except Exception:
		cash_position = 0.0
	try:
		inventory = flt(_inventory_value(company), 2)
	except Exception:
		inventory = 0.0

	# ── Financial Ratios (from ERPNext report) ──
	try:
		ratios = _financial_ratios(comp)
	except Exception:
		ratios = {}

	# ── Cash Flow Summary ──
	try:
		cf = _cash_flow_summary(company, from_date, to_date)
	except Exception:
		cf = {}

	# ── Budget Summary ──
	try:
		budget = _budget_summary(comp)
	except Exception:
		budget = {}

	# ── Calculate margins ──
	net_margin_pct = flt((net_profit / revenue) * 100, 1) if revenue else 0

	# ── Liquidity (from ratios report or calculated) ──
	current_ratio = ratios.get("Current Ratio", 0)
	quick_ratio = ratios.get("Quick Ratio", 0)

	# ── YoY Comparison ──
	prior_from = str(add_years(from_date, -1))
	prior_to = str(add_years(to_date, -1))
	try:
		prev_pnl = _pnl_totals(comp, prior_from, prior_to)
	except Exception:
		prev_pnl = {"income": 0, "net_profit": 0}
	prev_revenue = flt(prev_pnl["income"])
	prev_net_profit = flt(prev_pnl["net_profit"])

	rev_yoy = flt(((revenue - prev_revenue) / prev_revenue) * 100, 1) if prev_revenue else None
	profit_yoy = (
		flt(((net_profit - prev_net_profit) / abs(prev_net_profit)) * 100, 1) if prev_net_profit else None
	)

	def _trend(change_pct):
		if change_pct is None:
			return "flat"
		return "up" if change_pct > 0 else ("down" if change_pct < 0 else "flat")

	bi_cards = [
		{
			"label": "Revenue",
			"value": revenue,
			"change_pct": rev_yoy,
			"change_period": "YoY",
			"trend": _trend(rev_yoy),
			"icon": "trending-up",
		},
		{
			"label": "Net Profit",
			"value": net_profit,
			"change_pct": profit_yoy,
			"change_period": "YoY",
			"trend": _trend(profit_yoy),
			"icon": "bar-chart-3",
		},
		{
			"label": "Cash Position",
			"value": cash_position,
			"change_pct": None,
			"change_period": None,
			"trend": "up" if cash_position > 0 else "down",
			"icon": "wallet",
		},
		{
			"label": "AR Outstanding",
			"value": total_receivables,
			"change_pct": None,
			"change_period": None,
			"trend": "flat",
			"icon": "arrow-up-right",
		},
		{
			"label": "AP Outstanding",
			"value": total_payables,
			"change_pct": None,
			"change_period": None,
			"trend": "flat",
			"icon": "arrow-down-right",
		},
	]

	# ── KPI chart ──
	gross_profit_ratio = ratios.get("Gross Profit Ratio", 0)
	kpi_categories = ["Net Margin %", "Gross Profit Ratio", "Current Ratio", "Quick Ratio"]
	kpi_values = [net_margin_pct, gross_profit_ratio, current_ratio, quick_ratio]

	result = {
		"bi_cards": bi_cards,
		"financial_highlights": {
			"revenue": revenue,
			"total_expenses": total_expenses,
			"net_profit": net_profit,
			"cash_position": cash_position,
		},
		"kpis": {
			"financial": {
				"gross_profit_ratio": gross_profit_ratio,
				"net_margin_pct": net_margin_pct,
				"roa_pct": ratios.get("Return on Asset Ratio", 0),
				"roe_pct": ratios.get("Return on Equity Ratio", 0),
			},
			"operational": {
				"debtor_turnover": ratios.get("Debtor Turnover Ratio", 0),
				"creditor_turnover": ratios.get("Creditor Turnover Ratio", 0),
				"inventory_turnover": ratios.get("Inventory Turnover Ratio", 0),
				"fixed_asset_turnover": ratios.get("Fixed Asset Turnover Ratio", 0),
			},
			"liquidity": {
				"current_ratio": current_ratio,
				"quick_ratio": quick_ratio,
			},
			"solvency": {
				"debt_equity_ratio": ratios.get("Debt Equity Ratio", 0),
				"gross_profit_ratio": ratios.get("Gross Profit Ratio", 0),
				"net_profit_ratio": ratios.get("Net Profit Ratio", 0),
			},
		},
		"cash_flow": cf,
		"receivables_summary": {"total_outstanding": total_receivables},
		"payables_summary": {"total_outstanding": total_payables},
		"balance_sheet_snapshot": {
			"total_assets": total_assets,
			"receivables": total_receivables,
			"inventory": inventory,
			"cash_and_bank": cash_position,
			"current_liabilities": total_payables,
			"net_working_capital": flt(total_receivables + inventory + cash_position - total_payables, 2),
		},
		"budget_summary": budget,
		"period": {"from": from_date, "to": to_date},
		"echart_option": build_bar_chart(
			title="Financial KPIs",
			categories=kpi_categories,
			series_data=kpi_values,
			y_axis_name="Value",
			series_name="KPI",
		),
	}
	return build_currency_response(result, comp)


# ═══════════════════════════════════════════════════════════════════
# Tool: Monthly Comparison
# ═══════════════════════════════════════════════════════════════════


@register_tool(
	name="get_monthly_comparison",
	category="finance",
	description=(
		"Get month-over-month comparison of revenue, expenses, and net profit. "
		"Data sourced from ERPNext Profit and Loss report with monthly periodicity. "
		"Shows monthly amounts and variance (change) from previous month."
	),
	parameters={
		"months": {
			"type": "integer",
			"description": "Number of recent months to compare (default 6, max 12)",
		},
		"company": {
			"type": "string",
			"description": "Company name. Optional — omit to use user's default company.",
		},
	},
	doctypes=["GL Entry"],
)
def get_monthly_comparison(months=6, company=None):
	"""Month-over-month revenue, expenses, and net profit from P&L report.

	Phase 19: Routes through the FinancialReportEngine template path when
	the toggle is enabled, ensuring monthly data matches the user-facing
	P&L report.  The extraction logic works with both standard and
	template-engine row formats.
	"""
	company = get_company_filter(company)
	comp = primary(company)
	months = min(months or 6, 12)

	from frappe.utils import add_months, get_first_day, get_last_day

	start_date = str(get_first_day(add_months(nowdate(), -months + 1)))
	end_date = str(get_last_day(nowdate()))

	# Build filters — include report_type when FRE is enabled
	use_fre = is_fre_enabled()
	filters = build_financial_filters(
		company=comp,
		from_date=start_date,
		to_date=end_date,
		periodicity="Monthly",
		report_type="profit_and_loss" if use_fre else None,
	)

	from erpnext.accounts.report.profit_and_loss_statement.profit_and_loss_statement import (
		execute,
	)

	result = get_report_data(execute, filters)
	data = result.get("data", [])
	columns = result.get("columns", [])

	# Extract period keys from columns (skip metadata columns)
	period_keys = _extract_period_keys(columns)

	# Extract income/expense/net_profit totals per period from data rows
	income_total, expense_total, net_profit_row = _extract_monthly_totals(data, period_keys)

	# Build monthly comparison data
	monthly = []
	prev_revenue = None
	prev_expenses = None
	prev_net = None

	for pk in period_keys:
		key = pk["key"]
		revenue = flt(income_total.get(key, 0), 2)
		expenses = flt(expense_total.get(key, 0), 2)
		# Net profit from the report's own Net Profit row, or revenue - expenses
		net = flt(net_profit_row.get(key, revenue - expenses), 2)

		entry = {
			"month": pk["label"],
			"revenue": revenue,
			"expenses": expenses,
			"net_profit": net,
		}

		if prev_revenue is not None:
			entry["revenue_change"] = flt(revenue - prev_revenue, 2)
			entry["revenue_change_pct"] = (
				flt(((revenue - prev_revenue) / prev_revenue) * 100, 1) if prev_revenue else 0
			)
			entry["expenses_change"] = flt(expenses - prev_expenses, 2)
			entry["net_profit_change"] = flt(net - prev_net, 2)

		prev_revenue = revenue
		prev_expenses = expenses
		prev_net = net
		monthly.append(entry)

	# Build chart
	chart_categories = [m["month"] for m in monthly]
	series_list = [
		{"name": "Revenue", "data": [m["revenue"] for m in monthly]},
		{"name": "Expenses", "data": [m["expenses"] for m in monthly]},
		{"name": "Net Profit", "data": [m["net_profit"] for m in monthly]},
	]

	result = {
		"monthly": monthly,
		"period_months": months,
		"period": {"from": start_date, "to": end_date},
		"echart_option": build_multi_series_chart(
			title="Monthly Financial Comparison",
			categories=chart_categories,
			series_list=series_list,
			y_axis_name="Amount",
			chart_type="line",
		),
	}
	return build_currency_response(result, comp)


# ═══════════════════════════════════════════════════════════════════
# Monthly comparison helpers
# ═══════════════════════════════════════════════════════════════════

# Column fieldnames that are metadata, not period values.
_MONTHLY_META_COLUMNS = frozenset(
	{
		"account",
		"account_name",
		"acc_name",
		"acc_number",
		"total",
		"currency",
		"",
	}
)


def _extract_period_keys(columns: list[dict]) -> list[dict]:
	"""Extract period column keys from report columns.

	Works for both standard and template-engine column formats.
	Returns list of {key, label} dicts for each period column.
	"""
	period_keys = []
	for col in columns:
		fn_name = col.get("fieldname", "")
		if fn_name in _MONTHLY_META_COLUMNS:
			continue
		fieldtype = col.get("fieldtype", "")
		if fieldtype in ("Currency", "Float"):
			period_keys.append({"key": fn_name, "label": col.get("label", fn_name)})
	return period_keys


def _extract_monthly_totals(
	data: list[dict],
	period_keys: list[dict],
) -> tuple[dict, dict, dict]:
	"""Extract income/expense totals and net profit per period from P&L rows.

	Works with both standard-path and template-engine-path row formats:
	- Standard path: uses ``is_group`` + ``parent_account`` to find totals
	- Template path: uses ``bold`` + ``indent`` + label matching

	Returns:
		(income_total, expense_total, net_profit_row) — dicts mapping
		period key → value.
	"""
	income_total: dict[str, float] = {}
	expense_total: dict[str, float] = {}
	net_profit_row: dict[str, float] = {}
	current_section: str | None = None

	# Label candidates (lowercase) for section detection
	income_labels = ("income", "revenue")
	expense_labels = ("expense", "expenditure", "cost")
	net_profit_labels = ("net profit", "profit for the year", "profit (loss)", "net income")

	for row in data:
		account = (row.get("account") or row.get("account_name") or "").strip()
		account_lower = account.lower()
		if not account_lower:
			continue

		indent = row.get("indent", 0)
		is_bold = bool(row.get("bold"))

		# ── Section header detection ──
		# Standard path: root-level group accounts (is_group=True, no parent_account)
		# Template path: bold rows at indent=0 containing section keywords
		is_root_row = row.get("is_group") and not row.get("parent_account")
		is_template_header = is_bold and indent == 0

		if is_root_row or is_template_header:
			if any(lbl in account_lower for lbl in income_labels):
				current_section = "income"
			elif any(lbl in account_lower for lbl in expense_labels):
				current_section = "expense"

		# ── Total row extraction ──
		# Capture the section total values: root-level group or bold total row
		if is_root_row or is_template_header:
			target = income_total if current_section == "income" else expense_total
			for pk in period_keys:
				val = row.get(pk["key"])
				if val is not None and isinstance(val, (int, float)) and not isinstance(val, bool):
					target[pk["key"]] = flt(val)

		# ── Net profit row ──
		if any(lbl in account_lower for lbl in net_profit_labels):
			for pk in period_keys:
				val = row.get(pk["key"])
				if val is not None and isinstance(val, (int, float)) and not isinstance(val, bool):
					net_profit_row[pk["key"]] = flt(val)

	return income_total, expense_total, net_profit_row
