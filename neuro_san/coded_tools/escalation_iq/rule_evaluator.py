from typing import Any
from typing import Dict
from typing import List


class RuleEvaluator:
    """
    Evaluates data-only policy rules against case facts with a tiny, safe condition language
    (no eval). A condition is {"field": ..., "op": ..., "value": ...} with ops
    ==, !=, >, >=, <, <=, in, not_in, contains. A rule's "when" list is AND-ed and an optional
    "when_any" list is OR-ed; both must hold when both are present.
    """

    @staticmethod
    def compare(actual: Any, op: str, expected: Any) -> bool:
        """
        Compares one fact with one expected value.

        :param actual: The fact value from the case.
        :param op: The comparison operator.
        :param expected: The value from the rule.
        :return: True when the comparison holds; False also when the fact is missing.
        """
        if actual is None:
            return False
        if op in ("in", "not_in"):
            options: List[str] = []
            option: Any
            # Normalize every allowed option for case-insensitive matching
            for option in list(expected):
                options.append(str(option).lower())
            found: bool = str(actual).lower() in options
            return found if op == "in" else not found
        if op == "contains":
            return str(expected).lower() in str(actual).lower()
        if isinstance(expected, bool) or isinstance(actual, bool):
            same: bool = bool(actual) == bool(expected)
            return same if op == "==" else (not same if op == "!=" else False)
        try:
            left: float = float(actual)
            right: float = float(expected)
        except (TypeError, ValueError):
            left_text: str = str(actual).lower()
            right_text: str = str(expected).lower()
            if op == "==":
                return left_text == right_text
            if op == "!=":
                return left_text != right_text
            return False
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        return False

    @staticmethod
    def evaluate_condition(condition: Dict[str, Any], facts: Dict[str, Any]) -> bool:
        """
        Evaluates a single condition.

        :param condition: The condition dictionary.
        :param facts: The case facts.
        :return: True when the condition holds.
        """
        field: str = str(condition.get("field", ""))
        op: str = str(condition.get("op", "=="))
        return RuleEvaluator.compare(facts.get(field), op, condition.get("value"))

    @staticmethod
    def evaluate_rule(rule: Dict[str, Any], facts: Dict[str, Any]) -> bool:
        """
        Evaluates a rule's "when" (all) and "when_any" (at least one) condition lists.

        :param rule: The rule dictionary.
        :param facts: The case facts.
        :return: True when the rule triggers.
        """
        condition: Dict[str, Any]
        # Every "when" condition must hold
        for condition in rule.get("when", []):
            if not RuleEvaluator.evaluate_condition(condition, facts):
                return False
        any_list: List[Dict[str, Any]] = rule.get("when_any", [])
        if not any_list:
            return True
        # At least one "when_any" condition must hold
        for condition in any_list:
            if RuleEvaluator.evaluate_condition(condition, facts):
                return True
        return False

    @staticmethod
    def describe_conditions(rule: Dict[str, Any]) -> str:
        """
        Renders a rule's conditions as readable text for explanations.

        :param rule: The rule dictionary.
        :return: A short description such as "priority in [P1, P2] AND prior_contacts >= 3".
        """
        parts: List[str] = []
        condition: Dict[str, Any]
        # Format each "when" condition
        for condition in rule.get("when", []):
            parts.append(f"{condition.get('field')} {condition.get('op')} {condition.get('value')}")
        text: str = " AND ".join(parts)
        any_parts: List[str] = []
        # Format each "when_any" condition
        for condition in rule.get("when_any", []):
            any_parts.append(f"{condition.get('field')} {condition.get('op')} {condition.get('value')}")
        if any_parts:
            text = text + (" AND " if text else "") + "(" + " OR ".join(any_parts) + ")"
        return text
