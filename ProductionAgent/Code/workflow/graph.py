"""Construct and compile the ProductionAgent LangGraph workflow.

This module owns graph wiring only: node registration, edges, and compilation.
Business work stays inside the node modules, shared data stays in state.py, and
conditional decisions stay in routing.py.

Main classes:
    ProductionAgentGraph:
        Builds the six-node workflow and exposes one invoke boundary.

Main methods:
    invoke():
        Runs one graph invocation from START until RESPONSE reaches END.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from .nodes.argument_resolver import ArgumentResolverNode
from .nodes.execution import ExecutionNode
from .nodes.post_processing import PostProcessingNode
from .nodes.request import RequestNode
from .nodes.response import ResponseNode
from .nodes.selector import SelectorNode
from .routing import GraphRouter
from .state import AgentState


class ProductionAgentGraph:
    """Own the compiled six-node workflow used by ProductionAgentOrchestrator."""

    def __init__(self) -> None:
        self._router = GraphRouter()
        self._request = RequestNode()
        self._selector = SelectorNode()
        self._argument_resolver = ArgumentResolverNode()
        self._execution = ExecutionNode()
        self._post_processing = PostProcessingNode()
        self._response = ResponseNode()

        self._compiled_graph = self._build_graph()

    def invoke(self, state: AgentState) -> AgentState:
        """Run one complete graph invocation and return the updated shared state."""
        result: Any = self._compiled_graph.invoke(state)
        return result

    def _build_graph(self) -> Any:
        graph = StateGraph(AgentState)

        graph.add_node("request", self._request.run)
        graph.add_node("selector", self._selector.run)
        graph.add_node("argument_resolver", self._argument_resolver.run)
        graph.add_node("execution", self._execution.run)
        graph.add_node("post_processing", self._post_processing.run)
        graph.add_node("response", self._response.run)

        graph.add_edge(START, "request")
        graph.add_conditional_edges(
            "request",
            self._router.after_request,
            {
                "selector": "selector",
                "argument_resolver": "argument_resolver",
                "post_processing": "post_processing",
            },
        )
        graph.add_conditional_edges(
            "selector",
            self._router.after_selector,
            {
                "argument_resolver": "argument_resolver",
                "response": "response",
            },
        )
        graph.add_conditional_edges(
            "argument_resolver",
            self._router.after_argument_resolver,
            {
                "execution": "execution",
                "response": "response",
            },
        )
        graph.add_edge("execution", "post_processing")
        graph.add_edge("post_processing", "response")
        graph.add_edge("response", END)

        return graph.compile()
