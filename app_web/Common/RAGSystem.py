#==================================================================
# RAGSystem.py
#
# Author: Davide Pasca, 2024/05/20
# Description:
#==================================================================

import json
from .logger import *
from typing import Callable, Optional
from .MsgThread import MsgThread as MsgThread
from .ToolItem import ToolItem

# RAG (Retrieval Augmented Generation) tools
import chromadb
from llama_index.core import VectorStoreIndex, StorageContext, load_index_from_storage
from llama_index.vector_stores.chroma import ChromaVectorStore
#from llama_index.core import SimpleDirectoryReader
from llama_index.core.schema import Document

import docx

def convert_docx_to_md(docx_file):
    document = docx.Document(docx_file)
    md_content = ""
    for para in document.paragraphs:
        if para.style and para.style.name.startswith('Heading'):
            heading_level = int(para.style.name.split(' ')[1])
            md_content += '#' * heading_level + ' ' + para.text + '\n\n'
        elif para.style and para.style.name == 'List Bullet':
            md_content += '- ' + para.text + '\n'
        else:
            md_content += para.text + '\n\n'
    return md_content

class RAGSystem:
    def __init__(self, rag_query_instructions):
        self.tool_items = []
        self.indices = []
        self.retrievers = []
        self.rag_query_instructions = rag_query_instructions

        # Append the RAG tool definition
        logmsg("Creating RAG tool definition")
        self.tool_items.append(
            ToolItem(
                name="search_knowledge_base",
                function=self.rag_search_knowledge_base,
                requires_assistant=False,
                definition={
                    "name": "search_knowledge_base",
                    "description": "Search the knowledge base for information",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query"
                            }
                        },
                        "required": ["query"]
                    }
                }
            )
        )

    def add_persistent_storage(self, index_persist_dir, chroma_persist_dir):
        # Initialize Chroma client
        logmsg(f"Initializing Chroma client for index {len(self.indices)}, persisting to {chroma_persist_dir}...")
        chdb = chromadb.PersistentClient(path=chroma_persist_dir)
        chroma_collection = chdb.get_or_create_collection("quickstart")
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)

        logmsg(f"Loading documents and creating index persisting to {index_persist_dir}...")
        storage_context = StorageContext.from_defaults(
            persist_dir=index_persist_dir,
            vector_store=vector_store)

        # Load the index
        logmsg("Loading existing index...")
        index = load_index_from_storage(storage_context)
        self.indices.append(index)
        self.retrievers.append(index.as_retriever(similarity_top_k=3))
        doc_count = len(index.docstore.docs)
        logmsg(f"Found {doc_count} documents in the index")

    def add_immediate_storage(self, docs_dir):
        # Initialize Chroma client
        logmsg(f"Initializing Chroma client for index {len(self.indices)}...")
        chroma_collection = chromadb.Client().create_collection(f"imm_coll_{len(self.indices)}")
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)

        logmsg(f"Scanning directory {docs_dir} and adding files to index...")
        # Scan the directory and add the .docx files to the index
        documents = []
        for filename in os.listdir(docs_dir):
            # Ignore temporary files
            if filename.startswith('~$'):
                continue

            # Process only .docx files
            if filename.endswith('.docx'):
                docx_file = os.path.join(docs_dir, filename)
                md_content = convert_docx_to_md(docx_file)
                doc = Document(
                    text=md_content,
                    metadata={
                        'title': os.path.splitext(filename)[0],
                        'url': '',  # Empty for now
                    },
                    id_=os.path.splitext(filename)[0]
                )
                documents.append(doc)

        logmsg(f"Found {len(documents)} .docx files in the directory")

        if len(documents) == 0:
            logmsg("No documents found, skipping index creation")
            return

        logmsg("Creating index...")
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_documents(documents, storage_context=storage_context)
        self.indices.append(index)
        self.retrievers.append(index.as_query_engine())

    def rag_search_knowledge_base(self, arguments):
        query = arguments["query"]
        if inst := self.rag_query_instructions:
            query = query + ". " + inst

        results = []
        for retriever in self.retrievers:
            #retrieved_docs = self.query_engine.retrieve(query)
            retrieved_docs = retriever.retrieve(query)
            logmsg(f"Retrieved {len(retrieved_docs)} documents")

            for doc in retrieved_docs:
                score = doc.score
                text = doc.text
                metadata = doc.node.extra_info

                # Uncomment to see the found snippets
                logmsg(f"score: {score}, metadata: {metadata}")
                logmsg(f"text: {doc.node.text}")

                result = {
                    "score": score,
                    "text": text,
                    "metadata": metadata
                }
                results.append(result)

        return json.dumps(results)

    def get_tool_items(self):
        return self.tool_items
