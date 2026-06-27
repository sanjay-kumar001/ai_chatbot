
![AI Chatbot](screenshots/ai_chatbot_banner.png)

---

# AI Chatbot Application for Frappe/ERPNext

> A modern, feature-rich AI chatbot application built with Frappe framework and Frappe UI, featuring OpenAI and Claude integration with powerful ERPNext business intelligence tools.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Frappe](https://img.shields.io/badge/Frappe-v15+-orange.svg)](https://frappeframework.com/)
[![ERPNext](https://img.shields.io/badge/ERPNext-v15+-green.svg)](https://erpnext.com/)

## Features

### Chat Interface
- Modern single-page chat UI built with Vue 3, Vite, and Tailwind CSS
- Sidebar with conversation history, provider switcher, and dark mode toggle
- Fresh new chat with enabled input on every load
- Responsive layout (desktop and mobile)
- Markdown rendering (marked.js) with syntax highlighting (highlight.js)
- Apache ECharts for inline chart rendering (bar, line, pie, stacked, horizontal bar)
- PDF export of individual messages or full conversations
- File upload with LLM Vision API support (images, PDFs)
- Voice input/output (speech-to-text, text-to-speech)

### AI Providers
- OpenAI: GPT-4o, GPT-4o-mini, GPT-4-Turbo, GPT-3.5-Turbo
- Anthropic Claude: Opus 4.5, Sonnet 4.5, Haiku 4.5
- Google Gemini
- Switch providers on the fly from the sidebar

### Real-Time Streaming
- Token-by-token streaming via Frappe Realtime (Socket.IO / WebSocket)
- Typing indicator while the AI is generating a response

### Multi-Company and Multi-Currency
- Every tool accepts a `company` parameter (defaults to the user's default company)
- Monetary aggregations use `base_*` fields for company-currency consistency
- Cross-company consolidated reports for group-level analysis
- Per-conversation target currency selection
- Include-subsidiaries toggle for automatic child company inclusion

### Consolidation
- Parent company detection, cross-subsidiary aggregation with currency conversion

### Permissions
- DocType-based tool filtering — users only see tools they have access to

### Financial Analyst
- CFO-grade analysis behaviour when finance tools are enabled
- CFO dashboard returns styled metric cards with YoY change percentages (Revenue, Net Profit, Cash, AR, AP)
- Finance tools support **Accounting Dimensions** filtering
- Hierarchical grouping by territory, customer_group, customer, item_group, accounting_dimensions, department with period columns (monthly/quarterly/yearly)
- Trial balance, GL summary, account statement — authoritative accounting data from GL entries
- Frontend renders indented data tables with group headers, subtotals, and bold formatting

![AI Financial Analysis](screenshots/ai_financial_analysis.gif)

### Voice Communication
- Speech-to-text input (Web Speech API) and text-to-speech output (SpeechSynthesis)
- User defined voice output language in **Chabot Settings**
- **Auto-speak:** When user submits via voice, AI response auto-speaks after streaming completes
- **Manual "Listen" button** on all assistant messages (Volume2/VolumeX icons)

### Intelligent Document Processing (IDP)
Extract structured data from uploaded documents (invoices, POs, receipts, quotations) using LLM Vision/text extraction and ERPNext schema discovery. Map non-uniform, multi-language source data to ERPNext DocType schemas with semantic reasoning. Create records and compare documents against existing ERPNext records.
- LLM performs semantic reasoning to identify which source values map to which ERPNext fields
- Schema mapping resolves naming discrepancies between source document fields and ERPNext DocType structure
- Supported DocTypes: Sales Invoice, Purchase Invoice, Quotation, Sales Order, Purchase Order, Delivery Note, Purchase Receipt
- **Output Language** (default: English) — document can be in any language; extracted values are translated. System prompt instructs the LLM to translate text values (item descriptions, terms, remarks, party names) to the target language while preserving numbers, dates, currency codes, and proper nouns

### Auto Email & Scheduled Reports
- AI-generated scheduled reports delivered via email on configurable schedules.
- **PDF** attachment with tables and charts.

### PDF Export from Chat
- User can export any AI chatbot response (including tables and charts) as a downloadable PDF directly from the chat interface. Both single-message and full-conversation exports are supported.

### ERPNext Business Intelligence Tools (80)

**CRM (6)** -- Lead statistics, opportunity pipeline, lead conversion rates, sales funnel, lead source analysis, opportunity by stage

**Sales / Selling (5)** -- Sales analytics, top customers, sales trend, revenue by territory, revenue by item group

**Buying / Purchase (4)** -- Purchase analytics, supplier performance, purchase trend, purchase by item group

**Finance (38)** -- Financial summary, cash flow analysis, multi-dimensional analytics, financial overview, monthly comparison, CFO dashboard (comprehensive BI cards with YoY), GL summary, trial balance, account statement, budget vs actual, budget variance, cash flow statement, cash flow trend, bank balance, receivable aging, top debtors, payable aging, top creditors, profitability by customer/item/territory, liquidity/profitability/efficiency ratios, working capital summary, cash conversion cycle, consolidated reports, session management (subsidiaries toggle, target currency)

**Inventory / Stock (4)** -- Stock summary, low stock alerts, stock movement, stock ageing

**HRMS (6)** -- Employee count, attendance summary, leave balance, payroll summary, department-wise salary, employee turnover

**IDP (3)** -- Document extraction via LLM Vision API (any language, any format), ERPNext record creation from extracted data, document comparison for reconciliation

**Predictive Analytics (5)** -- Revenue forecast, territory forecast, demand forecast, cash flow forecast, anomaly detection (statistical methods: z-score, IQR)

**Operations / CRUD (9)** -- Create leads, opportunities, todos; search customers, items, documents; update lead status, opportunity status, todos

See [docs/TOOLS_REFERENCE.md](docs/TOOLS_REFERENCE.md) for the complete tool reference with parameters.


### Additional Capabilities
- @mention system for inline context (company, period, cost center, department, warehouse, customer, item, accounting dimensions)
- Token usage tracking and cost estimation per request
- Scheduled reports with email and PDF delivery
- Multi-agent orchestration for complex, multi-step queries
- Context optimization: last 20 messages retained, chart data stripped from history
- Configurable AI persona, system prompt, and response language (10 languages)
- IDP output language setting (extract data in any configured language)
- Per-conversation language override
- Tool plugin system for extending with custom tools from external Frappe apps
- Cascade deletion of conversations (messages and token usage cleaned up automatically)

---
## Demo

[![AI Chatbot Demo](https://img.youtube.com/vi/8D0QucDbnPo/0.jpg)](https://www.youtube.com/watch?v=8D0QucDbnPo)


---

## Prerequisites

- Frappe Framework (v15+)
- ERPNext (v15+) -- required for business intelligence tools
- HRMS app -- optional, required only for HR tools
- Python 3.10+
- Node.js 18+
- An API key from at least one supported provider (OpenAI, Anthropic, or Google)

---

## Installation

```bash
# Get the app
bench get-app https://github.com/sanjay-kumar001/ai_chatbot

# Install on your site
bench --site <your-site> install-app ai_chatbot

# Run migrations
bench --site <your-site> migrate

# Build frontend assets
bench build --app ai_chatbot

# Restart
bench restart
```

All Python dependencies (including IDP document processing) are installed automatically with the app. `pypdf` and `openpyxl` are provided by the Frappe framework.

---

## Configuration

1. Navigate to **Chatbot Settings** at `/app/chatbot-settings`
2. Select your AI Provider (OpenAI, Claude, or Gemini)
3. Enter the corresponding API key (stored encrypted via Frappe's Password field)
4. Enable or disable tool categories (CRM, Sales, Purchase, Finance, Inventory, HRMS, Operations, IDP, Predictive)
5. Optionally configure:
   - AI persona and system prompt
   - Default response language
   - IDP output language (Extract Data In)
   - Scheduled report settings

---

## Usage

After setup, open the chatbot at:

```
https://<your-site>/ai-chatbot
```

Type natural-language questions about your business data. Examples:

| Prompt | Output Type |
|--------|-------------|
| Show top 10 customers by revenue this year | Table |
| Sales trend month by month for this fiscal year | Chart |
| What are our outstanding receivables? | Table |
| What is the current cash balance? | Number |
| Show expense breakdown by cost center | Chart |
| Create a new Lead for John Doe from Acme Corp | Record creation |
| Compare sales this month vs last month | Table |
| Show CFO dashboard | BI dashboard with cards |
| Forecast revenue for next 3 months | Chart with confidence intervals |
| Extract data from this invoice | Document processing |

Charts are rendered with Apache ECharts. The backend returns `echart_option` objects; the frontend renders them inline in the chat.

See [docs/SAMPLE_USER_PROMPT.md](docs/SAMPLE_USER_PROMPT.md) for 80+ sample prompts organized by category.

---

## @Mention System

Type `@` in the chat input to insert contextual filters. Mentions are resolved to actual ERPNext values before being sent to the AI.

| Mention | Purpose | Example |
|---------|---------|---------|
| `@company` | Filter by company | `@company:Acme Inc` |
| `@period` | Set date range | `@period:this quarter` |
| `@cost_center` | Filter by cost center | `@cost_center:Main` |
| `@department` | Filter by department | `@department:Sales` |
| `@warehouse` | Filter by warehouse | `@warehouse:Stores - A` |
| `@customer` | Filter by customer | `@customer:John Doe` |
| `@item` | Filter by item | `@item:Widget A` |
| `@accounting_dimension` | Filter by custom dimension | `@accounting_dimension:Project X` |

See [docs/AT_MENTION_GUIDE.md](docs/AT_MENTION_GUIDE.md) for the complete guide.

---

## Architecture Overview

```
ai_chatbot/                          # Python package (Frappe backend)
|
|-- api/
|   |-- chat.py                      # @frappe.whitelist() endpoints
|
|-- chatbot/doctype/
|   |-- chatbot_settings/            # Single DocType: provider config, toggles
|   |-- chatbot_conversation/        # Conversation records with session context
|   |-- chatbot_message/             # Messages with tool calls, attachments
|   |-- chatbot_token_usage/         # Per-request token and cost tracking
|   |-- chatbot_scheduled_report/    # Scheduled report configuration
|
|-- core/
|   |-- config.py                    # App configuration helpers
|   |-- constants.py                 # App-wide constants
|   |-- prompts.py                   # System prompt builder
|   |-- session_context.py           # Per-conversation session state
|   |-- token_tracker.py             # Token usage and cost tracking
|
|-- tools/
|   |-- registry.py                  # Decorator-based tool registration system
|   |-- base.py                      # Backward-compatible wrapper
|   |-- crm.py                       # CRM tools (6)
|   |-- selling.py                   # Selling tools (5)
|   |-- buying.py                    # Buying tools (4)
|   |-- stock.py                     # Inventory tools (4)
|   |-- hrms.py                      # HRMS tools (6, loaded if HRMS installed)
|   |-- idp.py                       # Intelligent Document Processing (3)
|   |-- session.py                   # Session context tools (2)
|   |-- finance/                     # Finance sub-modules (38)
|   |   |-- account.py, analytics.py, budget.py, cash_flow.py, cfo.py,
|   |   |-- consolidation.py, gl_analytics.py, payables.py, profitability.py,
|   |   |-- ratios.py, receivables.py, working_capital.py
|   |-- predictive/                  # Predictive analytics sub-modules (5)
|   |   |-- sales_forecast.py, demand_forecast.py,
|   |   |-- cash_flow_forecast.py, anomaly_detection.py
|   |-- operations/                  # CRUD operations (9)
|       |-- create.py, search.py, update.py
|
|-- utils/
|   |-- ai_providers.py              # OpenAI, Claude, Gemini API integration
|
|-- automation/
|   |-- scheduled_reports.py         # Scheduler-driven report generation
|
|-- idp/
|   |-- mapper.py                    # Document extraction and field mapping
|   |-- content_extractor.py         # File content extraction (PDF, image, Excel, Word)
|   |-- schema_builder.py            # DocType schema generation for LLM
|
|-- data/
|   |-- charts.py                    # ECharts option builders
|   |-- currency.py                  # Currency response formatting
|   |-- grouping.py                  # Multi-dimensional grouping utilities
|
|-- public/frontend/                 # Built frontend assets (generated)


frontend/                            # Vue 3 SPA (source)
|
|-- src/
|   |-- pages/ChatView.vue           # Main chat interface
|   |-- components/
|   |   |-- Sidebar.vue              # Conversation list, provider switcher
|   |   |-- ChatHeader.vue           # Conversation header
|   |   |-- ChatMessage.vue          # Message rendering (markdown, charts)
|   |   |-- ChatInput.vue            # Input with @mentions, file upload
|   |   |-- TypingIndicator.vue      # Streaming indicator
|   |-- utils/api.js                 # ChatAPI singleton with CSRF handling
|
|-- vite.config.js                   # Build config with manual chunks
|-- tailwind.config.js               # Tailwind CSS configuration
```

---

## Tool Plugin System

External Frappe apps can register custom tools with the chatbot without modifying this app.

### 1. Create a tool module in your app

```python
# my_app/chatbot_tools/manufacturing.py

from ai_chatbot.tools.registry import register_tool

@register_tool(
    name="get_production_summary",
    category="manufacturing",
    description="Get production order summary for a date range",
    parameters={
        "from_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
        "to_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
        "company": {"type": "string", "description": "Company name"},
    },
    doctypes=["Work Order"],
)
def get_production_summary(from_date=None, to_date=None, company=None):
    # Your implementation here
    ...
```

### 2. Register the module in your app's hooks.py

```python
# my_app/hooks.py

ai_chatbot_tool_modules = ["my_app.chatbot_tools.manufacturing"]
```

### 3. Optionally register a new category

If you want your tools grouped under a new category with a toggle in Chatbot Settings:

```python
from ai_chatbot.tools.registry import register_tool_category

register_tool_category("manufacturing", settings_field=None)
# Pass settings_field="enable_manufacturing_tools" if you add
# a corresponding checkbox to Chatbot Settings via customize form.
# If settings_field is None, the category is always enabled.
```

The chatbot will automatically discover and load your tools at runtime. Permission checks are enforced based on the `doctypes` list declared in each tool.

---

## Development

### Frontend

```bash
cd apps/ai_chatbot/frontend

# Install dependencies
npm install

# Start dev server (http://localhost:8080, proxies API to Frappe)
npm run dev

# Production build (outputs to ai_chatbot/public/frontend)
npm run build
```

### Backend

```bash
# Start Frappe development server
bench start

# Run backend tests
bench --site <your-site> run-tests --app ai_chatbot

# Linting
ruff check .
ruff format .

# Or via pre-commit
pre-commit run --all-files
```

### Code Conventions

- **Python**: Tabs for indentation, 110-character line length, double quotes, type hints
- **JavaScript/Vue**: Vue 3 Composition API (`<script setup>`), Tailwind CSS
- **API pattern**: `@frappe.whitelist()` decorators, Frappe ORM (`frappe.qb` / `frappe.get_all`) for database access -- no raw SQL with string interpolation
- **Error handling**: `try/except` with `frappe.log_error()`

### Dependencies

**Python** (runtime): frappe, openai, anthropic, twilio==8.5.0, python-docx>=1.1, requests (pypdf and openpyxl provided by Frappe)

**Frontend**: vue 3, vue-router, marked, highlight.js, lucide-vue-next, tailwindcss, echarts, socket.io-client

---

## Documentation

| Document | Description |
|----------|-------------|
| [PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) | High-level architecture and design decisions |
| [PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) | Detailed file and directory structure |
| [TOOLS_REFERENCE.md](docs/TOOLS_REFERENCE.md) | Complete tool reference with parameters (80 tools) |
| [SAMPLE_USER_PROMPT.md](docs/SAMPLE_USER_PROMPT.md) | 80+ example prompts organized by category |
| [AT_MENTION_GUIDE.md](docs/AT_MENTION_GUIDE.md) | @mention system usage guide |

---


## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create feature branch
3. Commit changes
4. Open pull request

## 📄 License

MIT License - See LICENSE file

## 📞 Support

- **Documentation**: See docs folder
- **Issues**: GitHub Issues
- **Email**: sanjay.kumar001@gmail.com

---

**Built with Claude.AI by Sanjay Kumar for the Frappe/ERPNext Community**

Version: 1.0.0
