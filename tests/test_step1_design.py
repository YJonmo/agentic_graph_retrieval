from firma2.step1_design import get_user_modes, get_graph_questions, get_initial_scope


def test_user_modes_are_defined():
    modes = get_user_modes()
    assert set(modes) == {"agent", "projection"}


def test_graph_questions_cover_identity_and_traversal():
    questions = get_graph_questions()
    assert len(questions) >= 5
    assert any("match" in q.lower() for q in questions)
    assert any("parent" in q.lower() or "ultimate" in q.lower() for q in questions)


def test_scope_distinguishes_in_scope_from_deferred():
    scope = get_initial_scope()
    assert "in_scope" in scope
    assert "deferred" in scope
    assert scope["in_scope"]
    assert scope["deferred"]
