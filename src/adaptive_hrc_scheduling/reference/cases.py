"""S16 synthetic development fixtures; not a projection of a complete factory run."""

from dataclasses import replace

from adaptive_hrc_scheduling.reference.domain import (
    Alternative,
    Instance,
    Person,
    Product,
    Resource,
    Task,
)


def tiny_cases():
    machine = Resource("CUT1")
    unary = Instance(
        "TINY_UNARY",
        4,
        (
            Task("A", (Alternative("H", 2, (("CUT1", 1),)),)),
            Task("B", (Alternative("H", 1, (("CUT1", 1),)),)),
        ),
        (machine,),
    )
    precedence = replace(
        unary,
        id="TINY_PRECEDENCE",
        tasks=(unary.tasks[0], replace(unary.tasks[1], predecessors=("A",))),
    )
    alternatives = Instance(
        "TINY_BINDINGS",
        4,
        (
            Task(
                "A",
                (
                    Alternative("FAST", 1, (("WELD_A", 1),), (("WELD", "P1"),), 3),
                    Alternative("SLOW", 2, (("WELD_B", 1),), (("WELD", "P2"),), 0),
                ),
            ),
            Task("B", (Alternative("H", 1, (("WELD_B", 1),), (("WELD", "P1"),)),)),
        ),
        (Resource("WELD_A"), Resource("WELD_B")),
        (Person("P1", ("WELD",), ((0, 2), (3, 4))), Person("P2", ("WELD",), ((0, 4),))),
    )
    product = Instance(
        "TINY_RECEIPT",
        5,
        (
            Task("READY", (Alternative("H", 1, (("OUT1", 1),)),)),
            Task(
                "STORE", (Alternative("MOVE", 1, (("CR1", 1),), cost=2, kind="MOVE"),), ("READY",)
            ),
            Task("RECEIVE", (Alternative("GATE", 1, kind="GATE"),), ("STORE",), release=3),
        ),
        (Resource("OUT1"), Resource("FG", 1), Resource("CR1")),
        products=(Product("M1", "READY", "STORE", "RECEIVE", "OUT1", "FG", 3, 2),),
    )
    return unary, precedence, alternatives, product


def buffer_case(capacity=2):
    tasks, products = [], []
    for i in range(1, 4):
        ready, store, receive = f"READY{i}", f"STORE{i}", f"RECEIVE{i}"
        tasks.extend(
            (
                Task(
                    ready,
                    (Alternative("H", 1, (("OUT1", 1),)),),
                    release=2 * (i - 1),
                    latest_end=2 * i - 1,
                ),
                Task(
                    store,
                    (Alternative("MOVE", 1, (("CR1", 1),), (("DRIVE", "D1"),), 2, "MOVE"),),
                    (ready,),
                ),
                Task(
                    receive,
                    (Alternative("GATE", 1, (("RECEIVER", 1),), kind="GATE"),),
                    (store,),
                    release=8,
                ),
            )
        )
        products.append(Product(f"M{i}", ready, store, receive, "OUT1", "FG", 16))
    return Instance(
        f"BUFFER_B{capacity}",
        16,
        tuple(tasks),
        (Resource("OUT1"), Resource("FG", capacity), Resource("CR1"), Resource("RECEIVER", 3)),
        (Person("D1", ("DRIVE",), ((0, 16),)),),
        tuple(products),
    )


def all_cases():
    tiny = tiny_cases()
    unavailable = replace(
        tiny[0],
        id="INFEASIBLE_CAPACITY",
        resources=(Resource("CUT1", 1),),
        tasks=(replace(tiny[0].tasks[0], alternatives=(Alternative("H", 2, (("CUT1", 2),)),)),),
    )
    return tiny + (buffer_case(2), buffer_case(3), unavailable)
