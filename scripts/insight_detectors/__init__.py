"""Insight detector registry.

Each category module exposes ``DETECTORS = [callable, ...]`` following the contract in
``_util``. ``ALL`` aggregates every category; ``insights.detect`` runs them and ranks the
results. Adding a category = add a module here and extend ``ALL`` — no other wiring.
"""
from __future__ import annotations

from insight_detectors import (
    core,
    aerobic,
    pace_execution,
    records_milestones,
    load_recovery,
    consistency_rhythm,
    form_cadence,
    hr_zones,
    elevation_terrain,
    goal_progress,
    temporal_patterns,
    comparative,
    volume_distance,
    anomaly_fun,
    body,
)

# Category modules are appended here as they land. Order is irrelevant (cards are score-ranked).
ALL = (
    list(core.DETECTORS)
    + list(aerobic.DETECTORS)
    + list(pace_execution.DETECTORS)
    + list(records_milestones.DETECTORS)
    + list(load_recovery.DETECTORS)
    + list(consistency_rhythm.DETECTORS)
    + list(form_cadence.DETECTORS)
    + list(hr_zones.DETECTORS)
    + list(elevation_terrain.DETECTORS)
    + list(goal_progress.DETECTORS)
    + list(temporal_patterns.DETECTORS)
    + list(comparative.DETECTORS)
    + list(volume_distance.DETECTORS)
    + list(anomaly_fun.DETECTORS)
    + list(body.DETECTORS)
)
