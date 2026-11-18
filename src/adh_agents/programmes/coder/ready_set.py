"""Ready-set projection from WorkManifest board waves (C.10)."""

from __future__ import annotations

from src.adh_agents.programmes.dev.workmanifest_board import BoardManifest, BoardWave


def ready_waves(
    manifest: BoardManifest,
    *,
    done_wave_ids: frozenset[str] | None = None,
) -> tuple[BoardWave, ...]:
    """Waves whose ``depends_on`` parents are all Done (empty deps ⇒ ready at seed)."""
    done = done_wave_ids or frozenset()
    out: list[BoardWave] = []
    for wave in manifest.waves:
        if wave.wave_id in done:
            continue
        if all(dep in done for dep in wave.depends_on):
            out.append(wave)
    return tuple(out)


def ready_repos(
    manifest: BoardManifest,
    *,
    done_wave_ids: frozenset[str] | None = None,
) -> tuple[str, ...]:
    """Unique repo suffixes for ready waves (stable wave order; first-seen wins)."""
    seen: list[str] = []
    for wave in ready_waves(manifest, done_wave_ids=done_wave_ids):
        repo = (wave.repo or "").strip()
        if repo and repo not in seen:
            seen.append(repo)
    return tuple(seen)


def ready_wave_ids_for_repo(
    manifest: BoardManifest,
    repo: str,
    *,
    done_wave_ids: frozenset[str] | None = None,
) -> tuple[str, ...]:
    want = (repo or "").strip()
    return tuple(
        w.wave_id
        for w in ready_waves(manifest, done_wave_ids=done_wave_ids)
        if (w.repo or "").strip() == want
    )
