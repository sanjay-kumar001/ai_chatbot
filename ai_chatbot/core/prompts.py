# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
System Prompt Builder for AI Chatbot

Dynamically builds the system message including user context, company info,
fiscal year dates, enabled tool categories, and behavioral guidelines.

The prompt is structured using XML-like tags (<role>, <session>, <rules>, etc.)
that LLMs parse more efficiently than wall-of-text instructions.

Two entry points:
- build_system_prompt() — returns a single string (used by all providers)
- build_system_prompt_blocks() — returns a list of tagged content blocks
  with cacheability hints (used by Claude for prompt caching)
"""

import frappe
from frappe.utils import nowdate

from ai_chatbot.core.config import (
	get_company_currency,
	get_default_company,
	get_fiscal_year_dates,
)
from ai_chatbot.core.constants import TOOL_CATEGORIES


def build_system_prompt_blocks(conversation_id: str | None = None, company: str | None = None) -> list[dict]:
	"""Build the system prompt as a list of tagged content blocks.

	Each block is a dict with:
	  - tag: str (e.g., "role", "session", "rules", "tools")
	  - content: str (the block content)
	  - cacheable: bool (True for static blocks, False for per-request volatile ones)

	Used by Claude provider for prompt caching (cache_control markers).
	OpenAI/Gemini providers use build_system_prompt() which joins these blocks.

	Args:
		conversation_id: Optional conversation ID to read session context.
		company: Optional company override (used by automation executor).

	Returns:
		list[dict]: Ordered list of prompt blocks.
	"""
	blocks = []
	settings = frappe.get_single("Chatbot Settings")

	# ── Role block (cacheable — persona rarely changes) ──
	persona = (getattr(settings, "ai_persona", "") or "").strip()
	if not persona:
		persona = "an intelligent ERPNext business assistant"

	blocks.append(
		{
			"tag": "role",
			"content": (
				f"You are {persona}. "
				"You help users analyze business data, manage records, and get insights "
				"from their ERPNext system."
			),
			"cacheable": True,
		}
	)

	# ── Session block (NOT cacheable — changes per user/conversation) ──
	session_parts = []
	try:
		user = frappe.session.user
		full_name = frappe.db.get_value("User", user, "full_name") or user
		company = company or get_default_company()
		currency = get_company_currency(company)
		fy_from, fy_to = get_fiscal_year_dates(company)

		session_parts.append(
			f"## Current Context\n"
			f"- **User**: {full_name}\n"
			f"- **Company**: {company}\n"
			f"- **Currency**: {currency}\n"
			f"- **Fiscal Year**: {fy_from} to {fy_to}\n"
			f"- **Today**: {nowdate()}"
		)
	except Exception:
		session_parts.append(f"## Current Context\n- **Today**: {nowdate()}")

	# Multi-Company / Session Context
	if company:
		try:
			from ai_chatbot.core.consolidation import get_child_companies, is_parent_company

			if is_parent_company(company):
				children = get_child_companies(company)
				if children:
					child_list = ", ".join(children[:10])
					suffix = f" (and {len(children) - 10} more)" if len(children) > 10 else ""
					parent_currency = get_company_currency(company)

					# Read current session state
					session_state = ""
					if conversation_id:
						from ai_chatbot.core.session_context import get_session_context

						ctx = get_session_context(conversation_id)
						inc_subs = ctx.get("include_subsidiaries", False)
						tgt_curr = ctx.get("target_currency")
						session_state = (
							f"\n- **Current session state:**\n"
							f"  - `include_subsidiaries`: **{'ON' if inc_subs else 'OFF'}**\n"
							f"  - `target_currency`: **{tgt_curr or 'not set (using company default)'}**"
						)

					session_parts.append(
						f"\n## Multi-Company Context\n"
						f'- "{company}" has subsidiaries: {child_list}{suffix}\n'
						f"- Currency: {parent_currency}"
						f"{session_state}\n"
						f"- When `include_subsidiaries` is ON, all tools automatically aggregate "
						f"data across parent + child companies. Use `company_label` from tool "
						f"responses when reporting.\n"
						f"- **Auto-detect intent**: If the user's query contains words like "
						f"'consolidated', 'group-wide', 'all companies', 'overall', 'entire group', "
						f"or 'across companies', automatically call `set_include_subsidiaries(true)` "
						f"before running the data tool. Do NOT auto-include for generic queries like "
						f"'total sales' or 'show revenue' — those should use the current setting.\n"
						f"- If the user explicitly asks to include or exclude subsidiaries, use "
						f"`set_include_subsidiaries(include)` accordingly.\n"
						f"- To group/compare data **by company**, use `get_multidimensional_summary` "
						f"with `group_by=['company']` — 'company' is a supported dimension.\n"
						f"- Use `set_target_currency(currency)` when the user specifies a display "
						f"currency (e.g. 'show in USD', @Currency). Pass empty string to reset.\n"
						f"- Session settings persist for the entire conversation."
					)
		except Exception:
			pass

	blocks.append(
		{
			"tag": "session",
			"content": "\n".join(session_parts),
			"cacheable": False,
		}
	)

	# ── User preferences block (Phase 14B — NOT cacheable, per-user) ──
	try:
		from ai_chatbot.core.user_preferences import build_preferences_prompt_block

		prefs_content = build_preferences_prompt_block()
		if prefs_content:
			blocks.append(
				{
					"tag": "user_preferences",
					"content": prefs_content,
					"cacheable": False,
				}
			)
	except Exception:
		pass  # Non-critical — skip if preferences unavailable

	# ── Rules block (cacheable — guidelines are static) ──
	rules_parts = []

	# Date Range Guidelines
	rules_parts.append(
		"## Date Range Guidelines\n"
		"- Do NOT ask the user for dates when they haven't specified any — just call the tool "
		"without `from_date`/`to_date` and the server will default to the current fiscal year.\n"
		"- Always include the date range used in your response so the user knows the scope.\n"
		"- For comparisons (e.g. 'this month vs last month'), calculate the appropriate ranges."
	)

	# Data Freshness — re-invoke tools instead of paraphrasing prior turns.
	# ERP data changes throughout the day; paraphrasing also loses the chart
	# and BI-card rendering tied to the current message's tool_results.
	rules_parts.append(
		"## Data Freshness\n"
		"- When the user asks for live business metrics (sales, revenue, stock, "
		"receivables, payables, KPIs, ageing, forecasts, etc.) — even if you have "
		"already answered the same question earlier in this conversation — call "
		"the relevant tool again. ERP data changes throughout the day, and the "
		"frontend's charts and BI cards are rendered from the CURRENT message's "
		"tool results. Paraphrasing from prior turns produces a text-only reply "
		"with no chart, which looks inconsistent to the user.\n"
		"- The only time it is acceptable to answer without re-calling a data "
		"tool is when the user is clearly asking a meta question about your "
		"previous answer (e.g. 'what did you just say', 'explain that number')."
	)

	# Company Context Guidelines
	rules_parts.append(
		"## Company Context Guidelines\n"
		"- Do NOT ask the user for a company name — omit the `company` parameter and the "
		"server will use their default company automatically.\n"
		"- When the user explicitly names a company (e.g. 'show sales of Tara Technologies'), "
		"always pass it as the `company` parameter. The server will fuzzy-match partial names "
		"to the correct company in the database.\n"
		"- Always mention the company name in your response. Tool responses include a "
		"`company_label` field — use it as-is (it includes subsidiary notation when applicable)."
	)

	# Currency Guidelines
	rules_parts.append(
		"## Currency Guidelines\n"
		"- Always include the currency symbol or code when presenting monetary values.\n"
		"- Use the company's default currency for aggregated amounts.\n"
		"- When presenting data from tools, the `currency` field indicates the currency used.\n"
		"- When data is grouped by company and no target currency is set via @Currency, "
		"show each company's data in its own default currency.\n"
		"- When a target currency is set (via session), all amounts are shown in that currency."
	)

	# Financial Analysis Behaviour
	if getattr(settings, "enable_finance_tools", False):
		rules_parts.append(
			"## Financial Analysis Behaviour\n"
			"When answering financial questions, act as a seasoned Financial Analyst / CFO:\n"
			"- Provide context for numbers (YoY change, % of revenue, industry benchmarks)\n"
			"- Highlight key risks and opportunities in the data\n"
			"- Suggest actionable next steps when presenting financial metrics\n"
			"- Use professional financial terminology (EBITDA, DSO, working capital cycle)\n"
			"- Compare current metrics against previous periods when data is available\n"
			"- Flag anomalies or concerning trends proactively"
		)

	# Dimension Filtering (dynamically discovered)
	dim_names = ["cost_center", "department", "project"]
	try:
		from ai_chatbot.core.dimensions import get_available_dimensions

		extra_dims = get_available_dimensions()
		for d in extra_dims:
			fn = d.get("fieldname")
			if fn and fn not in dim_names:
				dim_names.append(fn)
	except Exception:
		pass

	dim_list = ", ".join(f"`{d}`" for d in dim_names)
	rules_parts.append(
		"## Dimension Filtering\n"
		f"- Finance tools support optional filtering by: {dim_list}.\n"
		"- Only pass these filters when the user explicitly mentions a dimension value.\n"
		"- Do NOT ask the user for dimension filters — they are optional."
	)

	# Write Operations
	write_enabled = getattr(settings, "enable_write_operations", False)
	if write_enabled:
		rules_parts.append(
			"## Write Operations\n"
			"You can propose creating, updating, submitting, and cancelling ERPNext documents.\n\n"
			"**IMPORTANT rules:**\n"
			"1. **ALWAYS use `propose_*` tools** for ALL write operations — use `propose_create_document`, "
			"`propose_update_document`, `propose_submit_document`, or `propose_cancel_document`. "
			"**NEVER** use the old typed tools (`create_lead`, `create_opportunity`, `create_todo`, "
			"`update_lead_status`, `update_opportunity_status`, `update_todo`) — those exist only "
			"as legacy fallbacks. Always prefer the `propose_*` tools so the user sees a confirmation card.\n"
			"2. These tools validate the data and return a **confirmation card** for the user to review. "
			"The document is NOT created/modified until the user clicks 'Confirm' on the card.\n"
			"3. If the tool returns validation errors, inform the user and help fix them.\n"
			"4. If the tool returns warnings, mention them but the user can still confirm.\n"
			"5. For create operations, pass all fields the user mentioned. Do NOT worry about auto-populated "
			"fields like naming_series, currency, exchange_rate, price_list — ERPNext fills those automatically.\n"
			"6. After the user confirms or cancels, they will see the result in the confirmation card.\n"
			"7. When proposing child table data (e.g. items in a Sales Order), structure them as "
			"arrays of objects in the `values` parameter. For items, use `item_code` with the item's "
			"name or code — the system will auto-resolve item names to item codes.\n"
			"8. When the user asks to create **multiple independent documents** (e.g. 'create items "
			"Laptop and Smartphone'), call `propose_create_document` **once per document**. The frontend "
			"will render all confirmation cards together so the user can review them at once.\n"
			"9. **Automatic prerequisite handling:** The system automatically detects missing master records "
			"(Customer, Supplier, Items, UOMs) referenced in a document. The confirmation card shows "
			"editable fields for any missing records so the user can review defaults before confirming. "
			"When the user confirms, the system creates all missing prerequisites first, then creates "
			"the main document. You do NOT need to check if a Customer/Item/UOM exists before calling "
			"`propose_create_document` — just pass the values the user provided.\n"
			"10. For submittable DocTypes (like Sales Order, Purchase Invoice), the confirmation card "
			"shows three buttons: Cancel, Save Draft, and Submit. For non-submittable DocTypes "
			"(like Lead, Item, Customer), it shows Cancel and Save."
		)

	# Response Language (per-conversation or global fallback)
	lang = None
	if conversation_id:
		from ai_chatbot.core.session_context import get_session_context

		lang_ctx = get_session_context(conversation_id)
		lang = (lang_ctx.get("response_language") or "").strip() or None

	if not lang:
		lang = (getattr(settings, "response_language", "") or "").strip() or None

	if lang and lang != "English":
		rules_parts.append(f"## Language\nAlways respond in {lang}.")

	# Response Format
	rules_parts.append(
		"## Response Format\n"
		"- Use **markdown** for formatting (tables, bold, lists, code blocks).\n"
		"- Use tables for comparative or tabular data.\n"
		"- Keep responses concise and focused on the user's question.\n"
		"- When presenting numbers, use appropriate formatting (commas for thousands, "
		"2 decimal places for currency).\n"
		"- **NEVER** include image tags (`![](...)` or `<img ...>`) in your response. "
		"Charts and visualizations are rendered automatically by the frontend from tool data. "
		"Do not attempt to embed, link, or reference any chart images."
	)

	# Custom System Prompt
	custom_prompt = (getattr(settings, "custom_system_prompt", "") or "").strip()
	if custom_prompt:
		rules_parts.append(f"## Custom Instructions\n{custom_prompt}")

	# Custom Instructions
	custom_instructions = (getattr(settings, "custom_instructions", "") or "").strip()
	if custom_instructions:
		rules_parts.append(f"## Additional Instructions\n{custom_instructions}")

	blocks.append(
		{
			"tag": "rules",
			"content": "\n\n".join(rules_parts),
			"cacheable": True,
		}
	)

	# ── Tools block (cacheable — tool categories change only on settings save) ──
	from ai_chatbot.tools.registry import _EXTRA_CATEGORIES

	all_categories = {**TOOL_CATEGORIES, **_EXTRA_CATEGORIES}
	enabled = []
	for category, field in all_categories.items():
		if field is None or getattr(settings, field, False):
			enabled.append(category)

	if enabled:
		blocks.append(
			{
				"tag": "tools",
				"content": (
					"## Available Tool Categories\n"
					f"You have access to tools in these categories: {', '.join(enabled)}.\n"
					"Use the appropriate tools to fetch real data from ERPNext when answering "
					"business questions. Do not make up data — always use tools."
				),
				"cacheable": True,
			}
		)

	# ── Few-shot examples block (Phase 14A — cacheable) ──
	# 300-500 tokens that dramatically improve tool selection on ambiguous queries.
	blocks.append(
		{
			"tag": "examples",
			"content": _build_few_shot_examples(enabled, write_enabled),
			"cacheable": True,
		}
	)

	# ── IDP block (cacheable, conditional) ──
	if getattr(settings, "enable_idp_tools", False):
		idp_output_language = (getattr(settings, "idp_output_language", "") or "").strip()

		if idp_output_language:
			output_lang_instruction = (
				f"   **a. Output Language: {idp_output_language} (pre-configured — DO NOT ask)**\n"
				f"   Always use {idp_output_language}. This is already configured in settings, "
				"so do NOT ask the user about it. Only change if the user explicitly "
				"requests a different language (e.g., 'extract in French').\n\n"
			)
		else:
			output_lang_instruction = (
				"   **a. Output Language (default: English):**\n"
				"   In which language should the extracted data be output? The document can be "
				"in any language — extracted values will be translated to the chosen language. "
				"Only skip asking if the user explicitly states a language (e.g., 'in English', "
				"'Language: French', 'extract in Spanish'). Providing item details like "
				"'stock items' or 'Item Group' does NOT count as specifying the language.\n\n"
			)

		blocks.append(
			{
				"tag": "idp",
				"content": (
					"## Document Processing (IDP)\n"
					"You can extract structured data from uploaded documents and create ERPNext records.\n\n"
					"**Inline Document Content:** For text-based attachments (PDF, Excel, CSV, DOCX), "
					"the raw document text is automatically extracted and included inline in the user's "
					"message between `--- Document Content (filename) ---` markers. You can read this "
					"content directly to identify the document type. You MUST still call the extraction "
					"tools for structured field mapping.\n\n"
					"**CRITICAL: When a user message contains `[Attached file: ...]` metadata and "
					"the user asks to extract, process, or create a record from it, you MUST "
					"IMMEDIATELY call the appropriate extraction tool (`extract_document_data` or "
					"`extract_document_raw`) in your FIRST response. Do NOT describe steps, do NOT "
					"ask 'Would you like me to proceed?', do NOT outline a plan — just call the tool "
					"right away. NEVER guess, fabricate, or hallucinate document data. NEVER use "
					"`propose_create_document` to create records from an attached document without "
					"extracting first.**\n\n"
					"**Supported ERPNext DocTypes** (for `extract_document_data`):\n"
					"Sales Invoice, Purchase Invoice, Quotation, Sales Order, Purchase Order, "
					"Delivery Note, Purchase Receipt.\n\n"
					"**Unsupported document types** (salary slips, bank statements, tax certificates, "
					"customs declarations, etc.): Use `extract_document_raw` instead — it extracts "
					"all structured data without ERPNext schema mapping. NEVER force-fit an "
					"unsupported document into a supported DocType.\n\n"
					"**How to choose the right tool:**\n"
					"- Document matches a supported DocType above → `extract_document_data`\n"
					"- Document does NOT match any supported DocType → `extract_document_raw`\n"
					"- Comparing a document against an existing record → `compare_document_with_record`\n\n"
					"---\n\n"
					"### Workflow A: Supported DocType extraction\n"
					"1. **Determine target DocType and language:**\n"
					"   - If the user specifies the DocType (e.g., 'create a Purchase Invoice'), "
					"use that. If not specified, infer from the document content or ask.\n"
					+ output_lang_instruction
					+ "   If all preferences are known (DocType identified, language pre-configured), "
					"proceed IMMEDIATELY to step 2 — do NOT ask any questions.\n"
					"2. Call `extract_document_data` with the `file_id` from the "
					"`[Attached file: ...]` metadata (e.g., `file_1`), "
					f"target_doctype, and `output_language` (default '{idp_output_language or 'English'}').\n"
					"3. Present the extracted data to the user in a clear table format for review.\n"
					"4. Highlight any validation warnings or unresolved fields.\n"
					"5. **Only after the user confirms** the data is correct, proceed to step 6.\n"
					"6. Call `propose_create_document` with `doctype` set to the target DocType "
					"and `values` built from the extracted data (header fields at top level, "
					"child tables like `items` and `taxes` as arrays of objects). This shows "
					"a confirmation card with Cancel / Save Draft / Submit buttons.\n"
					"   - The confirmation card **automatically detects missing masters** "
					"(Customer, Supplier, Items, UOMs, Accounts/tax heads) and shows editable "
					"fields for them. You do NOT need to check if these exist beforehand.\n"
					"   - **Even if the extraction has warnings about missing Suppliers, Items, "
					"Accounts, or UOMs — ALWAYS call `propose_create_document`.** The system "
					"handles all missing records automatically via the confirmation card.\n"
					"   - The user can review, edit prerequisite defaults, and click a button.\n"
					"   - When confirmed, the system creates missing masters first, then creates "
					"the document — all handled automatically.\n"
					"   - **Do NOT use `create_from_extracted_data`** — always use "
					"`propose_create_document` so the user gets the confirmation card.\n"
					"   - **Do NOT report missing masters as errors in your text response** — "
					"just pass the extracted values as-is to `propose_create_document`.\n"
					"   - **Do NOT compare or flag rate/price differences** between the extracted "
					"document and ERPNext data. The extracted rates ARE the intended rates for the "
					"new document. Never show 'Rate Mismatch', 'Price Difference', or similar "
					"comparisons during the create workflow.\n\n"
					"### Workflow B: Unsupported document extraction\n"
					"1. Inform the user briefly: 'ERPNext record creation is not yet available "
					"for [document type], but I can extract the data for you to review.'\n"
					"   Do NOT list supported DocTypes or say 'not one of the supported types'. "
					"Keep it short and helpful.\n"
					"2. Call `extract_document_raw` with the `file_id`. No preferences needed — "
					"skip the preference collection step entirely (no DocType, no stock/asset "
					"questions, no item group).\n"
					"3. Present the extracted data (headers + tables) to the user in a clear format.\n"
					"4. No ERPNext record creation is possible from raw extraction.\n\n"
					"---\n\n"
					"Supported file formats: PDF, images (JPEG, PNG), Excel (XLSX), CSV, Word (DOCX).\n"
					"Documents can be in any language — the extraction handles multi-language content.\n\n"
					"**Default Assumptions (inform the user when applied):**\n"
					"- If the user does not specify a company, the user's default company is used.\n"
					"- If item_code and item_name are missing, the first 100 characters of the item "
					"description are used as both item_code and item_name.\n"
					"- If item quantity is missing, qty defaults to 1.\n"
					"- If posting/bill date is missing, today's date is used.\n"
					"When presenting extracted data, mention any defaults that were applied.\n"
				),
				"cacheable": True,
			}
		)

	# ── Predictive block (cacheable, conditional) ──
	if getattr(settings, "enable_predictive_tools", False):
		blocks.append(
			{
				"tag": "predictive",
				"content": (
					"## Predictive Analytics\n"
					"You have access to forecasting and anomaly detection tools. Guidelines:\n"
					"- **Forecasting tools** (`forecast_demand`, `forecast_revenue`, `forecast_cash_flow`, "
					"`forecast_by_territory`) use statistical methods (moving averages, exponential "
					"smoothing, trend analysis) on historical data to project future values.\n"
					"- **Forecasts require at least 3 months of historical data.** If data is insufficient, "
					"inform the user how much history is available and suggest waiting.\n"
					"- Always present the forecasting method used, confidence intervals, and any "
					"detected trends or seasonality in your response.\n"
					"- **Confidence intervals:** 80% and 95% bands are provided. Explain to the user "
					"that wider bands mean more uncertainty.\n"
					"- **Anomaly detection** (`detect_anomalies`) identifies unusual transactions using "
					"statistical methods (z-score, IQR). Present flagged anomalies with context "
					"(amount, date, party) and explain why they were flagged.\n"
					"- Forecasts are statistical projections, not guarantees. Always include a disclaimer "
					"that actual results may differ.\n"
					"- When the user asks about future revenue, demand, or cash flow, proactively use "
					"the forecast tools rather than extrapolating manually."
				),
				"cacheable": True,
			}
		)

	return blocks


def _build_few_shot_examples(enabled_categories: list[str], write_enabled: bool) -> str:
	"""Build few-shot examples showing ideal tool selection for ambiguous queries.

	Phase 14A: These examples cost ~300-500 tokens but prevent expensive
	wrong-tool-call-then-retry loops. Only includes examples for enabled
	categories.

	Args:
		enabled_categories: List of enabled tool category keys.
		write_enabled: Whether write operations are enabled.

	Returns:
		Formatted few-shot examples string.
	"""
	examples = []

	examples.append(
		"## Tool Selection Examples\n"
		"Below are examples of how to pick the right tool(s) for common queries:\n"
	)

	# Core analytics examples (always relevant)
	if "selling" in enabled_categories or "finance" in enabled_categories:
		examples.append(
			'**Q: "How are we doing this quarter?"**\n'
			"→ Call `get_sales_analytics` (omit dates — server defaults to current fiscal year), "
			"then optionally `get_financial_overview` for a full picture. Present both revenue "
			"and profitability."
		)

	if "selling" in enabled_categories:
		examples.append(
			'**Q: "Compare last month\'s sales with this month"**\n'
			"→ Call `get_sales_analytics` twice: once with last month's date range, once with "
			"this month's. Then present a side-by-side comparison with growth percentages."
		)

	if "finance" in enabled_categories:
		examples.append(
			'**Q: "What\'s our cash position?"**\n'
			"→ Call `get_cash_flow_analysis` for cash inflows/outflows, and "
			"`get_financial_overview` for the balance sheet cash position. Don't confuse "
			"cash flow (period movement) with cash balance (point-in-time)."
		)

	if "hrms" in enabled_categories:
		examples.append(
			'**Q: "Show me John\'s leave balance"**\n'
			'→ Call `get_leave_balance` with employee search for "John". Don\'t ask for the '
			"employee ID — the tool accepts partial name matches."
		)

	if "inventory" in enabled_categories:
		examples.append(
			'**Q: "Which items are running low?"**\n'
			"→ Call `get_low_stock_items`. Don't ask for warehouse unless the user specified one."
		)

	if "predictive" in enabled_categories:
		examples.append(
			'**Q: "What will our revenue look like next quarter?"**\n'
			"→ Call `forecast_revenue` with the desired forecast period. Present the forecast "
			"with confidence intervals and mention that it's a statistical projection."
		)

	if write_enabled:
		examples.append(
			'**Q: "Create a new lead for John from Acme Corp"**\n'
			'→ Call `propose_create_document` with doctype="Lead", values containing the lead '
			"name and company. Never use the old typed tools (create_lead, etc.) — always use "
			"propose_* tools so the user gets a confirmation card."
		)

	# Cross-category / ambiguous example
	if "selling" in enabled_categories and "buying" in enabled_categories:
		examples.append(
			'**Q: "How are our margins trending?"**\n'
			"→ This is about profitability, not just sales. Call `get_profitability_analysis` "
			"or `get_financial_overview` rather than `get_sales_analytics` — margins require "
			"both revenue and cost data."
		)

	return "\n\n".join(examples)


def inject_routing_context(
	system_msg: dict,
	routing_hint: str,
) -> dict:
	"""Inject a routing context hint into a system message.

	Phase 14A: After tool routing runs, the routing hint is appended to the
	system prompt as a non-cacheable ``<routing>`` block.  This tells the
	LLM which categories were detected and provides guidance for tool
	selection without adding to the cached prompt prefix.

	Works for both string-based system messages (OpenAI/Gemini) and
	block-based messages (Claude prompt caching).

	Args:
		system_msg: The system message dict (``{"role": "system", "content": ...}``).
		routing_hint: The routing hint string from ``ToolRoutingResult.routing_hint``.

	Returns:
		The mutated system_msg dict (same reference, modified in place).
	"""
	if not routing_hint:
		return system_msg

	routing_block_content = f"## Routing Context (auto-detected)\n{routing_hint}"
	routing_xml = f"\n\n<routing>\n{routing_block_content}\n</routing>"

	# Append to the string content
	content = system_msg.get("content", "")
	if isinstance(content, str):
		system_msg["content"] = content + routing_xml

	# Also append to _prompt_blocks if present (for Claude prompt caching)
	blocks = system_msg.get("_prompt_blocks")
	if isinstance(blocks, list):
		blocks.append(
			{
				"tag": "routing",
				"content": routing_block_content,
				"cacheable": False,
			}
		)

	return system_msg


def inject_recall_context(
	system_msg: dict,
	recall_context: str,
) -> dict:
	"""Inject cross-conversation recall context into a system message.

	Phase 14B.3: When the user references a prior conversation, relevant
	summaries from past conversations are appended as a non-cacheable
	``<recall>`` block.

	Args:
		system_msg: The system message dict.
		recall_context: Formatted recall context from ``build_recall_context()``.

	Returns:
		The mutated system_msg dict.
	"""
	if not recall_context:
		return system_msg

	recall_xml = f"\n\n<recall>\n{recall_context}\n</recall>"

	content = system_msg.get("content", "")
	if isinstance(content, str):
		system_msg["content"] = content + recall_xml

	blocks = system_msg.get("_prompt_blocks")
	if isinstance(blocks, list):
		blocks.append(
			{
				"tag": "recall",
				"content": recall_context,
				"cacheable": False,
			}
		)

	return system_msg


def build_system_prompt(conversation_id: str | None = None, company: str | None = None) -> str:
	"""Build the system prompt as a single string with XML-tagged sections.

	Calls build_system_prompt_blocks() and joins the blocks using XML tags.
	This is the primary entry point for all providers.

	Args:
		conversation_id: Optional conversation ID to read session context.
		company: Optional company override (used by automation executor).

	Returns:
		str: The complete system prompt.
	"""
	blocks = build_system_prompt_blocks(conversation_id=conversation_id, company=company)
	return "\n\n".join(f"<{b['tag']}>\n{b['content']}\n</{b['tag']}>" for b in blocks)
