import glob
import json
import os
from datetime import datetime

# Antigravity App Data Path
ANTIGRAVITY_APP_DATA = os.path.expanduser("~/.gemini/antigravity")
BRAIN_DIR = os.path.join(ANTIGRAVITY_APP_DATA, "brain")

# AgentsView Search Path for Gemini-like sessions.
# This matches what internal/parser/discovery.go expects.
AGENTSVIEW_GEMINI_TMP = os.path.expanduser("~/.gemini/tmp/antigravity/chats")


def parse_antigravity_session(session_path):
    """
    Parses an Antigravity 'brain' directory into a Gemini-compatible message list.
    """
    session_id = os.path.basename(session_path)
    steps_dir = os.path.join(session_path, ".system_generated", "steps")

    if not os.path.exists(steps_dir):
        return None

    # Sort steps numerically
    steps = sorted(os.listdir(steps_dir), key=lambda x: int(x) if x.isdigit() else 999)

    messages = []
    for step in steps:
        content_path = os.path.join(steps_dir, step, "content.md")
        if not os.path.exists(content_path):
            continue

        with open(content_path, encoding="utf-8") as f:
            content = f.read()

        # For Antigravity, each 'step' usually represents an agent response or tool use.
        # We simplify this into an alternating user/gemini stream for AgentsView.
        # In a real sync, we'd parse the role from the metadata, but for now we alternate.
        messages.append(
            {
                "type": "gemini" if int(step) % 2 == 0 else "user",
                "content": content,
                "timestamp": datetime.now().isoformat() + "Z",
            }
        )

    if not messages:
        return None

    return {
        "sessionId": session_id,
        "startTime": datetime.now().isoformat() + "Z",  # Approximated
        "lastUpdated": datetime.now().isoformat() + "Z",
        "messages": messages,
        "kind": "main",
    }


def sync():
    if not os.path.exists(BRAIN_DIR):
        print(f"Error: Antigravity brain directory not found at {BRAIN_DIR}")
        return

    os.makedirs(AGENTSVIEW_GEMINI_TMP, exist_ok=True)
    print(f"Syncing Antigravity sessions to {AGENTSVIEW_GEMINI_TMP}...")

    session_dirs = [d for d in glob.glob(os.path.join(BRAIN_DIR, "*")) if os.path.isdir(d)]

    count = 0
    for s_dir in session_dirs:
        session_id = os.path.basename(s_dir)
        data = parse_antigravity_session(s_dir)
        if data:
            target_path = os.path.join(AGENTSVIEW_GEMINI_TMP, f"session-{session_id}.json")
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            count += 1
            print(f"  [OK] Exported {session_id}")

    print(f"\nDone. Exported {count} sessions.")
    print("Run 'make view-sessions' to see them in AgentsView dashboard.")


if __name__ == "__main__":
    sync()
