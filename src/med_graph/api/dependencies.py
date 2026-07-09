"""Request-scoped access to the shared GraphClient held on app state."""

from fastapi import Request

from med_graph.graph.client import GraphClient


def get_client(request: Request) -> GraphClient:
    return request.app.state.client
