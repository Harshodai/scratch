#!/usr/bin/env python3
"""End-to-end test for the Level 10.2 RAG system."""

import asyncio
import json
import time
import os
import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, '/home/ubuntu')

# Mock AWS credentials for testing
os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

from main_final import (
    upload_files, 
    process_document, 
    serialize_faiss_index,
    deserialize_faiss_index,
    compress_data,
    decompress_data,
    vector_cache
)
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from fastapi.testclient import TestClient
from main_final import app

print("=" * 80)
print("LEVEL 10.2 RAG SYSTEM - END-TO-END TEST")
print("=" * 80)

# ===== Test 1: Compression & Decompression =====
print("\n[TEST 1] Zstandard Compression & Decompression")
print("-" * 80)
try:
    test_data = b"Hello World! " * 1000
    compressed = compress_data(test_data)
    decompressed = decompress_data(compressed)
    
    compression_ratio = (1 - len(compressed) / len(test_data)) * 100
    print(f"✓ Original size: {len(test_data)} bytes")
    print(f"✓ Compressed size: {len(compressed)} bytes")
    print(f"✓ Compression ratio: {compression_ratio:.1f}%")
    print(f"✓ Data integrity: {'PASS' if test_data == decompressed else 'FAIL'}")
except Exception as e:
    print(f"✗ FAILED: {e}")

# ===== Test 2: Document Processing =====
print("\n[TEST 2] Document Processing (Multiple Formats)")
print("-" * 80)

sample_files = {
    "PDF": "/home/ubuntu/sample_files/sample_document.pdf",
    "Excel (Multi-Sheet)": "/home/ubuntu/sample_files/sample_data.xlsx",
    "PowerPoint": "/home/ubuntu/sample_files/sample_presentation.pptx",
    "Markdown": "/home/ubuntu/sample_files/sample_guide.md",
}

async def test_document_processing():
    for file_type, file_path in sample_files.items():
        if not os.path.exists(file_path):
            print(f"✗ {file_type}: File not found")
            continue
        
        try:
            docs = await process_document(file_path, Path(file_path).name)
            print(f"✓ {file_type}: Processed {len(docs)} chunks")
            if docs:
                print(f"  - Sample content: {docs[0].page_content[:80]}...")
                print(f"  - Metadata: {docs[0].metadata}")
        except Exception as e:
            print(f"✗ {file_type}: {str(e)[:100]}")

asyncio.run(test_document_processing())

# ===== Test 3: FAISS Index Serialization =====
print("\n[TEST 3] FAISS Index Serialization & Compression")
print("-" * 80)
try:
    # Create a mock FAISS index
    def mock_embed(text):
        return [0.1] * 1536
    
    docs = [
        Document(page_content="Quantum computing is revolutionary", metadata={"source": "test.pdf"}),
        Document(page_content="Machine learning powers AI", metadata={"source": "test.pdf"}),
    ]
    
    import faiss
    index = faiss.IndexFlatL2(1536)
    vectorstore = FAISS(embedding_function=mock_embed, index=index, docstore={}, index_to_docstore_id={})
    
    # Serialize and compress
    compressed_index = serialize_faiss_index(vectorstore)
    print(f"✓ Serialized FAISS index size: {len(compressed_index)} bytes")
    
    # Deserialize
    restored_vectorstore = deserialize_faiss_index(compressed_index)
    print(f"✓ Deserialized FAISS index successfully")
    print(f"✓ Index type: {type(restored_vectorstore)}")
except Exception as e:
    print(f"✗ FAILED: {str(e)[:100]}")

# ===== Test 4: LRU Cache =====
print("\n[TEST 4] LRU Cache Management")
print("-" * 80)
try:
    test_session_id = "test_session_123"
    mock_vectorstore = vectorstore
    
    # Add to cache
    vector_cache[test_session_id] = mock_vectorstore
    print(f"✓ Added session to cache. Cache size: {len(vector_cache)}")
    
    # Retrieve from cache
    retrieved = vector_cache.get(test_session_id)
    print(f"✓ Retrieved session from cache: {retrieved is not None}")
    
    # Delete from cache
    del vector_cache[test_session_id]
    print(f"✓ Deleted session from cache. Cache size: {len(vector_cache)}")
except Exception as e:
    print(f"✗ FAILED: {str(e)[:100]}")

# ===== Test 5: FastAPI Endpoints =====
print("\n[TEST 5] FastAPI Endpoints")
print("-" * 80)
try:
    client = TestClient(app)
    
    # Test health endpoint
    response = client.get("/health")
    print(f"✓ GET /health: {response.status_code}")
    print(f"  Response: {response.json()}")
    
    # Test upload endpoint (with actual files)
    with open("/home/ubuntu/sample_files/sample_guide.md", "rb") as f:
        files = [("files", ("sample_guide.md", f, "text/markdown"))]
        response = client.post("/upload_files", files=files)
    
    if response.status_code == 200:
        data = response.json()
        session_id = data.get("session_id")
        print(f"✓ POST /upload_files: {response.status_code}")
        print(f"  Session ID: {session_id}")
        print(f"  Metrics: {data.get('metrics')}")
        
        # Test delete endpoint
        response = client.delete(f"/session/{session_id}")
        print(f"✓ DELETE /session/{session_id}: {response.status_code}")
        print(f"  Response: {response.json()}")
    else:
        print(f"✗ POST /upload_files: {response.status_code}")
        print(f"  Error: {response.text[:200]}")
        
except Exception as e:
    print(f"✗ FAILED: {str(e)[:100]}")

# ===== Test 6: Streaming Response =====
print("\n[TEST 6] Streaming Response (Chat Endpoint)")
print("-" * 80)
try:
    client = TestClient(app)
    
    # Upload a file first
    with open("/home/ubuntu/sample_files/sample_guide.md", "rb") as f:
        files = [("files", ("sample_guide.md", f, "text/markdown"))]
        response = client.post("/upload_files", files=files)
    
    if response.status_code == 200:
        session_id = response.json()["session_id"]
        
        # Test chat endpoint
        chat_request = {
            "session_id": session_id,
            "question": "What are the key machine learning best practices?"
        }
        
        response = client.post("/chat", json=chat_request)
        print(f"✓ POST /chat: {response.status_code}")
        
        if response.status_code == 200:
            # Parse SSE response
            events = []
            for line in response.text.split('\n'):
                if line.startswith('data: '):
                    try:
                        event = json.loads(line[6:])
                        events.append(event)
                    except:
                        pass
            
            print(f"✓ Received {len(events)} events")
            
            # Check for metadata event
            metadata_events = [e for e in events if e.get('type') == 'metadata']
            token_events = [e for e in events if e.get('type') == 'token']
            
            print(f"  - Metadata events: {len(metadata_events)}")
            if metadata_events:
                print(f"    Sources: {metadata_events[0].get('sources')}")
            print(f"  - Token events: {len(token_events)}")
            if token_events:
                print(f"    Sample token: {token_events[0].get('text')[:50]}...")
        else:
            print(f"✗ Chat endpoint error: {response.text[:200]}")
    else:
        print(f"✗ Upload failed: {response.status_code}")
        
except Exception as e:
    print(f"✗ FAILED: {str(e)[:200]}")

print("\n" + "=" * 80)
print("END-TO-END TEST COMPLETED")
print("=" * 80)
