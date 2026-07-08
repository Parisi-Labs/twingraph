"""FMI interop helpers for foreign `fmu` model bindings (spec §31.3).

TwinGraph never executes an FMU — foreign references are validated at compile
and dispatched by the application runtime. What the compiler *does* need is the
binding's ``io_contract``, and hand-transcribing one from an FMU's
``modelDescription.xml`` is exactly the kind of drift the contract check exists
to catch. This module derives it mechanically instead:

    desc = read_fmu_model_description("thermal.fmu")
    contract = io_contract_from_fmu(desc)

Supports FMI 2.x and 3.x model descriptions, including ``declaredType`` unit
lookups through ``TypeDefinitions``. stdlib only (``xml.etree`` + ``zipfile``).
Before parsing, TwinGraph rejects ``DOCTYPE`` and ``ENTITY`` declarations to
avoid entity-expansion and external-entity constructs without adding a runtime
dependency.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from .errors import FmiParseError
from .registry import IOContract

_MODEL_DESCRIPTION = "modelDescription.xml"
_UNSAFE_XML_DECLARATION = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)

# FMI 3.0 variable element tags (FMI 2.0 uses <ScalarVariable> with a typed child).
_FMI3_VARIABLE_TAGS = frozenset(
    {
        "Float32",
        "Float64",
        "Int8",
        "UInt8",
        "Int16",
        "UInt16",
        "Int32",
        "UInt32",
        "Int64",
        "UInt64",
        "Boolean",
        "String",
        "Binary",
        "Enumeration",
        "Clock",
    }
)

_PARAMETER_CAUSALITIES = frozenset(
    {"parameter", "calculatedParameter", "structuralParameter"}
)


@dataclass(frozen=True)
class FmiVariable:
    """One scalar variable from a model description."""

    name: str
    causality: str  # input | output | parameter | calculatedParameter | ...
    type: str  # Real, Float64, Integer, Boolean, ...
    unit: str | None = None
    declared_type: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class FmuModelDescription:
    """Typed summary of an FMU's modelDescription.xml."""

    fmi_version: str
    model_name: str
    supports_model_exchange: bool
    supports_co_simulation: bool
    model_identifier: str | None
    variables: tuple[FmiVariable, ...]

    def inputs(self) -> tuple[FmiVariable, ...]:
        return tuple(v for v in self.variables if v.causality == "input")

    def outputs(self) -> tuple[FmiVariable, ...]:
        return tuple(v for v in self.variables if v.causality == "output")

    def parameters(self) -> tuple[FmiVariable, ...]:
        return tuple(
            v for v in self.variables if v.causality in _PARAMETER_CAUSALITIES
        )


def parse_model_description(xml_text: str) -> FmuModelDescription:
    """Parse a modelDescription.xml document (FMI 2.x or 3.x)."""
    _reject_unsafe_xml_declarations(xml_text)
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise FmiParseError(f"modelDescription.xml is not well-formed XML: {exc}") from exc
    if root.tag != "fmiModelDescription":
        raise FmiParseError(
            f"expected root element 'fmiModelDescription', got '{root.tag}'"
        )
    fmi_version = root.get("fmiVersion", "")
    if fmi_version.startswith("2."):
        variables = _parse_variables_fmi2(root)
    elif fmi_version.startswith("3."):
        variables = _parse_variables_fmi3(root)
    else:
        raise FmiParseError(
            f"unsupported fmiVersion '{fmi_version}' (FMI 2.x and 3.x are supported)"
        )

    me = root.find("ModelExchange")
    cs = root.find("CoSimulation")
    identifier = None
    for interface in (cs, me):
        if interface is not None and interface.get("modelIdentifier"):
            identifier = interface.get("modelIdentifier")
            break

    return FmuModelDescription(
        fmi_version=fmi_version,
        model_name=root.get("modelName", ""),
        supports_model_exchange=me is not None,
        supports_co_simulation=cs is not None,
        model_identifier=identifier,
        variables=variables,
    )


def read_fmu_model_description(path: str | Path) -> FmuModelDescription:
    """Read modelDescription.xml out of a packed ``.fmu`` (zip) archive."""
    fmu_path = Path(path)
    try:
        with zipfile.ZipFile(fmu_path) as archive:
            xml_text = archive.read(_MODEL_DESCRIPTION).decode("utf-8")
    except FileNotFoundError:
        raise FmiParseError(f"FMU archive not found: {fmu_path}") from None
    except zipfile.BadZipFile as exc:
        raise FmiParseError(f"'{fmu_path}' is not a zip archive: {exc}") from exc
    except KeyError:
        raise FmiParseError(
            f"'{fmu_path}' contains no {_MODEL_DESCRIPTION} at the archive root"
        ) from None
    return parse_model_description(xml_text)


def _reject_unsafe_xml_declarations(xml_text: str) -> None:
    if _UNSAFE_XML_DECLARATION.search(xml_text):
        raise FmiParseError(
            "modelDescription.xml contains a DOCTYPE or ENTITY declaration; "
            "entity expansion and external entities are not supported"
        )


def io_contract_from_fmu(desc: FmuModelDescription) -> IOContract:
    """Derive the foreign binding's io_contract from a parsed model description.

    FMI causality maps directly: ``input`` -> contract inputs, ``output`` ->
    contract outputs, parameter causalities -> contract params. Units are kept
    as declared by the FMU; compile folds them through the unit registry, so SI
    spellings (``W``, ``K``, ``Pa``, ``J``, ``kg/s``) validate against twin
    variables without manual conversion.
    """
    return IOContract(
        inputs={v.name: _port(v) for v in desc.inputs()},
        outputs={v.name: _port(v) for v in desc.outputs()},
        params={v.name: _port(v) for v in desc.parameters()},
    )


def _port(v: FmiVariable) -> dict:
    return {"unit": v.unit} if v.unit else {}


def _declared_type_units_fmi2(root: ElementTree.Element) -> dict[str, str]:
    units: dict[str, str] = {}
    for simple_type in root.iterfind("TypeDefinitions/SimpleType"):
        name = simple_type.get("name")
        if not name:
            continue
        for typed in simple_type:
            unit = typed.get("unit")
            if unit:
                units[name] = unit
    return units


def _parse_variables_fmi2(root: ElementTree.Element) -> tuple[FmiVariable, ...]:
    declared_units = _declared_type_units_fmi2(root)
    variables: list[FmiVariable] = []
    for scalar in root.iterfind("ModelVariables/ScalarVariable"):
        name = scalar.get("name")
        if not name:
            raise FmiParseError("FMI 2.0 ScalarVariable without a 'name' attribute")
        typed = next(iter(scalar), None)
        if typed is None:
            raise FmiParseError(
                f"FMI 2.0 ScalarVariable '{name}' has no type element (Real, Integer, ...)"
            )
        declared_type = typed.get("declaredType")
        unit = typed.get("unit") or (
            declared_units.get(declared_type) if declared_type else None
        )
        variables.append(
            FmiVariable(
                name=name,
                causality=scalar.get("causality", "local"),
                type=typed.tag,
                unit=unit,
                declared_type=declared_type,
                description=scalar.get("description"),
            )
        )
    return tuple(variables)


def _declared_type_units_fmi3(root: ElementTree.Element) -> dict[str, str]:
    units: dict[str, str] = {}
    type_definitions = root.find("TypeDefinitions")
    if type_definitions is None:
        return units
    for typed in type_definitions:
        name = typed.get("name")
        unit = typed.get("unit")
        if name and unit:
            units[name] = unit
    return units


def _parse_variables_fmi3(root: ElementTree.Element) -> tuple[FmiVariable, ...]:
    declared_units = _declared_type_units_fmi3(root)
    model_variables = root.find("ModelVariables")
    if model_variables is None:
        return ()
    variables: list[FmiVariable] = []
    for element in model_variables:
        if element.tag not in _FMI3_VARIABLE_TAGS:
            continue
        name = element.get("name")
        if not name:
            raise FmiParseError(
                f"FMI 3.0 variable <{element.tag}> without a 'name' attribute"
            )
        declared_type = element.get("declaredType")
        unit = element.get("unit") or (
            declared_units.get(declared_type) if declared_type else None
        )
        variables.append(
            FmiVariable(
                name=name,
                causality=element.get("causality", "local"),
                type=element.tag,
                unit=unit,
                declared_type=declared_type,
                description=element.get("description"),
            )
        )
    return tuple(variables)
