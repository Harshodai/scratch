import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware


class ZeroTrustMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("Authorization")
        if not auth or "test-ephemeral-123" not in auth:
            print("ZERO-TRUST INTERCEPT: Rejected Unauthorized Request.")
            return JSONResponse(status_code=401, content={"detail": "Zero-Trust Error: Missing Ephemeral Auth"})
        return await call_next(request)

mcp = FastMCP("dummy_jira")

@mcp.tool()
def get_jira_status() -> str:
    """Fetches Jira status using an ephemeral token."""
    return "Jira is Operational! Your stateless Zero-Trust connection succeeded!"

if __name__ == "__main__":
    app = mcp.sse_app()
    app.add_middleware(ZeroTrustMiddleware)
    print("Starting Dummy Jira FastMCP Server on Localhost:8123...")
    uvicorn.run(app, host="127.0.0.1", port=8123)
