import pytest

from agentforge.contracts import check_schema
from agentforge.core import ForgeError


def test_schema_keyword_names_in_data_are_not_treated_as_code():
    check_schema(
        {
            "type": "object",
            "properties": {"pattern": {"type": "string"}},
            "const": {"$ref": "ordinary task data"},
        }
    )


@pytest.mark.parametrize(
    "schema",
    [
        {"input_string": {"type": "string"}},
        {"type": "string", "maxLenght": 5},
        {"type": "object", "properties": {"text": {"type": "string", "typo": True}}},
    ],
)
def test_unknown_schema_keywords_cannot_silently_disable_contracts(schema):
    with pytest.raises(ForgeError, match="Unsupported"):
        check_schema(schema)
