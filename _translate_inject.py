"""Inject translated elements back into HTML. Args: <html_file> <translations_json_file>"""
import json, sys
from bs4 import BeautifulSoup

# 헤딩(h1~h6)은 영어 유지 — 본문 텍스트만 번역
BLOCK = {'p','li','dt','dd','figcaption','caption'}
SKIP  = {'code','pre','script','style','math'}

def skip_ancestor(el):
    return any(getattr(p,'name',None) in SKIP for p in el.parents)

def block_child(el):
    return any(getattr(c,'name',None) in BLOCK for c in el.descendants)

html_path = sys.argv[1]
translations = json.loads(open(sys.argv[2], encoding='utf-8').read())

html = open(html_path, encoding='utf-8').read()
soup = BeautifulSoup(html, 'html.parser')
article = soup.find('article', class_='bd-article')

if not article:
    print('No article found, skipping.')
    sys.exit(0)

targets = []
for el in article.find_all(BLOCK):
    if skip_ancestor(el) or block_child(el):
        continue
    t = el.get_text(strip=True)
    if t and t != '#' and len(t) > 1:
        targets.append(el)

if len(targets) != len(translations):
    print(f'ERROR: {len(targets)} elements vs {len(translations)} translations', file=sys.stderr)
    sys.exit(1)

for el, tr in zip(targets, translations):
    el.clear()
    frag = BeautifulSoup(tr, 'html.parser')
    for child in list(frag.children):
        el.append(child)

# 페이지 제목도 번역 목록 마지막에 포함한 경우 처리 (선택)
open(html_path, 'w', encoding='utf-8').write(str(soup))
print(f'OK: {html_path}')
