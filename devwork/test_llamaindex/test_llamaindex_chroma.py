import os
import sys
import chromadb
from llama_index.core import (
    VectorStoreIndex, SimpleDirectoryReader, StorageContext, load_index_from_storage
)
from llama_index.vector_stores.chroma import ChromaVectorStore

# Directory for persisting llmaindex index data
INDEX_PERSIST_DIR = "./_index_data"
DOCSTORE_FILE = os.path.join(INDEX_PERSIST_DIR, "docstore.json")
# Directory for persisting Chroma data
CHROMA_PERSIST_DIR = "./_chroma_db"

# Initialize Chroma client
db = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
chroma_collection = db.get_or_create_collection("quickstart")
vector_store = ChromaVectorStore(chroma_collection=chroma_collection)

# Ensure persist directory exists
if not os.path.exists(INDEX_PERSIST_DIR):
    os.makedirs(INDEX_PERSIST_DIR, exist_ok=True)

# Check if docstore.json exists, if not, prepare for indexing
if not os.path.isfile(DOCSTORE_FILE):
    print("Loading documents and creating index...")
    documents = SimpleDirectoryReader("src_data").load_data()
    print(f"Indexing {len(documents)} documents...")
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex.from_documents(documents, storage_context=storage_context)
    index.storage_context.persist(persist_dir=INDEX_PERSIST_DIR)
else:
    print("Loading existing index...")
    storage_context = StorageContext.from_defaults(persist_dir=INDEX_PERSIST_DIR, vector_store=vector_store)
    index = load_index_from_storage(storage_context)

import time

class TimerLogger:
    def __init__(self, name):
        self.name = name
    def __enter__(self):
        self.start = time.time()
        return self
    def __exit__(self, *args):
        self.end = time.time()
        print(f"{self.name} took {self.end - self.start} seconds")

# Index ready for querying
search_str = sys.argv[1] if len(sys.argv) > 1 else "ricetta di marmellata alle fragole"
if True:
    with TimerLogger("Query") as tl:
        print(f"Querying: {search_str}")
        query_engine = index.as_query_engine()
        response = query_engine.query(search_str)
        print(response)
else:
    # Example of querying using Chroma's API (this is hypothetical)
    results = chroma_collection.query(search_str)
    print(results)
