"""BM25Okapi 应用层打分（ADR-0013 §5，规格 §6）。"""

from __future__ import annotations

from memhub.kb.bm25 import BM25Okapi, tokenize


def test_tokenize_follows_query_terms_rule() -> None:
    """照搬 `query._terms`：空白切分 + 小写；CJK ≥4 字的段补相邻二元组。"""
    assert tokenize("HTTPX trust_env") == ["httpx", "trust_env"]
    # 「代理失败」4 个 CJK 字符 → 额外产出 3 个相邻二元组
    assert tokenize("代理失败") == ["代理失败", "代理", "理失", "失败"]
    # 不足 4 个 CJK 字符不补二元组
    assert tokenize("重试") == ["重试"]
    # 混合串：判定看 **CJK 字符数**，达标后对整段 token 补二元组
    assert tokenize("abc重试def") == ["abc重试def"]  # 仅 2 个 CJK 字符
    assert tokenize("abc重试def重试") == [
        "abc重试def重试",
        "ab",
        "bc",
        "c重",
        "重试",
        "试d",
        "de",
        "ef",
        "f重",
        "重试",
    ]


def test_tokenize_matches_legacy_terms_exactly() -> None:
    """与 `query._terms` 逐字对齐：切换实现不得改变召回面（规格 §6）。"""
    from memhub.kb.query import _terms

    for text in [
        "HTTPX trust_env",
        "代理失败",
        "重试退避",
        "abc重试def重试",
        "abcd重试",
        "Proxy 502 排查",
        "  ",
    ]:
        assert tokenize(text, dedupe=True) == _terms(text), text


def test_tokenize_dedupes_nothing_for_documents() -> None:
    """文档侧保留词频；去重只发生在查询侧。"""
    assert tokenize("proxy proxy") == ["proxy", "proxy"]


def test_ranks_exact_document_above_partial() -> None:
    docs = [
        ["proxy", "502", "trust_env"],
        ["proxy", "站", "放大", "故障"],
        ["unrelated"],
    ]
    index = BM25Okapi(docs)
    scores = index.get_scores(["proxy", "502"])
    assert scores[0] > scores[1] > 0
    assert scores[2] == 0


def test_scores_are_reproducible_and_order_stable() -> None:
    docs = [tokenize("代理 502 排查"), tokenize("代理配置"), tokenize("无关内容")]
    first = BM25Okapi(docs).get_scores(tokenize("代理 502"))
    second = BM25Okapi(docs).get_scores(tokenize("代理 502"))
    assert first == second


def test_empty_query_scores_zero() -> None:
    index = BM25Okapi([tokenize("代理 502")])
    assert index.get_scores([]) == [0.0]
