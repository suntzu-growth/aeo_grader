from __future__ import annotations

from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

from tools.aeo.nodes.tool_aeo import tool_aeo_node
from tools.aeo.nodes.especialista_aeo import especialista_aeo_node


class AEOSubgraphState(TypedDict, total=False):
    input_data: str
    aeo_data: Optional[dict]
    especialista_aeo_output: Optional[dict]
    status: Optional[str]
    response_msg: Optional[str]


def create_aeo_subgraph():
    builder = StateGraph(AEOSubgraphState)

    builder.add_node("tool_aeo", tool_aeo_node)
    builder.add_node("especialista_aeo", especialista_aeo_node)

    builder.set_entry_point("tool_aeo")
    builder.add_edge("tool_aeo", "especialista_aeo")
    builder.add_edge("especialista_aeo", END)

    return builder.compile()