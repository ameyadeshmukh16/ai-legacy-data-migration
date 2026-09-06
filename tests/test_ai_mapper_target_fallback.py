from agents.ai_mapper import _fallback_target

# Reproduces real LLM outputs seen live (Groq gpt-oss-120b) when the prompt
# gave no target schema hints: empty string, the literal 'UNKNOWN' placeholder,
# and None all need to fall back to a valid source-derived name so the
# executor never sees an empty or colliding target_column.

def test_empty_string_falls_back_to_source_column():
    assert _fallback_target("", "dept_id") == "dept_id"

def test_unknown_placeholder_falls_back_to_source_column():
    assert _fallback_target("UNKNOWN", "dept_cd") == "dept_cd"

def test_none_falls_back_to_source_column():
    assert _fallback_target(None, "dept_typ_cd") == "dept_typ_cd"

def test_invalid_identifier_falls_back_to_source_column():
    assert _fallback_target("bad name!", "dept_typ_cd") == "dept_typ_cd"

def test_valid_inferred_name_is_kept():
    assert _fallback_target("department_name", "dept_name") == "department_name"
