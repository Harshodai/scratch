# AgentsView Integration Guide for CentRAG

This guide explains how to use **AgentsView** to visualize and analyze Antigravity sessions and CentRAG developmental logs.

---

## 🚀 Quick Start

To see your current and past sessions in the dashboard:

1. **Sync Sessions**: Use the internal exporter to format Antigravity logs for AgentsView.
   ```bash
   make sync-view
   ```

2. **Launch Dashboard**: Start the AgentsView server.
   ```bash
   make view-sessions
   ```

3. **Open Browser**: Navigate to `http://localhost:8080`.

---

## 🛠️ Makefile Commands

| Command | Action |
|---------|--------|
| `make sync-view` | Exports Antigravity `brain/` sessions to `~/.gemini/tmp/` for indexing. |
| `make view-sessions` | Starts the `agentsview` server from the local repository. |
| `make agentsview-build` | Rebuilds the AgentsView binary from source. |

---

## 📁 Data Mapping

- **Antigravity Source**: `~/.gemini/antigravity/brain/`
- **AgentsView Search Cache**: `~/.gemini/tmp/antigravity/chats/`
- **AgentsView Database**: `~/.agentsview/sessions.db` (SQLite)

---

## 🧐 How it Works

1. **CentRAG Script**: `centrag/scripts/sync_agentsview.py` scans the Antigravity "brain" directory where step-by-step metadata is stored.
2. **Translation**: It transforms custom markdown steps into the standardized **Gemini CLI JSON** format.
3. **Discovery**: `agentsview` is configured to auto-discover files in `~/.gemini/tmp/` with the `session-*.json` pattern.
4. **Visualization**: The dashboard provides full-text search across your implementation plans, audit results, and coding conversations.

---

## ⚠️ Troubleshooting

- **Sessions not appearing?**: Run `make sync-view` and check if `~/.gemini/tmp/antigravity/chats/` contains JSON files.
- **Port Conflict?**: If 8080 is taken, use `agentsview -port 9090`.
- **Missing Binary?**: Run `make agentsview-build` first.

---

> [!TIP]
> Use the `r` key in the AgentsView dashboard to force a manual resync without restarting the server.
