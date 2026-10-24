import re
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Pattern


class ArgReader:
    """
    Static helpers that coerce the loosely typed string arguments an LLM sends to a
    coded tool (for example "10,000", "$250k", "99.9%", "Multi AZ") into clean Python values.
    """

    NUMBER_PATTERN: Pattern[str] = re.compile(r"\s*(-?\d+(?:\.\d+)?)\s*([km])?(?![a-z])")
    SUFFIX_MULTIPLIERS: Dict[str, float] = {"k": 1000.0, "m": 1000000.0}
    LIST_SPLITTER: Pattern[str] = re.compile(r"[,;\n]")
    RECORD_SPLITTER: Pattern[str] = re.compile(r"[;\n]")

    @staticmethod
    def to_float(value: Any, default: float) -> float:
        """
        Converts a value such as "10,000", "$250k" or "99.9%" to a float.

        :param value: The raw argument value.
        :param default: The value returned when no number can be found in the input.
        :return: The parsed float, or the default.
        """
        if value is None:
            return default
        text: str = str(value).strip().lower()
        text = text.replace(",", "").replace("$", "").replace("%", "").replace("_", "")
        match: Optional[re.Match] = ArgReader.NUMBER_PATTERN.match(text)
        if match is None:
            return default
        number: float = float(match.group(1))
        suffix: Optional[str] = match.group(2)
        if suffix is not None:
            number = number * ArgReader.SUFFIX_MULTIPLIERS.get(suffix, 1.0)
        return number

    @staticmethod
    def to_int(value: Any, default: int) -> int:
        """
        Converts a loosely formatted value to an int.

        :param value: The raw argument value.
        :param default: The value returned when no number can be found in the input.
        :return: The parsed int, or the default.
        """
        return int(round(ArgReader.to_float(value, float(default))))

    @staticmethod
    def to_bool(value: Any, default: bool) -> bool:
        """
        Converts values such as "yes", "true", "1", "no" or a real bool to a bool.

        :param value: The raw argument value.
        :param default: The value returned when the input is missing or not understood.
        :return: The parsed bool, or the default.
        """
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        text: str = str(value).strip().lower()
        if text in ("true", "yes", "y", "1", "t"):
            return True
        if text in ("false", "no", "n", "0", "f", "none"):
            return False
        return default

    @staticmethod
    def to_token(value: Any) -> str:
        """
        Normalizes free text to a lower_snake_case token.

        :param value: The raw argument value.
        :return: The normalized token, empty when the value is None.
        """
        if value is None:
            return ""
        text: str = str(value).strip().lower()
        text = re.sub(r"[\s\-/]+", "_", text)
        return text

    @staticmethod
    def to_choice(value: Any, allowed: List[str], default: str) -> str:
        """
        Normalizes the value and returns it only when it is one of the allowed choices.

        :param value: The raw argument value.
        :param allowed: The permitted lower_snake_case choices.
        :param default: The choice returned when the value is missing or not allowed.
        :return: One of the allowed choices, or the default.
        """
        token: str = ArgReader.to_token(value)
        if token in allowed:
            return token
        return default

    @staticmethod
    def to_list(value: Any) -> List[str]:
        """
        Splits a comma, semicolon or newline separated string (or a real list) into unique tokens.

        :param value: The raw argument value.
        :return: The ordered list of unique normalized tokens.
        """
        raw_items: List[Any] = []
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            raw_items = list(value)
        else:
            raw_items = ArgReader.LIST_SPLITTER.split(str(value))

        tokens: List[str] = []
        raw_item: Any
        # Normalize each item and keep the first occurrence only
        for raw_item in raw_items:
            token: str = ArgReader.to_token(raw_item)
            if token and token not in tokens:
                tokens.append(token)
        return tokens

    @staticmethod
    def to_records(value: Any) -> List[str]:
        """
        Splits a semicolon or newline separated string into non-empty raw records.

        :param value: The raw argument value.
        :return: The list of stripped, non-empty records.
        """
        if value is None:
            return []
        raw_records: List[str] = ArgReader.RECORD_SPLITTER.split(str(value))
        records: List[str] = []
        raw_record: str
        # Keep only records that contain visible text
        for raw_record in raw_records:
            stripped: str = raw_record.strip()
            if stripped:
                records.append(stripped)
        return records
