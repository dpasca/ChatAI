# Load the environment variables, override the existing ones
from dotenv import load_dotenv
load_dotenv(override=True)

import os
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
def create_index_and_db(force_reindex=False):
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
        documents = SimpleDirectoryReader(SOURCE_DIR).load_data()
        logmsg(f"Indexing {len(documents)} documents...")
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_documents(documents, storage_context=storage_context)
        index.storage_context.persist(persist_dir=INDEX_PERSIST_DIR)
    else:
        logmsg("Loading existing index...")
        storage_context = StorageContext.from_defaults(persist_dir=INDEX_PERSIST_DIR, vector_store=vector_store)
        index = load_index_from_storage(storage_context)

def test_query(index_perist_dir, chroma_persist_dir, search_str):
    # Initialize Chroma client
    logmsg(f"Initializing Chroma client with {chroma_persist_dir}...")
    db = chromadb.PersistentClient(path=chroma_persist_dir)
    chroma_collection = db.get_or_create_collection("quickstart")
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    logmsg(f"Loading index from {index_perist_dir}...")
    storage_context = StorageContext.from_defaults(persist_dir=index_perist_dir, vector_store=vector_store)
    index = load_index_from_storage(storage_context)

    query = index.as_query_engine()
    response = query.query(search_str)
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
    #create_index_and_db(force_reindex=True)
    # Do a test query
    test_query(
        INDEX_PERSIST_DIR,
        CHROMA_PERSIST_DIR,
        "ricetta di marmellata alle fragole")

    # Then upload the index and the database to the cloud storage
    upload_to_storage()

    # Test downloading from the cloud storage
    test_download_from_storage()
