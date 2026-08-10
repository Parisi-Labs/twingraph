"""Optional spatial topology profile for TwinGraph documents.

The profile is data-only: it describes coordinate frames, geometry, placement,
ports, routes, corridors, and reservations.  It deliberately does not perform
placement or routing optimization.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import CODES, Diagnostic
from .units import Quantity, UnitRegistry

if TYPE_CHECKING:
    from .document import TwinGraph
    from .registry import TypeRegistry

_ID_PATTERN = r"^[A-Za-z0-9_.:-]+$"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FrameTransform(_Base):
    translation: list[float] = Field(default_factory=list, min_length=2, max_length=3)
    rotation: list[float] = Field(default_factory=list, min_length=1, max_length=3)


class CoordinateFrame(_Base):
    id: str = Field(pattern=_ID_PATTERN)
    dimensions: Literal[2, 3]
    distance_unit: str = "m"
    angle_unit: str = "deg"
    origin_convention: str = "right_handed"
    axis_labels: list[str] = Field(default_factory=list)
    parent_frame_id: str | None = None
    parent_transform: FrameTransform | None = None

    @model_validator(mode="after")
    def _parent_and_transform_are_paired(self) -> CoordinateFrame:
        if (self.parent_frame_id is None) != (self.parent_transform is None):
            raise ValueError("parent_frame_id and parent_transform must be supplied together")
        if self.axis_labels and len(self.axis_labels) != self.dimensions:
            raise ValueError("axis_labels length must equal frame dimensions")
        return self


class PointGeometry(_Base):
    kind: Literal["point"] = "point"
    frame_id: str
    coordinates: list[float] = Field(min_length=2, max_length=3)


class BoundingBoxGeometry(_Base):
    kind: Literal["bounding_box"] = "bounding_box"
    frame_id: str
    minimum: list[float] = Field(min_length=2, max_length=3)
    maximum: list[float] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def _ordered_bounds(self) -> BoundingBoxGeometry:
        if len(self.minimum) != len(self.maximum):
            raise ValueError("bounding-box minimum and maximum dimensions must match")
        if any(low > high for low, high in zip(self.minimum, self.maximum, strict=True)):
            raise ValueError("bounding-box minimum must not exceed maximum")
        return self


class PolygonGeometry(_Base):
    kind: Literal["polygon"] = "polygon"
    frame_id: str
    vertices: list[list[float]] = Field(min_length=3)

    @model_validator(mode="after")
    def _valid_vertices(self) -> PolygonGeometry:
        dimensions = {len(vertex) for vertex in self.vertices}
        if len(dimensions) != 1 or next(iter(dimensions), 0) not in (2, 3):
            raise ValueError("polygon vertices must use one common 2D or 3D dimensionality")
        if len({tuple(vertex) for vertex in self.vertices}) < 3:
            raise ValueError("polygon requires at least three distinct vertices")
        return self


class PolylineGeometry(_Base):
    kind: Literal["polyline"] = "polyline"
    frame_id: str
    vertices: list[list[float]] = Field(min_length=2)

    @model_validator(mode="after")
    def _valid_vertices(self) -> PolylineGeometry:
        dimensions = {len(vertex) for vertex in self.vertices}
        if len(dimensions) != 1 or next(iter(dimensions), 0) not in (2, 3):
            raise ValueError("polyline vertices must use one common 2D or 3D dimensionality")
        return self


Geometry = Annotated[
    PointGeometry | BoundingBoxGeometry | PolygonGeometry | PolylineGeometry,
    Field(discriminator="kind"),
]


class SpatialPort(_Base):
    """Anchor and reach metadata composed onto an existing ``EntityPort``."""

    frame_id: str
    anchor: list[float] = Field(min_length=2, max_length=3)
    orientation: list[float] = Field(default_factory=list, max_length=3)
    reach: Geometry | None = None
    compatibility: list[str] = Field(default_factory=list)
    required_clearance: Geometry | None = None


class EntityPlacement(_Base):
    entity_id: str
    frame_id: str
    position: list[float] = Field(min_length=2, max_length=3)
    orientation: list[float] = Field(default_factory=list, max_length=3)
    footprint: Geometry | None = None
    height: Quantity | None = None
    required_clearance: BoundingBoxGeometry | None = None


class SpatialRegion(_Base):
    id: str = Field(pattern=_ID_PATTERN)
    geometry: Geometry
    role: Literal["region", "corridor", "exclusion_zone"] = "region"
    capacity: Quantity | None = None


class SpatialRoute(_Base):
    id: str = Field(pattern=_ID_PATTERN)
    source_entity_id: str
    source_port: str
    target_entity_id: str
    target_port: str
    path: PolylineGeometry
    corridor_id: str | None = None
    capacity: Quantity | None = None
    compatibility: list[str] = Field(default_factory=list)
    state: Literal["proposed", "reserved", "observed"] = "proposed"


class SpatialReservation(_Base):
    id: str = Field(pattern=_ID_PATTERN)
    geometry: Geometry
    reserved_by_entity_id: str | None = None
    route_id: str | None = None
    capacity: Quantity | None = None
    state: Literal["proposed", "confirmed", "released"] = "proposed"
    evidence_refs: list[str] = Field(default_factory=list)


class SpatialTopology(_Base):
    profile_version: Literal["twingraph-spatial/0.1"] = "twingraph-spatial/0.1"
    frames: list[CoordinateFrame] = Field(default_factory=list)
    placements: list[EntityPlacement] = Field(default_factory=list)
    regions: list[SpatialRegion] = Field(default_factory=list)
    routes: list[SpatialRoute] = Field(default_factory=list)
    reservations: list[SpatialReservation] = Field(default_factory=list)
    extensions: dict[str, Any] = Field(default_factory=dict)


def validate_spatial_topology(
    graph: TwinGraph,
    *,
    type_registry: TypeRegistry,
    unit_registry: UnitRegistry,
) -> list[Diagnostic]:
    """Return compile diagnostics for the optional spatial profile."""

    topology = graph.spatial
    if topology is None:
        return []
    diagnostics: list[Diagnostic] = []

    def add(code: str, message: str, ref: dict[str, Any] | None = None) -> None:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code=code,
                message=message,
                stage="validate_spatial_topology",
                ref=ref,
            )
        )

    frames: dict[str, CoordinateFrame] = {}
    for frame in topology.frames:
        if frame.id in frames:
            add(CODES.DUPLICATE_ID, f"coordinate frame id '{frame.id}' appears more than once")
        frames[frame.id] = frame
        if not unit_registry.is_known(frame.distance_unit) or not unit_registry.compatible(
            frame.distance_unit, "m"
        ):
            add(
                CODES.UNIT_MISMATCH,
                f"coordinate frame '{frame.id}' distance_unit '{frame.distance_unit}' "
                "is not a distance unit",
                {"frame": frame.id, "field": "distance_unit"},
            )
        if not unit_registry.is_known(frame.angle_unit) or not unit_registry.compatible(
            frame.angle_unit, "deg"
        ):
            add(
                CODES.UNIT_MISMATCH,
                f"coordinate frame '{frame.id}' angle_unit '{frame.angle_unit}' is not an angle unit",
                {"frame": frame.id, "field": "angle_unit"},
            )

    for frame in topology.frames:
        if frame.parent_frame_id and frame.parent_frame_id not in frames:
            add(
                CODES.DANGLING_REF,
                f"coordinate frame '{frame.id}' parent '{frame.parent_frame_id}' does not resolve",
                {"frame": frame.id, "ref": frame.parent_frame_id},
            )
        if frame.parent_transform:
            _check_coordinates(
                add,
                frames,
                frame.parent_frame_id or frame.id,
                frame.parent_transform.translation,
                f"coordinate frame '{frame.id}' translation",
                {"frame": frame.id, "field": "parent_transform.translation"},
            )
            _check_orientation(
                add,
                frames,
                frame.parent_frame_id or frame.id,
                frame.parent_transform.rotation,
                f"coordinate frame '{frame.id}' rotation",
                {"frame": frame.id, "field": "parent_transform.rotation"},
            )
    _check_frame_cycles(frames, add)

    entities = {entity.id: entity for entity in graph.entities}
    regions = {region.id: region for region in topology.regions}
    routes = {route.id: route for route in topology.routes}
    evidence_ids = {evidence.id for evidence in graph.evidence}

    for placement in topology.placements:
        if placement.entity_id not in entities:
            add(
                CODES.DANGLING_REF,
                f"placement entity '{placement.entity_id}' does not resolve",
                {"entity": placement.entity_id},
            )
        _check_coordinates(
            add,
            frames,
            placement.frame_id,
            placement.position,
            f"placement for entity '{placement.entity_id}'",
            {"entity": placement.entity_id, "field": "position"},
        )
        _check_orientation(
            add,
            frames,
            placement.frame_id,
            placement.orientation,
            f"placement for entity '{placement.entity_id}' orientation",
            {"entity": placement.entity_id, "field": "orientation"},
        )
        for geometry in (
            placement.footprint,
            placement.required_clearance,
        ):
            if geometry:
                _check_geometry(add, frames, geometry, {"entity": placement.entity_id})
        if placement.height and not unit_registry.compatible(placement.height.unit, "m"):
            add(
                CODES.UNIT_MISMATCH,
                f"placement for entity '{placement.entity_id}' height must use a distance unit",
                {"entity": placement.entity_id, "field": "height"},
            )

    for entity in graph.entities:
        for port_id, port in entity.ports.items():
            if port.spatial:
                _check_coordinates(
                    add,
                    frames,
                    port.spatial.frame_id,
                    port.spatial.anchor,
                    f"entity '{entity.id}' port '{port_id}' anchor",
                    {"entity": entity.id, "port": port_id},
                )
                _check_orientation(
                    add,
                    frames,
                    port.spatial.frame_id,
                    port.spatial.orientation,
                    f"entity '{entity.id}' port '{port_id}' orientation",
                    {"entity": entity.id, "port": port_id},
                )
                for geometry in (port.spatial.reach, port.spatial.required_clearance):
                    if geometry:
                        _check_geometry(
                            add,
                            frames,
                            geometry,
                            {"entity": entity.id, "port": port_id},
                        )

    for region in topology.regions:
        _check_geometry(add, frames, region.geometry, {"region": region.id})

    for route in topology.routes:
        _check_route_endpoint(add, entities, route, "source")
        _check_route_endpoint(add, entities, route, "target")
        _check_geometry(add, frames, route.path, {"route": route.id})
        if route.corridor_id and route.corridor_id not in regions:
            add(
                CODES.DANGLING_REF,
                f"route '{route.id}' corridor '{route.corridor_id}' does not resolve",
                {"route": route.id, "ref": route.corridor_id},
            )
        _check_port_compatibility(add, entities, route)

    for reservation in topology.reservations:
        _check_geometry(add, frames, reservation.geometry, {"reservation": reservation.id})
        if reservation.reserved_by_entity_id and reservation.reserved_by_entity_id not in entities:
            add(
                CODES.DANGLING_REF,
                f"reservation '{reservation.id}' entity does not resolve",
                {"reservation": reservation.id, "ref": reservation.reserved_by_entity_id},
            )
        if reservation.route_id and reservation.route_id not in routes:
            add(
                CODES.DANGLING_REF,
                f"reservation '{reservation.id}' route does not resolve",
                {"reservation": reservation.id, "ref": reservation.route_id},
            )
        for evidence_ref in reservation.evidence_refs:
            if evidence_ref not in evidence_ids:
                add(
                    CODES.DANGLING_REF,
                    f"reservation '{reservation.id}' evidence '{evidence_ref}' does not resolve",
                    {"reservation": reservation.id, "ref": evidence_ref},
                )

    _check_clearance_overlaps(topology.placements, add)
    _check_duplicate_spatial_ids(topology, add)
    _ = type_registry  # reserved for type-pack-specific spatial validators
    return diagnostics


def _check_coordinates(add, frames, frame_id, coordinates, label, ref) -> None:
    frame = frames.get(frame_id)
    if frame is None:
        add(CODES.DANGLING_REF, f"{label} references missing frame '{frame_id}'", ref)
    elif len(coordinates) != frame.dimensions:
        add(
            CODES.STRUCTURE,
            f"{label} has {len(coordinates)} dimensions; frame '{frame_id}' requires "
            f"{frame.dimensions}",
            ref,
        )


def _check_orientation(add, frames, frame_id, orientation, label, ref) -> None:
    if not orientation:
        return
    frame = frames.get(frame_id)
    if frame is None:
        return  # the missing frame is reported by the paired coordinate check
    expected = 1 if frame.dimensions == 2 else 3
    if len(orientation) != expected:
        add(
            CODES.STRUCTURE,
            f"{label} has {len(orientation)} values; frame '{frame_id}' requires {expected}",
            ref,
        )


def _check_geometry(add, frames, geometry, ref) -> None:
    if isinstance(geometry, PointGeometry):
        points = [geometry.coordinates]
    elif isinstance(geometry, BoundingBoxGeometry):
        points = [geometry.minimum, geometry.maximum]
    else:
        points = geometry.vertices
    for point in points:
        _check_coordinates(add, frames, geometry.frame_id, point, f"{geometry.kind} geometry", ref)


def _check_frame_cycles(frames, add) -> None:
    for start in sorted(frames):
        seen: set[str] = set()
        current = start
        while current in frames and frames[current].parent_frame_id:
            if current in seen:
                add(
                    CODES.CYCLE,
                    f"coordinate frame parent cycle includes '{current}'",
                    {"frame": current},
                )
                break
            seen.add(current)
            current = frames[current].parent_frame_id


def _check_route_endpoint(add, entities, route, side) -> None:
    entity_id = getattr(route, f"{side}_entity_id")
    port_id = getattr(route, f"{side}_port")
    entity = entities.get(entity_id)
    if entity is None:
        add(
            CODES.DANGLING_REF,
            f"route '{route.id}' {side} entity '{entity_id}' does not resolve",
            {"route": route.id, "field": f"{side}_entity_id"},
        )
    elif port_id not in entity.ports:
        add(
            CODES.DANGLING_REF,
            f"route '{route.id}' {side} port '{port_id}' is not exposed by entity '{entity_id}'",
            {"route": route.id, "field": f"{side}_port"},
        )


def _check_port_compatibility(add, entities, route) -> None:
    source = entities.get(route.source_entity_id)
    target = entities.get(route.target_entity_id)
    if not source or not target:
        return
    source_port = source.ports.get(route.source_port)
    target_port = target.ports.get(route.target_port)
    if not source_port or not target_port or not source_port.spatial or not target_port.spatial:
        return
    source_tags = set(source_port.spatial.compatibility)
    target_tags = set(target_port.spatial.compatibility)
    required = set(route.compatibility)
    if required and (not required <= source_tags or not required <= target_tags):
        add(
            CODES.STRUCTURE,
            f"route '{route.id}' compatibility is not supported by both endpoint ports",
            {"route": route.id, "field": "compatibility"},
        )
    elif source_tags and target_tags and source_tags.isdisjoint(target_tags):
        add(
            CODES.STRUCTURE,
            f"route '{route.id}' endpoint ports have incompatible spatial metadata",
            {"route": route.id, "field": "compatibility"},
        )


def _check_clearance_overlaps(placements, add) -> None:
    by_frame = defaultdict(list)
    for placement in placements:
        if placement.required_clearance:
            by_frame[placement.required_clearance.frame_id].append(
                (placement.entity_id, placement.required_clearance)
            )
    for frame_id, clearances in by_frame.items():
        for index, (left_id, left) in enumerate(clearances):
            for right_id, right in clearances[index + 1 :]:
                if len(left.minimum) != len(right.minimum):
                    continue
                overlaps = all(
                    left.minimum[axis] < right.maximum[axis]
                    and right.minimum[axis] < left.maximum[axis]
                    for axis in range(len(left.minimum))
                )
                if overlaps:
                    add(
                        CODES.STRUCTURE,
                        f"required clearances for entities '{left_id}' and '{right_id}' overlap "
                        f"in frame '{frame_id}'",
                        {"entities": [left_id, right_id], "frame": frame_id},
                    )


def _check_duplicate_spatial_ids(topology, add) -> None:
    locations = defaultdict(list)
    for kind, values in (
        ("frame", topology.frames),
        ("region", topology.regions),
        ("route", topology.routes),
        ("reservation", topology.reservations),
    ):
        for value in values:
            locations[value.id].append(kind)
    for ident, kinds in sorted(locations.items()):
        if len(kinds) > 1:
            add(
                CODES.DUPLICATE_ID,
                f"spatial id '{ident}' is reused across {', '.join(kinds)}",
                {"id": ident, "kinds": kinds},
            )


__all__ = [
    "BoundingBoxGeometry",
    "CoordinateFrame",
    "EntityPlacement",
    "FrameTransform",
    "Geometry",
    "PointGeometry",
    "PolygonGeometry",
    "PolylineGeometry",
    "SpatialPort",
    "SpatialRegion",
    "SpatialReservation",
    "SpatialRoute",
    "SpatialTopology",
    "validate_spatial_topology",
]
