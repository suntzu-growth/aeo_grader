from __future__ import annotations

from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

from tools.gsc.nodes.tool_gsc import tool_gsc_node
from tools.gsc.nodes.especialista_gsc import especialista_gsc_node


class GSCSubgraphState(TypedDict, total=False):
    input_data: str
    gsc_data: Optional[dict]
    especialista_gsc_output: Optional[dict]
    status: Optional[str]
    response_msg: Optional[str]

def create_gsc_subgraph():
    builder = StateGraph(GSCSubgraphState)

    builder.add_node("tool_gsc", tool_gsc_node)
    builder.add_node("especialista_gsc", especialista_gsc_node)

    builder.set_entry_point("tool_gsc")
    builder.add_edge("tool_gsc", "especialista_gsc")
    builder.add_edge("especialista_gsc", END)

    return builder.compile()