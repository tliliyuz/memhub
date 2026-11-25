"""应用层 BM25Okapi 打分（ADR-0013 §5，规格 §6）。

不引入第三方 BM25 库：`rank-bm25` 停更于 2022 年且拖入 numpy（离线 wheelhouse
体积），而 Okapi 本体只有几十行。分词规则**原样照搬** `query._terms`
（空白切分 + 小写；CJK 连续字符 ≥4 个才补相邻二元组），改阈值会改变召回面。

打分只做排序，不对外暴露原始分；对外 `score` 仍归一化到 0–1（见 `query.search`）。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence

# BM25Okapi 的经验参数（与 ElKassas/rank-bm25 默认一致）。
K1 = 1.5
B = 0.75
_CJK = ("一", "鿿")


def _cjk_len(token: str) -> int:
    return sum(1 for char in token if _CJK[0] <= char <= _CJK[1])


def tokenize(text: str, *, dedupe: bool = False) -> list[str]:
    """与 `query._terms` 同口径的分词；`dedupe=True` 用于查询侧。"""
    terms: list[str] = []
    for token in re.split(r"\s+", text.strip().lower()):
        if not token:
            continue
        terms.append(token)
        if _cjk_len(token) >= 4:
            terms.extend(token[index : index + 2] for index in range(len(token) - 1))
    return list(dict.fromkeys(terms)) if dedupe else terms


class BM25Okapi:
    """对一个候选集做 BM25 打分；候选集由调用方按授权/库/kind/tier 过滤后给出。"""

    def __init__(self, corpus: Sequence[Sequence[str]]) -> None:
        self.corpus = [list(document) for document in corpus]
        self.lengths = [len(document) for document in self.corpus]
        self.average = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        self.frequencies = [Counter(document) for document in self.corpus]
        document_frequency: Counter[str] = Counter()
        for document in self.corpus:
            document_frequency.update(set(document))
        total = len(self.corpus)
        # 出现在全部文档的词 idf 为负，会倒扣分数；夹到极小的正数下限。
        self.idf = {
            term: max(math.log(1 + (total - freq + 0.5) / (freq + 0.5)), 1e-9)
            for term, freq in document_frequency.items()
        }

    def get_scores(self, query: Iterable[str]) -> list[float]:
        terms = list(query)
        scores: list[float] = []
        for frequency, length in zip(self.frequencies, self.lengths, strict=True):
            score = 0.0
            for term in terms:
                tf = frequency.get(term, 0)
                if not tf:
                    continue
                denominator = tf + K1 * (1 - B + B * (length / self.average if self.average else 0))
                score += self.idf.get(term, 0.0) * tf * (K1 + 1) / denominator
            scores.append(score)
        return scores


def normalize(raw: float, *, ceiling: float) -> float:
    """把 BM25 原始分单调映射到 0–1；`ceiling` 是本次候选集的最高分。

    契约只要求「单调、稳定、0–1」，不承诺与旧 `raw/(raw+5)` 同值（规格 §6）。
    最高分固定映射到 0.99，避免 1.0 让调用方误以为是精确匹配。
    """
    if raw <= 0 or ceiling <= 0:
        return 0.0
    return round(min(0.99, raw / ceiling * 0.99), 3)
