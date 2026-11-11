"""PE engg handoff naming — greenfield slug helpers."""

from __future__ import annotations

from src.adh_agents.runtime.room_resolve import engg_room_slug_for, is_engg_room


def test_engg_slug_and_kind_helper() -> None:
    assert engg_room_slug_for("INIT-REALWORLD-002") == "engg-init-realworld-002"
    assert is_engg_room("engg-init-realworld-002")
    assert not is_engg_room("task-init-realworld-002")


def test_dispatch_has_no_dev_engg_emit() -> None:
    import inspect

    from src.adh_agents.execution import dispatch_service as ds

    src = inspect.getsource(ds.HermesDispatchService)
    assert "_emit_dev_engg_baton" not in src
    assert "dev.engg_think" not in src or "pe.review" in src
    # Stronger: method must not exist
    assert not hasattr(ds.HermesDispatchService, "_emit_dev_engg_baton")
