"""Tìm kiếm tiếng Việt không dấu bằng BM25 (không cần thư viện ngoài).

Từ tiếng Việt thường gồm 2 âm tiết ("chấm công", "nghỉ phép") nên ngoài từng âm tiết còn
đánh chỉ mục cả cặp âm tiết liền nhau; câu hỏi khớp đúng cụm thì được điểm cao hơn.
"""
import math
import re
import unicodedata

# âm tiết hay gặp trong câu hỏi nhưng không giúp phân biệt chủ đề (đã bỏ dấu)
#   (không đưa vào: "làm", "ra", "vào", "lại", "máy", "qua"... vì là một nửa của cụm có nghĩa)
STOPWORDS = set("""
a ah ak ha anh chi em ban toi minh tui ta chung ho no ai
la thi ma va voi cua cho o tai tu
co khong chua da dang se duoc bi can phai nen muon hay hoac
gi nao sao the nhu nay kia do day vay roi nhe nha
cach bao nhieu khi luc
cai nhung cac mot it rat
giup huong dan xem biet hoi
""".split())


def strip_accents(text):
    """'Nghỉ phép' -> 'nghi phep' (cả chữ đ)."""
    text = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def words(text):
    """Âm tiết đã bỏ dấu, giữ cả từ dừng (dùng để dò cụm từ)."""
    return re.findall(r"[a-z0-9]+", strip_accents(text))


def terms(text):
    """Âm tiết + cặp âm tiết liền nhau, bỏ từ dừng."""
    ws = [w for w in words(text) if w not in STOPWORDS]
    return ws + [f"{a} {b}" for a, b in zip(ws, ws[1:])]


def contains_phrase(text_words, phrase_words):
    """Cụm phrase_words có nằm liền trong text_words không."""
    n = len(phrase_words)
    return n > 0 and any(text_words[i:i + n] == phrase_words for i in range(len(text_words) - n + 1))


class Index:
    """Chỉ mục BM25. docs: [(key, [(văn bản, trọng số), ...])]; trọng số nhân số lần xuất hiện."""

    K1, B = 1.2, 0.75

    def __init__(self, docs):
        self.keys, self.tf, self.lengths = [], [], []
        df = {}
        for key, fields in docs:
            counts = {}
            for text, weight in fields:
                for t in terms(text):
                    counts[t] = counts.get(t, 0) + weight
            self.keys.append(key)
            self.tf.append(counts)
            self.lengths.append(sum(counts.values()) or 1)
            for t in counts:
                df[t] = df.get(t, 0) + 1
        n = len(self.keys) or 1
        self.avg = sum(self.lengths) / n
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def coverage(self, query, key):
        """Tỉ lệ âm tiết (không tính từ dừng) của câu hỏi có mặt trong tài liệu `key`."""
        q = [t for t in terms(query) if " " not in t]
        if not q:
            return 0.0
        counts = self.tf[self.keys.index(key)]
        return sum(1 for t in q if t in counts) / len(q)

    def search(self, query, limit=5, allowed=None):
        """[(key, điểm)] giảm dần; allowed: tập key được phép (None = tất cả)."""
        q = terms(query)
        out = []
        for key, counts, length in zip(self.keys, self.tf, self.lengths):
            if allowed is not None and key not in allowed:
                continue
            score = 0.0
            for t in q:
                f = counts.get(t)
                if f:
                    bonus = 1.5 if " " in t else 1.0  # khớp cả cụm hai âm tiết
                    score += bonus * self.idf[t] * f * (self.K1 + 1) / (
                        f + self.K1 * (1 - self.B + self.B * length / self.avg))
            if score > 0:
                out.append((key, round(score, 3)))
        out.sort(key=lambda x: -x[1])
        return out[:limit]
