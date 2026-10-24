from datetime import date
from datetime import datetime
from datetime import timedelta
from logging import getLogger
from logging import Logger
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple

from neuro_san.interfaces.coded_tool import CodedTool
from typing_extensions import override

from neuro_san.coded_tools.escalation_iq.arg_reader import ArgReader
from neuro_san.coded_tools.escalation_iq.evidence_ledger import EvidenceLedger
from neuro_san.coded_tools.escalation_iq.pack_repository import PackRepository
from neuro_san.coded_tools.escalation_iq.text_similarity import TextSimilarity


class SimilarCaseSearch(CodedTool):
    """
    Finds comparable historical cases with TF-IDF similarity, summarizes how each past resolution
    performed, measures how often similar cases were escalated, and detects recurrence (a cluster of
    similar recent cases) that signals a systemic problem.
    """

    OUTCOME_SUCCESS: Dict[str, float] = {
        "resolved": 1.0, "escalated_resolved": 0.7, "reopened": 0.2, "failed": 0.0
    }
    RELATED_THRESHOLD: float = 0.1
    CATEGORY_BONUS: float = 0.08
    POOL_SIZE: int = 10

    @override
    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> str:
        """
        Searches the pack's history for the registered case.

        :param args: Optional "query" (defaults to the case description) and "top_k" (default 5, max 8).
        :param sly_data: Provides the case; receives the "similar" evidence and the recurrence count.
        :return: A text summary of similar cases, resolution performance and recurrence.
        """
        logger: Logger = getLogger(self.__class__.__name__)
        case: Dict[str, Any] = EvidenceLedger.get_case(sly_data)
        if not case:
            return "Error: no case registered. Call case_intake first."
        domain: str = str(case.get("domain"))
        try:
            config: Dict[str, Any] = PackRepository.load_config(domain)
            history: List[Dict[str, str]] = PackRepository.load_history(domain)
        except (OSError, ValueError) as exc:
            logger.error("Cannot load domain pack %s: %s", domain, exc)
            return f"Error: cannot load domain pack: {exc}"
        if not history:
            return "No historical cases are available for this domain."

        query: str = str(args.get("query") or case.get("description"))
        top_k: int = min(8, max(1, ArgReader.to_int(args.get("top_k"), 5)))
        category: str = str(case.get("category") or "")

        documents: List[str] = []
        row: Dict[str, str]
        # Build the searchable text of each historical case
        for row in history:
            documents.append(f"{row.get('description', '')} {str(row.get('category', '')).replace('_', ' ')}")
        ranked: List[Tuple[int, float]] = TextSimilarity.rank(query, documents)

        pool: List[Dict[str, Any]] = []
        index: int
        similarity: float
        # Keep related cases, with a small bonus for the same category
        for index, similarity in ranked:
            if similarity < self.RELATED_THRESHOLD:
                continue
            item: Dict[str, Any] = self.to_item(history[index], similarity)
            item["rank_score"] = similarity + (self.CATEGORY_BONUS if item.get("category") == category else 0.0)
            pool.append(item)
        pool.sort(key=self.rank_of, reverse=True)
        pool = pool[:self.POOL_SIZE]

        latest: date = self.latest_date(history)
        recurrence: Dict[str, Any] = config.get("recurrence", {})
        window_days: int = int(recurrence.get("window_days", 30))
        strong_threshold: float = float(recurrence.get("similarity_threshold", 0.14))
        systemic_threshold: int = int(recurrence.get("systemic_threshold", 3))
        cutoff: date = latest - timedelta(days=window_days)

        strong_recent: List[Dict[str, Any]] = []
        entry: Dict[str, Any]
        # Recurrence counts strong, recent matches in the same category
        for entry in pool:
            same_category: bool = (not category) or entry.get("category") == category
            if same_category and float(entry.get("similarity", 0.0)) >= strong_threshold:
                if self.parse_date(str(entry.get("date"))) >= cutoff:
                    strong_recent.append(entry)
        repeat_count: int = len(strong_recent)
        systemic: bool = repeat_count >= systemic_threshold

        stats: Dict[str, Dict[str, Any]] = self.resolution_stats(pool)
        escalation_rate: float = self.weighted_escalation_rate(pool)
        EvidenceLedger.update_case(sly_data, {"repeat_similar_count": repeat_count})

        evidence: Dict[str, Any] = {
            "top_cases": pool[:top_k], "pool_size": len(pool), "resolution_stats": stats,
            "escalation_rate": escalation_rate, "repeat_similar_count": repeat_count, "systemic": systemic,
            "window_days": window_days, "latest_history_date": latest.isoformat(),
            "avg_hours_not_escalated": self.average_hours(pool, "no"),
            "avg_hours_escalated": self.average_hours(pool, "yes"),
        }
        EvidenceLedger.record(sly_data, "similar", evidence)
        logger.info("Found %s related cases, %s recurring", len(pool), repeat_count)

        if not pool:
            return "SIMILAR CASES: none found above the similarity threshold. Treat this as a novel case."
        lines: List[str] = [f"SIMILAR HISTORICAL CASES (top {min(top_k, len(pool))} of {len(pool)} related)"]
        for entry in pool[:top_k]:
            lines.append(
                f"- {entry.get('case_id')} ({entry.get('date')}, sim {entry.get('similarity')}): "
                f"{entry.get('description')} -> {entry.get('resolution')} => {entry.get('outcome')}, "
                f"escalated: {entry.get('escalated')}"
                + (f" to {entry.get('escalated_to')}" if entry.get("escalated_to") else "")
                + f", {entry.get('hours_to_resolve')}h, satisfaction {entry.get('satisfaction')}/5"
            )
        lines.append("Resolution performance (similarity-weighted success, 1.0 = always resolved cleanly):")
        resolution: str
        # One line per past resolution
        for resolution in stats:
            lines.append(
                f"- {resolution}: success {stats.get(resolution, {}).get('success')} "
                f"over {stats.get(resolution, {}).get('support')} case(s)"
            )
        lines.append(f"Historical escalation rate among similar cases: {round(escalation_rate * 100)}%")
        lines.append(
            f"RECURRENCE: {repeat_count} similar case(s) in the same category within {window_days} days "
            f"before {latest.isoformat()}. Systemic pattern: {'YES' if systemic else 'no'}"
        )
        return "\n".join(lines)

    @staticmethod
    def to_item(row: Dict[str, str], similarity: float) -> Dict[str, Any]:
        """
        Converts a CSV row to a result item.

        :param row: The history row.
        :param similarity: The cosine similarity to the query.
        :return: The result item.
        """
        return {
            "case_id": row.get("case_id"), "date": row.get("date"), "category": row.get("category"),
            "description": row.get("description"), "resolution": row.get("resolution"),
            "outcome": row.get("outcome"), "escalated": row.get("escalated"),
            "escalated_to": row.get("escalated_to"), "hours_to_resolve": row.get("hours_to_resolve"),
            "satisfaction": row.get("satisfaction"), "similarity": round(similarity, 2),
        }

    @staticmethod
    def rank_of(item: Dict[str, Any]) -> float:
        """
        Sort key for result items.

        :param item: A result item.
        :return: The rank score including the category bonus.
        """
        return float(item.get("rank_score", 0.0))

    @staticmethod
    def parse_date(text: str) -> date:
        """
        Parses a YYYY-MM-DD date.

        :param text: The date text.
        :return: The date, or date.min when the text is malformed.
        """
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return date.min

    @staticmethod
    def latest_date(history: List[Dict[str, str]]) -> date:
        """
        Finds the most recent case date, used as the reference "today" of the synthetic history.

        :param history: The history rows.
        :return: The latest date.
        """
        latest: date = date.min
        row: Dict[str, str]
        # Track the maximum date
        for row in history:
            parsed: date = SimilarCaseSearch.parse_date(str(row.get("date")))
            if parsed > latest:
                latest = parsed
        return latest

    @staticmethod
    def resolution_stats(pool: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        Computes similarity-weighted success per past resolution.

        :param pool: The related cases.
        :return: A dictionary resolution -> {"success", "support"}.
        """
        weights: Dict[str, float] = {}
        successes: Dict[str, float] = {}
        support: Dict[str, int] = {}
        item: Dict[str, Any]
        # Accumulate weighted outcomes per resolution
        for item in pool:
            name: str = str(item.get("resolution"))
            weight: float = float(item.get("similarity", 0.0))
            outcome: float = SimilarCaseSearch.OUTCOME_SUCCESS.get(str(item.get("outcome")), 0.5)
            weights[name] = weights.get(name, 0.0) + weight
            successes[name] = successes.get(name, 0.0) + weight * outcome
            support[name] = support.get(name, 0) + 1
        result: Dict[str, Dict[str, Any]] = {}
        key: str
        # Normalize to a 0-1 success value
        for key in weights:
            total: float = weights.get(key, 0.0)
            result[key] = {"success": round(successes.get(key, 0.0) / total, 2) if total else 0.0,
                           "support": support.get(key, 0)}
        return result

    @staticmethod
    def weighted_escalation_rate(pool: List[Dict[str, Any]]) -> float:
        """
        Computes the similarity-weighted share of related cases that were escalated.

        :param pool: The related cases.
        :return: A value between 0 and 1.
        """
        total: float = 0.0
        escalated: float = 0.0
        item: Dict[str, Any]
        # Weight each case by its similarity
        for item in pool:
            weight: float = float(item.get("similarity", 0.0))
            total = total + weight
            if item.get("escalated") == "yes":
                escalated = escalated + weight
        return round(escalated / total, 2) if total else 0.0

    @staticmethod
    def average_hours(pool: List[Dict[str, Any]], escalated: str) -> float:
        """
        Averages time to resolve for escalated or non-escalated related cases.

        :param pool: The related cases.
        :param escalated: "yes" or "no".
        :return: The average hours, 0.0 when there are no such cases.
        """
        values: List[float] = []
        item: Dict[str, Any]
        # Collect the hours of matching cases
        for item in pool:
            if item.get("escalated") == escalated:
                values.append(ArgReader.to_float(item.get("hours_to_resolve"), 0.0))
        return round(sum(values) / len(values), 1) if values else 0.0
