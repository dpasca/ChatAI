from duckduckgo_search import ddg
import json

def do_search(query_string):
    results = ddg(query_string, max_results=10)
    return results

# Example usage
res = do_search("What's the weather in Tokyo tomorrow")
print(res)