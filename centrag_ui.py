
import gradio as gr
import requests
import json
import os
from typing import List, Dict, Any

# --- Configuration ---
API_BASE_URL = os.getenv("CENTRAG_API_URL", "http://localhost:8000")
DEFAULT_TEAM_ID = "demo-team-123"
DEFAULT_API_KEY = "centrag_dev_token_12345"

# --- API Helpers ---

def upload_document(file, team_id: str, api_key: str):
    if file is None:
        return "Please select a file.", None
    
    url = f"{API_BASE_URL}/v1/documents"
    headers = {"X-API-Key": api_key, "X-Team-ID": team_id}
    
    try:
        with open(file.name, "rb") as f:
            files = {"file": (os.path.basename(file.name), f, "application/pdf")}
            response = requests.post(url, headers=headers, files=files)
            
        if response.status_code == 202:
            data = response.json()
            return f"✅ Upload Successful!\nDocument ID: {data.get('id')}\nStatus: {data.get('status')}", data
        else:
            return f"❌ Upload Failed ({response.status_code}): {response.text}", None
    except Exception as e:
        return f"⚠️ Error: {str(e)}", None

def query_rag(query: str, team_id: str, api_key: str, stream: bool = False):
    if not query:
        return "Please enter a query."
    
    url = f"{API_BASE_URL}/v1/retrieve"
    headers = {
        "X-API-Key": api_key, 
        "X-Team-ID": team_id,
        "Content-Type": "application/json"
    }
    payload = {
        "queries": [query],
        "metadata_filter": {},
        "limit": 5
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            data = response.json()
            # Format results
            results = data.get("results", [])
            output = ""
            for i, res in enumerate(results):
                output += f"### Query: {res.get('query')}\n\n"
                for j, match in enumerate(res.get("matches", [])):
                    score = match.get("score", 0)
                    content = match.get("content", "")
                    metadata = match.get("metadata", {})
                    output += f"**[{j+1}] Score: {score:.4f}** (Source: {metadata.get('filename', 'unknown')})\n"
                    output += f"> {content[:300]}...\n\n"
            return output
        else:
            return f"❌ Query Failed ({response.status_code}): {response.text}"
    except Exception as e:
        return f"⚠️ Error: {str(e)}"

# --- UI Theme ---
theme = gr.themes.Soft(
    primary_hue="indigo",
    secondary_hue="slate",
    neutral_hue="slate",
    font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui", "sans-serif"],
).set(
    body_background_fill="*neutral_50",
    block_background_fill="white",
    block_border_width="1px",
    block_label_text_weight="600",
    button_primary_background_fill="*primary_600",
    button_primary_background_fill_hover="*primary_700",
)

# --- UI Layout ---
with gr.Blocks(theme=theme, title="CentRAG | Enterprise Document Intelligence") as demo:
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("# 🚀 CentRAG")
            gr.Markdown("Enterprise-grade RAG with dual-path retrieval.")
        
        with gr.Column(scale=1):
            with gr.Group():
                team_id_input = gr.Textbox(label="Team ID", value=DEFAULT_TEAM_ID, placeholder="Enter Team ID")
                api_key_input = gr.Password(label="API Key", value=DEFAULT_API_KEY, placeholder="Enter API Key")

    with gr.Tabs():
        # Ingestion Tab
        with gr.TabItem("📥 Ingestion"):
            with gr.Row():
                with gr.Column():
                    file_input = gr.File(label="Upload PDF Document", file_types=[".pdf"])
                    upload_btn = gr.Button("Process Document", variant="primary")
                with gr.Column():
                    upload_output = gr.Markdown("Status: Idle")
                    upload_json = gr.JSON(label="Response Details")
            
            upload_btn.click(
                upload_document, 
                inputs=[file_input, team_id_input, api_key_input], 
                outputs=[upload_output, upload_json]
            )

        # Retrieval Tab
        with gr.TabItem("🔍 Retrieval"):
            with gr.Row():
                with gr.Column():
                    query_input = gr.Textbox(label="Ask a Question", placeholder="e.g., What are the core architectural principles?")
                    query_btn = gr.Button("Search Knowledge", variant="primary")
                with gr.Column():
                    query_output = gr.Markdown("Results will appear here...")
            
            query_btn.click(
                query_rag, 
                inputs=[query_input, team_id_input, api_key_input], 
                outputs=[query_output]
            )

    gr.Markdown("---")
    gr.Markdown("Built with FastAPI, Qdrant, and PageIndex. Developed by DeepMind Advanced Agentic Coding.")

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
