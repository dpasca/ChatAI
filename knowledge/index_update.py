# Load the environment variables, override the existing ones
from dotenv import load_dotenv
load_dotenv(override=True)

import os
import json
import shutil
import time
import re

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

# Where the articles to index are located
SOURCE_DIR = "_source_for_db"
# Directory for persisting llmaindex index data
INDEX_PERSIST_DIR = "_index_data"
# Directory for persisting Chroma data
CHROMA_PERSIST_DIR = "_chroma_db"

#===================================================================
from llama_index.core.schema import Document
import uuid

# Assuming 'articles' is a list of article dictionaries loaded from your JSON files
def prepare_documents_for_indexing(articles: List[dict]) -> List[Document]:
    prepared_documents = []
    for article in articles:
        # Create a Document instance for each article
        # Adapt this based on the actual structure of your articles and what Document expects

        # Use the URL as the document ID, or the title, or generate a unique ID
        use_id = article.get('url')
        if not use_id or use_id.strip() == '':
            # Use the title, replace spaces with underscores, and remove special characters
            title = article.get('title', '')
            use_id = re.sub(r'\W+', '', title.replace(' ', '_'))
        if not use_id:
            use_id = str(uuid.uuid4())

        doc = Document(
            text=article.get('content', '') + '\n' + json.dumps(article.get('recipe', ''), ensure_ascii=False),
            metadata={
                'title': article.get('title', ''),
                'url': article.get('url', ''),
                # Include other metadata as needed
            },
            id_=use_id
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
        if os.path.exists(INDEX_PERSIST_DIR):
            shutil.rmtree(INDEX_PERSIST_DIR)
        if os.path.exists(CHROMA_PERSIST_DIR):
            shutil.rmtree(CHROMA_PERSIST_DIR)

    # Initialize Chroma client
    db = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    chroma_collection = db.get_or_create_collection("quickstart")
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)

    # Ensure persist directory exists
    if not os.path.exists(INDEX_PERSIST_DIR):
        os.makedirs(INDEX_PERSIST_DIR, exist_ok=True)

    logmsg("Loading documents...")
    #documents = SimpleDirectoryReader(SOURCE_DIR).load_data()
    documents = load_documents(SOURCE_DIR)

    start_time = time.time()

    # Check if docstore.json exists
    docstore_file = os.path.join(INDEX_PERSIST_DIR, "docstore.json")
    if force_reindex or not os.path.isfile(docstore_file):
        logmsg("Creating new index...")
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        logmsg(f"Indexing {len(documents)} documents...")
        index = VectorStoreIndex.from_documents(documents, storage_context=storage_context)
    else:
        logmsg("Loading existing index for update...")
        storage_context = StorageContext.from_defaults(persist_dir=INDEX_PERSIST_DIR, vector_store=vector_store)
        index = load_index_from_storage(storage_context)

        # NOTE: "NotImplementedError: Vector store integrations that store text in the vector store are not supported by ref_doc_info yet."

        #logmsg("Updating index with new documents...")
        #new_documents = []
        #for doc in documents:
        #    if doc.id_ in index.ref_doc_info:
        #        new_documents.append(doc)

        #logmsg(f"Adding {len(new_documents)} new documents to the index...")
        #index.add_documents(new_documents)

    index.storage_context.persist(persist_dir=INDEX_PERSIST_DIR)
    logmsg(f"Indexing completed in {time.time() - start_time:.2f} seconds.")


#===================================================================
# TESTING STUFF
def rag_search_knowledge_base(search_str, retriever):
    #retrieved_docs = self.query_engine.retrieve(query)
    retrieved_docs = retriever.retrieve(search_str)
    #logmsg(f"Retrieved {len(retrieved_docs)} documents")

    results = []
    for doc in retrieved_docs:
        score = doc.score
        text = doc.text
        metadata = doc.node.extra_info

        # Uncomment to see the found snippets
        #logmsg(f"score: {score}, metadata: {metadata}")
        #logmsg(f"text: {doc.node.text}")

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
import argparse

if __name__ == "__main__":

    # First create the index and the database
    # NOTE: forcing index for now, because update is not possible
    create_index_and_db(force_reindex=True)

    if False: # Do a test query
        test_query(
            INDEX_PERSIST_DIR,
            CHROMA_PERSIST_DIR,
            "ricetta di marmellata alle fragole")
