import sys
import os.path
from llama_index.core import (
    VectorStoreIndex,
    SimpleDirectoryReader,
    StorageContext,
    load_index_from_storage,
)

# check if storage already exists
PERSIST_DIR = "./_storage"
if not os.path.exists(PERSIST_DIR):
    # load the documents and create the index
    documents = SimpleDirectoryReader("src_data").load_data()
    print(f"Indexing {len(documents)} documents...")
    index = VectorStoreIndex.from_documents(documents)
    # store it for later
    index.storage_context.persist(persist_dir=PERSIST_DIR)
else:
    # load the existing index
    print("Loading existing index...")
    storage_context = StorageContext.from_defaults(persist_dir=PERSIST_DIR)
    index = load_index_from_storage(storage_context)

# Either way we can now query the index
print("Index ready for querying")
query_engine = index.as_query_engine()

# Get the query from the command line arguments
query_string = sys.argv[1] if len(sys.argv) > 1 else "ricetta di marmellata, in italiano, con URL di riferimento"

print(f"Querying: {query_string}")
response = query_engine.query(query_string)
print(response)