"""Lossless immutable-object graph for independently audited replay snapshots.

References only share equal source objects; no state fields, events or intervals
are omitted. The reader reconstructs the same domain records before auditing.
"""

import json
from dataclasses import fields, is_dataclass

from .contracts.codec import require
from .domain import production as m


def dump(proof, stream):
    """Write the same compact JSON bytes with one C-encoded record per chunk.

    The standard streaming encoder writes every scalar token separately. Proof
    graphs already provide natural record boundaries, so retain streaming across
    nodes/decisions without materializing a second full serialized proof string.
    """

    def array(rows):
        stream.write("[")
        for i, row in enumerate(rows):
            if i:
                stream.write(",")
            stream.write(json.dumps(row, separators=(",", ":")))
        stream.write("]")

    def mapping(value, graph=False):
        stream.write("{")
        for i, (key, item) in enumerate(value.items()):
            if i:
                stream.write(",")
            stream.write(json.dumps(key) + ":")
            if key == "snapshot_graph" and not graph:
                mapping(item, graph=True)
            elif type(item) is list:
                array(item)
            else:
                stream.write(json.dumps(item, separators=(",", ":")))
        stream.write("}")

    mapping(proof)


def encode(value):
    nodes, seen = [], {}

    def visit(item):
        if type(item) in (str, int, float, bool, type(None)):
            return item
        require(is_dataclass(item) or type(item) is tuple, "PROOF_GRAPH_TYPE")
        key = id(item)
        if key in seen:
            return {"ref": seen[key]}
        if type(item) is tuple:
            row = dict(kind="tuple", values=[visit(x) for x in item])
        else:
            row = dict(
                kind=type(item).__name__,
                values=[visit(getattr(item, f.name)) for f in fields(item)],
            )
        index = len(nodes)
        seen[key] = index
        nodes.append(row)
        return {"ref": index}

    root = visit(value)
    return dict(format="P051-IMMUTABLE-GRAPH-1", nodes=nodes, root=root)


def decode(data):
    require(
        set(data) == {"format", "nodes", "root"} and data["format"] == "P051-IMMUTABLE-GRAPH-1",
        "PROOF_GRAPH_FORMAT",
    )
    values = []

    def resolve(item):
        if type(item) is dict:
            require(
                set(item) == {"ref"}
                and type(item["ref"]) is int
                and 0 <= item["ref"] < len(values),
                "PROOF_GRAPH_REFERENCE",
            )
            return values[item["ref"]]
        require(type(item) in (str, int, float, bool, type(None)), "PROOF_GRAPH_ATOM")
        return item

    for row in data["nodes"]:
        require(set(row) == {"kind", "values"} and type(row["values"]) is list, "PROOF_GRAPH_NODE")
        args = [resolve(x) for x in row["values"]]
        if row["kind"] == "tuple":
            result = tuple(args)
        else:
            cls = getattr(m, row["kind"], None)
            require(
                isinstance(cls, type) and is_dataclass(cls) and len(args) == len(fields(cls)),
                "PROOF_GRAPH_RECORD",
            )
            result = cls(*args)
        values.append(result)
    result = resolve(data["root"])
    require(isinstance(result, m.ExecutionSnapshot), "PROOF_GRAPH_ROOT")
    return result
