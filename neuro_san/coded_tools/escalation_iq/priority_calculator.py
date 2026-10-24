from logging import getLogger
from logging import Logger
from typing import Any
from typing import Dict
from typing import List

from neuro_san.interfaces.coded_tool import CodedTool
from typing_extensions import override

from neuro_san.coded_tools.escalation_iq.arg_reader import ArgReader
from neuro_san.coded_tools.escalation_iq.evidence_ledger import EvidenceLedger
from neuro_san.coded_tools.escalation_iq.pack_repository import PackRepository
from neuro_san.coded_tools.escalation_iq.rule_evaluator import RuleEvaluator


class PriorityCalculator(CodedTool):
    """
    Validates the classifier's category and severity against the pack, then derives the priority
    (P1-P4) from severity points plus data-driven impact rules, and starts the SLA clock.
    """

    @override
    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> str:
        """
        Computes priority and SLA position.

        :param args: "category", "severity" and optional "business_area" chosen by the classifier.
        :param sly_data: Provides the case; receives the "classification" evidence and derived facts.
        :return: A text summary with the point breakdown, priority and SLA status.
        """
        logger: Logger = getLogger(self.__class__.__name__)
        case: Dict[str, Any] = EvidenceLedger.get_case(sly_data)
        if not case:
            return "Error: no case registered. Call case_intake first."
        try:
            config: Dict[str, Any] = PackRepository.load_config(str(case.get("domain")))
        except (OSError, ValueError) as exc:
            logger.error("Cannot load domain pack: %s", exc)
            return f"Error: cannot load domain pack: {exc}"

        categories: Dict[str, Any] = config.get("taxonomy", {}).get("categories", {})
        warnings: List[str] = []
        category: str = ArgReader.to_token(args.get("category"))
        if category not in categories:
            guessed: str = self.guess_category(str(case.get("description")), categories)
            warnings.append(f"Category '{category}' is not in the taxonomy; using '{guessed}'.")
            category = guessed
        entry: Dict[str, Any] = categories.get(category, {})
        business_area: str = str(entry.get("business_area") or args.get("business_area") or "General")

        severity_points: Dict[str, int] = config.get("priority", {}).get("severity_points", {})
        severity: str = ArgReader.to_choice(args.get("severity"), list(severity_points.keys()), "medium")
        if ArgReader.to_token(args.get("severity")) != severity:
            warnings.append("Severity was missing or invalid; assumed medium.")

        facts: Dict[str, Any] = dict(case)
        facts["category"] = category
        facts["severity"] = severity
        facts["regulated"] = bool(case.get("regulated")) or bool(entry.get("regulated"))

        breakdown: List[str] = [f"severity {severity}: +{severity_points.get(severity, 2)}"]
        points: int = int(severity_points.get(severity, 2))
        rule: Dict[str, Any]
        # Add the points of every impact rule that matches the case facts
        for rule in config.get("priority", {}).get("impact_rules", []):
            if RuleEvaluator.evaluate_rule(rule, facts):
                points = points + int(rule.get("points", 0))
                breakdown.append(f"{rule.get('label')}: +{rule.get('points')}")

        thresholds: Dict[str, int] = config.get("priority", {}).get("thresholds", {})
        priority: str = "P4"
        if points >= int(thresholds.get("P1", 7)):
            priority = "P1"
        elif points >= int(thresholds.get("P2", 5)):
            priority = "P2"
        elif points >= int(thresholds.get("P3", 3)):
            priority = "P3"

        sla_hours: float = float(config.get("sla_hours", {}).get(priority, 24))
        hours_open: float = float(case.get("hours_open", 0.0))
        sla_pct: float = round(hours_open / sla_hours * 100.0, 1) if sla_hours > 0 else 0.0
        remaining: float = round(sla_hours - hours_open, 1)

        derived: Dict[str, Any] = {
            "category": category, "severity": severity, "business_area": business_area,
            "regulated": facts.get("regulated"), "priority": priority, "priority_points": points,
            "sla_hours": sla_hours, "sla_pct": sla_pct, "sla_hours_remaining": remaining,
        }
        EvidenceLedger.update_case(sly_data, derived)
        evidence: Dict[str, Any] = dict(derived)
        evidence["breakdown"] = breakdown
        evidence["warnings"] = warnings
        evidence["owning_team"] = entry.get("team") or config.get("default_team")
        EvidenceLedger.record(sly_data, "classification", evidence)
        logger.info("Classified as %s / %s / %s", category, severity, priority)

        sla_status: str = f"{remaining} hours remaining" if remaining >= 0 else f"BREACHED by {abs(remaining)} hours"
        lines: List[str] = [
            "CLASSIFICATION AND PRIORITY (deterministic)",
            f"Category: {category} | Business area: {business_area} | Owning team: {evidence.get('owning_team')}",
            f"Severity: {severity} | Regulated: {facts.get('regulated')}",
            f"Priority points: {points} ({'; '.join(breakdown)})",
            f"PRIORITY: {priority} | SLA {sla_hours} hours, {hours_open} open ({sla_pct}% used), {sla_status}",
        ]
        lines.extend(warnings)
        return "\n".join(lines)

    @staticmethod
    def guess_category(description: str, categories: Dict[str, Any]) -> str:
        """
        Picks the category whose keywords appear most often in the description.

        :param description: The case description.
        :param categories: The taxonomy categories.
        :return: The best matching category name, or "unclassified" when nothing matches.
        """
        text: str = description.lower()
        best: str = "unclassified"
        best_hits: int = 0
        name: str
        # Count keyword hits per category
        for name in categories:
            hits: int = 0
            keyword: str
            for keyword in categories.get(name, {}).get("keywords", []):
                if str(keyword).lower() in text:
                    hits = hits + 1
            if hits > best_hits:
                best_hits = hits
                best = name
        return best
