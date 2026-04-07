
import os
import uuid
import asyncio
import time
import pickle
import logging
import faiss
from typing import List, Dict, Any, Optional, AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, status, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from langchain_community.vectorstores import FAISS
from langchain_aws import ChatBedrock, BedrockEmbeddings
from langchain.docstore.document import Document
from langchain.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

# Docling for High-Accuracy Parsing
from docling.document_converter import DocumentConverter
from docling.chunking import HybridChunker

import redis

# --- Configuration --- #
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_EMBEDDING_MODEL = os.getenv("BEDROCK_EMBEDDING_MODEL", "amazon.titan-embed-text-v2:0")
BEDROCK_LLM_MODEL = os.getenv("BEDROCK_LLM_MODEL", "anthropic.claude-3-5-sonnet-20240620-v1:0")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_TTL_SECONDS = int(os.getenv("REDIS_TTL_SECONDS", 3600))  # 1 hour for non-real-time

UPLOAD_DIR = "./temp_uploads"
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB limit
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".html"}

os.makedirs(UPLOAD_DIR, exist_ok=True)

# --- Logging Setup --- #
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Pydantic Models --- #
class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, description="Session ID from upload")
    question: str = Field(..., min_length=1, max_length=2000, description="Question to ask")

class ChatResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]
    metrics: Dict[str, float]

class UploadResponse(BaseModel):
    session_id: str
    message: str
    metrics: Dict[str, Any]

# --- Redis Client with Connection Pooling --- #
redis_pool = redis.ConnectionPool(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    max_connections=20,
    socket_connect_timeout=5,
    socket_timeout=5,
    health_check_interval=30
)
redis_client = redis.Redis(connection_pool=redis_pool)

# --- AWS Bedrock Clients --- #
embeddings = BedrockEmbeddings(
    model_id=BEDROCK_EMBEDDING_MODEL,
    region_name=AWS_REGION
)

llm = ChatBedrock(
    model_id=BEDROCK_LLM_MODEL,
    region_name=AWS_REGION,
    streaming=True,
    model_kwargs={
        "temperature": 0.1,
        "max_tokens": 2000,
        "anthropic_version": "bedrock-2023-05-31"
    }
)

# --- Docling Components --- #
doc_converter = DocumentConverter()
chunker = HybridChunker(
    tokenizer="BAAI/bge-small-en-v1.5",  # Compatible with embeddings
    max_chunk_size=512,
    merge_peers=True
)

# --- Helper Functions --- #

def validate_file_extension(filename: str) -> bool:
    """Check if file extension is allowed."""
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS

async def save_upload_file(file: UploadFile) -> str:
    """Save uploaded file to disk asynchronously."""
    file_location = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}_{file.filename}")
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds {MAX_FILE_SIZE // (1024*1024)}MB limit"
        )
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _write_file, file_location, content)
    return file_location

def _write_file(path: str, content: bytes):
    """Synchronous file write helper."""
    with open(path, "wb") as f:
        f.write(content)

def process_document_with_docling(file_path: str, filename: str) -> List[Document]:
    """Process document using Docling with HybridChunker."""
    try:
        result = doc_converter.convert(file_path)
        chunks = list(chunker.chunk(result.document))
        documents = []
        for chunk in chunks:
            page_no = None
            if chunk.prov and len(chunk.prov) > 0:
                page_no = chunk.prov[0].page_no
            metadata = {
                "source": filename,
                "type": os.path.splitext(filename)[1].lower(),
                "page": page_no,
                "chunk_type": chunk.meta.heading_type if hasattr(chunk.meta, 'heading_type') else "text"
            }
            documents.append(Document(page_content=chunk.text, metadata=metadata))
        return documents
    except Exception as e:
        logger.error(f"Docling processing error for {filename}: {str(e)}")
        raise

def serialize_faiss_index(vectorstore: FAISS) -> bytes:
    """Serialize FAISS index to bytes for Redis storage."""
    try:
        serialized_data = {
            'index': faiss.serialize_index(vectorstore.index),
            'docstore': vectorstore.docstore,
            'index_to_docstore_id': vectorstore.index_to_docstore_id
        }
        return pickle.dumps(serialized_data, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as e:
        logger.error(f"FAISS serialization error: {str(e)}")
        raise

def deserialize_faiss_index(serialized_data: bytes) -> FAISS:
    """Deserialize FAISS index from bytes."""
    try:
        data = pickle.loads(serialized_data)
        index = faiss.deserialize_index(data['index'])
        vectorstore = FAISS(
            embedding_function=embeddings.embed_query,
            index=index,
            docstore=data['docstore'],
            index_to_docstore_id=data['index_to_docstore_id']
        )
        return vectorstore
    except Exception as e:
        logger.error(f"FAISS deserialization error: {str(e)}")
        raise

def store_session_data(session_id: str, documents: List[Document], vectorstore: FAISS):
    """Store documents and FAISS index in Redis with TTL."""
    try:
        docs_key = f"session_docs:{session_id}"
        docs_data = [{"page_content": d.page_content, "metadata": d.metadata} for d in documents]
        redis_client.setex(docs_key, REDIS_TTL_SECONDS, pickle.dumps(docs_data))
        index_key = f"faiss_index:{session_id}"
        serialized_index = serialize_faiss_index(vectorstore)
        redis_client.setex(index_key, REDIS_TTL_SECONDS, serialized_index)
        logger.info(f"Stored session {session_id} in Redis")
    except redis.RedisError as e:
        logger.error(f"Redis storage error: {str(e)}")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Session storage unavailable")

def get_session_vectorstore(session_id: str) -> Optional[FAISS]:
    """Retrieve FAISS index from Redis."""
    try:
        index_key = f"faiss_index:{session_id}"
        serialized_data = redis_client.get(index_key)
        if serialized_data:
            return deserialize_faiss_index(serialized_data)
        return None
    except redis.RedisError as e:
        logger.error(f"Redis retrieval error: {str(e)}")
        return None

# --- RAG Chain with Streaming --- #

RAG_PROMPT_TEMPLATE = """You are a professional assistant. Answer the question based ONLY on the provided context.
If the answer is not in the context, say "I don't know".
Always cite your sources using the format [^source_filename^page_X].

Context:
{context}

Question: {question}

Helpful Answer:"""

rag_prompt = ChatPromptTemplate.from_template(RAG_PROMPT_TEMPLATE)

def format_documents_for_context(docs: List[Document]) -> str:
    """Format documents into context string with citations."""
    formatted = []
    for i, doc in enumerate(docs):
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", "unknown")
        formatted.append(f"[Document {i+1}] Source: {source}, Page: {page}\n{doc.page_content}")
    return "\n\n".join(formatted)

# --- FastAPI App --- #

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up RAG Backend...")
    yield
    logger.info("Shutting down RAG Backend...")
    if os.path.exists(UPLOAD_DIR):
        for filename in os.listdir(UPLOAD_DIR):
            file_path = os.path.join(UPLOAD_DIR, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)

app = FastAPI(title="RAG Document Q&A API", version="2.0.1", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/upload_files", response_model=UploadResponse)
async def upload_files(files: List[UploadFile] = File(...)):
    session_id = str(uuid.uuid4())
    uploaded_paths: List[str] = []
    all_documents: List[Document] = []
    start_time = time.time()
    
    try:
        for file in files:
            if not validate_file_extension(file.filename):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"File type not allowed: {file.filename}")
            file_path = await save_upload_file(file)
            uploaded_paths.append(file_path)
            docs = await asyncio.get_event_loop().run_in_executor(None, process_document_with_docling, file_path, file.filename)
            all_documents.extend(docs)
        
        vectorstore = await asyncio.get_event_loop().run_in_executor(None, FAISS.from_documents, all_documents, embeddings)
        await asyncio.get_event_loop().run_in_executor(None, store_session_data, session_id, all_documents, vectorstore)
        
        return UploadResponse(
            session_id=session_id,
            message="Files processed successfully.",
            metrics={"ingestion_time": round(time.time() - start_time, 2), "chunks": len(all_documents)}
        )
    finally:
        for path in uploaded_paths:
            if os.path.exists(path): os.remove(path)

@app.post("/chat")
async def chat(request: ChatRequest):
    vectorstore = await asyncio.get_event_loop().run_in_executor(None, get_session_vectorstore, request.session_id)
    if not vectorstore:
        raise HTTPException(status_code=404, detail="Session expired.")

    retriever = vectorstore.as_retriever(search_kwargs={"k": 5})
    
    # Modern LCEL Chain
    chain = (
        {"context": retriever | format_documents_for_context, "question": RunnablePassthrough()}
        | rag_prompt
        | llm
        | StrOutputParser()
    )

    async def event_generator():
        try:
            async for chunk in chain.astream(request.question):
                yield chunk
        except Exception as e:
            yield f"Error: {str(e)}"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/health")
async def health_check():
    try:
        redis_client.ping()
        return {"status": "healthy", "redis": "connected"}
    except:
        return JSONResponse(status_code=503, content={"status": "unhealthy"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
