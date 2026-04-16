from __future__ import annotations

from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

from tools.ga4.nodes.tool_ga4 import tool_ga4_node
from tools.ga4.nodes.especialista_ga4 import especialista_ga4_node


class GA4SubgraphState(TypedDict, total=False):
    input_data: str
    ga4_data: Optional[dict]
    especialista_ga4_output: Optional[dict]
    status: Optional[str]
    response_msg: Optional[str]


def create_ga4_subgraph():
    builder = StateGraph(GA4SubgraphState)

    builder.add_node("tool_ga4", tool_ga4_node)
    builder.add_node("especialista_ga4", especialista_ga4_node)

    builder.set_entry_point("tool_ga4")
    builder.add_edge("tool_ga4", "especialista_ga4")
    builder.add_edge("especialista_ga4", END)

    return builder.compile()