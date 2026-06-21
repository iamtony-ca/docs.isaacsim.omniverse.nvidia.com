#!/usr/bin/env python3
"""
Isaac Sim 문서 영어 → 한국어 번역 스크립트

사용법:
  python translate_docs.py                      # 전체 번역 (재실행 시 미완료 파일만)
  python translate_docs.py --dir sensors        # 특정 폴더만
  python translate_docs.py --limit 5            # 처음 N개 파일만 테스트
  python translate_docs.py --dry-run            # 번역 없이 대상 파일 목록만 출력
  python translate_docs.py --concurrency 10     # 동시 API 요청 수 조정 (기본: 5)

진행 상황은 .translation_progress.json에 저장되어 중단 후 재시작 가능.
ANTHROPIC_API_KEY 환경변수가 설정되어 있어야 합니다.
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import anthropic
from bs4 import BeautifulSoup, NavigableString, Tag

DOCS_DIR = Path(__file__).parent
PROGRESS_FILE = DOCS_DIR / ".translation_progress.json"

# claude-haiku: 속도/비용 효율적, 번역 품질 충분
MODEL = "claude-haiku-4-5-20251001"

# 한 번의 API 호출에 담을 최대 문자 수 (토큰 제한 고려)
MAX_CHARS_PER_BATCH = 8000

# 번역 대상 블록 요소 태그
# 헤딩(h1~h6)은 영어 유지 — 본문 텍스트만 번역
BLOCK_TAGS = frozenset({"p", "dt", "dd", "figcaption", "caption"})
# li는 별도 처리 (하위 블록 요소가 없는 경우에만)
LIST_ITEM_TAGS = frozenset({"li", "td", "th"})

# 번역하지 않을 태그 (코드, 스크립트 등)
SKIP_ANCESTOR_TAGS = frozenset({"code", "pre", "script", "style", "math"})

# 번역하지 않을 최상위 폴더
SKIP_DIRS = frozenset({"_static", "_images", "_downloads", "py"})

SYSTEM_PROMPT = """당신은 NVIDIA Isaac Sim 로보틱스 시뮬레이션 문서의 영어→한국어 전문 기술 번역가입니다.

입력: HTML 내용물(innerHTML)이 담긴 JSON 배열 (각 항목은 하나의 문단/제목/목록 항목)
출력: 동일한 길이의 JSON 배열 (각 항목을 한국어로 번역)

번역 규칙:
1. HTML 태그(<strong>, <em>, <a>, <kbd>, <code> 등)는 그대로 보존
2. 코드 식별자, API 이름, 함수명, 파일 경로, URL, 버전 번호는 번역하지 말 것
3. USD, PhysX, OmniGraph, RTX, ROS, Isaac Sim 같은 고유 제품명/기술 용어는 영어 유지
4. /World/Robot 같은 경로, True/False 같은 코드 값 번역 금지
5. 자연스럽고 명확한 한국어 기술 문서 문체 사용
6. JSON 배열만 반환, 다른 텍스트 없이

중요: 입력과 출력의 배열 길이가 반드시 동일해야 합니다."""


def has_skip_ancestor(element: Tag) -> bool:
    for parent in element.parents:
        if getattr(parent, "name", None) in SKIP_ANCESTOR_TAGS:
            return True
    return False


def has_block_descendant(element: Tag) -> bool:
    for child in element.descendants:
        if getattr(child, "name", None) in (BLOCK_TAGS | LIST_ITEM_TAGS):
            return True
    return False


def get_translatable_elements(article: Tag) -> list[Tag]:
    """번역 대상 블록 요소 수집 (중복 번역 방지 포함)."""
    results = []
    target_tags = BLOCK_TAGS | LIST_ITEM_TAGS

    for elem in article.find_all(target_tags):
        if has_skip_ancestor(elem):
            continue
        if has_block_descendant(elem):
            continue
        # headerlink (#) 텍스트만 있는 경우 스킵
        text = elem.get_text(strip=True)
        if not text or text == "#" or len(text) < 2:
            continue
        results.append(elem)

    return results


async def translate_batch(
    client: anthropic.AsyncAnthropic, items: list[tuple[Tag, str]]
) -> list[str]:
    """HTML 내용 배치를 번역하여 반환."""
    html_list = [inner_html for _, inner_html in items]
    payload = json.dumps(html_list, ensure_ascii=False)

    response = await client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": payload}],
    )

    raw = response.content[0].text.strip()
    # 마크다운 코드 블록 제거
    raw = re.sub(r"^```(?:json)?\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    translated = json.loads(raw)

    if len(translated) != len(html_list):
        raise ValueError(
            f"번역 결과 개수 불일치: 요청 {len(html_list)}개, 응답 {len(translated)}개"
        )

    return translated


def apply_translation(elem: Tag, new_inner_html: str) -> None:
    """번역된 HTML로 요소 내용 교체."""
    elem.clear()
    fragment = BeautifulSoup(new_inner_html, "html.parser")
    for child in list(fragment.children):
        elem.append(child)


async def translate_file(
    client: anthropic.AsyncAnthropic,
    html_file: Path,
    semaphore: asyncio.Semaphore,
    dry_run: bool = False,
) -> bool:
    """HTML 파일 한 개를 번역. 성공 시 True 반환."""
    try:
        content = html_file.read_text(encoding="utf-8")
        soup = BeautifulSoup(content, "html.parser")

        article = soup.find("article", class_="bd-article")
        if not article:
            return True  # 본문 없는 파일 (index 등) 스킵

        elements = get_translatable_elements(article)
        if not elements:
            return True

        if dry_run:
            print(f"  [DRY] {html_file.name}: {len(elements)}개 요소")
            return True

        # 문자 수 기준으로 배치 분할
        batches: list[list[tuple[Tag, str]]] = []
        current_batch: list[tuple[Tag, str]] = []
        current_chars = 0

        for elem in elements:
            inner = elem.decode_contents()
            if current_chars + len(inner) > MAX_CHARS_PER_BATCH and current_batch:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0
            current_batch.append((elem, inner))
            current_chars += len(inner)

        if current_batch:
            batches.append(current_batch)

        # 번역 실행 (동시 요청 제한 적용)
        for batch in batches:
            async with semaphore:
                translated_list = await translate_batch(client, batch)

            for (elem, _), new_html in zip(batch, translated_list):
                apply_translation(elem, new_html)

        # 페이지 제목도 번역
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            original_title = title_tag.string
            async with semaphore:
                translated_titles = await translate_batch(
                    client, [(title_tag, original_title)]
                )
            title_tag.string = translated_titles[0]

        html_file.write_text(str(soup), encoding="utf-8")
        return True

    except Exception as e:
        print(f"  [ERROR] {html_file.relative_to(DOCS_DIR)}: {e}", file=sys.stderr)
        return False


async def main() -> None:
    parser = argparse.ArgumentParser(description="Isaac Sim 문서 한국어 번역")
    parser.add_argument("--dir", default="", help="번역할 하위 폴더 (예: sensors)")
    parser.add_argument("--limit", type=int, default=0, help="처리할 최대 파일 수")
    parser.add_argument("--dry-run", action="store_true", help="API 호출 없이 대상만 확인")
    parser.add_argument("--concurrency", type=int, default=5, help="동시 API 요청 수")
    parser.add_argument("--reset", action="store_true", help="진행 기록 초기화 후 처음부터")
    args = parser.parse_args()

    client = anthropic.AsyncAnthropic()

    # 진행 기록 로드
    completed: set[str] = set()
    if not args.reset and PROGRESS_FILE.exists():
        completed = set(json.loads(PROGRESS_FILE.read_text()))
        print(f"이미 완료된 파일: {len(completed)}개")

    # 대상 HTML 파일 탐색
    search_root = DOCS_DIR / args.dir if args.dir else DOCS_DIR
    html_files = sorted(
        f
        for f in search_root.rglob("*.html")
        if f.relative_to(DOCS_DIR).parts[0] not in SKIP_DIRS
        and str(f.relative_to(DOCS_DIR)) not in completed
    )

    if args.limit:
        html_files = html_files[: args.limit]

    total = len(html_files)
    if total == 0:
        print("번역할 파일이 없습니다.")
        return

    print(f"번역 대상: {total}개 파일")

    semaphore = asyncio.Semaphore(args.concurrency)
    done = 0
    success = 0

    async def process(f: Path) -> None:
        nonlocal done, success
        rel = str(f.relative_to(DOCS_DIR))
        ok = await translate_file(client, f, semaphore, args.dry_run)
        done += 1
        if ok and not args.dry_run:
            completed.add(rel)
            success += 1
        status = "OK" if ok else "FAIL"
        print(f"[{done}/{total}] [{status}] {rel}")

        # 10개마다 진행 저장
        if done % 10 == 0 and not args.dry_run:
            PROGRESS_FILE.write_text(json.dumps(sorted(completed), ensure_ascii=False))

    await asyncio.gather(*[process(f) for f in html_files])

    if not args.dry_run:
        PROGRESS_FILE.write_text(json.dumps(sorted(completed), ensure_ascii=False))
        print(f"\n완료: {success}/{total}개 파일 번역 성공")


if __name__ == "__main__":
    asyncio.run(main())
