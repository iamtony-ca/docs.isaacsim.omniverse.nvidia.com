"""Extract translatable elements from one HTML file. Prints JSON array."""
import json, sys
from bs4 import BeautifulSoup

# 헤딩(h1~h6)은 영어 유지 — 본문 텍스트만 번역
BLOCK = {'p','li','dt','dd','figcaption','caption'}
SKIP  = {'code','pre','script','style','math'}

def skip_ancestor(el):
    return any(getattr(p,'name',None) in SKIP for p in el.parents)

def block_child(el):
    return any(getattr(c,'name',None) in BLOCK for c in el.descendants)

html = open(sys.argv[1], encoding='utf-8').read()
soup = BeautifulSoup(html, 'html.parser')
article = soup.find('article', class_='bd-article')

if not article:
    print('[]')
    sys.exit(0)

items = []
for el in article.find_all(BLOCK):
    if skip_ancestor(el) or block_child(el):
        continue
    t = el.get_text(strip=True)
    if t and t != '#' and len(t) > 1:
        items.append(el.decode_contents())

print(json.dumps(items, ensure_ascii=False))
