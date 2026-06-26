# AI Chatbot -- Sample User Prompts

A comprehensive guide of sample prompts you can try with the AI Chatbot. Each prompt includes the expected output format and a brief description of what to expect. Click any prompt in the Help Modal (the help icon next to the send button) to insert it directly into the chat input.

Output types:
- **table** -- sortable data table, often with hierarchical grouping
- **chart** -- interactive Apache ECharts visualization (bar, line, pie, etc.)
- **number** -- single metric with optional supporting context
- **mixed** -- combination of cards, tables, and charts
- **record** -- record creation or update confirmation
- **search** -- search results listing

---

## Sales / Selling

| Prompt | Output | Expected Result |
|--------|--------|-----------------|
| What is the total sales this month? | number | Revenue figure with currency symbol, date range, and company name |
| Show top 10 customers by revenue this year | table | Ranked list of customers with revenue amounts in company currency |
| Sales trend month by month for this fiscal year | chart | Line chart showing monthly revenue progression across the fiscal year |
| Compare sales this month vs last month | table | Side-by-side comparison with absolute difference and percentage change |
| Break down sales by territory | chart | Pie chart showing revenue distribution across territories |
| Show sales by product category | chart | Bar chart with revenue broken down by item group |
| Which products are most profitable? | chart | Items with revenue, cost, margin %, and ECharts chart |
| Show profitability breakdown by territory | chart | Pie chart with territory-wise margin data |
| Show sales for @company Acme Corp in @period Last Quarter | table | Filtered sales data scoped to specified company and period |
| Who are our top 5 customers by order count? | table | Ranked list of customers sorted by number of sales orders placed |
| Show monthly sales trend for last 6 months | chart | Line chart with six data points showing recent revenue trajectory |
| Show sales register for this month | table | All sales transactions with tax details from ERPNext Sales Register |
| Show item-wise sales register for [Customer] | table | Item-level sales details from ERPNext Item-wise Sales Register |

---

## Finance / Accounting

| Prompt | Output | Expected Result |
|--------|--------|-----------------|
| Give me a financial overview | chart | Revenue, total expenses, net profit, cash position, AR/AP with bar chart and BI cards |
| Show me the CFO dashboard | mixed | Financial highlights, KPIs (net margin, gross profit ratio, current/quick ratio), cash flow, aging summaries |
| Show profit and loss for this fiscal year | table | Income, expense, and net profit/loss from ERPNext P&L report |
| Show monthly P&L breakdown | table | Monthly columns showing income and expenses from ERPNext P&L report |
| Show the balance sheet | table | Assets, liabilities, and equity from ERPNext Balance Sheet report |
| Show the trial balance | table | All accounts with opening, debit, credit, and closing balances |
| Show the general ledger for our cash account | table | Detailed GL entries with posting date, party, debit/credit, running balance |
| Show accounts receivable aging | table | Invoice-wise outstanding from ERPNext AR report with aging buckets (0-30, 31-60, 61-90, 90+) |
| Show accounts receivable summary | table | Total outstanding per customer from ERPNext AR Summary report |
| Show accounts payable aging | table | Invoice-wise outstanding to suppliers from ERPNext AP report |
| Show accounts payable summary | table | Total outstanding per supplier from ERPNext AP Summary report |
| What are the financial ratios? | table | Liquidity, solvency, and turnover ratios from ERPNext Financial Ratios report |
| Show budget vs actual for this fiscal year | table | Budget, actual, and variance from ERPNext Budget Variance report |
| Show cash flow statement | table | Operating, investing, and financing activities from ERPNext Cash Flow report |
| Show cash flow trend for the last 12 months | chart | Multi-series line chart (inflow, outflow, net) from Payment Entry data |
| What are the current bank balances? | number | Bank/cash accounts with individual and total balances from GL |
| Show month-over-month comparison for the last 3 months | chart | Revenue, expenses, net profit with MoM variance and line chart |
| Show account balances by root type | table | Group account balances from ERPNext Account Balance report |
| Show consolidated P&L for the group | table | Consolidated P&L across all subsidiary companies |
| Show consolidated trial balance | table | Consolidated trial balance across selected companies |
| Show GL summary by account type | chart | GL summary grouped by account type (Bank, Cash, Receivable, etc.) |
| Which products are most profitable? | chart | Items with revenue, cost, margin % from profitability analysis |
| Show profitability breakdown by territory | chart | Territory-wise margin data with pie chart |

---

## HR / HRMS

| Prompt | Output | Expected Result |
|--------|--------|-----------------|
| How many active employees do we have? | chart | Total count with department-wise breakdown and pie chart |
| Show employee distribution by department | chart | Pie chart with department segments and headcount |
| Show attendance summary for this month | chart | Present, Absent, On Leave, Half Day, WFH counts with bar chart |
| What is the leave balance for an employee? | table | Leave type breakdown: allocated, consumed, balance per type |
| Show payroll summary for this month | chart | Gross pay, deductions, net pay totals with bar chart |
| Show department-wise salary distribution | chart | Departments with gross/net pay and pie chart |
| Show employee turnover for this year | chart | Hires, exits, turnover rate % with multi-series bar chart |
| Show headcount by @department | table | Filtered count for the specified department |
| Show new hires vs exits for last 6 months | chart | Dual-bar chart comparing monthly joinings and separations |
| What is the total payroll cost this month? | number | Sum of gross or net salary for the current month payroll |

---

## CRM

| Prompt | Output | Expected Result |
|--------|--------|-----------------|
| Show me lead statistics | chart | Total leads, status breakdown with pie chart |
| Show opportunity pipeline | chart | Opportunities with amounts by sales stage, bar chart |
| What is our lead conversion rate? | number | Total leads, converted count, conversion rate percentage |
| Which lead sources are performing best? | chart | Sources ranked by lead count with pie chart |
| Show the sales funnel | chart | Leads > Opportunities > Quotations > Orders with conversion rates |
| Show opportunities by sales stage | chart | Stages with count and total value per stage, bar chart |
| Show all open opportunities | table | Filtered opportunities with status Open, amounts, expected close date |
| List recent activities for @customer | table | Activity log for the specified customer |
| Show top opportunities by value | table | Ranked list of the highest-value open opportunities with details |
| Analyze leads by source | chart | Pie chart showing lead distribution by source (website, referral, etc.) |

---

## Stock / Inventory

| Prompt | Output | Expected Result |
|--------|--------|-----------------|
| What is the total stock value? | number | Aggregate valuation of all warehouse stock in company currency |
| Show low stock items below reorder level | table | Items where current stock is below configured reorder level |
| Top 10 items by stock quantity | table | Items ranked by quantity on hand across all warehouses |
| Show stock movement for the last 30 days | chart | In/out movements with multi-series bar chart |
| Show stock ageing report | table | Items with age in days from ERPNext Stock Ageing report |
| Show stock balance for @item in @warehouse | table | Filtered stock balance from ERPNext Stock Balance report |
| Show warehouse-wise stock summary | table | Stock quantities and values broken down by warehouse |
| Which items are running low? | table | Items approaching or below reorder level with current quantities |
| Show stock ledger for [Item Code] | table | Detailed inward/outward transactions from ERPNext Stock Ledger report |
| Show current stock balance by item group | table | Inventory snapshot with quantities and values from ERPNext Stock Balance report |

---

## Purchasing / Buying

| Prompt | Output | Expected Result |
|--------|--------|-----------------|
| Show pending purchase orders | table | Open purchase orders with supplier, amount, and expected delivery date |
| Top suppliers by purchase amount this year | table | Ranked list of suppliers by total purchase value |
| What is the total purchase amount this quarter? | number | Aggregate purchase value for the current fiscal quarter |
| Show the purchase trend for the last 12 months | chart | Line chart showing monthly purchase amounts over time |
| Break down purchases by item group | chart | Bar chart of purchase spend distributed across item groups |
| Show purchase register for this quarter | table | All purchase transactions with tax details from ERPNext Purchase Register |
| Show item-wise purchase register for [Supplier] | table | Item-level purchase details from ERPNext Item-wise Purchase Register |
| Compare purchase amounts: this quarter vs last quarter | table | Side-by-side quarterly comparison with variance |

---

## Document Processing (IDP)

Upload a document (invoice, PO, quotation) using the attachment button, then use these prompts.

| Prompt | Output | Expected Result |
|--------|--------|-----------------|
| Extract data from this invoice | table | Structured extraction of header fields and line items for review |
| Create a purchase invoice from the extracted data | record | ERPNext Purchase Invoice created after user confirmation |
| Extract and create a sales invoice from this document | table + record | Extraction displayed for review, then record created on confirmation |
| Compare this uploaded PO with Sales Order SO-00123 | table | Field-by-field comparison highlighting discrepancies |
| What does this document contain? | table | Extracted fields, party name, amounts, line items, and dates |
| Process this receipt and create a purchase receipt | table + record | Extraction from receipt image, then Purchase Receipt creation |

Notes on IDP:
- Supported file types: PDF, images (PNG, JPG, TIFF), Excel, Word, CSV
- Documents can be in any language; extracted values are translated to English by default
- The chatbot always presents extracted data for your review before creating any record
- If items or parties do not exist in ERPNext, the chatbot will ask whether to create them

---

## Predictive Analytics

### Trend Analysis

| Prompt | Output | Expected Result |
|--------|--------|-----------------|
| Analyse the revenue trend for the last 12 months | chart | Trend direction, slope per month, R-squared, growth rates, moving averages, chart with regression line overlay |
| Show expense trend for the last 24 months | chart | Purchase-based expense trend with MA-3, MA-6 bands and seasonality detection |
| Analyse demand trend for [Item Name] | chart | Item-level quantity trend with linear regression and period-over-period growth rates |
| What is the revenue trend this year? | chart | Current-year revenue trend with first-half vs second-half comparison |
| Is there any seasonality in our sales? | chart | Trend analysis highlighting seasonality_detected flag and seasonal patterns |

### Forecasting

| Prompt | Output | Expected Result |
|--------|--------|-----------------|
| Forecast sales revenue for next 3 months | chart | Line chart with predicted revenue, confidence intervals, and trend direction |
| Predict demand for [Item Name] for next quarter | chart | Item-level demand forecast with upper and lower bounds |
| Cash flow projection for next 3 months | chart | Projected cash inflows and outflows with net position |
| Revenue forecast by territory for next quarter | chart | Territory-wise revenue predictions with confidence bands |

### Anomaly Detection

| Prompt | Output | Expected Result |
|--------|--------|-----------------|
| Detect any anomalies in our recent transactions | table | Flagged transactions with unusually large amounts or atypical patterns |
| Show anomalies in purchase transactions | table | Unusual purchase amounts, new suppliers with large first orders |

Notes on Predictive Analytics:
- **Trend analysis** uses linear regression, moving averages, and seasonality detection on historical data. It is retrospective (looks backward), not predictive.
- **Forecasting** uses Holt-Winters (triple exponential smoothing) when 12+ months of seasonal data are available, Holt's method for trend-only data, and EMA as fallback.
- At least 6 months of historical data is recommended for reliable forecasts
- Confidence intervals widen further into the future, reflecting increasing uncertainty
- Anomaly detection flags statistical outliers, not necessarily errors

---

## Prescriptive Analytics

Prescriptive tools go beyond describing what happened — they compute specific actions to take. Each tool returns an **action** field, a chart, and quantified impact estimates. These tools require sufficient historical data (typically 6+ months).

### Inventory Optimisation (`optimize_inventory`)

| Prompt | Output | Expected Result |
|--------|--------|-----------------|
| What is the optimal reorder quantity for [Item Name]? | mixed | EOQ, safety stock, reorder point, carrying/order cost estimates, stockout risk (high/medium/low), bar chart |
| Optimise inventory for item [Item Code] at 99% service level | mixed | EOQ recalculated with z=2.33 for 99% service level, safety stock, reorder point, and bar chart |
| Show EOQ and reorder point for [Item Name] with lead time 14 days | mixed | EOQ and safety stock adjusted to 14-day lead time, cost projections |
| What is the safety stock level for [Item Name]? | mixed | Safety stock with z-score for 95% service level, stockout risk label, current stock vs thresholds chart |
| What is the stockout risk for [Item Name]? | mixed | Current stock compared to reorder point and safety stock; risk = high / medium / low |

### Pricing Optimisation (`optimize_pricing`)

| Prompt | Output | Expected Result |
|--------|--------|-----------------|
| What is the optimal price for [Item Name]? | mixed | Recommended price, price elasticity (e), R², demand regime (elastic/inelastic/anomalous), expected margin impact |
| Estimate price elasticity for [Item Name] | mixed | Elasticity value, confidence (R²), current vs recommended price, expected volume change % |
| Should we raise the price of [Item Name]? | mixed | Pricing recommendation with quantified margin change; warns if demand is inelastic or data is noisy |
| What price maximises profit for [Item Name]? | mixed | Profit-maximising price from constant-elasticity model, bar chart: Current / Cost / Recommended |
| Analyse price sensitivity for [Item Name] with marginal cost 250 | mixed | Elasticity regression with overridden marginal cost; recommended price based on cost-plus-markup rule |

### Procurement Optimisation (`optimize_procurement`)

| Prompt | Output | Expected Result |
|--------|--------|-----------------|
| Recommend procurement improvements | mixed | Supplier consolidation flag, new-supplier risk alerts, bulk-purchase candidates, priority-ranked action list |
| Show procurement strategy recommendations | mixed | Top supplier spend share, risk flags for large first-order suppliers, items to order in bulk |
| Are there any risky new suppliers? | mixed | New suppliers (first purchase within last 90 days) whose first invoice is a statistical outlier (z > 2σ) |
| Which items should we consolidate into bulk orders? | mixed | Items ordered 4+ times in the last 90 days — candidates for fewer, larger purchase orders |
| How concentrated is our supplier base? | mixed | Top-5 supplier share of total spend; recommends consolidation if < 70% or flags high concentration if > 90% |
| Show supplier risk analysis for the last 6 months | mixed | 6-month procurement analysis: spend, concentration, new-supplier outliers, bulk candidates |

### Production Scheduling (`optimize_production_schedule`)

| Prompt | Output | Expected Result |
|--------|--------|-----------------|
| Build a production schedule for [Item Name] | mixed | 6-month Silver-Meal schedule with monthly production quantities, ending inventory, setup/holding cost totals |
| Create a production plan for [Item Name] for next 3 months | mixed | 3-month schedule with demand forecast, recommended production per month, cost breakdown |
| Optimise production for [Item Name] with monthly capacity 500 units | mixed | Schedule capped at 500 units/month; excess demand rolled forward; capacity utilisation % |
| What is the optimal lot size for producing [Item Name]? | mixed | Silver-Meal lots that minimise setup + holding cost, shown as a bar chart of demand vs production vs inventory |
| Show production schedule for [Item Name] with setup cost 200 and holding cost 30% | mixed | Schedule recalculated with custom setup and holding cost inputs |

### Working Capital Optimisation (`optimize_working_capital`)

| Prompt | Output | Expected Result |
|--------|--------|-----------------|
| Analyse our working capital | mixed | DSO, DPO, DIO, CCC metrics vs targets; priority-ranked recommendations; current vs target bar chart |
| What is our cash conversion cycle? | mixed | CCC = DSO + DIO - DPO with component breakdown and comparison to default targets |
| How can we improve cash flow from operations? | mixed | Working capital recommendations: tighten credit (DSO), extend payables (DPO), reduce inventory days (DIO) |
| What is our Days Sales Outstanding? | mixed | DSO = (AR outstanding / net sales) × period days, with action if above target of 45 days |
| How much cash can we free up by improving collections? | mixed | Dollar impact estimate: (current DSO - target DSO) × daily sales |
| Optimise working capital with target DSO 30 days and DPO 45 days | mixed | CCC analysis with custom DSO and DPO targets; recommendations calibrated to your goals |
| What is our Days Inventory Outstanding? | mixed | DIO = (inventory value / net purchases) × period days; flags if above 60-day target |

Notes on Prescriptive Analytics:
- **Inventory**: Uses 12 months of Sales Invoice history; requires `valuation_rate`, `last_purchase_rate`, or `standard_rate` on the Item master.
- **Pricing**: Requires at least 6 months of sales with price variation (≥ 3 distinct average monthly prices). Low R² (< 0.3) results in a low-confidence warning.
- **Procurement**: Analyses submitted Purchase Invoices only. New-supplier risk flags use a 2-sigma threshold on first-invoice amounts.
- **Production**: Forecasts demand using Holt-Winters or Holt's method; needs ≥ 6 months of history. Capacity rollover is one period only.
- **Working Capital**: Point-in-time AR/AP outstanding; period-window net sales and purchases. Increase `months_back` for a longer averaging window.

---

## Multi-Company

| Prompt | Output | Expected Result |
|--------|--------|-----------------|
| Show consolidated P&L including subsidiaries | table | Consolidated P&L from ERPNext Consolidated Financial Statement report |
| Show consolidated balance sheet for the group | table | Consolidated Balance Sheet across all subsidiary companies |
| Show consolidated trial balance | table | Trial balance across selected companies from ERPNext report |
| @company Tara Technologies show sales this quarter | table | Sales data scoped to the specified company only |
| Include subsidiaries in the sales report | mixed | Toggles subsidiary inclusion for all subsequent queries in the session |
| @company Tara Technologies @period This Quarter show P&L | table | Profit and loss scoped to a specific company and time period |
| Compare sales across companies this fiscal year | table | Company-wise sales comparison with totals |

---

## General / Operations

These prompts require write operations to be enabled in Chatbot Settings.

| Prompt | Output | Expected Result |
|--------|--------|-----------------|
| Create a new customer "ABC Corp" | record | Customer record created after confirmation of details |
| Search for item "Laptop" | search | Matching items displayed with codes, names, and stock status |
| Update status of SO-00123 to Closed | record | Sales Order status updated after confirmation |
| Create a sales order for customer ABC Corp | record | Guided sales order creation with item and quantity prompts |
| Show details of Purchase Order PO-00456 | table | Full details of the specified purchase order |
| What ERPNext tools are available? | table | List of enabled tool categories and their capabilities |

---

## Tips

**Use @mentions to scope queries.** Type `@` in the chat input to see available categories: `@company`, `@period`, `@cost_center`, `@department`, `@warehouse`, `@customer`, `@item`, `@accounting_dimension`. These let you target specific companies, date ranges, or entities without typing full names. See the [AT_MENTION_GUIDE.md](AT_MENTION_GUIDE.md) for full details.

**Charts are interactive.** Prompts that return chart output render as interactive Apache ECharts visualizations. You can hover for tooltips, zoom, and pan. Charts are also included when you export a conversation to PDF.

**Results depend on your data and permissions.** The chatbot queries live ERPNext data. If a module is not installed (e.g., HRMS) or tools are disabled in Chatbot Settings, related prompts will not return results. Your user role permissions also apply -- you only see data you are authorized to access.

**Ask follow-up questions.** You can drill down into any result. For example, after seeing top customers, ask "Show sales details for the top customer" or "Break this down by item group."

**Upload documents for IDP processing.** Click the paperclip icon (or drag and drop) to attach invoices, purchase orders, receipts, or other documents. The chatbot extracts structured data using AI vision and maps it to ERPNext fields.

**Use voice input.** Click the microphone icon to dictate your prompt. The chatbot auto-sends after detecting 2 seconds of silence. Voice input works for any prompt type.

**Export conversations.** Use the download icon on any assistant message to export it as a PDF. You can also export the entire conversation from the chat header menu.

**Set your preferred language.** Use the language selector in the chat header to receive responses in Hindi, Spanish, French, German, and other supported languages.

**Combine @mentions for precision.** Use multiple @mentions in a single prompt for highly targeted queries: `@company Tara Technologies @period This Quarter -- show sales by territory`.
