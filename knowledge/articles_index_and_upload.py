# Load the environment variables, override the existing ones
from dotenv import load_dotenv
load_dotenv(override=True)

import os
import json
import shutil
import time

import chromadb
from llama_index.core import (
    VectorStoreIndex, SimpleDirectoryReader, StorageContext, load_index_from_storage
)
from llama_index.vector_stores.chroma import ChromaVectorStore

# Update the path for the modules below
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app_web.Common.StorageCloud import StorageCloud as Storage
from app_web.Common.logger import *

from typing import List

"""
This script will index all *.md files found in SOURCE_DIR.
The index will be persisted to INDEX_PERSIST_DIR.
The Chroma data will be persisted to CHROMA_PERSIST_DIR.
These persist directories will then be uploaded to the cloud storage
with StorageCloud.
"""

# Where the articles to index are located
SOURCE_DIR = "_source_for_db"
# Directory for persisting llmaindex index data
INDEX_PERSIST_DIR = "_index_data"
# Directory for persisting Chroma data
CHROMA_PERSIST_DIR = "_chroma_db"

TEST_DIR_PREFIX = "_tmp_test_"

#===================================================================
from llama_index.core.schema import Document
import uuid

# Assuming 'articles' is a list of article dictionaries loaded from your JSON files
def prepare_documents_for_indexing(articles: List[dict]) -> List[Document]:
    prepared_documents = []
    for article in articles:
        # Create a Document instance for each article
        # Adapt this based on the actual structure of your articles and what Document expects
        doc = Document(
            text=article.get('content', '') + '\n' + json.dumps(article.get('recipe', ''), ensure_ascii=False),
            metadata={
                'title': article.get('title', ''),
                'url': article.get('url', ''),
                # Include other metadata as needed
            },
            id_=article.get('url', str(uuid.uuid4())),  # Use URL as ID, or generate if not available
        )
        prepared_documents.append(doc)

    return prepared_documents

def load_documents(source_dir):
    documents = []
    for filename in os.listdir(source_dir):
        if not filename.endswith(".json"):
            continue

        logmsg(f"Loading from file {source_dir}/{filename}...")

        with open(os.path.join(source_dir, filename), 'r', encoding='utf-8') as file:
            articles = json.load(file)
            for article in articles:
                documents.append(article)

    return prepare_documents_for_indexing(documents)

def create_index_and_db(force_reindex=False):

    # Clear existing database if reindexing
    if force_reindex:
        shutil.rmtree(INDEX_PERSIST_DIR)
        shutil.rmtree(CHROMA_PERSIST_DIR)

    # Initialize Chroma client
    db = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    chroma_collection = db.get_or_create_collection("quickstart")
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)

    # Ensure persist directory exists
    if not os.path.exists(INDEX_PERSIST_DIR):
        os.makedirs(INDEX_PERSIST_DIR, exist_ok=True)

    # Check if docstore.json exists, if not, prepare for indexing
    docstore_file = os.path.join(INDEX_PERSIST_DIR, "docstore.json")
    if force_reindex or not os.path.isfile(docstore_file):
        logmsg("Loading documents and creating index...")
        #documents = SimpleDirectoryReader(SOURCE_DIR).load_data()
        documents = load_documents(SOURCE_DIR)
        start_time = time.time()
        logmsg(f"Indexing {len(documents)} documents...")
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_documents(documents, storage_context=storage_context)
        index.storage_context.persist(persist_dir=INDEX_PERSIST_DIR)
        logmsg(f"Indexing completed in {time.time() - start_time:.2f} seconds.")
    else:
        logmsg("Loading existing storage content...")
        storage_context = StorageContext.from_defaults(persist_dir=INDEX_PERSIST_DIR, vector_store=vector_store)
        logmsg("Loading existing index...")
        index = load_index_from_storage(storage_context)
        logmsg("Done loading index.")

def rag_search_knowledge_base(search_str, query_engine):
    similarity_top_k = 5

    retrieved_docs = query_engine.retrieve(search_str)

    results = []
    for doc in retrieved_docs[:similarity_top_k]:
        score = doc.score
        text = doc.text
        metadata = doc.node.extra_info

        logmsg(f"node.text: {doc.node.text}")

        result = {
            "score": score,
            "text": text,
            "metadata": metadata
        }
        results.append(result)

    return json.dumps(results)

def test_query(index_perist_dir, chroma_persist_dir, search_str):
    # Initialize Chroma client
    logmsg(f"Initializing Chroma client with {chroma_persist_dir}...")
    db = chromadb.PersistentClient(path=chroma_persist_dir)
    chroma_collection = db.get_or_create_collection("quickstart")
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    logmsg(f"Loading index from {index_perist_dir}...")
    storage_context = StorageContext.from_defaults(persist_dir=index_perist_dir, vector_store=vector_store)
    index = load_index_from_storage(storage_context)

    query_engine = index.as_query_engine()
    #response = query_engine.query(search_str)
    response = rag_search_knowledge_base(search_str, query_engine)
    logmsg(f"Query: {search_str}")
    logmsg(f"Response: {response}")

#===================================================================
def create_storage():
    if os.getenv("DO_STORAGE_CONTAINER") is None:
        logmsg("DO_STORAGE_CONTAINER not set. Skipping storage creation...")
        return
    logmsg("Creating storage...")
    storage = Storage(
        bucket=os.getenv("DO_STORAGE_CONTAINER"),
        access_key=os.getenv("DO_SPACES_ACCESS_KEY"),
        secret_key=os.getenv("DO_SPACES_SECRET_KEY"),
        endpoint=os.getenv("DO_STORAGE_SERVER"))
    return storage

# Create the storage to use for uploading the indicized articles
def upload_to_storage():
    storage = create_storage()
    # Upload directories
    storage.upload_dir(
        local_dir=INDEX_PERSIST_DIR,
        target_dir=INDEX_PERSIST_DIR,
        use_file_listing=True)
    storage.upload_dir(
        local_dir=CHROMA_PERSIST_DIR,
        target_dir=CHROMA_PERSIST_DIR,
        use_file_listing=True)

def test_download_from_storage():
    import filecmp
    import shutil

    storage = create_storage()

    # Download directories
    storage.download_dir(
        local_dir=TEST_DIR_PREFIX+INDEX_PERSIST_DIR,
        cloud_dir=INDEX_PERSIST_DIR,
        use_file_listing=True)
    storage.download_dir(
        local_dir=TEST_DIR_PREFIX+CHROMA_PERSIST_DIR,
        cloud_dir=CHROMA_PERSIST_DIR,
        use_file_listing=True)

    # Compare the downloaded files with the original files, ignoring file_listing.txt
    index_match = filecmp.dircmp(INDEX_PERSIST_DIR, TEST_DIR_PREFIX+INDEX_PERSIST_DIR, ignore=['file_listing.txt'])
    chroma_match = filecmp.dircmp(CHROMA_PERSIST_DIR, TEST_DIR_PREFIX+CHROMA_PERSIST_DIR, ignore=['file_listing.txt'])

    if index_match.diff_files or chroma_match.diff_files:
        logerr("Downloaded files do NOT match the uploaded files.")
    else:
        logmsg("Downloaded files do match the uploaded files.")

    test_query(
        TEST_DIR_PREFIX+INDEX_PERSIST_DIR,
        TEST_DIR_PREFIX+CHROMA_PERSIST_DIR,
        "ricetta di marmellata alle fragole")

    # Remove the temporary directories
    #shutil.rmtree(f"_tmp_test_{INDEX_PERSIST_DIR}")
    #shutil.rmtree(f"_tmp_test_{CHROMA_PERSIST_DIR}")

#===================================================================
if __name__ == "__main__":
    # First create the index and the database
    create_index_and_db(force_reindex=False)
    # Do a test query
    test_query(
        INDEX_PERSIST_DIR,
        CHROMA_PERSIST_DIR,
        "ricetta di marmellata alle fragole")

    # Then upload the index and the database to the cloud storage
    upload_to_storage()

    # Test downloading from the cloud storage
    test_download_from_storage()
