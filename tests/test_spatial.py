from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import twingraph as tg
from pydantic import ValidationError
from twingraph.canonical import hash_input
from twingraph.errors import CODES
from twingraph.registry import InMemoryTypeRegistry, PropSpec, TypeDef

_EXAMPLE = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "public_spatial_topology_01.twingraph.json"
)


def _spatial_registry():
    return tg.build_type_registry((*tg.BUILTIN_TYPE_PACKS, tg.SPATIAL_TYPE_PACK))


def _graph() -> tg.TwinGraph:
    return tg.TwinGraph.load(json.loads(_EXAMPLE.read_text()))


def _compile(graph, model_registry):
    return tg.compile_graph(
        graph,
        type_registry=_spatial_registry(),
        model_registry=model_registry,
    )


def test_spatial_pack_is_optional_and_composable():
    assert not tg.BUILTIN_TYPE_REGISTRY.has("metis.spatial.Corridor@1")
    registry = _spatial_registry()
    assert registry.has("metis.spatial.Corridor@1")
    assert registry.has("metis.relation.routes_through@1")


def test_spatial_pack_preserves_core_located_in_type_and_unit_validation(model_registry):
    graph = _graph()
    graph.relations.append(
        tg.Relation(
            id="bad-distance",
            type_ref="located_in",
            source_entity_id="origin",
            target_entity_id="destination",
            properties={"distance_km": {"value": 1.0, "unit": "MW"}},
        )
    )
    result = _compile(graph, model_registry)
    assert CODES.UNIT_MISMATCH in {item.code for item in result.report.errors()}
    located_in = _spatial_registry().resolve("metis.relation.located_in@1")
    assert any(prop.name == "distance_km" for prop in located_in.optional_properties)


def test_type_registry_rejects_conflicting_redefinitions():
    registry = InMemoryTypeRegistry()
    original = TypeDef(
        type_ref="example.Asset@1",
        kind="entity",
        title="Asset",
        optional_properties=(PropSpec("length", unit="m", required=False),),
    )
    registry.register(original)
    registry.register(original)
    with pytest.raises(ValueError, match="conflicting TypeDef"):
        registry.register(
            TypeDef(type_ref="example.Asset@1", kind="entity", title="Different asset")
        )


def test_spatial_profile_round_trips_and_compiles(model_registry):
    raw = json.loads(_EXAMPLE.read_text())
    jsonschema.validate(raw, tg.TwinGraph.model_json_schema())
    graph = tg.TwinGraph.load(raw)
    loaded = tg.TwinGraph.model_validate_json(graph.model_dump_json())
    assert loaded.spatial is not None
    assert loaded.entities[0].ports["outbound"].spatial is not None
    result = _compile(loaded, model_registry)
    assert result.ok, result.report.errors()


def test_existing_documents_remain_valid_without_spatial(demo_doc):
    graph = tg.TwinGraph.load(demo_doc)
    assert graph.spatial is None


def test_spatial_compile_reports_missing_frames_dimensions_units_and_ports(model_registry):
    graph = _graph()
    graph.spatial.placements[0].frame_id = "missing"
    graph.spatial.placements[1].position = [8.0, 2.0, 0.0]
    graph.spatial.frames[0].angle_unit = "MW"
    graph.spatial.routes[0].target_port = "ghost"

    result = _compile(graph, model_registry)
    codes = {diagnostic.code for diagnostic in result.report.errors()}
    assert CODES.DANGLING_REF in codes
    assert CODES.STRUCTURE in codes
    assert CODES.UNIT_MISMATCH in codes


def test_spatial_compile_reports_overlapping_required_clearances(model_registry):
    graph = _graph()
    graph.spatial.placements[1].required_clearance = tg.BoundingBoxGeometry(
        frame_id="site",
        minimum=[3.0, 1.0],
        maximum=[7.0, 5.0],
    )
    result = _compile(graph, model_registry)
    assert any("required clearances" in item.message for item in result.report.errors())


def test_duplicate_placements_report_and_hash_deterministically(model_registry):
    first = _graph()
    duplicate = first.spatial.placements[0].model_copy(deep=True)
    duplicate.position = [3.0, 3.0]
    duplicate.required_clearance = None
    first.spatial.placements.append(duplicate)

    second = first.model_copy(deep=True)
    second.spatial.placements.reverse()
    assert first.compute_content_hash() == second.compute_content_hash()
    result = _compile(first, model_registry)
    assert any(
        item.code == CODES.DUPLICATE_ID and "spatial placement" in item.message
        for item in result.report.errors()
    )


def test_port_compatibility_only_enforces_route_requirements(model_registry):
    graph = _graph()
    source = graph.entities[0].ports["outbound"].spatial
    target = graph.entities[1].ports["inbound"].spatial
    source.compatibility = ["outlet"]
    target.compatibility = ["inlet"]
    graph.spatial.routes[0].compatibility = []
    assert _compile(graph, model_registry).ok

    graph.spatial.routes[0].compatibility = ["ground_route"]
    result = _compile(graph, model_registry)
    assert any("compatibility" in item.message for item in result.report.errors())


def test_frame_cycles_parent_refs_and_transform_dimensions_are_reported(model_registry):
    graph = _graph()
    graph.spatial.frames[0].parent_frame_id = "child"
    graph.spatial.frames[0].parent_transform = tg.FrameTransform(
        translation=[0.0, 0.0], rotation=[0.0]
    )
    graph.spatial.frames.append(
        tg.CoordinateFrame(
            id="child",
            dimensions=2,
            parent_frame_id="site",
            parent_transform=tg.FrameTransform(
                translation=[0.0, 0.0], rotation=[0.0]
            ),
        )
    )
    graph.spatial.frames.append(
        tg.CoordinateFrame(
            id="orphan",
            dimensions=2,
            parent_frame_id="missing",
            parent_transform=tg.FrameTransform(
                translation=[0.0, 0.0], rotation=[0.0]
            ),
        )
    )
    graph.spatial.frames.append(tg.CoordinateFrame(id="world-3d", dimensions=3))
    graph.spatial.frames.append(
        tg.CoordinateFrame(
            id="bad-transform",
            dimensions=2,
            parent_frame_id="world-3d",
            parent_transform=tg.FrameTransform(
                translation=[0.0, 0.0], rotation=[0.0]
            ),
        )
    )
    result = _compile(graph, model_registry)
    codes = {item.code for item in result.report.errors()}
    assert CODES.CYCLE in codes
    assert CODES.DANGLING_REF in codes
    assert CODES.STRUCTURE in codes


def test_duplicate_spatial_ids_are_reported(model_registry):
    graph = _graph()
    graph.spatial.regions.append(
        tg.SpatialRegion(
            id="route-1",
            geometry=graph.spatial.regions[0].geometry.model_copy(deep=True),
        )
    )
    result = _compile(graph, model_registry)
    assert any(
        item.code == CODES.DUPLICATE_ID and "route-1" in item.message
        for item in result.report.errors()
    )


def test_frame_transform_requires_explicit_identity_components():
    with pytest.raises(ValidationError):
        tg.FrameTransform()


def test_spatial_distance_units_include_feet_but_angles_exclude_radians(model_registry):
    graph = _graph()
    graph.spatial.frames[0].distance_unit = "feet"
    assert _compile(graph, model_registry).ok

    graph.spatial.frames[0].angle_unit = "rad"
    result = _compile(graph, model_registry)
    assert CODES.UNIT_MISMATCH in {item.code for item in result.report.errors()}


def test_proposed_reservation_does_not_claim_observed_state(model_registry):
    graph = _graph()
    reservation = graph.spatial.reservations[0]
    assert reservation.state == "proposed"
    assert _compile(graph, model_registry).ok


def test_geometry_shape_is_validated_at_parse():
    with pytest.raises(ValidationError, match="at least three distinct"):
        tg.PolygonGeometry(
            frame_id="site",
            vertices=[[0.0, 0.0], [0.0, 0.0], [1.0, 1.0]],
        )


def test_spatial_hash_is_independent_of_collection_order():
    first = _graph()
    second = first.model_copy(deep=True)
    second.spatial.placements.reverse()
    second.spatial.regions.reverse()
    second.spatial.routes.reverse()
    assert first.compute_content_hash() == second.compute_content_hash()


def test_absent_spatial_defaults_do_not_change_legacy_hash_input(demo_doc):
    graph = tg.TwinGraph.load(demo_doc)
    payload = hash_input(graph.model_dump(mode="json"))
    assert "spatial" not in payload
    assert all(
        "spatial" not in port
        for entity in payload["entities"]
        for port in entity["ports"].values()
    )
