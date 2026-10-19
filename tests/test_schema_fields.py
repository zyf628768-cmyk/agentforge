from agentforge.contracts import check_schema


def test_schema_keyword_names_in_data_are_not_treated_as_code():
    check_schema(
        {
            "type": "object",
            "properties": {"pattern": {"type": "string"}},
            "const": {"$ref": "ordinary task data"},
        }
    )
