"""
Enterprise Rate Limiting Middleware

This module enforces rate-limiting at the API gateway layer. It acts as a defense-in-depth mechanism
before requests hit the complex Guardrail or LLM Gateway circuit breakers, preventing simple burst abuse
or DoS vectors against the RAG retrieval endpoints. 
"""

import time
from collections import defaultdict
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

class SimpleRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 100, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        
        # Note: In a true multi-instance deployment, this dict would be replaced by Redis.
        # Since this RAG architecture already defines L2 Cache (Redis), a Principle Architect 
        # would hook this into `centrag/cache/l2_redis.py` over time.
        self.requests = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        
        # Clean up old timestamps
        self.requests[client_ip] = [
            timestamp for timestamp in self.requests[client_ip] 
            if timestamp > now - self.window_seconds
        ]
        
        if len(self.requests[client_ip]) >= self.max_requests:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down."},
                headers={"Retry-After": str(self.window_seconds)}
            )
            
        self.requests[client_ip].append(now)
        
        response = await call_next(request)
        return response
