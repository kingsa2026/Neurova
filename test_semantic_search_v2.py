import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from neurova.cognitive_layers.memory_layer.semantic_search import SemanticSearch

print('=== Semantic Search Test ===')

search = SemanticSearch()

# Test keyword extraction
text = '数据库挂了，API返回500错误'
keywords = search._extract_keywords(text)
print('Keywords from "{}": {}'.format(text, keywords))

# Test similarity
sim1 = search.compute_similarity('数据库挂了', '数据库故障')
print('Similarity (数据库挂了 vs 数据库故障): {:.2f}'.format(sim1))

sim2 = search.compute_similarity('数据库挂了', '服务器重启')
print('Similarity (数据库挂了 vs 服务器重启): {:.2f}'.format(sim2))

# Test keyword index
memories = [
    {'id': 'mem1', 'content': '数据库挂了'},
    {'id': 'mem2', 'content': 'API返回错误'},
    {'id': 'mem3', 'content': '服务器重启'},
]

search.build_keyword_index(memories)
print('Keyword index built: {} keywords'.format(len(search._keyword_index)))

# Test search
results = search.search_by_keywords('数据库', limit=2)
print('Search results for "数据库": {}'.format(results))
