import math
from heapq import nlargest
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Sequence, Tuple


class BM25Index:
    def __init__(self, corpus_tokens: Sequence[Sequence[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_count = len(corpus_tokens)
        self.avg_doc_len = 0.0
        self.doc_lens: List[int] = []
        self.term_freqs: List[Dict[str, int]] = []
        self.idf: Dict[str, float] = {}

        if not corpus_tokens:
            return

        doc_freq: Dict[str, int] = defaultdict(int)
        total_len = 0

        for tokens in corpus_tokens:
            freq = Counter(tokens)
            self.term_freqs.append(dict(freq))
            doc_len = len(tokens)
            self.doc_lens.append(doc_len)
            total_len += doc_len

            for term in freq:
                doc_freq[term] += 1

        self.avg_doc_len = total_len / float(self.doc_count)
        for term, n_qi in doc_freq.items():
            self.idf[term] = math.log(1.0 + (self.doc_count - n_qi + 0.5) / (n_qi + 0.5))

    def score(self, query_tokens: Iterable[str]) -> List[float]:
        if self.doc_count == 0:
            return []

        q_terms = list(query_tokens)
        if not q_terms:
            return [0.0] * self.doc_count

        scores = [0.0] * self.doc_count
        for idx in range(self.doc_count):
            doc_tf = self.term_freqs[idx]
            doc_len = self.doc_lens[idx]
            denom_norm = self.k1 * (1 - self.b + self.b * (doc_len / self.avg_doc_len))
            total = 0.0

            for term in q_terms:
                tf = doc_tf.get(term, 0)
                if tf == 0:
                    continue
                idf = self.idf.get(term, 0.0)
                total += idf * (tf * (self.k1 + 1)) / (tf + denom_norm)

            scores[idx] = total
        return scores

    def top_k(self, query_tokens: Iterable[str], k: int) -> List[Tuple[int, float]]:
        scores = self.score(query_tokens)
        if not scores:
            return []
        ranked = nlargest(max(0, k), enumerate(scores), key=lambda item: item[1])
        return [(idx, score) for idx, score in ranked if score > 0.0]
