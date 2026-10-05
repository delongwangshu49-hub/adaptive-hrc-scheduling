"""Explicit RP06 one-attempt wet-area repair branch; no implicit stock reset."""

from dataclasses import replace
from types import SimpleNamespace

from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.production_geometry import route


def append_rework(builder, pid):
    b = builder
    prefix = pid + ".REPAIR."
    group = pid + ".GROUP-REPAIR"
    b.groups.append(m.Group(group, pid, "REPAIR", 11, 1.2, (2.4, 2.4, 2)))
    first_new = len(b.operations)
    core = {a.code: a for a in b.core if a.product_id == pid}
    original_patch = tuple(i for i in b.rows if i.startswith(pid + ".WT-W."))
    roots = ("MEP-RECEIVE", "MEP-STORE", "KIT", "F1-KIT", "F1")

    def lot(name, quantity, disposition, parents=(), offset=(0, 0, 0), activity="WPROOF"):
        ident = prefix + name
        water = "WATER" in name
        b.lots.append(
            m.Lot(
                ident,
                pid,
                "WATER" if water else "B-WT",
                "t",
                quantity,
                quantity,
                (1.2, 0.8, 0.6),
                "UNPRODUCED" if parents else "SUPPLIER",
                tuple(parents),
                False,
                False,
                False,
                group,
                "AUX-WATER" if water else "B-WT",
                disposition,
            )
        )
        b.ports[ident] = {
            r: b.material_slot(r, ident, offset, working=r == "F1")
            for r in (tuple(reversed(roots)) if parents else roots)
        }
        b.rows[ident] = dict(carrier="CART-01", activity=activity)
        return ident

    patch = lot("PATCH", 0.02, "PRODUCT")
    water = (
        lot("WATER-01", 0.05, "AUXILIARY", offset=(-0.6, 0.8, 0), activity="TEST-SET"),
        lot("WATER-02", 0.05, "AUXILIARY", offset=(0.6, 0.8, 0), activity="TEST-SET"),
    )
    scrap = lot("SCRAP", 0.02, "SCRAP", original_patch)
    wastewater = lot("WASTE-WATER", 0.1, "WASTEWATER", water)

    def work(name, prior, hours, **kwargs):
        return b.operation(
            prefix + name,
            "WORK",
            product=pid,
            activity=prefix + name,
            source="F1",
            entity=pid,
            prior=tuple(prior),
            duration=hours,
            roles=kwargs.pop("roles", (("T1", "WET", "F1"),)),
            kappa=kwargs.pop("kappa", 0.5),
            **kwargs,
        )

    def reserve(name, items, prior):
        return b.operation(
            prefix + name + ".RESERVE",
            "RESERVE",
            product=pid,
            activity=prefix + name,
            source="F1",
            prior=tuple(prior),
            inputs=items,
            input_places=[(i, b.ports[i]["F1"]) for i, _ in items],
        )

    def outward(ident, prior):
        delivered = b.deliver(ident, pid, tuple(prior))
        quantity = next(x.quantity for x in b.lots if x.id == ident)
        return b.operation(
            ident + ".RETURN",
            "RETURN",
            product=pid,
            source=b.ports[ident]["MEP-RECEIVE"],
            target="EXTERNAL",
            entity=ident,
            prior=(delivered,),
            inputs=((ident, quantity),),
            input_places=((ident, b.ports[ident]["MEP-RECEIVE"]),),
        )

    diagnosis = work(
        "DIAGNOSE",
        (
            pid + ".WASTE-WATER.RETURN",
            pid + ".TEST-Q-POND-RETRIEVE_TOOL",
        ),
        0.5,
    )
    removal = work(
        "REMOVE",
        (diagnosis,),
        0.5,
        mass_remove_t=0.02,
        outputs=((scrap, 0.02),),
        output_places=((scrap, b.ports[scrap]["F1"]),),
    )
    scrap_return = outward(scrap, (removal,))
    patch_delivery = b.deliver(patch, pid, (scrap_return,))
    patch_reserve = reserve("INSTALL", ((patch, 0.02),), (patch_delivery,))
    installation = work(
        "INSTALL",
        (patch_reserve,),
        0.5,
        inputs=((patch, 0.02),),
        input_places=((patch, b.ports[patch]["F1"]),),
    )
    dry = work(
        "WAIT-W",
        (installation,),
        0,
        roles=(),
        kappa=0,
        wait_after=installation,
        wait_h=4,
        production_mode="WAIT",
    )
    water_delivery = tuple(b.deliver(i, pid, (installation,)) for i in water)

    def tool(name, source, target, prior):
        ident = prefix + name
        rt = route(
            SimpleNamespace(places=tuple(b.places.values())),
            ident + "-ROUTE",
            source,
            target,
            "TEST1",
        )
        return b.operation(
            ident,
            "DEPLOY_TOOL" if source == "TEST-PARK" else "RETRIEVE_TOOL",
            product=pid,
            source=source,
            target=target,
            entity="TEST1",
            prior=tuple(prior),
            roles=(("QA1", "TOOL", source),),
            equipment=("TEST1",),
            rt=rt,
        )

    deployed = tool("TEST-DEPLOY", "TEST-PARK", "TEST-USE", (dry, *water_delivery))
    water_items = tuple((i, 0.05) for i in water)
    water_reserve = reserve("TEST-SET", water_items, (deployed,))
    fill = work(
        "TEST-SET",
        (water_reserve,),
        0.5,
        inputs=water_items,
        input_places=tuple((i, b.ports[i]["F1"]) for i in water),
        equipment=("TEST1",),
        hold_device="TEST1",
        wait_gate=core["WAIT-W"].release_evidence,
    )
    soak = work(
        "WAIT-TEST",
        (fill,),
        0,
        roles=(),
        kappa=0,
        wait_after=fill,
        wait_h=4,
        production_mode="WAIT",
    )
    inspect = work(
        "Q-POND",
        (soak,),
        0.5,
        roles=(("QA1", "QA", "F1"), ("T1", "WET", "F1")),
        kappa=0,
        equipment=("TEST1",),
        release_device="TEST1",
        mass_remove_t=0.1,
        outputs=((wastewater, 0.1),),
        output_places=((wastewater, b.ports[wastewater]["F1"]),),
        wait_gate=core["WAIT-TEST"].release_evidence,
    )
    tool("TEST-RETRIEVE", "TEST-USE", "TEST-PARK", (inspect,))
    outward(wastewater, (inspect,))
    b.operations[first_new:] = [replace(op, attempt_index=1) for op in b.operations[first_new:]]
