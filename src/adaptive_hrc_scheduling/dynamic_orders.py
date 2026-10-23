"""P042 dynamic family: immutable approved templates and explicit configuration views.

S18 admission is unchanged. A materialized view has its own real digest; C0 and
every issued command remain immutable. The history is also usable by audits.
"""

import json
from dataclasses import replace
from functools import lru_cache
from importlib.resources import files

from adaptive_hrc_scheduling.contracts.codec import decode, require
from adaptive_hrc_scheduling.contracts.production import digest, validate
from adaptive_hrc_scheduling.contracts.session import digest as sha
from adaptive_hrc_scheduling.domain import production as m

VERSION = "P042-PROD-1.0"
SPECIFICATION = "P042-PROD-SPEC-1.0"
MATERIAL_PLANS = {"TEMPLATE-JIT-v1": 0, "TEMPLATE-DELAY-1H-v1": 1}
COLLECTIONS = (
    "products",
    "core_activities",
    "core_edges",
    "places",
    "routes",
    "lots",
    "entities",
    "operations",
    "evidence",
    "groups",
    "bindings",
    "support_layouts",
)


@lru_cache(maxsize=1)
def templates():
    raw = files("adaptive_hrc_scheduling").joinpath("simulation_inputs/P042_templates_v1.json")
    data = json.loads(raw.read_bytes())
    for value in data.values():
        validate(decode(m.Configuration, value))
    return data


def template_registry():
    return {key: sha(value) for key, value in templates().items()}


def production_schema(kind):
    from adaptive_hrc_scheduling.contracts.production import production_schema as static_schema

    value = static_schema(kind, simulation=True)
    for name, definition in value["$defs"].items():
        props = definition.get("properties", {})
        if "schema_version" in props:
            props["schema_version"] = {"enum": [VERSION]}
        if name == "Configuration":
            props["specification"] = {"enum": [SPECIFICATION]}
        if name == "WorldEvent":
            props["kind"]["enum"].append("CATALOG_REGISTER")
    return value


def _key(row):
    if hasattr(row, "id"):
        return row.id
    if isinstance(row, m.Edge):
        return row.source, row.target, row.relation
    return row.activity_id, row.mode_id, row.unit_id


def _merge(old, added):
    indexed = {_key(x): x for x in old}
    for row in added:
        key = _key(row)
        require(key not in indexed or indexed[key] == row, "GENERATION_ID_COLLISION:" + str(key))
        indexed[key] = row
    return tuple(indexed.values())


@lru_cache(maxsize=40)
def instantiate(template_id, pid):
    require(template_id in templates(), "TEMPLATE_UNSUPPORTED")
    require(pid.startswith("PRODUCT-") and int(pid[8:]) >= 1, "PRODUCT_ID")
    value = json.loads(json.dumps(templates()[template_id]).replace("PRODUCT-1", pid))
    if int(pid[8:]) % 2 == 0:
        preserved = json.loads(
            files("adaptive_hrc_scheduling")
            .joinpath("simulation_inputs/S15_preserved_inputs.json")
            .read_bytes()
        )
        even = json.loads(
            json.dumps(preserved[template_id]["even_buffer_routes"]).replace("PRODUCT-1", pid)
        )
        routes = {r["id"]: r for r in even}
        value["routes"] = [routes.get(r["id"], r) for r in value["routes"]]
        for op in value["operations"]:
            if op["id"] == pid + ".BUFFER":
                op["target"] = "FG2"
            if op["id"] == pid + ".SHIP":
                op["location"] = "FG2"
    # Template order IDs are placeholders, never registered runtime objects.
    return decode(m.Configuration, value)


def generate(config, payload, now_h):
    require(not config.rework_enabled, "DYNAMIC_REWORK_TEMPLATE_UNSUPPORTED")
    require(payload["template_revision"] == "v1", "TEMPLATE_UNSUPPORTED")
    require(
        template_registry().get(payload["template_id"]) == payload["template_sha256"],
        "TEMPLATE_DIGEST",
    )
    require(payload["material_plan_id"] in MATERIAL_PLANS, "MATERIAL_PLAN_UNSUPPORTED")
    require(payload["due_sim_h"] > now_h, "DUE_PASSED")
    ids = {p.id for p in config.products}
    order_ids = {p.order_id for p in config.products} | {payload["order_id"]}
    start = max(int(p[8:]) for p in ids) + 1
    result = config
    generated = []
    for n in range(start, start + payload["quantity"]):
        pid = f"PRODUCT-{n}"
        require(pid != payload["order_id"], "GENERATION_ID_COLLISION")
        template = instantiate(payload["template_id"], pid)
        generated_ids = {
            row.id for name in COLLECTIONS for row in getattr(template, name) if hasattr(row, "id")
        }
        require(not generated_ids & order_ids, "GENERATION_ID_COLLISION")
        if config.schema_version == "P043-PROD-1.0":
            require(
                not generated_ids & {p.id for p in config.people},
                "GENERATION_PERSON_ID_COLLISION",
            )
        product = replace(
            template.products[0],
            order_id=payload["order_id"],
            release_h=now_h,
            due_h=payload["due_sim_h"],
        )
        template = replace(template, products=(product,))
        result = replace(
            result,
            **{key: _merge(getattr(result, key), getattr(template, key)) for key in COLLECTIONS},
        )
        generated.append(pid)
    from adaptive_hrc_scheduling import production_supports
    from adaptive_hrc_scheduling.production_admission import profile

    result = replace(
        result,
        schema_version=config.schema_version
        if config.schema_version == "P043-PROD-1.0"
        else VERSION,
        specification=config.specification
        if config.schema_version == "P043-PROD-1.0"
        else SPECIFICATION,
        research=profile(result),
        support_layouts=production_supports.layouts(result),
    )
    validate(result)
    return result, tuple(generated)


def validate_dynamic_configuration(config):
    """Validate a separate family through the exact unchanged S18 physical model."""
    require(config.specification == SPECIFICATION, "DYNAMIC_SPECIFICATION")
    require(not config.rework_enabled, "DYNAMIC_REWORK_TEMPLATE_UNSUPPORTED")
    from adaptive_hrc_scheduling.production_admission import validate_admission

    canonical = replace(
        config,
        schema_version="S18-PROD-2.0",
        specification="S18-PROD-SPEC-2.0",
        products=tuple(
            replace(p, due_h=templates()[p.variant]["products"][0]["due_h"])
            for p in config.products
        ),
    )
    validate_admission(canonical)


class CatalogHistory:
    """Append-only views, with deterministic generation proof, no executor dependency."""

    def __init__(self, initial, generations=()):
        self.initial = initial
        self.generations = []
        self.views = {digest(initial): initial}
        self.current = initial
        self.by_event = {}
        self.priorities = {}
        for row in generations:
            self.append(row)

    def append(self, row):
        require(row["before_config_sha256"] == digest(self.current), "GENERATION_PREVIOUS_VIEW")
        config, products = generate(self.current, row["payload"], row["sim_h"])
        require(
            list(products) == row["product_ids"] and digest(config) == row["config_sha256"],
            "GENERATION_RECONSTRUCTION",
        )
        require(row["event_id"] not in self.by_event, "GENERATION_DUPLICATE_EVENT")
        self.generations.append(row)
        self.views[digest(config)] = config
        self.by_event[row["event_id"]] = row
        self.current = config
        for pid in products:
            self.priorities[pid] = row["payload"]["priority"]
        return config

    def config_at(self, events):
        config = self.initial
        for event in events:
            if event.id in self.by_event:
                config = self.views[self.by_event[event.id]["config_sha256"]]
        return config

    def event_config(self, event):
        require(event.config_sha256 in self.views, "UNKNOWN_EVENT_VIEW")
        return self.views[event.config_sha256]

    def command_config(self, command):
        require(command.config_sha256 in self.views, "UNKNOWN_COMMAND_VIEW")
        return self.views[command.config_sha256]

    def validate_event(self, event):
        config = self.event_config(event)
        validate(replace(event, command=None, command_sha256=None, kind="CLOCK"), config=config)
        if event.command:
            validate(event.command, config=self.command_config(event.command))
            require(event.command_sha256 == digest(event.command), "COMMAND_DIGEST")

    def priority_bias(self):
        # EDD still uses real due_h within the explicit urgency class.
        activities = {a.id: a.product_id for a in self.current.core_activities}
        activities.update({op.activity_id: op.product_id for op in self.current.operations})
        return tuple(
            (aid, -1 if self.priorities.get(pid) == "URGENT" else 0)
            for aid, pid in activities.items()
        )

    def fork(self):
        import copy

        other = copy.copy(self)
        other.generations = list(self.generations)
        other.views = dict(self.views)
        other.by_event = dict(self.by_event)
        other.priorities = dict(self.priorities)
        if hasattr(self, "active_products"):
            other.active_products = set(self.active_products)
        return other

    def score(self, state, prefix):
        from adaptive_hrc_scheduling.production_admission import completed_activity

        progress = {
            p.id: sum(
                completed_activity(self.current, state.completed, a.id)
                and not completed_activity(self.current, prefix.completed, a.id)
                for a in self.current.core_activities
                if a.product_id == p.id
            )
            for p in self.current.products
        }
        return (
            -sum(progress[p] for p in progress if self.priorities.get(p) == "URGENT"),
            -sum(
                progress[p.id] / max(0.01, p.due_h - prefix.time_h) for p in self.current.products
            ),
            sum(h.exposure for h in state.humans),
            max(h.exposure for h in state.humans),
        )


def append_world(world, config, products):
    """Only add initially empty state; preserve every pre-existing state record."""
    from adaptive_hrc_scheduling.production_backend import initial_state

    added = initial_state(config)
    ids = set(products)
    new_lots = {x.id for x in config.lots if x.product_id in ids}
    new_entities = {x.id for x in config.entities if x.product_id in ids}
    world.config, world.config_hash = config, digest(config)
    world.operations.update({x.id: x for x in config.operations})
    world.routes.update({x.id: x for x in config.routes})
    world.places.update({x.id: x for x in config.places})
    world.lots.update({x.id: x for x in config.lots})
    world.entities.update({x.id: x for x in config.entities})
    world.s = replace(
        world.s,
        lots=world.s.lots + tuple(x for x in added.lots if x.id in new_lots),
        positions=world.s.positions
        + tuple(x for x in added.positions if x.id in new_lots | new_entities),
        products=world.s.products
        + tuple(replace(x, released=False) for x in added.products if x.product_id in ids),
        masses=world.s.masses + tuple(m.MassState(i, 0) for i in sorted(new_entities)),
        research=config.research,
    )
    world._capacity()
