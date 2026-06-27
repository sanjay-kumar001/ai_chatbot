# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
LLM-Powered Semantic Document Mapper

Constructs a structured extraction prompt combining the raw document content
with the target ERPNext DocType schema, sends it to the configured AI provider,
and parses the structured JSON response.

This is the core of the IDP system — the LLM does the semantic reasoning to
map non-uniform, multi-language source data to ERPNext fields.
"""

from __future__ import annotations

import json
import re

import frappe

from ai_chatbot.core.logger import log_error
from ai_chatbot.idp.extractors.base import extract_content
from ai_chatbot.idp.schema import build_schema_prompt, get_doctype_schema
from ai_chatbot.utils.ai_providers import get_ai_provider

# Maximum characters of extracted text to include in the prompt
MAX_CONTENT_LENGTH = 15000

# Common field name mistakes the LLM makes — map to correct ERPNext fieldnames
_FIELD_ALIASES = {
	"terms_and_conditions": "terms",
	"bank_details": "remarks",
	"contact_person": "contact_display",
}


#: Transaction DocTypes where `company` must come from the session context.
#: The LLM occasionally mis-identifies the recipient block on an invoice as
#: the ERPNext "company" field, which then gets fuzzy-matched to an unrelated
#: Company record. For record-creation flows we overwrite `company` with the
#: session value to prevent that. The comparison flow intentionally leaves
#: the LLM value intact so mismatches remain visible.
_CONTEXT_COMPANY_DOCTYPES = frozenset({
	"Sales Invoice",
	"Purchase Invoice",
	"Sales Order",
	"Purchase Order",
	"Quotation",
	"Delivery Note",
	"Purchase Receipt",
})


def extract_and_map(
	file_url: str,
	target_doctype: str,
	company: str | None = None,
	output_language: str = "English",
	enforce_context_company: bool = False,
) -> dict:
	"""Extract data from a document and map it to an ERPNext DocType schema.

	Orchestrates the full extraction pipeline:
	1. Extract raw content from the file (text or image)
	2. Build the target schema description
	3. Construct the LLM extraction prompt
	4. Send to AI provider and parse response
	5. Normalize extracted values (dates, numbers)

	Args:
		file_url: Frappe file URL of the uploaded document.
		target_doctype: ERPNext DocType to map to (e.g., "Sales Invoice").
		company: Company context for defaults.
		output_language: Language for extracted output values (default "English").
		enforce_context_company: If True, overwrite `company` in the extracted
			data with the session-context `company` for supported transaction
			DocTypes. Use this on record-creation paths. Leave False on
			comparison/audit paths where LLM-extracted values must remain
			visible so discrepancies are not silently hidden.

	Returns:
		dict with keys:
			success: bool
			extracted_data: dict — the mapped field values
			unmapped_fields: list — source fields that could not be mapped
			warnings: list — non-fatal issues encountered
	"""
	# Step 1: Extract content
	content = extract_content(file_url)

	# Step 2: Build schema prompt
	schema_prompt = build_schema_prompt(target_doctype)
	schema = get_doctype_schema(target_doctype)

	# Step 3: Build LLM messages
	messages = _build_extraction_messages(
		content, schema_prompt, target_doctype, company, output_language, schema
	)

	# Step 4: Call AI provider
	settings = frappe.get_single("Chatbot Settings")
	provider_name = settings.ai_provider or "OpenAI"
	provider = get_ai_provider(provider_name)

	try:
		response = provider.chat_completion(messages)
	except Exception as e:
		log_error(f"IDP extraction LLM error: {e!s}", title="IDP")
		return {"success": False, "error": f"AI provider error: {e!s}"}

	# Step 5: Parse response
	extracted_json = _parse_llm_response(response, provider_name)
	if not extracted_json:
		return {"success": False, "error": "Could not parse structured data from AI response"}

	# Step 6: Normalize values
	normalized = _normalize_extracted_data(extracted_json, schema)

	# Step 7: Enforce context-only fields (record-creation paths only).
	# For transaction DocTypes on the creation path, overwrite the LLM's
	# `company` value with the session-context company. This prevents the
	# LLM's occasional mis-identification of the document recipient as the
	# ERPNext company from flowing into the extracted data or confirmation
	# card. The comparison path leaves `enforce_context_company=False` so
	# genuine discrepancies remain visible to the user.
	normalized_data = normalized.get("data", {}) or {}
	if (
		enforce_context_company
		and company
		and target_doctype in _CONTEXT_COMPANY_DOCTYPES
		and _schema_has_company_field(schema)
	):
		normalized_data["company"] = company

	return {
		"success": True,
		"extracted_data": normalized_data,
		"unmapped_fields": extracted_json.get("unmapped_fields", []),
		"warnings": normalized.get("warnings", []),
		"source_file": file_url,
		"target_doctype": target_doctype,
	}


def _schema_has_company_field(schema: dict) -> bool:
	"""Return True if the target DocType schema declares a `company` field."""
	for field in schema.get("fields", []) or []:
		if field.get("fieldname") == "company":
			return True
	return False


def extract_raw(
	file_url: str,
	output_language: str = "English",
) -> dict:
	"""Extract all structured data from a document without ERPNext schema mapping.

	For documents that don't match any supported ERPNext DocType (e.g., salary
	slips, bank statements, tax certificates). Extracts whatever structured data
	the document contains and returns it as-is.

	Args:
		file_url: Frappe file URL of the uploaded document.
		output_language: Language for extracted output values (default "English").

	Returns:
		dict with keys:
			success: bool
			document_type: str — detected document type
			headers: dict — key-value pairs from the document header
			tables: list[list[dict]] — tabular data sections found
			summary: str — brief description of the document
	"""
	# Step 1: Extract content
	content = extract_content(file_url)

	# Step 2: Build generic extraction messages (no schema)
	messages = _build_raw_extraction_messages(content, output_language)

	# Step 3: Call AI provider
	settings = frappe.get_single("Chatbot Settings")
	provider_name = settings.ai_provider or "OpenAI"
	provider = get_ai_provider(provider_name)

	try:
		response = provider.chat_completion(messages)
	except Exception as e:
		log_error(f"IDP raw extraction LLM error: {e!s}", title="IDP")
		return {"success": False, "error": f"AI provider error: {e!s}"}

	# Step 4: Parse response
	extracted_json = _parse_llm_response(response, provider_name)
	if not extracted_json:
		return {"success": False, "error": "Could not parse structured data from AI response"}

	return {
		"success": True,
		"document_type": extracted_json.get("document_type", "Unknown"),
		"headers": extracted_json.get("headers", {}),
		"tables": extracted_json.get("tables", []),
		"summary": extracted_json.get("summary", ""),
		"source_file": file_url,
	}


def _build_raw_extraction_messages(
	content: dict,
	output_language: str = "English",
) -> list[dict]:
	"""Build LLM messages for generic (schema-free) document extraction."""
	system_message = (
		"You are an expert data extraction specialist. Your task is to extract ALL "
		"structured data from the uploaded document. Do NOT map to any specific ERP "
		"schema — extract the data exactly as it appears in the document.\n\n"
		"CRITICAL RULES:\n"
		"1. Respond ONLY with valid JSON. No markdown fences, no explanations.\n"
		"2. Extract ALL fields — header/metadata fields as key-value pairs, and any "
		"tabular data as arrays of objects.\n"
		"3. Convert dates to YYYY-MM-DD format.\n"
		"4. Strip currency symbols from numbers but preserve the currency code.\n"
		"5. Preserve the original field names/labels from the document as JSON keys.\n"
		"6. NEVER include boilerplate text like 'This is a computer generated document'.\n"
	)

	if output_language and output_language.lower() != "original":
		system_message += (
			f"\nOUTPUT LANGUAGE: {output_language}\n"
			f"Translate all text values to {output_language}. Keep numbers, dates, "
			f"currency codes, and proper nouns (names) unchanged.\n"
		)

	user_parts = [
		"Extract ALL structured data from the following document.\n\n"
		"## Required JSON Output Format\n\n"
		"```json\n"
		"{\n"
		'  "document_type": "detected type (e.g., Salary Slip, Bank Statement, Tax Certificate)",\n'
		'  "headers": {\n'
		'    "field_label": "value",\n'
		"    ...\n"
		"  },\n"
		'  "tables": [\n'
		"    [\n"
		'      {"column1": "value", "column2": "value", ...},\n'
		"      ...\n"
		"    ]\n"
		"  ],\n"
		'  "summary": "Brief one-line description of the document"\n'
		"}\n"
		"```\n\n"
		"**Rules:**\n"
		"- `headers`: All non-tabular key-value pairs (dates, names, IDs, totals, etc.)\n"
		"- `tables`: Each distinct table in the document as a separate array of row objects. "
		"If the document has an earnings table and a deductions table, return them as two "
		"separate arrays within `tables`.\n"
		"- If there are no tables, set `tables` to an empty array.\n"
		"- Use the field labels from the document as JSON keys (cleaned up for readability).\n\n"
		"Respond ONLY with the JSON object."
	]

	if content["content_type"] == "text":
		text = content["text"]
		if len(text) > MAX_CONTENT_LENGTH:
			text = text[:MAX_CONTENT_LENGTH] + "\n\n[... content truncated ...]"

		user_parts.append(f"\n\n## Document Content\n\n```\n{text}\n```")

		return [
			{"role": "system", "content": system_message},
			{"role": "user", "content": "\n".join(user_parts)},
		]

	# Image content — use Vision API format
	user_text = "\n".join(user_parts)
	user_text += "\n\n## Document\n\nSee the attached image of the document."

	return [
		{"role": "system", "content": system_message},
		{
			"role": "user",
			"content": [
				{"type": "text", "text": user_text},
				{
					"type": "image_url",
					"image_url": {
						"url": f"data:{content['mime_type']};base64,{content['base64']}",
					},
				},
			],
		},
	]


def _build_extraction_messages(
	content: dict,
	schema_prompt: str,
	target_doctype: str,
	company: str | None,
	output_language: str = "English",
	schema: dict | None = None,
) -> list[dict]:
	"""Build the messages array for the LLM extraction call.

	For text-based documents, embeds the text in the user message.
	For images, uses Vision API format with base64 image.

	Args:
		content: Extracted content from the file.
		schema_prompt: Human-readable schema description.
		target_doctype: Target DocType name.
		company: Company context.
		output_language: Language for extracted output values.

	Returns:
		List of message dicts in OpenAI format.
	"""
	system_message = _build_system_prompt(target_doctype, company, output_language)

	# Build dynamic child table rules and JSON format from schema
	child_tables = schema.get("child_tables", {}) if schema else {}
	child_table_rules = _build_child_table_rules(child_tables)
	json_output_format = _build_json_output_format(child_tables)

	user_parts = [
		f"Extract structured data from the following document and map it to the "
		f"ERPNext **{target_doctype}** schema.\n\n"
		f"## Target Schema\n\n{schema_prompt}\n\n"
		f"## Extraction Rules\n\n"
		f"1. Map source fields to target fields using semantic reasoning — field names "
		f"in the document may differ from ERPNext field names.\n"
		f"2. The document may be in ANY language. Identify fields by their semantic "
		f"meaning, not by exact header text.\n"
		f"3. Convert ALL dates to YYYY-MM-DD format.\n"
		f"4. Strip currency symbols, commas, and whitespace from numeric values. "
		f'Return clean numbers (e.g., "$1,234.56" → 1234.56).\n'
		f"5. If a currency is mentioned or can be inferred, include it in the "
		f"`currency` field. If not found, omit it.\n"
		f"6. Set `conversion_rate` to 1.0 unless explicitly stated otherwise.\n"
		f"{child_table_rules}"
		f"7. For Link fields, use the most likely matching name from ERPNext "
		f"(e.g., a customer name, supplier name, or item code).\n"
		f"8. If a field cannot be identified, set it to null — do NOT guess.\n"
		f"9. Include any source fields you could not map in `unmapped_fields`.\n"
		f"10. **Party identification (CRITICAL for invoices):** The company/entity "
		f"shown in the document header/letterhead/logo is the **issuer** of the "
		f"document. The entity listed under 'Customer', 'Bill To', 'Ship To', "
		f"'Buyer', or 'M/S' is the **recipient**.\n"
		f"   - For **Purchase Invoice**: extract the issuer's ACTUAL COMPANY NAME "
		f"(from the letterhead/logo/header) and set it as the `supplier` field value. "
		f"The recipient is YOUR company — ignore it (ERPNext sets `company` separately). "
		f"Do NOT set supplier to the word 'Supplier' — use the real company name.\n"
		f"   - For **Sales Invoice**: the issuer is YOUR company (ignore it); extract "
		f"the recipient's ACTUAL NAME and set it as the `customer` field value.\n"
		f"   - For **Purchase Order**: extract the recipient/addressee's ACTUAL NAME "
		f"and set it as the `supplier` field value.\n"
		f"   - For **Quotation/Sales Order**: extract the recipient's ACTUAL NAME "
		f"and set it as the `customer` field value.\n"
		f"   **IMPORTANT: The supplier/customer field must contain an actual company "
		f"or person name extracted from the document, NEVER the literal word "
		f"'Supplier' or 'Customer'.**\n\n"
		f"## Content Filtering (CRITICAL)\n\n"
		f"You MUST completely discard the following boilerplate text. It is NOT part of "
		f"the document's terms, conditions, or any other field:\n"
		f'- "This document is created automatically and does not require signature"\n'
		f'- "This is a computer generated document"\n'
		f'- "No signature required"\n'
		f'- "This is a system generated document"\n'
		f"- Any variation of the above auto-generation disclaimers or footer notices.\n"
		f"These phrases MUST NOT appear in `terms`, `remarks`, or ANY other extracted "
		f"field. Strip them completely.\n\n"
		f"## Special Field Mappings\n\n"
		f"Apply these mappings when the source document contains these fields:\n"
		f'- **"Attn." / "Attention" / "Contact Person"** → map to `contact_display`\n'
		f'- **"Address" / "Billing Address" / "Shipping Address"** (party address block) '
		f"→ map to `address_display`\n"
		f"- **Terms & Conditions section** — IMPORTANT: Carefully separate the actual "
		f"terms/conditions text from bank details. The Terms & Conditions section often "
		f"contains a mix of:\n"
		f"  1. **Actual terms text** (e.g., payment terms, thank-you notes, wire transfer "
		f"instructions like 'Please include invoice number when making wire transfer') "
		f"→ map ALL of this to the header field `terms` (fieldname: `terms`). "
		f"The `terms` field is a Text Editor field that holds free-form text. "
		f"Do NOT use `tc_name` — that is a Link field for referencing a pre-defined "
		f"Terms template. Do NOT use `terms_and_conditions` either.\n"
		f"  2. **Bank/payment details** (Account Name, Bank Name, Bank Address, IBAN, "
		f"Swift Code, IFSC, Account Number, Sort Code, Routing Number, Currency, "
		f"Payable To) → collect ALL bank-related fields into the header field "
		f"`remarks` (fieldname: `remarks`) as formatted text (e.g., "
		f"'Bank Details:\\nAccount Name: ...\\nBank: ...\\n"
		f"IBAN: ...\\nSwift Code: ...'). Do NOT use `bank_details` as the key.\n"
		f"  Do NOT mix bank details into the `terms` field or vice versa.\n"
		f"  CRITICAL: Use the exact fieldnames `terms` and `remarks` in the JSON output.\n"
		f"- Do NOT create separate lead/customer records for items. Items are product "
		f"line items, not contacts or parties.\n\n"
		f"## Fields to EXCLUDE from extraction\n\n"
		f"Do NOT populate these fields — they are auto-managed by ERPNext:\n"
		f"- `tc_name` (Terms and Conditions Link — do NOT map terms text here)\n"
		f"- `naming_series`\n"
		f"- `docstatus`\n\n"
		f"## Required JSON Output Format\n\n"
		f"```json\n{json_output_format}\n```\n\n"
		f"Respond ONLY with the JSON object. No explanations or markdown outside the JSON."
	]

	if content["content_type"] == "text":
		# Truncate very long documents
		text = content["text"]
		if len(text) > MAX_CONTENT_LENGTH:
			text = text[:MAX_CONTENT_LENGTH] + "\n\n[... content truncated ...]"

		user_parts.append(f"\n\n## Document Content\n\n```\n{text}\n```")

		return [
			{"role": "system", "content": system_message},
			{"role": "user", "content": "\n".join(user_parts)},
		]

	# Image content — use Vision API format
	user_text = "\n".join(user_parts)
	user_text += "\n\n## Document\n\nSee the attached image of the document."

	return [
		{"role": "system", "content": system_message},
		{
			"role": "user",
			"content": [
				{"type": "text", "text": user_text},
				{
					"type": "image_url",
					"image_url": {
						"url": f"data:{content['mime_type']};base64,{content['base64']}",
					},
				},
			],
		},
	]


def _is_items_table(child: dict) -> bool:
	"""Check if a child table schema represents an items/line-items table.

	Detects by looking for a Link field pointing to the Item DocType.
	"""
	return any(
		f.get("fieldtype") == "Link" and f.get("link_doctype") == "Item" for f in child.get("fields", [])
	)


def _is_tax_table(child: dict) -> bool:
	"""Check if a child table schema represents a taxes/charges table.

	Detects by looking for fields named charge_type or account_head.
	"""
	field_names = {f["fieldname"] for f in child.get("fields", [])}
	return bool({"charge_type", "account_head"} & field_names)


def _build_child_table_rules(child_tables: dict) -> str:
	"""Build dynamic extraction rules for all child tables in the schema.

	Generates items-specific rules for item tables, tax-specific rules
	for tax/charge tables, and generic rules for any other child tables.

	Returns a multi-line rule string to embed in the extraction prompt.
	"""
	if not child_tables:
		return ""

	parts = []
	for table_fieldname, child in child_tables.items():
		table_label = child.get("label", table_fieldname)

		if _is_items_table(child):
			parts.append(
				f"- **{table_label}** (`{table_fieldname}`): Extract each line item/product/service "
				f"into the `{table_fieldname}` array. For EVERY item row you MUST populate ALL of these fields:\n"
				f"   - `item_code`: the product/part code or SKU. If no separate code column "
				f"exists, use the first 100 characters of the item description text.\n"
				f"   - `item_name`: a short product name or title (max ~140 characters).\n"
				f"   - `description`: the COMPLETE, VERBATIM, UNTRUNCATED text from the "
				f"Description / Item Name / Product column. This MUST be the FULL text including "
				f"ALL part numbers, specifications, model numbers, dimensions, materials, and "
				f"every word in the cell. NEVER truncate or summarize. The `description` field "
				f"MUST be AT LEAST as long as `item_name` — it should be the longest of the "
				f"three fields. If there is only one text column for the item, use the FULL text "
				f"as `description` and derive shorter versions for `item_code` and `item_name`.\n"
				f"   - `qty`: quantity.\n"
				f"   - `rate`: unit price/rate.\n"
				f"   - `amount`: line total amount.\n"
				f"   - `uom`: unit of measure.\n"
				f"   If the document has only ONE column for item identification (e.g., 'Description' "
				f"or 'Item Name'), use the FULL cell text as `description`, and use the first 100 "
				f"characters as both `item_code` and `item_name`.\n"
			)
		elif _is_tax_table(child):
			parts.append(
				f"- **{table_label}** (`{table_fieldname}`): Extract each tax, duty, or charge "
				f"line into the `{table_fieldname}` array. For each tax row, extract:\n"
				f'   - `charge_type`: set to `"On Net Total"` unless the document explicitly '
				f"states a different basis (e.g., on previous row total).\n"
				f"   - `account_head`: the tax/account name exactly as shown in the document "
				f'(e.g., "CGST", "SGST", "IGST", "VAT", "Service Tax"). '
				f"Include the full name — the system will resolve or create it.\n"
				f"   - `rate`: the tax rate as a percentage number (e.g., 9 for 9%).\n"
				f"   - `tax_amount`: the calculated tax amount.\n"
				f"   - `description`: the tax description or label from the document.\n"
				f"   - `included_in_print_rate`: set to 1 if the tax is included in item prices, "
				f"otherwise 0 or omit.\n"
				f"   If the document shows taxes (GST, VAT, duties, cess, etc.) you MUST extract "
				f"them here — do NOT ignore tax lines.\n"
			)
		else:
			# Generic child table — list key fields
			key_fields = [
				f"`{cf['fieldname']}` ({cf['label']})"
				for cf in child.get("fields", [])[:8]
				if cf.get("reqd") or cf["fieldname"] not in ("parent", "parentfield", "parenttype", "idx")
			]
			if key_fields:
				fields_str = ", ".join(key_fields)
				parts.append(
					f"- **{table_label}** (`{table_fieldname}`): If the document contains data "
					f"for this table, extract each row into the `{table_fieldname}` array. "
					f"Key fields: {fields_str}.\n"
				)

	if not parts:
		return ""

	return (
		"**Child Tables** — Extract data into the following child table arrays:\n" + "\n".join(parts) + "\n"
	)


def _build_json_output_format(child_tables: dict) -> str:
	"""Build the dynamic JSON output format example for the extraction prompt.

	Includes all child tables discovered from the DocType schema, with
	appropriate example fields for each table type.
	"""
	parts = ['  "header": {\n    "field_name": "value",\n    ...\n  }']

	for table_fieldname, child in child_tables.items():
		if _is_items_table(child):
			parts.append(
				f'  "{table_fieldname}": [\n'
				f'    {{"item_code": "...", "item_name": "...", "description": "full text...", '
				f'"qty": ..., "rate": ..., "amount": ..., "uom": "..."}},\n'
				f"    ...\n"
				f"  ]"
			)
		elif _is_tax_table(child):
			parts.append(
				f'  "{table_fieldname}": [\n'
				f'    {{"charge_type": "On Net Total", "account_head": "CGST", '
				f'"rate": 9.0, "tax_amount": 100.0, "description": "CGST @ 9%"}},\n'
				f"    ...\n"
				f"  ]"
			)
		else:
			# Generic: show a few key fields from the schema
			example_fields = []
			for cf in child.get("fields", [])[:4]:
				example_fields.append(f'"{cf["fieldname"]}": "..."')
			if example_fields:
				row_example = ", ".join(example_fields)
				parts.append(f'  "{table_fieldname}": [\n    {{{row_example}}},\n    ...\n  ]')

	parts.append('  "unmapped_fields": ["source_field_1", "source_field_2"]')

	return "{\n" + ",\n".join(parts) + "\n}"


def _build_system_prompt(target_doctype: str, company: str | None, output_language: str = "English") -> str:
	"""Build the system prompt for the extraction LLM call."""
	parts = [
		"You are an expert data extraction specialist for ERPNext ERP systems. "
		"Your task is to extract structured data from business documents "
		"(invoices, purchase orders, quotations, receipts) and map the extracted "
		"fields to ERPNext DocType schemas.",
		"",
		"You excel at:",
		"- Identifying fields regardless of language or naming conventions",
		"- Mapping non-standard headers to standard ERPNext field names",
		"- Normalizing dates, currencies, and numeric values",
		"- Handling multi-format documents (tables, free-form text, mixed layouts)",
		"- Translating extracted values to the requested output language",
	]

	if company:
		parts.append(f"\nCompany context: {company}")

	# Output language instruction
	if output_language and output_language.lower() != "original":
		parts.append(
			f"\nOUTPUT LANGUAGE: {output_language}"
			f"\nAll extracted text values (item descriptions, item names, terms, remarks, "
			f"addresses, party names, and any other free-text fields) MUST be translated "
			f"to {output_language}. Keep numeric values, dates, currency codes, and "
			f"ERPNext field names (JSON keys) unchanged — only translate the text content. "
			f"Proper nouns (company names, person names) should be kept in their original form."
		)

	parts.append(
		"\nCRITICAL RULES:"
		"\n1. Respond ONLY with valid JSON. No markdown fences, no explanations."
		"\n2. NEVER include boilerplate text like 'This document is created automatically', "
		"'This is a computer generated document', or similar auto-generation disclaimers "
		"in ANY field (especially not in `terms`)."
		"\n3. For each item row, you MUST populate `item_code`, `item_name`, AND "
		"`description` — if the document has only one column for item identification, "
		"use the full text as `description` and shortened versions for `item_code`/`item_name`."
		"\n4. The `description` field for each item MUST contain the FULL, VERBATIM text "
		"from the source document. It must NEVER be shorter than `item_name`. If the "
		"document has detailed product descriptions, specifications, or notes in the "
		"item rows, ALL of that text goes into `description`."
		"\n5. When the document contains taxes, charges, duties, GST, VAT, or fees, "
		"you MUST extract each tax/charge line into the taxes child table array. "
		"Include the tax description, rate percentage, tax amount, and the account/head name. "
		"Do NOT put tax information only in the header — it MUST go into the child table rows."
	)

	return "\n".join(parts)


def _parse_llm_response(response: dict, provider_name: str) -> dict | None:
	"""Parse the LLM response to extract the JSON object.

	Handles both OpenAI and Claude response formats.

	Args:
		response: Raw API response from the AI provider.
		provider_name: "OpenAI", "Claude", or "Gemini".

	Returns:
		Parsed dict or None if parsing failed.
	"""
	text = ""

	if provider_name == "Claude":
		# Claude format: response.content[0].text
		content_blocks = response.get("content", [])
		for block in content_blocks:
			if block.get("type") == "text":
				text = block.get("text", "")
				break
	else:
		# OpenAI/Gemini format: response.choices[0].message.content
		choices = response.get("choices", [])
		if choices:
			text = choices[0].get("message", {}).get("content", "")

	if not text:
		return None

	return _extract_json_from_text(text)


def _extract_json_from_text(text: str) -> dict | None:
	"""Extract a JSON object from LLM response text.

	Handles cases where the LLM wraps JSON in markdown code fences
	or adds explanatory text before/after.

	Args:
		text: Raw LLM response text.

	Returns:
		Parsed dict or None.
	"""
	# Try direct parse first
	text = text.strip()
	try:
		return json.loads(text)
	except json.JSONDecodeError:
		pass

	# Try extracting from markdown code fence
	code_block_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
	if code_block_match:
		try:
			return json.loads(code_block_match.group(1).strip())
		except json.JSONDecodeError:
			pass

	# Try finding first { to last }
	first_brace = text.find("{")
	last_brace = text.rfind("}")
	if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
		try:
			return json.loads(text[first_brace : last_brace + 1])
		except json.JSONDecodeError:
			pass

	return None


def _normalize_extracted_data(extracted: dict, schema: dict) -> dict:
	"""Normalize extracted values to match ERPNext expectations.

	- Converts date strings to YYYY-MM-DD
	- Strips currency symbols and commas from numbers
	- Sets default conversion_rate to 1.0

	Args:
		extracted: Parsed JSON from LLM response.
		schema: DocType schema from get_doctype_schema().

	Returns:
		dict with "data" (normalized) and "warnings" (list of issues).
	"""
	warnings = []
	header = extracted.get("header", {})

	# Build a lookup of field types from schema (header fields only)
	field_types = {}
	for f in schema.get("fields", []):
		field_types[f["fieldname"]] = f["fieldtype"]

	# Normalize header fields
	normalized_header = {}
	for key, value in header.items():
		if value is None:
			continue
		ftype = field_types.get(key, "Data")
		normalized_value, warning = _normalize_value(key, value, ftype)
		if warning:
			warnings.append(warning)
		if normalized_value is not None:
			normalized_header[key] = normalized_value

	# Fix common LLM field name mistakes
	for alias, correct_name in _FIELD_ALIASES.items():
		if alias in normalized_header and correct_name not in normalized_header:
			normalized_header[correct_name] = normalized_header.pop(alias)
		elif alias in normalized_header:
			del normalized_header[alias]

	# If tc_name contains free text (not a valid template name), move to terms
	tc_value = normalized_header.get("tc_name")
	if tc_value and len(str(tc_value)) > 50:
		if "terms" not in normalized_header:
			normalized_header["terms"] = normalized_header.pop("tc_name")
		else:
			del normalized_header["tc_name"]

	# Remove fields that should not be set from extraction
	for exclude_field in ("naming_series", "docstatus"):
		normalized_header.pop(exclude_field, None)

	# Set default conversion_rate if not present
	if "conversion_rate" not in normalized_header:
		normalized_header["conversion_rate"] = 1.0

	# Default posting_date / bill_date to today if missing
	from frappe.utils import nowdate

	for date_field in ("posting_date", "transaction_date", "bill_date"):
		if date_field in field_types and date_field not in normalized_header:
			normalized_header[date_field] = nowdate()
			warnings.append(f"Assumed today's date for missing '{date_field}'.")

	# Normalize ALL child tables from schema (items, taxes, etc.)
	result = {**normalized_header}

	for table_fieldname, child in schema.get("child_tables", {}).items():
		raw_rows = extracted.get(table_fieldname, [])
		if not isinstance(raw_rows, list) or not raw_rows:
			continue

		# Build per-table field type lookup
		ct_field_types = {}
		for cf in child.get("fields", []):
			ct_field_types[cf["fieldname"]] = cf["fieldtype"]

		is_item_table = _is_items_table(child)

		normalized_rows = []
		for idx, row in enumerate(raw_rows):
			if not isinstance(row, dict):
				continue
			norm_row = {}
			for key, value in row.items():
				if value is None:
					continue
				ftype = ct_field_types.get(key, "Data")
				normalized_value, warning = _normalize_value(f"{table_fieldname}[{idx}].{key}", value, ftype)
				if warning:
					warnings.append(warning)
				if normalized_value is not None:
					norm_row[key] = normalized_value

			if norm_row:
				# Apply items-specific defaults only to item tables
				if is_item_table:
					_apply_item_defaults(norm_row, idx, table_fieldname, warnings)
				normalized_rows.append(norm_row)

		if normalized_rows:
			result[table_fieldname] = normalized_rows

	return {"data": result, "warnings": warnings}


def _apply_item_defaults(norm_item: dict, idx: int, table_fieldname: str, warnings: list) -> None:
	"""Apply items-specific default values (qty, item_code, item_name).

	Only called for child tables that are Item-type tables
	(i.e., have a Link field to the Item DocType).
	"""
	# Default qty to 1 if missing
	if "qty" not in norm_item:
		norm_item["qty"] = 1.0
		warnings.append(f"{table_fieldname}[{idx}]: Assumed qty = 1 (not found in document).")

	# If item_code and item_name are both missing, derive from description
	has_item_code = bool(norm_item.get("item_code"))
	has_item_name = bool(norm_item.get("item_name"))
	description = norm_item.get("description", "")

	if not has_item_code and not has_item_name and description:
		derived_name = description[:100].strip()
		norm_item["item_code"] = derived_name
		norm_item["item_name"] = derived_name
		warnings.append(
			f"{table_fieldname}[{idx}]: Derived item_code/item_name from description (first 100 chars)."
		)
	elif not has_item_code and has_item_name:
		norm_item["item_code"] = norm_item["item_name"]
	elif has_item_code and not has_item_name:
		norm_item["item_name"] = norm_item["item_code"]


def _normalize_value(field_path: str, value, field_type: str) -> tuple:
	"""Normalize a single field value based on its expected type.

	Args:
		field_path: Dot-path for error reporting (e.g., "posting_date", "items[0].qty").
		value: Raw value from LLM extraction.
		field_type: ERPNext field type (Date, Currency, Float, Int, etc.).

	Returns:
		(normalized_value, warning_string_or_None)
	"""
	if field_type in ("Date", "Datetime"):
		return _normalize_date(field_path, value)

	if field_type in ("Currency", "Float", "Percent"):
		return _normalize_number(field_path, value)

	if field_type == "Int":
		return _normalize_int(field_path, value)

	if field_type == "Check":
		if isinstance(value, bool):
			return int(value), None
		if isinstance(value, str):
			return int(value.lower() in ("1", "true", "yes")), None
		return int(bool(value)), None

	# Data, Link, Select, Text — return as-is (string)
	return str(value) if value is not None else None, None


def _normalize_date(field_path: str, value) -> tuple:
	"""Normalize a date value to YYYY-MM-DD format."""
	if not isinstance(value, str):
		value = str(value)

	value = value.strip()

	# Already in YYYY-MM-DD format
	if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
		return value, None

	# Try common date formats
	from frappe.utils import getdate

	try:
		parsed = getdate(value)
		return str(parsed), None
	except Exception:
		pass

	# Try additional formats
	import datetime

	formats = [
		"%d/%m/%Y",
		"%m/%d/%Y",
		"%d-%m-%Y",
		"%m-%d-%Y",
		"%d.%m.%Y",
		"%Y/%m/%d",
		"%B %d, %Y",
		"%b %d, %Y",
		"%d %B %Y",
		"%d %b %Y",
	]
	for fmt in formats:
		try:
			parsed = datetime.datetime.strptime(value, fmt)
			return parsed.strftime("%Y-%m-%d"), None
		except ValueError:
			continue

	return value, f"Could not parse date for {field_path}: '{value}'"


def _normalize_number(field_path: str, value) -> tuple:
	"""Normalize a numeric value — strip currency symbols and commas."""
	if isinstance(value, int | float):
		return float(value), None

	if not isinstance(value, str):
		value = str(value)

	# Strip common currency symbols, commas, spaces
	cleaned = re.sub(r"[^\d.\-]", "", value.replace(",", ""))

	if not cleaned:
		return None, f"Could not parse number for {field_path}: '{value}'"

	try:
		return float(cleaned), None
	except ValueError:
		return None, f"Could not parse number for {field_path}: '{value}'"


def _normalize_int(field_path: str, value) -> tuple:
	"""Normalize an integer value."""
	if isinstance(value, int):
		return value, None
	if isinstance(value, float):
		return int(value), None

	num, warning = _normalize_number(field_path, value)
	if num is not None:
		return int(num), warning
	return None, warning
