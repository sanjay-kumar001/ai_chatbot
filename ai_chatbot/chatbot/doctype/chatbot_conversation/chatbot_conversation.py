# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class ChatbotConversation(Document):
	"""Chatbot Conversation DocType Controller"""

	def before_insert(self):
		"""Called before document is inserted"""
		# Set timestamps
		self.created_at = now_datetime()
		self.updated_at = now_datetime()

		# Set default user if not set
		if not self.user:
			self.user = frappe.session.user

	def before_save(self):
		"""Called before document is saved"""
		# Update timestamp
		self.updated_at = now_datetime()

	def validate(self):
		"""Validate document before save"""
		from ai_chatbot.utils.ai_providers import SUPPORTED_PROVIDERS

		if self.ai_provider not in SUPPORTED_PROVIDERS:
			frappe.throw(f"Invalid AI provider. Must be one of: {', '.join(SUPPORTED_PROVIDERS)}")

	def on_trash(self):
		"""Called when document is deleted — cascade to linked records"""
		frappe.db.delete("Chatbot Token Usage", {"conversation": self.name})
		frappe.db.delete("Chatbot Message", {"conversation": self.name})
		frappe.db.delete("Chatbot Audit Log", {"conversation": self.name})

	def update_message_count(self):
		"""Update the message count for this conversation"""
		count = frappe.db.count("Chatbot Message", {"conversation": self.name})
		self.message_count = count
		self.save(ignore_permissions=True, ignore_version=True)

	def update_token_usage(self, tokens):
		"""Add tokens to the total usage"""
		self.total_tokens = (self.total_tokens or 0) + tokens
		self.save(ignore_permissions=True, ignore_version=True)
