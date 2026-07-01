import twingraph as tg


def _twin():
    g = tg.TwinGraph.new("VizDemo", created_by="t")
    g.entities.append(tg.Entity(id="bat", type_ref="metis.energy.Battery@1", name="B",
                                properties={"power_max_mw": 1.0, "energy_max_mwh": 4.0}))
    g.entities.append(tg.Entity(id="node", type_ref="metis.energy.MarketNode@1", name="N",
                                properties={"market": "NYISO", "location_id": "ZONE_J"}))
    g.variables.append(tg.Variable(id="soc", owner_ref="bat", name="state_of_charge",
                                   role="state", unit="MW.h"))
    g.relations.append(tg.Relation(id="r", type_ref="connected_to",
                                   source_entity_id="bat", target_entity_id="node"))
    return g


def test_mermaid_has_nodes_and_edges():
    m = tg.to_mermaid(_twin())
    assert m.startswith("graph LR")
    assert "bat[" in m and "node[" in m
    assert "bat -->|connected_to| node" in m
    assert "state_of_charge" in m


def test_dot_is_a_digraph():
    d = tg.to_dot(_twin())
    assert d.startswith("digraph twin {") and d.rstrip().endswith("}")
    assert "bat -> node" in d
