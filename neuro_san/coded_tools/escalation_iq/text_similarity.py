import math
import re
from typing import Dict
from typing import List
from typing import Pattern
from typing import Set
from typing import Tuple


class TextSimilarity:
    """
    Dependency-free TF-IDF cosine similarity used to find comparable historical cases.
    It stands in for a vector database (FAISS/Chroma) so the demo needs no extra installs.
    """

    WORD_PATTERN: Pattern[str] = re.compile(r"[a-z0-9]+")
    STOPWORDS: Set[str] = {
        "the", "and", "for", "with", "that", "this", "from", "have", "has", "was", "were", "are", "but",
        "not", "his", "her", "their", "they", "them", "she", "him", "our", "out", "all", "can", "cannot",
        "after", "before", "because", "since", "about", "into", "over", "than", "then", "also", "been",
        "being", "which", "while", "when", "what", "who", "its", "any", "more", "most", "some", "same",
        "very", "keeps", "says", "said", "still", "again", "customer", "client",
    }

    @staticmethod
    def stem(token: str) -> str:
        """
        Applies a light suffix-stripping stemmer.

        :param token: A lowercase word.
        :return: The stemmed word.
        """
        if token.endswith("ies") and len(token) > 4:
            return token[:-3] + "y"
        if token.endswith("ing") and len(token) > 5:
            return token[:-3]
        if token.endswith("ed") and len(token) > 4:
            return token[:-2]
        if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
            return token[:-1]
        return token

    @staticmethod
    def tokenize(text: str) -> List[str]:
        """
        Splits text into stemmed, stopword-free tokens.

        :param text: The raw text.
        :return: The ordered token list.
        """
        tokens: List[str] = []
        word: str
        # Keep meaningful words only
        for word in TextSimilarity.WORD_PATTERN.findall(text.lower()):
            if len(word) < 3 or word in TextSimilarity.STOPWORDS:
                continue
            tokens.append(TextSimilarity.stem(word))
        return tokens

    @staticmethod
    def rank(query: str, documents: List[str]) -> List[Tuple[int, float]]:
        """
        Scores every document against the query.

        :param query: The query text.
        :param documents: The candidate document texts.
        :return: (document index, cosine similarity) pairs, best first, zero scores omitted.
        """
        doc_tokens: List[List[str]] = []
        document_frequency: Dict[str, int] = {}
        document: str
        # Tokenize each document and count how many documents contain each token
        for document in documents:
            tokens: List[str] = TextSimilarity.tokenize(document)
            doc_tokens.append(tokens)
            token: str
            for token in set(tokens):
                document_frequency[token] = document_frequency.get(token, 0) + 1

        total: int = len(documents)
        query_vector: Dict[str, float] = TextSimilarity.vectorize(
            TextSimilarity.tokenize(query), document_frequency, total)
        query_norm: float = TextSimilarity.norm(query_vector)
        if query_norm == 0.0:
            return []

        scored: List[Tuple[int, float]] = []
        index: int
        # Cosine similarity of each document vector with the query vector
        for index in range(total):
            vector: Dict[str, float] = TextSimilarity.vectorize(doc_tokens[index], document_frequency, total)
            doc_norm: float = TextSimilarity.norm(vector)
            if doc_norm == 0.0:
                continue
            dot: float = 0.0
            term: str
            for term in query_vector:
                dot = dot + query_vector.get(term, 0.0) * vector.get(term, 0.0)
            similarity: float = dot / (query_norm * doc_norm)
            if similarity > 0.0:
                scored.append((index, round(similarity, 4)))
        scored.sort(key=TextSimilarity.score_of, reverse=True)
        return scored

    @staticmethod
    def vectorize(tokens: List[str], document_frequency: Dict[str, int], total: int) -> Dict[str, float]:
        """
        Builds a TF-IDF vector with sublinear term frequency and smoothed inverse document frequency.

        :param tokens: The document tokens.
        :param document_frequency: Number of documents containing each token.
        :param total: Number of documents.
        :return: The sparse vector.
        """
        counts: Dict[str, int] = {}
        token: str
        # Count each token occurrence
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        vector: Dict[str, float] = {}
        term: str
        # Weight each term by tf * idf
        for term in counts:
            idf: float = math.log((total + 1.0) / (document_frequency.get(term, 0) + 1.0)) + 1.0
            vector[term] = (1.0 + math.log(counts.get(term, 1))) * idf
        return vector

    @staticmethod
    def norm(vector: Dict[str, float]) -> float:
        """
        Computes the Euclidean norm of a sparse vector.

        :param vector: The sparse vector.
        :return: The norm.
        """
        total: float = 0.0
        value: float
        # Sum the squares of all weights
        for value in vector.values():
            total = total + value * value
        return math.sqrt(total)

    @staticmethod
    def score_of(pair: Tuple[int, float]) -> float:
        """
        Sort key returning the similarity of an (index, score) pair.

        :param pair: The (index, score) pair.
        :return: The score.
        """
        return pair[1]
