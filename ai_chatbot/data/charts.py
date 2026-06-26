# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt
"""
ECharts Option Builders for AI Chatbot

Reusable helpers that construct complete ECharts option dicts.
Tools call these to embed chart data in their response; the frontend
passes the dict straight to echarts.setOption().
"""

# Color palette for all charts — vibrant, accessible, and distinct
CHART_COLORS = [
	"#5470c6",  # blue
	"#91cc75",  # green
	"#fac858",  # yellow
	"#ee6666",  # red
	"#73c0de",  # cyan
	"#3ba272",  # teal
	"#fc8452",  # orange
	"#9a60b4",  # purple
	"#ea7ccc",  # pink
	"#5db8b0",  # mint
]


def _colorize_data(series_data):
	"""Assign individual colors to each data point for single-series charts."""
	return [
		{"value": v, "itemStyle": {"color": CHART_COLORS[i % len(CHART_COLORS)]}}
		for i, v in enumerate(series_data)
	]


def build_bar_chart(
	title: str,
	categories: list[str],
	series_data: list,
	y_axis_name: str = "",
	series_name: str = "",
) -> dict:
	"""Build a vertical bar chart.

	Args:
		title: Chart title text.
		categories: X-axis labels.
		series_data: List of numeric values (same length as categories).
		y_axis_name: Y-axis label (e.g. "USD", "Count").
		series_name: Legend name for the data series.

	Returns:
		Complete ECharts option dict.
	"""
	return {
		"title": {"text": title, "left": "center", "textStyle": {"fontSize": 14}},
		"tooltip": {"trigger": "axis"},
		"grid": {"left": "15%", "right": "5%", "bottom": "15%", "top": "22%"},
		"xAxis": {
			"type": "category",
			"data": categories,
			"axisLabel": {"rotate": 30 if len(categories) > 6 else 0, "fontSize": 11},
		},
		"yAxis": {"type": "value", "name": y_axis_name, "nameGap": 10},
		"series": [
			{
				"name": series_name or title,
				"type": "bar",
				"data": _colorize_data(series_data),
				"itemStyle": {"borderRadius": [4, 4, 0, 0]},
			}
		],
	}


def build_line_chart(
	title: str,
	categories: list[str],
	series_data: list,
	y_axis_name: str = "",
	series_name: str = "",
) -> dict:
	"""Build a line chart.

	Args:
		title: Chart title text.
		categories: X-axis labels (e.g. months).
		series_data: List of numeric values.
		y_axis_name: Y-axis label.
		series_name: Legend name.

	Returns:
		Complete ECharts option dict.
	"""
	return {
		"color": CHART_COLORS,
		"title": {"text": title, "left": "center", "textStyle": {"fontSize": 14}},
		"tooltip": {"trigger": "axis"},
		"grid": {"left": "15%", "right": "5%", "bottom": "15%", "top": "22%"},
		"xAxis": {
			"type": "category",
			"data": categories,
			"axisLabel": {"fontSize": 11},
		},
		"yAxis": {"type": "value", "name": y_axis_name, "nameGap": 10},
		"series": [
			{
				"name": series_name or title,
				"type": "line",
				"data": series_data,
				"smooth": True,
				"areaStyle": {"opacity": 0.15},
			}
		],
	}


def build_multi_series_chart(
	title: str,
	categories: list[str],
	series_list: list[dict],
	y_axis_name: str = "",
	chart_type: str = "line",
) -> dict:
	"""Build a multi-series line or bar chart.

	Args:
		title: Chart title text.
		categories: X-axis labels.
		series_list: List of dicts with "name" and "data" keys.
			Example: [{"name": "Inflow", "data": [100, 200]}, ...]
		y_axis_name: Y-axis label.
		chart_type: "line" or "bar".

	Returns:
		Complete ECharts option dict.
	"""
	series = []
	for s in series_list:
		entry = {
			"name": s["name"],
			"type": chart_type,
			"data": s["data"],
		}
		if chart_type == "line":
			entry["smooth"] = True
		elif chart_type == "bar":
			entry["itemStyle"] = {"borderRadius": [4, 4, 0, 0]}
		series.append(entry)

	return {
		"color": CHART_COLORS,
		"title": {"text": title, "left": "center", "textStyle": {"fontSize": 14}},
		"tooltip": {"trigger": "axis"},
		"legend": {"top": 26, "type": "scroll", "data": [s["name"] for s in series_list]},
		"grid": {"left": "15%", "right": "5%", "bottom": "14%", "top": "30%"},
		"xAxis": {
			"type": "category",
			"data": categories,
			"axisLabel": {"fontSize": 11},
		},
		"yAxis": {"type": "value", "name": y_axis_name, "nameGap": 10},
		"series": series,
	}


def build_pie_chart(title: str, data: list[dict]) -> dict:
	"""Build a pie chart.

	Args:
		title: Chart title text.
		data: List of dicts with "name" and "value" keys.
			Example: [{"name": "Region A", "value": 1000}, ...]

	Returns:
		Complete ECharts option dict.
	"""
	return {
		"color": CHART_COLORS,
		"title": {"text": title, "left": "center", "textStyle": {"fontSize": 14}},
		"tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
		"legend": {"orient": "vertical", "left": "left", "top": "middle"},
		"series": [
			{
				"type": "pie",
				"radius": ["35%", "60%"],
				"center": ["55%", "55%"],
				"data": data,
				"emphasis": {
					"itemStyle": {"shadowBlur": 10, "shadowOffsetX": 0, "shadowColor": "rgba(0,0,0,0.5)"}
				},
				"label": {"formatter": "{b}\n{d}%"},
			}
		],
	}


def build_stacked_bar_chart(
	title: str,
	categories: list[str],
	series_list: list[dict],
	y_axis_name: str = "",
) -> dict:
	"""Build a stacked bar chart.

	Args:
		title: Chart title text.
		categories: X-axis labels (e.g. period labels).
		series_list: List of dicts with "name" and "data" keys.
			Each series becomes a stacked layer.
		y_axis_name: Y-axis label.

	Returns:
		Complete ECharts option dict.
	"""
	series = []
	for i, s in enumerate(series_list):
		series.append(
			{
				"name": s["name"],
				"type": "bar",
				"stack": "total",
				"data": s["data"],
				"itemStyle": {"color": CHART_COLORS[i % len(CHART_COLORS)]},
				"emphasis": {"focus": "series"},
			}
		)

	return {
		"color": CHART_COLORS,
		"title": {"text": title, "left": "center", "textStyle": {"fontSize": 14}},
		"tooltip": {
			"trigger": "axis",
			"axisPointer": {"type": "shadow"},
		},
		"legend": {"top": 26, "type": "scroll", "data": [s["name"] for s in series_list]},
		"grid": {"left": "15%", "right": "5%", "bottom": "14%", "top": "30%"},
		"xAxis": {
			"type": "category",
			"data": categories,
			"axisLabel": {"rotate": 30 if len(categories) > 6 else 0, "fontSize": 11},
		},
		"yAxis": {"type": "value", "name": y_axis_name, "nameGap": 10},
		"series": series,
	}


def build_horizontal_bar(
	title: str,
	categories: list[str],
	series_data: list,
	x_axis_name: str = "",
	series_name: str = "",
) -> dict:
	"""Build a horizontal bar chart.

	Args:
		title: Chart title text.
		categories: Y-axis labels (e.g. customer names).
		series_data: List of numeric values (same length as categories).
		x_axis_name: X-axis label.
		series_name: Legend name.

	Returns:
		Complete ECharts option dict.
	"""
	return {
		"title": {"text": title, "left": "center", "textStyle": {"fontSize": 14}},
		"tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
		"grid": {"left": "25%", "right": "10%", "bottom": "10%", "top": "22%"},
		"xAxis": {"type": "value", "name": x_axis_name},
		"yAxis": {
			"type": "category",
			"data": categories,
			"axisLabel": {"fontSize": 11, "width": 120, "overflow": "truncate"},
		},
		"series": [
			{
				"name": series_name or title,
				"type": "bar",
				"data": _colorize_data(series_data),
				"itemStyle": {"borderRadius": [0, 4, 4, 0]},
			}
		],
	}
