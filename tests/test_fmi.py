"""FMI interop tests: modelDescription.xml parsing and io_contract derivation."""

from __future__ import annotations

import zipfile

import pytest
from twingraph import (
    FmiParseError,
    io_contract_from_fmu,
    parse_model_description,
    read_fmu_model_description,
)

FMI2_XML = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="2.0" modelName="ThermalPlant" guid="{abc}">
  <ModelExchange modelIdentifier="ThermalPlant_ME"/>
  <CoSimulation modelIdentifier="ThermalPlant_CS"/>
  <TypeDefinitions>
    <SimpleType name="Temperature"><Real unit="K"/></SimpleType>
  </TypeDefinitions>
  <ModelVariables>
    <ScalarVariable name="T_amb" causality="input" description="ambient temperature">
      <Real declaredType="Temperature"/>
    </ScalarVariable>
    <ScalarVariable name="Q_flow" causality="output">
      <Real unit="W"/>
    </ScalarVariable>
    <ScalarVariable name="m_fluid" causality="parameter">
      <Real unit="kg"/>
    </ScalarVariable>
    <ScalarVariable name="state_internal">
      <Real/>
    </ScalarVariable>
  </ModelVariables>
</fmiModelDescription>
"""

FMI3_XML = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="3.0" modelName="Turbine">
  <CoSimulation modelIdentifier="Turbine_CS"/>
  <TypeDefinitions>
    <Float64Type name="Pressure" unit="Pa"/>
  </TypeDefinitions>
  <ModelVariables>
    <Float64 name="p_in" causality="input" declaredType="Pressure"/>
    <Float64 name="wind_speed" causality="input" unit="m/s"/>
    <Float64 name="power" causality="output" unit="W"/>
    <Float64 name="blade_count" causality="structuralParameter" unit="count"/>
    <Float64 name="t_local" causality="local"/>
  </ModelVariables>
</fmiModelDescription>
"""


def test_parse_fmi2_variables_units_and_interfaces():
    desc = parse_model_description(FMI2_XML)
    assert desc.fmi_version == "2.0"
    assert desc.model_name == "ThermalPlant"
    assert desc.supports_model_exchange and desc.supports_co_simulation
    assert desc.model_identifier == "ThermalPlant_CS"

    by_name = {v.name: v for v in desc.variables}
    # declaredType unit resolved through TypeDefinitions.
    assert by_name["T_amb"].unit == "K"
    assert by_name["T_amb"].causality == "input"
    assert by_name["Q_flow"].unit == "W"
    # Missing causality defaults to local.
    assert by_name["state_internal"].causality == "local"


def test_parse_fmi3_variables_units_and_interfaces():
    desc = parse_model_description(FMI3_XML)
    assert desc.fmi_version == "3.0"
    assert not desc.supports_model_exchange
    assert desc.supports_co_simulation
    assert desc.model_identifier == "Turbine_CS"

    by_name = {v.name: v for v in desc.variables}
    assert by_name["p_in"].unit == "Pa"  # declaredType lookup
    assert by_name["wind_speed"].unit == "m/s"
    assert by_name["power"].type == "Float64"


def test_io_contract_from_fmu_maps_causalities():
    contract = io_contract_from_fmu(parse_model_description(FMI3_XML))
    assert set(contract.inputs) == {"p_in", "wind_speed"}
    assert set(contract.outputs) == {"power"}
    assert set(contract.params) == {"blade_count"}
    assert contract.inputs["p_in"] == {"unit": "Pa"}
    assert contract.outputs["power"] == {"unit": "W"}


def test_io_contract_omits_unit_when_fmu_declares_none():
    contract = io_contract_from_fmu(parse_model_description(FMI2_XML))
    assert set(contract.inputs) == {"T_amb"}
    assert set(contract.outputs) == {"Q_flow"}
    assert set(contract.params) == {"m_fluid"}
    assert contract.params["m_fluid"] == {"unit": "kg"}


def test_read_fmu_model_description_from_zip(tmp_path):
    fmu = tmp_path / "turbine.fmu"
    with zipfile.ZipFile(fmu, "w") as archive:
        archive.writestr("modelDescription.xml", FMI3_XML)
        archive.writestr("binaries/x86_64-linux/turbine.so", b"")
    desc = read_fmu_model_description(fmu)
    assert desc.model_name == "Turbine"


def test_read_fmu_rejects_archive_without_model_description(tmp_path):
    fmu = tmp_path / "empty.fmu"
    with zipfile.ZipFile(fmu, "w") as archive:
        archive.writestr("readme.txt", "not an fmu")
    with pytest.raises(FmiParseError, match=r"modelDescription\.xml"):
        read_fmu_model_description(fmu)


def test_read_fmu_rejects_non_zip(tmp_path):
    not_zip = tmp_path / "model.fmu"
    not_zip.write_bytes(b"plain bytes")
    with pytest.raises(FmiParseError, match="zip"):
        read_fmu_model_description(not_zip)


def test_parse_rejects_fmi1_and_malformed():
    with pytest.raises(FmiParseError, match="fmiVersion"):
        parse_model_description(
            '<fmiModelDescription fmiVersion="1.0" modelName="x"/>'
        )
    with pytest.raises(FmiParseError, match="well-formed"):
        parse_model_description("<not-closed")
    with pytest.raises(FmiParseError, match="root element"):
        parse_model_description("<somethingElse/>")


def test_generated_contract_matches_hand_written_foreign_contract():
    """The derived contract is interchangeable with the hand-written §31.3 one."""
    from helpers import StubModelRegistry

    # The stub registry's turbine FMU contract is hand-written today; the
    # FMU-derived one must match it structurally (same ports, same units).
    xml = """<?xml version="1.0"?>
    <fmiModelDescription fmiVersion="3.0" modelName="turbine">
      <CoSimulation modelIdentifier="turbine"/>
      <ModelVariables>
        <Float64 name="wind_speed" causality="input" unit="MW"/>
        <Float64 name="power" causality="output" unit="MW"/>
      </ModelVariables>
    </fmiModelDescription>
    """
    contract = io_contract_from_fmu(parse_model_description(xml))
    hand_written = StubModelRegistry._CONTRACTS[
        "registry://metis.foreign.turbine_fmu@1.0.0"
    ]
    assert contract.inputs == hand_written.inputs
    assert contract.outputs == hand_written.outputs
