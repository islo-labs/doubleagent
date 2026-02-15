"""Unit tests for NamespaceRouter isolation."""

from doubleagent_sdk.namespace import NamespaceRouter


def test_default_namespace_created_lazily():
    router = NamespaceRouter()
    state = router.get_state()
    assert state is not None
    assert len(router.list_namespaces()) == 1


def test_separate_namespaces_get_separate_overlays():
    router = NamespaceRouter(baseline={
        "repos": {"r1": {"id": 1, "name": "shared"}},
    })

    state_a = router.get_state("agent-a")
    state_b = router.get_state("agent-b")

    # Both see baseline
    assert state_a.get("repos", "r1")["name"] == "shared"
    assert state_b.get("repos", "r1")["name"] == "shared"

    # Agent A writes
    state_a.put("repos", "r2", {"id": 2, "name": "a-only"})

    # Agent B doesn't see it
    assert state_b.get("repos", "r2") is None
    # Agent A sees it
    assert state_a.get("repos", "r2")["name"] == "a-only"


def test_reset_namespace_preserves_others():
    router = NamespaceRouter(baseline={
        "repos": {"r1": {"id": 1, "name": "shared"}},
    })

    state_a = router.get_state("agent-a")
    state_b = router.get_state("agent-b")

    state_a.put("repos", "r-a", {"id": 10, "name": "a-temp"})
    state_b.put("repos", "r-b", {"id": 20, "name": "b-temp"})

    router.reset_namespace("agent-a")

    assert state_a.get("repos", "r-a") is None
    assert state_b.get("repos", "r-b")["name"] == "b-temp"


def test_reset_all():
    router = NamespaceRouter()
    state_a = router.get_state("a")
    state_b = router.get_state("b")
    state_a.put("x", "1", {"v": 1})
    state_b.put("x", "2", {"v": 2})

    router.reset_all()

    assert state_a.get("x", "1") is None
    assert state_b.get("x", "2") is None


def test_load_baseline_propagates():
    router = NamespaceRouter()
    state = router.get_state("test")
    state.put("repos", "r1", {"id": 1})

    router.load_baseline({"repos": {"r2": {"id": 2, "name": "new-baseline"}}})

    # Old overlay data cleared
    assert state.get("repos", "r1") is None
    # New baseline visible
    assert state.get("repos", "r2")["name"] == "new-baseline"


def test_delete_namespace():
    router = NamespaceRouter()
    router.get_state("temp")
    assert router.delete_namespace("temp") is True
    assert router.delete_namespace("nonexistent") is False


def test_list_namespaces_metadata():
    router = NamespaceRouter()
    state = router.get_state("ns1")
    state.put("repos", "r1", {"id": 1})

    nss = router.list_namespaces()
    assert len(nss) == 1
    assert nss[0]["namespace"] == "ns1"
    assert nss[0]["has_baseline"] is False
