"""Minimal MCP server over stdio — serves a magic secret phrase."""
import json
import os
import sys
from typing import Optional

_METHOD_NOT_FOUND = -32601
_MAGIC_PHRASE = os.environ.get(
    "MCP_MAGIC_PHRASE",
    "phoenix-flame-{}".format(os.urandom(4).hex()),
)


def main() -> None:
    """Read stdin, dispatch JSON-RPC, write responses to stdout."""
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        response = _process_line(line)
        if response is not None:
            sys.stdout.write("{}\n".format(response))
            sys.stdout.flush()


def _process_line(raw_line: str) -> Optional[str]:
    """Parse JSON-RPC line and dispatch by method."""
    try:
        request = json.loads(raw_line)
    except json.JSONDecodeError:
        return None
    return _route_request(request)


def _route_request(request: dict) -> Optional[str]:
    """Route JSON-RPC request by method name."""
    method = request.get("method", "")
    request_id = request.get("id")
    routes = {
        "initialize": _handle_initialize,
        "tools/list": _handle_tools_list,
        "tools/call": _handle_tools_call,
        "notifications/initialized": lambda _rid, _prm: None,
    }
    route_fn = routes.get(method)
    if route_fn is None:
        return _build_response(request_id, {
            "code": _METHOD_NOT_FOUND,
            "message": "Unknown method: {}".format(method),
        }, is_error=True)
    return route_fn(request_id, request.get("params", {}))


def _handle_initialize(request_id, _unused) -> str:
    """Build initialize response."""
    return _build_response(request_id, {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "magic-secret", "version": "1.0.0"},
    })


def _handle_tools_list(request_id, _unused) -> str:
    """Build tools/list response."""
    return _build_response(request_id, {
        "tools": [{
            "name": "get_secret",
            "description": "Returns the magic secret phrase.",
            "inputSchema": {"type": "object", "properties": {}},
        }],
    })


def _handle_tools_call(request_id, request_params: dict) -> Optional[str]:
    """Dispatch tool call by name."""
    tool_name = request_params.get("name", "")
    if tool_name == "get_secret":
        return _build_response(request_id, {
            "content": [{"type": "text", "text": _MAGIC_PHRASE}],
            "isError": False,
        })
    return _build_response(request_id, {
        "code": _METHOD_NOT_FOUND,
        "message": "Unknown tool: {}".format(tool_name),
    }, is_error=True)


def _build_response(
    request_id, payload: dict, *, is_error: bool = False,
) -> str:
    """Build JSON-RPC success or error response."""
    if is_error:
        return json.dumps({
            "jsonrpc": "2.0", "id": request_id, "error": payload,
        })
    return json.dumps({
        "jsonrpc": "2.0", "id": request_id, "result": payload,
    })


if __name__ == "__main__":
    main()
