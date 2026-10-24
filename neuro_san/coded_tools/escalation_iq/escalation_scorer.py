from logging import getLogger
from logging import Logger
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from neuro_san.interfaces.coded_tool import CodedTool
from typing_extensions import override

from neuro_san.coded_tools.escalation_iq.evidence_ledger import EvidenceLedger
from neuro_san.coded_tools.escalation_iq.pack_repository import PackRepository


class EscalationScorer(CodedTool):
    """
    Produces the explainable escalation decision: a 0-100 score built from named factors, a gated
    decision band, the target team, a confidence level, the pivotal factors that would flip the
    decision, and a comparison with the previous run of the same case (for what-if analysis).
    """

    REQUIRED_EVIDENCE: List[str] = ["classification", "similar", "playbook", "policy"]

    DEFAULT_SCORING: Dict[str, Any] = {
        "priority_points": {"P1": 25, "P2": 15, "P3": 8, "P4": 0},
        "sla_points": [{"min": 100, "points": 15}, {"min": 75, "points": 10}, {"min": 50, "points": 5}],
        "prior_contact_points": [{"min": 3, "points": 8}, {"min": 2, "points": 4}],
        "recurrence_points": [{"min": 5, "points": 10}, {"min": 3, "points": 6}, {"min": 1, "points": 2}],
        "value_points": [{"min": 10000, "points": 8}, {"min": 1000, "points": 4}],
        "frustration_points": {"high": 6, "medium": 2, "low": 0},
        "weak_resolution_points": 8,
        "strong_resolution_credit": -8,
        "authority_exceeded_points": 8,
        "high_escalation_rate_points": 6,
        "policy_weight_scale": 0.5,
        "policy_weight_cap": 20,
        "thresholds": {"monitor": 30, "escalate": 50, "urgent": 80},
    }

    @override
    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> str:
        """
        Computes the escalation decision.

        :param args: Optional "context_note": analyst note recorded in the audit trail.
        :param sly_data: Provides all evidence; receives the "escalation" evidence.
        :return: A text decision with factor breakdown, target, confidence and pivotal factors.
        """
        logger: Logger = getLogger(self.__class__.__name__)
        missing: List[str] = []
        name: str
        # Every specialist tool must have published its evidence first
        for name in self.REQUIRED_EVIDENCE:
            if EvidenceLedger.fetch(sly_data, name) is None:
                missing.append(name)
        if missing:
            return "DECISION BLOCKED. Missing evidence: " + ", ".join(missing) + ". Run those tools first."

        case: Dict[str, Any] = EvidenceLedger.get_case(sly_data)
        try:
            config: Dict[str, Any] = PackRepository.load_config(str(case.get("domain")))
        except (OSError, ValueError) as exc:
            logger.error("Cannot load domain pack: %s", exc)
            return f"Error: cannot load domain pack: {exc}"

        scoring: Dict[str, Any] = dict(self.DEFAULT_SCORING)
        scoring.update(config.get("scoring", {}))
        thresholds: Dict[str, int] = scoring.get("thresholds", {})

        classification: Dict[str, Any] = EvidenceLedger.fetch(sly_data, "classification")
        similar: Dict[str, Any] = EvidenceLedger.fetch(sly_data, "similar")
        playbook: Dict[str, Any] = EvidenceLedger.fetch(sly_data, "playbook")
        policy: Dict[str, Any] = EvidenceLedger.fetch(sly_data, "policy")

        factors: List[Dict[str, Any]] = self.build_factors(case, similar, playbook, policy, scoring)
        score: int = 0
        factor: Dict[str, Any]
        # Add up the signed points of all factors
        for factor in factors:
            score = score + int(factor.get("points", 0))
        score = min(100, max(0, score))

        mandatory_rules: List[Dict[str, Any]] = []
        rule: Dict[str, Any]
        # Collect the mandatory rules that triggered
        for rule in policy.get("triggered", []):
            if rule.get("mandatory"):
                mandatory_rules.append(rule)
        forced: bool = bool(mandatory_rules)
        if forced:
            score = max(score, int(thresholds.get("escalate", 55)))

        decision: str = self.band(score, forced, str(case.get("priority")), thresholds)
        target, level, also_notify = self.choose_target(decision, policy, classification, config)

        pivotal: List[str] = self.pivotal_factors(factors, score, forced, str(case.get("priority")), thresholds, decision)
        confidence: str = self.confidence(case, similar, score, thresholds)

        evidence: Dict[str, Any] = {
            "decision": decision, "score": score, "confidence": confidence, "target_team": target,
            "target_level": level, "also_notify": also_notify, "forced_by_mandatory_rule": forced,
            "factors": factors, "pivotal_factors": pivotal, "context_note": str(args.get("context_note") or ""),
            "priority": case.get("priority"), "category": case.get("category"),
            "best_resolution": playbook.get("best"), "systemic": similar.get("systemic"),
            "sla_pct": case.get("sla_pct"),
        }
        previous: Optional[Dict[str, Any]] = sly_data.get(EvidenceLedger.PREVIOUS_KEY)
        EvidenceLedger.record(sly_data, "escalation", evidence)
        logger.info("Decision %s (%s)", decision, score)

        lines: List[str] = [
            f"ESCALATION DECISION: {decision}",
            f"Escalation score: {score}/100 | Confidence: {confidence} | Priority: {case.get('priority')}",
            f"Route to: {target} ({level})" + (f" | also notify: {', '.join(also_notify)}" if also_notify else ""),
        ]
        if forced:
            lines.append("Forced by mandatory policy: " + "; ".join(self.rule_labels(mandatory_rules)))
        lines.append("Score breakdown:")
        # One line per factor that contributed points
        for factor in factors:
            if int(factor.get("points", 0)) != 0:
                lines.append(f"- {factor.get('points'):+d}: {factor.get('label')} ({factor.get('detail')})")
        lines.append("Pivotal factors (removing any one would change the decision): "
                     + ("; ".join(pivotal) if pivotal else "none, the decision is stable"))
        if previous is not None:
            lines.append(self.compare_with_previous(previous, evidence))
        return "\n".join(lines)

    @staticmethod
    def pick_points(value: float, bands: List[Dict[str, Any]]) -> int:
        """
        Picks the points of the highest band whose minimum is reached.

        :param value: The measured value.
        :param bands: Band dictionaries with "min" and "points", highest minimum first.
        :return: The matching points, 0 when no band is reached.
        """
        band: Dict[str, Any]
        # Bands are ordered from highest to lowest minimum
        for band in bands:
            if value >= float(band.get("min", 0)):
                return int(band.get("points", 0))
        return 0

    @staticmethod
    def build_factors(case: Dict[str, Any], similar: Dict[str, Any], playbook: Dict[str, Any],
                      policy: Dict[str, Any], scoring: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Builds the named, signed factors that make up the escalation score.

        :param case: The classified case facts.
        :param similar: The similar-case evidence.
        :param playbook: The playbook evidence.
        :param policy: The policy evidence.
        :param scoring: The effective scoring configuration.
        :return: The list of factor dictionaries with label, points and detail.
        """
        factors: List[Dict[str, Any]] = []
        priority: str = str(case.get("priority"))
        factors.append({"label": "priority", "points": int(scoring.get("priority_points", {}).get(priority, 0)),
                        "detail": priority})
        factors.append({"label": "SLA burn", "detail": f"{case.get('sla_pct')}% of SLA used",
                        "points": EscalationScorer.pick_points(float(case.get("sla_pct", 0.0)), scoring.get("sla_points", []))})
        factors.append({"label": "prior contacts", "detail": f"{case.get('prior_contacts')} earlier attempts",
                        "points": EscalationScorer.pick_points(float(case.get("prior_contacts", 0)), scoring.get("prior_contact_points", []))})
        factors.append({"label": "recurrence", "detail": f"{case.get('repeat_similar_count')} similar recent cases",
                        "points": EscalationScorer.pick_points(float(case.get("repeat_similar_count", 0)), scoring.get("recurrence_points", []))})
        factors.append({"label": "value at risk", "detail": f"{case.get('value_at_risk')}",
                        "points": EscalationScorer.pick_points(float(case.get("value_at_risk", 0.0)), scoring.get("value_points", []))})
        frustration: str = str(case.get("frustration_level"))
        factors.append({"label": "stakeholder frustration", "detail": frustration,
                        "points": int(scoring.get("frustration_points", {}).get(frustration, 0))})
        scaled_weight: int = int(round(float(policy.get("total_weight", 0)) * float(scoring.get("policy_weight_scale", 0.5))))
        policy_points: int = min(int(scoring.get("policy_weight_cap", 20)), scaled_weight)
        factors.append({"label": "policy rules", "detail": f"{len(policy.get('triggered', []))} triggered",
                        "points": policy_points})

        support: int = int(playbook.get("best_support", 0))
        success: float = float(playbook.get("best_success", 0.5))
        if support >= 1 and success < 0.5:
            factors.append({"label": "weak resolution track record", "detail": f"best option success {success}",
                            "points": int(scoring.get("weak_resolution_points", 10))})
        elif support >= 2 and success >= 0.8:
            factors.append({"label": "proven resolution available", "detail": f"best option success {success}",
                            "points": int(scoring.get("strong_resolution_credit", -10))})
        if not playbook.get("best_within_l1"):
            factors.append({"label": "front-line authority exceeded", "detail": f"best option needs {playbook.get('best_authority_level')}",
                            "points": int(scoring.get("authority_exceeded_points", 10))})
        if int(similar.get("pool_size", 0)) >= 3 and float(similar.get("escalation_rate", 0.0)) >= 0.6:
            factors.append({"label": "similar cases usually escalated", "detail": f"{round(float(similar.get('escalation_rate', 0.0)) * 100)}% of similar cases",
                            "points": int(scoring.get("high_escalation_rate_points", 8))})
        return factors

    @staticmethod
    def band(score: int, forced: bool, priority: str, thresholds: Dict[str, int]) -> str:
        """
        Maps a score to a decision band.

        :param score: The escalation score.
        :param forced: True when a mandatory policy rule triggered.
        :param priority: The case priority.
        :param thresholds: The monitor, escalate and urgent thresholds.
        :return: The decision label.
        """
        if score >= int(thresholds.get("urgent", 80)) or (forced and priority == "P1"):
            return "URGENT_ESCALATION"
        if score >= int(thresholds.get("escalate", 55)) or forced:
            return "ESCALATE"
        if score >= int(thresholds.get("monitor", 35)):
            return "RESOLVE_AT_L1_WITH_MONITORING"
        return "RESOLVE_AT_L1"

    @staticmethod
    def choose_target(decision: str, policy: Dict[str, Any], classification: Dict[str, Any],
                      config: Dict[str, Any]) -> Tuple[str, str, List[str]]:
        """
        Chooses the escalation target, its level and who else to notify.

        :param decision: The decision band.
        :param policy: The policy evidence.
        :param classification: The classification evidence.
        :param config: The domain pack configuration.
        :return: A tuple (target team, level, list of teams to also notify).
        """
        if decision in ("RESOLVE_AT_L1", "RESOLVE_AT_L1_WITH_MONITORING"):
            return ("Front line (L1)", "L1", [])
        triggered: List[Dict[str, Any]] = policy.get("triggered", [])
        target: str = str(classification.get("owning_team") or config.get("default_team"))
        level: str = "L2"
        if triggered:
            target = str(triggered[0].get("escalate_to"))
            level = str(triggered[0].get("level", "L2"))
        if decision == "URGENT_ESCALATION":
            level = "L3"
        also: List[str] = []
        rule: Dict[str, Any]
        # Other triggered rules become notification targets
        for rule in triggered[1:]:
            team: str = str(rule.get("escalate_to"))
            if team != target and team not in also:
                also.append(team)
        owning: str = str(classification.get("owning_team") or "")
        if owning and owning != target and owning not in also:
            also.append(owning)
        return (target, level, also)

    @staticmethod
    def pivotal_factors(factors: List[Dict[str, Any]], score: int, forced: bool, priority: str,
                        thresholds: Dict[str, int], decision: str) -> List[str]:
        """
        Finds factors whose removal would change the decision band.

        :param factors: The score factors.
        :param score: The final score.
        :param forced: True when a mandatory rule forced the decision.
        :param priority: The case priority.
        :param thresholds: The decision thresholds.
        :param decision: The current decision.
        :return: Human-readable descriptions of the pivotal factors.
        """
        found: List[str] = []
        if forced:
            found.append("a mandatory policy rule is the reason; without it the score alone would decide")
        factor: Dict[str, Any]
        # Test the decision band after removing each factor
        for factor in factors:
            points: int = int(factor.get("points", 0))
            if points == 0:
                continue
            alternative: str = EscalationScorer.band(min(100, max(0, score - points)), False, priority, thresholds)
            if alternative != decision and not forced:
                found.append(f"{factor.get('label')} ({points:+d}) would move the decision to {alternative}")
        return found[:4]

    @staticmethod
    def confidence(case: Dict[str, Any], similar: Dict[str, Any], score: int, thresholds: Dict[str, int]) -> str:
        """
        Rates confidence from data completeness, similar-case support and distance from a threshold.

        :param case: The case facts.
        :param similar: The similar-case evidence.
        :param score: The score.
        :param thresholds: The decision thresholds.
        :return: High, Medium or Low.
        """
        assumed: int = len(case.get("assumed_fields", []))
        completeness: float = 1.0 - min(5, assumed) / 5.0
        support: int = int(similar.get("pool_size", 0))
        margin: int = 100
        name: str
        # Distance to the nearest decision threshold
        for name in thresholds:
            margin = min(margin, abs(score - int(thresholds.get(name, 0))))
        if completeness >= 0.8 and support >= 3 and margin >= 8:
            return "High"
        if completeness < 0.5 or support == 0:
            return "Low"
        return "Medium"

    @staticmethod
    def rule_labels(rules: List[Dict[str, Any]]) -> List[str]:
        """
        Formats rules as short labels.

        :param rules: Rule dictionaries.
        :return: Labels such as "R01 Legal threat".
        """
        labels: List[str] = []
        rule: Dict[str, Any]
        # Combine id and description
        for rule in rules:
            labels.append(f"{rule.get('id')} {rule.get('description')}")
        return labels

    @staticmethod
    def compare_with_previous(previous: Dict[str, Any], current: Dict[str, Any]) -> str:
        """
        Describes what changed since the previous run of the same session.

        :param previous: The earlier escalation evidence.
        :param current: The new escalation evidence.
        :return: A WHAT CHANGED line.
        """
        return (
            f"WHAT CHANGED since the previous run: decision {previous.get('decision')} -> {current.get('decision')}, "
            f"score {previous.get('score')} -> {current.get('score')}, priority {previous.get('priority')} -> "
            f"{current.get('priority')}, target {previous.get('target_team')} -> {current.get('target_team')}."
        )
