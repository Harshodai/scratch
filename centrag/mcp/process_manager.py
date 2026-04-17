"""
MCP Process Manager — Handles lifecycle of external MCP servers as local subprocesses.

The WHY:
    Servers like AWS, Jira, and Confluence typically run as standalone processes 
    (stdio or SSE). CentRAG needs a way to launch these "on-demand" and 
    communicate with them via the Model Context Protocol.

Pattern: ADAPTER / PROCESS MANAGER
"""

from __future__ import annotations

import atexit
import asyncio
import os
import signal
import subprocess
from typing import Dict, List, Optional
from centrag.utils.logger import get_logger

logger = get_logger("mcp.process_manager")

class MCPProcessManager:
    """
    Manages external MCP server processes.
    
    Provides 'launch-and-forget' with automatic cleanup.
    """

    def __init__(self):
        self._processes: Dict[str, subprocess.Popen] = {}
        # Register cleanup for when the main CentRAG process exits
        atexit.register(self.shutdown_all)

    def launch_server(
        self, 
        name: str, 
        command: List[str], 
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None
    ) -> bool:
        """
        Launch an MCP server process.
        
        Example:
            manager.launch_server("aws", ["npx", "-y", "@modelcontextprotocol/server-aws"])
        """
        if name in self._processes:
            # Check if still running
            if self._processes[name].poll() is None:
                logger.info("mcp_server_already_running", name=name)
                return True
            else:
                logger.info("mcp_server_zombie_cleanup", name=name)
                del self._processes[name]

        try:
            logger.info("mcp_server_launching", name=name, cmd=" ".join(command))
            
            # Merit: Use a new process group to avoid signal propagation issues
            # Only on non-windows. On Windows use specific flags if needed.
            creation_flags = 0
            if os.name == 'nt':
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP

            proc = subprocess.Popen(
                command,
                env={**os.environ, **(env or {})},
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=creation_flags
            )
            
            self._processes[name] = proc
            return True
        except Exception as e:
            logger.error("mcp_server_launch_failed", name=name, error=str(e))
            return False

    def shutdown_server(self, name: str):
        """Gracefully terminate a specific server."""
        if name in self._processes:
            proc = self._processes[name]
            logger.info("mcp_server_shutting_down", name=name)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            del self._processes[name]

    def shutdown_all(self):
        """Cleanup all managed processes."""
        for name in list(self._processes.keys()):
            self.shutdown_server(name)

    def is_alive(self, name: str) -> bool:
        """Check if a server process is currently running."""
        if name not in self._processes:
            return False
        return self._processes[name].poll() is None

    async def get_server_output(self, name: str, lines: int = 10) -> List[str]:
        """Debug helper to read recent logs from a server's stderr/stdout."""
        if name not in self._processes:
            return []
        
        proc = self._processes[name]
        # This is blocking, in a production system we'd use async streams
        # but for sub-process management this is a start.
        output = []
        try:
            # Read non-blocking if possible or just use what's in the pipe
            if proc.stderr:
                for _ in range(lines):
                    line = proc.stderr.readline()
                    if not line: break
                    output.append(line.strip())
        except Exception:
            pass
        return output
