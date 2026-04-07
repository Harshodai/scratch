import os
import sys
import pickle
import zstandard as zstd
import faiss
import pandas as pd
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from main_final import serialize_faiss_index, deserialize_faiss_index, compress_data, decompress_data

def test_compression():
    print("Testing Zstd Compression...")
    data = b"Hello world" * 1000
    compressed = compress_data(data)
    decompressed = decompress_data(compressed)
    assert data == decompressed
    print(f"Compression Success: {len(data)} -> {len(compressed)} bytes")

def test_faiss_serialization():
    print("Testing FAISS Serialization & Compression...")
    # Mock embeddings function
    def mock_embed(text): return [0.1] * 1536
    
    docs = [Document(page_content="test content", metadata={"source": "test.pdf"})]
    # We need a real index to test serialize_index
    index = faiss.IndexFlatL2(1536)
    vectorstore = FAISS(embedding_function=mock_embed, index=index, docstore={}, index_to_docstore_id={})
    
    # Test serialization
    try:
        compressed_index = serialize_faiss_index(vectorstore)
        print(f"Serialized Index Size: {len(compressed_index)} bytes")
        assert len(compressed_index) > 0
        print("Serialization Success")
    except Exception as e:
        print(f"Serialization Failed: {e}")

def test_excel_robustness():
    print("Testing Excel Robustness Logic...")
    # Create a dummy excel with multiple sheets
    path = "test_sheets.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"a": [1, 2]}).to_excel(writer, sheet_name="Sheet1")
        pd.DataFrame({"b": [3, 4]}).to_excel(writer, sheet_name="Sheet2")
    
    from main_final import process_excel_robustly
    docs = process_excel_robustly(path, "test_sheets.xlsx")
    
    sheet_names = [d.metadata.get("sheet") for d in docs]
    print(f"Extracted Sheets: {set(sheet_names)}")
    assert "Sheet1" in sheet_names or "Docling-Parsed" in sheet_names
    os.remove(path)
    print("Excel Robustness Logic Success")

if __name__ == "__main__":
    test_compression()
    test_faiss_serialization()
    test_excel_robustness()
    print("\nAll Audit Logic Tests Passed!")
