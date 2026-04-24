from __future__ import annotations

from fastapi import Request


def get_services(request: Request):
    return request.app.state.services
