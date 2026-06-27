# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
IDP Tools Module — Intelligent Document Processing

Registered tools that the LLM can call to:
1. Extract structured data from uploaded documents
2. Create ERPNext records from extracted data
3. Compare uploaded documents against existing records

These tools use the IDP pipeline: content extraction → LLM semantic mapping →
validation → record creation/comparison.
"""

import json

import frappe

from ai_chatbot.core.config import get_default_company
from ai_chatbot.core.logger import log_error
from ai_chatbot.data.currency import build_currency_response
from ai_chatbot.data.operations import create_document
from ai_chatbot.idp.comparison import compare_with_record
from ai_chatbot.idp.mapper import extract_and_map, extract_raw
from ai_chatbot.idp.validators import validate_extraction
from ai_chatbot.tools.registry import register_tool


@register_tool(
	name="extract_document_data",
	category="idp",
	description=(
		"Extract structured data from an uploaded document (invoice, purchase order, "
		"quotation, receipt) and map it to an ERPNext DocType schema. "
		"The document can be in any language and any format (PDF, image, Excel, Word). "
		"Handles non-uniform headers, inconsistent formats, and naming discrepancies. "
		"Returns the extracted fields for user review BEFORE creating any record. "
		"IMPORTANT: After extraction, ALWAYS present the results to the user for "
		"confirmation, then call propose_create_document to show a confirmation card."
	),
	parameters={
		"file_id": {
			"type": "string",
			"description": (
				"The file_id from the [Attached file: ...] metadata in the user's "
				"message (e.g., 'file_1'). Copy it exactly as shown."
			),
		},
		"target_doctype": {
			"type": "string",
			"description": (
				"ERPNext DocType to map the extracted data to. "
				"Supported: 'Sales Invoice', 'Purchase Invoice', 'Quotation', "
				"'Sales Order', 'Purchase Order', 'Delivery Note', 'Purchase Receipt'."
			),
		},
		"company": {
			"type": "string",
			"description": "Company name. Optional — omit to use user's default company.",
		},
		"output_language": {
			"type": "string",
			"description": (
				"Language for the extracted output values (e.g., 'English', 'Spanish', "
				"'French'). The document can be in any language — extracted field values "
				"(item descriptions, terms, remarks, party names) will be translated to "
				"this language. Default: 'English'."
			),
		},
	},
	doctypes=[],
)
def extract_document_data(file_id=None, target_doctype=None, company=None, output_language=None):
	"""Extract structured data from an uploaded document.

	Runs the full IDP pipeline:
	1. Content extraction (PDF text, image base64, Excel/CSV tabular)
	2. LLM semantic mapping to target DocType schema
	3. Post-extraction validation (only when strict validation is enabled)

	Returns extraction results for user review.
	"""
	if not file_id:
		return {"error": "file_id is required — use the file_id from [Attached file: ...] metadata"}

	if not target_doctype:
		return {"error": "target_doctype is required (e.g., 'Sales Invoice', 'Purchase Invoice')"}

	# Resolve file_id alias to actual file_url
	file_url = _resolve_file_id(file_id)
	if not file_url:
		return {
			"error": f"Unknown file_id: {file_id}. Use the exact file_id from the [Attached file: ...] metadata.",
			"stop_processing": True,
		}

	# Resolve company with an extra guard for IDP:
	# The LLM may pass a `company` argument derived from the document body
	# (e.g., the invoice recipient's name). `get_default_company` would
	# fuzzy-LIKE-match that against the Company doctype and silently pick
	# an unrelated record. For IDP we require an EXACT Company match for
	# any explicit argument; otherwise we fall back to the user's session
	# default. This prevents a PDF-sourced string from overriding the
	# user's own company identity.
	company = _resolve_idp_company(company)
	if not output_language:
		settings = frappe.get_single("Chatbot Settings")
		output_language = getattr(settings, "idp_output_language", "") or "English"

	# Step 1 & 2: Extract and map via LLM.
	# enforce_context_company=True: this is the record-creation path, so the
	# `company` field must come from the session context, not from the
	# document body (the LLM occasionally mis-identifies the invoice
	# recipient as the company).
	result = extract_and_map(
		file_url,
		target_doctype,
		company=company,
		output_language=output_language,
		enforce_context_company=True,
	)
	if not result.get("success"):
		return {"error": result.get("error", "Extraction failed")}

	extracted_data = result["extracted_data"]

	# Step 3: Validate only when strict validation is enabled
	settings = frappe.get_single("Chatbot Settings")
	strict_validation = getattr(settings, "enable_strict_idp_validation", False)

	if strict_validation:
		validation = validate_extraction(extracted_data, target_doctype, company=company)

		# Apply resolved links back into extracted data
		for field_path, resolved_value in validation.get("resolved_links", {}).items():
			if "[" in field_path:
				_apply_nested_resolution(extracted_data, field_path, resolved_value)
			else:
				extracted_data[field_path] = resolved_value

		return {
			"extracted_data": extracted_data,
			"target_doctype": target_doctype,
			"company": company,
			"validation": {
				"valid": validation["valid"],
				"errors": validation["errors"],
				"warnings": validation["warnings"],
			},
			"resolved_links": validation["resolved_links"],
			"unmapped_fields": result.get("unmapped_fields", []),
			"source_file": file_url,
			"message": (
				"Data extracted successfully. Please review the extracted fields above. "
				"If correct, confirm to create the record."
				if validation["valid"]
				else "Data extracted with validation errors. Please review and correct."
			),
		}

	# No strict validation — return extracted data directly.
	# ERPNext will handle validation via set_missing_values / set_item_defaults on save.
	return {
		"extracted_data": extracted_data,
		"target_doctype": target_doctype,
		"company": company,
		"validation": {"valid": True, "errors": [], "warnings": []},
		"resolved_links": {},
		"unmapped_fields": result.get("unmapped_fields", []),
		"source_file": file_url,
		"message": (
			"Data extracted successfully. Please review the extracted fields above. "
			"If correct, confirm to create the record. "
			"ERPNext will auto-populate missing defaults during save."
		),
	}


@register_tool(
	name="extract_document_raw",
	category="idp",
	description=(
		"Extract all structured data from an uploaded document WITHOUT mapping to any "
		"ERPNext DocType schema. Use this for document types that are NOT supported by "
		"extract_document_data — e.g., salary slips, bank statements, tax certificates, "
		"customs declarations, or any other non-standard document. "
		"Returns the raw extracted data (header fields + tables) exactly as found in "
		"the document, for the user to review. "
		"This tool does NOT create any ERPNext records."
	),
	parameters={
		"file_id": {
			"type": "string",
			"description": (
				"The file_id from the [Attached file: ...] metadata in the user's "
				"message (e.g., 'file_1'). Copy it exactly as shown."
			),
		},
		"output_language": {
			"type": "string",
			"description": (
				"Language for the extracted output values (e.g., 'English', 'Spanish'). "
				"Default: from Chatbot Settings."
			),
		},
	},
	doctypes=[],
)
def extract_document_raw(file_id=None, output_language=None):
	"""Extract all structured data from a document without ERPNext schema mapping.

	For documents that don't match any supported ERPNext DocType.
	Extracts header fields, tabular data, and a summary.
	"""
	if not file_id:
		return {"error": "file_id is required — use the file_id from [Attached file: ...] metadata"}

	# Resolve file_id alias to actual file_url
	file_url = _resolve_file_id(file_id)
	if not file_url:
		return {
			"error": f"Unknown file_id: {file_id}. Use the exact file_id from the [Attached file: ...] metadata.",
			"stop_processing": True,
		}

	if not output_language:
		settings = frappe.get_single("Chatbot Settings")
		output_language = getattr(settings, "idp_output_language", "") or "English"

	result = extract_raw(file_url, output_language=output_language)
	if not result.get("success"):
		return {"error": result.get("error", "Extraction failed")}

	return {
		"document_type": result.get("document_type", "Unknown"),
		"headers": result.get("headers", {}),
		"tables": result.get("tables", []),
		"summary": result.get("summary", ""),
		"source_file": file_url,
		"message": (
			"Data extracted successfully. The extracted fields and tables are shown above. "
			"Note: This is a raw extraction — no ERPNext record will be created from this data."
		),
	}


# NOTE: create_from_extracted_data is deprecated — record creation from IDP
# extraction now goes through propose_create_document (CRUD confirmation card)
# which handles missing masters automatically via detect_prerequisites /
# execute_prerequisites.  The function is kept for backward compatibility but
# is no longer registered as an LLM-callable tool.
def create_from_extracted_data(
	extracted_data_json=None,
	target_doctype=None,
	company=None,
	create_missing_masters=None,
	item_defaults_json=None,
):
	"""Create an ERPNext document from extracted and validated data.

	Expects the extracted_data from extract_document_data to be passed
	as a JSON string. Validates permissions and creates the document.

	When strict IDP validation is enabled, re-validates before creation.
	Otherwise, relies on ERPNext's built-in validation during doc.insert().
	"""
	if not extracted_data_json:
		return {"error": "extracted_data_json is required"}

	if not target_doctype:
		return {"error": "target_doctype is required"}

	# Check that write operations are enabled
	settings = frappe.get_single("Chatbot Settings")
	if not getattr(settings, "enable_write_operations", False):
		return {"error": "Write operations are disabled in Chatbot Settings"}

	# Parse the data
	if isinstance(extracted_data_json, str):
		try:
			extracted_data = json.loads(extracted_data_json)
		except json.JSONDecodeError:
			return {"error": "Invalid JSON in extracted_data_json"}
	else:
		extracted_data = extracted_data_json

	# Parse item defaults
	item_defaults = {}
	if item_defaults_json:
		if isinstance(item_defaults_json, str):
			try:
				item_defaults = json.loads(item_defaults_json)
			except json.JSONDecodeError:
				pass
		elif isinstance(item_defaults_json, dict):
			item_defaults = item_defaults_json

	company = get_default_company(company)

	# Re-validate before creation only when strict validation is enabled
	strict_validation = getattr(settings, "enable_strict_idp_validation", False)
	if strict_validation:
		validation = validate_extraction(extracted_data, target_doctype, company=company)
		if not validation["valid"]:
			return {
				"error": "Validation failed",
				"validation_errors": validation["errors"],
				"warnings": validation["warnings"],
			}

	# Determine whether to auto-create missing masters:
	# 1. Explicit parameter from LLM (user confirmed) takes priority
	# 2. Falls back to Chatbot Settings toggle
	should_auto_create = getattr(settings, "auto_create_idp_masters", False)
	if create_missing_masters is not None:
		should_auto_create = str(create_missing_masters).lower() in ("true", "1", "yes")

	created_masters = []

	if should_auto_create:
		created_masters = _auto_create_missing_masters(
			extracted_data, target_doctype, company, item_defaults=item_defaults
		)
	else:
		# Check if masters are missing — if so, report them and stop
		missing_masters = _find_missing_masters(extracted_data, target_doctype, company)
		if missing_masters:
			missing_items = [m for m in missing_masters if m["doctype"] == "Item"]
			missing_parties = [m for m in missing_masters if m["doctype"] in ("Customer", "Supplier")]
			missing_uoms = [m for m in missing_masters if m["doctype"] == "UOM"]
			hint_parts = []
			if missing_parties:
				names = ", ".join(f"{m['doctype']}: {m['value']}" for m in missing_parties)
				hint_parts.append(f"Missing: {names}.")
			if missing_items:
				names = ", ".join(m["value"] for m in missing_items[:5])
				hint_parts.append(f"Items not found: {names}.")
			if missing_uoms:
				names = ", ".join(m["value"] for m in missing_uoms)
				hint_parts.append(f"UOMs not found: {names}.")

			return {
				"error": "Cannot create record — missing master records in ERPNext.",
				"missing_masters": missing_masters,
				"action_required": (
					" ".join(hint_parts) + " Ask the user if they want to create these masters. If yes, "
					"ask about Item properties (Is Stock Item?, Is Fixed Asset?, Item Group?) "
					"then call this tool again with create_missing_masters='true' "
					"and item_defaults_json."
				),
			}

	# Create the document using existing create_document infrastructure
	# ERPNext handles set_missing_values, set_item_defaults, and validate on save
	try:
		result = create_document(target_doctype, extracted_data, company=company)
		if created_masters:
			result["auto_created_masters"] = created_masters
		return build_currency_response(result, company)
	except Exception as e:
		log_error(f"IDP record creation error: {e!s}", title="IDP")
		return {"error": f"Failed to create {target_doctype}: {e!s}"}


@register_tool(
	name="compare_document_with_record",
	category="idp",
	description=(
		"Compare an uploaded document with an existing ERPNext record and highlight "
		"differences. Useful for reconciliation — e.g., comparing a vendor's invoice "
		"against a Purchase Order, or a client's PO against a Sales Order. "
		"First extracts data from the document, then compares field-by-field."
	),
	parameters={
		"file_id": {
			"type": "string",
			"description": (
				"The file_id from the [Attached file: ...] metadata in the user's "
				"message (e.g., 'file_1'). Copy it exactly as shown."
			),
		},
		"doctype": {
			"type": "string",
			"description": "ERPNext DocType of the existing record to compare against.",
		},
		"docname": {
			"type": "string",
			"description": "Name/ID of the existing record to compare against.",
		},
		"company": {
			"type": "string",
			"description": "Company name. Optional — omit to use user's default company.",
		},
	},
	doctypes=[],
)
def compare_document_with_record(file_id=None, doctype=None, docname=None, company=None):
	"""Compare an uploaded document against an existing ERPNext record.

	Pipeline:
	1. Extract data from uploaded document using IDP extraction
	2. Load existing ERPNext record
	3. Field-by-field comparison
	4. Return discrepancy report
	"""
	if not file_id:
		return {"error": "file_id is required — use the file_id from [Attached file: ...] metadata"}
	if not doctype:
		return {"error": "doctype is required"}
	if not docname:
		return {"error": "docname is required"}

	# Resolve file_id alias to actual file_url
	file_url = _resolve_file_id(file_id)
	if not file_url:
		return {
			"error": f"Unknown file_id: {file_id}. Use the exact file_id from the [Attached file: ...] metadata.",
			"stop_processing": True,
		}

	company = _resolve_idp_company(company)

	# Step 1: Extract data from the uploaded document
	extraction = extract_and_map(file_url, doctype, company=company)
	if not extraction.get("success"):
		return {"error": f"Document extraction failed: {extraction.get('error', 'Unknown error')}"}

	extracted_data = extraction["extracted_data"]

	# Step 2 & 3: Compare with existing record
	comparison = compare_with_record(extracted_data, doctype, docname)
	if comparison.get("error"):
		return comparison

	return {
		"comparison": comparison,
		"source_file": file_url,
		"compared_with": f"{doctype}: {docname}",
		"message": comparison.get("summary", "Comparison complete."),
	}


def _resolve_idp_company(company: str | None) -> str:
	"""Resolve the Company for an IDP extraction call.

	Unlike `get_default_company`, this helper does NOT fuzzy-LIKE-match an
	explicit argument against the Company doctype. The LLM may pass a
	`company` value that was derived from the document body (e.g., the
	invoice recipient's name), and fuzzy-matching such a value can
	silently pick an unrelated Company record.

	Policy:
	- If an explicit `company` is given and exists as an exact Company
	  record name, use it.
	- Otherwise fall back to the user's session default via
	  `get_default_company()` (with `None`), which consults the user
	  default and then the global default.

	Returns:
		Company name string.
	"""
	if company and frappe.db.exists("Company", company):
		return company
	return get_default_company(None)


def _resolve_file_id(file_id: str) -> str | None:
	"""Resolve a file_id alias (e.g., 'file_1') to its actual file_url.

	Looks up the alias in frappe.flags.file_alias_registry, which is populated
	by get_conversation_history() when building the LLM message history.

	Args:
		file_id: The short alias (e.g., 'file_1').

	Returns:
		The real file_url string, or None if the alias is not found.
	"""
	registry = getattr(frappe.flags, "file_alias_registry", None) or {}
	return registry.get(file_id)


def _apply_nested_resolution(data: dict, field_path: str, resolved_value: str) -> None:
	"""Apply a resolved link value to a nested field path.

	Handles paths like "items[0].item_code" by navigating into
	the data structure.

	Args:
		data: The extracted data dict.
		field_path: Dot-path with array indices (e.g., "items[0].item_code").
		resolved_value: The resolved value to set.
	"""
	import re

	parts = re.split(r"\[(\d+)\]\.", field_path)
	if len(parts) != 3:
		return

	array_field = parts[0]
	index = int(parts[1])
	child_field = parts[2]

	items = data.get(array_field, [])
	if isinstance(items, list) and index < len(items):
		items[index][child_field] = resolved_value


# --- Master auto-creation helpers ---

# DocType field → master DocType mapping for common transaction link fields
_PARTY_FIELD_MAP = {
	"customer": "Customer",
	"supplier": "Supplier",
	"party_name": None,  # resolved by party_type
}

_ITEM_FIELD = "item_code"


def _find_missing_masters(data: dict, target_doctype: str, company: str) -> list[dict]:
	"""Identify master records referenced in extracted data that don't exist.

	Returns a list of dicts: [{"doctype": "Customer", "value": "Acme Corp"}, ...]
	"""
	missing = []

	# Check party (customer/supplier) fields
	for field, master_dt in _PARTY_FIELD_MAP.items():
		value = data.get(field)
		if not value:
			continue
		dt = master_dt or _infer_party_doctype(target_doctype)
		if dt and not frappe.db.exists(dt, value):
			# Also try by display name
			name_field = _get_display_name_field(dt)
			if not name_field or not frappe.db.exists(dt, {name_field: value}):
				missing.append({"doctype": dt, "value": value})

	# Check items for missing Item records
	items_table = _get_items_from_data(data)
	seen_items = set()
	for item in items_table:
		item_code = item.get(_ITEM_FIELD)
		if not item_code or item_code in seen_items:
			continue
		seen_items.add(item_code)
		if not frappe.db.exists("Item", item_code):
			# Also try by item_name
			if not frappe.db.exists("Item", {"item_name": item_code}):
				missing.append({"doctype": "Item", "value": item_code})

	# Check UOM
	for item in items_table:
		uom = item.get("uom")
		if uom and not frappe.db.exists("UOM", uom):
			missing.append({"doctype": "UOM", "value": uom})

	return missing


def _auto_create_missing_masters(
	data: dict, target_doctype: str, company: str, item_defaults: dict | None = None
) -> list[str]:
	"""Auto-create missing master records (Customer, Supplier, Item, UOM).

	Creates minimal records with the extracted name. Returns a list of
	human-readable descriptions of what was created.

	Args:
		data: Extracted document data (modified in-place with resolved names).
		target_doctype: Target ERPNext DocType.
		company: Company name.
		item_defaults: Optional dict with Item creation defaults:
			- is_stock_item (int 0/1, default 0)
			- is_fixed_asset (int 0/1, default 0)
			- item_group (str, default from Stock Settings)
	"""
	created = []
	item_defaults = item_defaults or {}

	# Party (Customer / Supplier)
	for field, master_dt in _PARTY_FIELD_MAP.items():
		value = data.get(field)
		if not value:
			continue
		dt = master_dt or _infer_party_doctype(target_doctype)
		if not dt:
			continue

		# Check if exists by name or display name
		if frappe.db.exists(dt, value):
			continue
		name_field = _get_display_name_field(dt)
		if name_field:
			existing = frappe.db.get_value(dt, {name_field: value}, "name")
			if existing:
				# Update the data to use the actual record name
				data[field] = existing
				continue

		# Create the master
		try:
			new_doc = frappe.new_doc(dt)
			if name_field:
				new_doc.set(name_field, value)
			if dt == "Customer":
				new_doc.customer_type = "Company"
				new_doc.customer_group = (
					frappe.db.get_single_value("Selling Settings", "customer_group") or "All Customer Groups"
				)
				new_doc.territory = (
					frappe.db.get_single_value("Selling Settings", "territory") or "All Territories"
				)
			elif dt == "Supplier":
				new_doc.supplier_group = (
					frappe.db.get_single_value("Buying Settings", "supplier_group") or "All Supplier Groups"
				)
			new_doc.insert(ignore_permissions=True)
			data[field] = new_doc.name
			created.append(f"{dt}: {new_doc.name}")
		except Exception as e:
			log_error(f"IDP auto-create {dt} '{value}' failed: {e!s}", title="IDP")

	# Resolve item defaults
	is_stock_item = int(item_defaults.get("is_stock_item", 0))
	is_fixed_asset = int(item_defaults.get("is_fixed_asset", 0))
	item_group = item_defaults.get("item_group") or (
		frappe.db.get_single_value("Stock Settings", "item_group") or "All Item Groups"
	)

	# Items
	items_table = _get_items_from_data(data)
	seen_items = set()
	for item in items_table:
		item_code = item.get(_ITEM_FIELD)
		if not item_code or item_code in seen_items:
			continue
		seen_items.add(item_code)

		if frappe.db.exists("Item", item_code):
			continue
		# Check by item_name
		existing = frappe.db.get_value("Item", {"item_name": item_code}, "name")
		if existing:
			item[_ITEM_FIELD] = existing
			continue

		# Create Item with user-specified defaults
		try:
			new_item = frappe.new_doc("Item")
			new_item.item_code = item_code
			new_item.item_name = item.get("item_name") or item_code
			new_item.description = item.get("description") or item_code
			new_item.item_group = item_group
			new_item.stock_uom = item.get("uom") or "Nos"
			new_item.is_stock_item = is_stock_item
			new_item.is_fixed_asset = is_fixed_asset
			new_item.insert(ignore_permissions=True)
			item[_ITEM_FIELD] = new_item.name
			created.append(f"Item: {new_item.name}")
		except Exception as e:
			log_error(f"IDP auto-create Item '{item_code}' failed: {e!s}", title="IDP")

	# UOM
	for item in items_table:
		uom = item.get("uom")
		if uom and not frappe.db.exists("UOM", uom):
			try:
				new_uom = frappe.new_doc("UOM")
				new_uom.uom_name = uom
				new_uom.insert(ignore_permissions=True)
				created.append(f"UOM: {uom}")
			except Exception as e:
				log_error(f"IDP auto-create UOM '{uom}' failed: {e!s}", title="IDP")

	if created:
		frappe.db.commit()

	return created


def _infer_party_doctype(target_doctype: str) -> str | None:
	"""Infer whether the party is a Customer or Supplier from the target DocType."""
	customer_doctypes = {"Sales Invoice", "Sales Order", "Quotation", "Delivery Note"}
	supplier_doctypes = {"Purchase Invoice", "Purchase Order", "Purchase Receipt"}
	if target_doctype in customer_doctypes:
		return "Customer"
	if target_doctype in supplier_doctypes:
		return "Supplier"
	return None


def _get_display_name_field(doctype: str) -> str | None:
	"""Get the display name field for a DocType."""
	name_map = {
		"Customer": "customer_name",
		"Supplier": "supplier_name",
		"Item": "item_name",
	}
	return name_map.get(doctype)


def _get_items_from_data(data: dict) -> list[dict]:
	"""Extract the items child table from extracted data."""
	# Prefer the standard "items" key
	items = data.get("items")
	if isinstance(items, list) and items and isinstance(items[0], dict):
		return items

	# Fallback: find the first list-of-dicts (for non-standard fieldnames)
	for _key, value in data.items():
		if isinstance(value, list) and value and isinstance(value[0], dict):
			return value
	return []
