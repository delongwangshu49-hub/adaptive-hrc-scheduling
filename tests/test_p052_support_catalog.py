"""Exact append_catalog method with a fake USD surface; not a Kit witness."""

import ast
import copy
import math
import sys
import types
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

R = next(
    p for p in Path(__file__).resolve().parents if (p / "src/adaptive_hrc_scheduling").is_dir()
)
sys.path[:0] = [str(R), str(R / "src"), str(R / "scripts")]
from build_simulation_production import configuration  # noqa: E402

from adaptive_hrc_scheduling import production_supports as support  # noqa: E402
from adaptive_hrc_scheduling.contracts.codec import require  # noqa: E402
from adaptive_hrc_scheduling.domain import production as m  # noqa: E402
from adaptive_hrc_scheduling.dynamic_orders import generate, template_registry  # noqa: E402
from sim.isaac.scene.model import Box, key, sweep  # noqa: E402

SOURCE = R / "sim/isaac/scene/production_port.py"


def method(path, cls, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    fn = next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == name)
    ns = dict(
        __package__="p052_scene_fixture",
        require=require,
        m=m,
        key=key,
        UsdGeom=NS(
            Imageable=lambda p: NS(
                ComputeVisibility=lambda: "inherited" if p.visible else "invisible"
            )
        ),
    )
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), "exec"), ns)
    return ns[name]


def support_class():
    p = R / "sim/isaac/scene/production_support_port.py"
    tree = ast.parse(p.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    ns = dict(
        math=math,
        replace=replace,
        support=support,
        require=require,
        m=m,
        Box=Box,
        key=key,
        sweep=sweep,
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(p), "exec"), ns)
    return ns["SupportPort"]


class Scene:
    def __init__(self):
        self.mapping = {}
        self.prims = {}
        self.positions = {}
        self.obstacles = []
        self.stage = self

    def GetPrimAtPath(self, path):
        return self.prims.get(path)

    def ident(self, ident, path, position):
        self.mapping[ident] = path
        self.prims[path] = NS(visible=True, attrs={})
        self.positions[ident] = tuple(position)

    def shape(self, *a, **kw):
        pass

    def attr(self, prim, k, v):
        prim.attrs[k] = v

    def RemovePrim(self, path):
        self.prims.pop(path, None)

    def actual_obstacles(self, ids):
        return self.obstacles


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.initial = configuration()
        payload = dict(
            order_id="NORMAL",
            template_id="SR-W1",
            template_revision="v1",
            template_sha256=template_registry()["SR-W1"],
            quantity=2,
            due_sim_h=2300,
            priority="NORMAL",
            material_plan_id="TEMPLATE-JIT-v1",
            arrival_rule="REQUEST_EFFECTIVE_TIME",
        )
        cls.three, cls.added = generate(cls.initial, payload, 1)
        cls.four, cls.last = generate(
            cls.three, dict(payload, order_id="URGENT", quantity=1, priority="URGENT"), 2
        )
        cls.append = staticmethod(method(SOURCE, "USDProductionPort", "append_catalog"))
        cls.Support = support_class()

    def setUp(self):
        scene = Scene()
        scene.ident("existing", "/existing", (1, 2, 3))
        self.p = NS(
            scene=scene,
            config=self.initial,
            mapping=scene.mapping,
            loads={},
            expected={"existing": (1, 2, 3)},
            quantities={},
            run_id="FIXTURE",
            epoch=0,
            ops={x.id: x for x in self.initial.operations},
            routes={x.id: x for x in self.initial.routes},
            places={x.id: x.position for x in self.initial.places},
            variable_ports={
                c.place_id for layout in self.initial.support_layouts for c in layout.contacts
            },
            support_aliases={},
        )
        self.p.position = lambda i: scene.positions[i]
        self.p.prim = lambda i: scene.GetPrimAtPath(scene.mapping[i])
        s = self.Support.__new__(self.Support)
        s.parent = self.p
        s.scene = scene
        s.config = self.initial
        s.layouts = {x.id: x for x in self.initial.support_layouts}
        s.states = {x.root: x for x in support.initial(self.initial)}
        s.previous = {"existing-command": self.initial.support_layouts[0]}
        s.sampled = {"existing-command": 0.01}
        s.expected = lambda root: tuple(
            m.BeamReadback(x.index, x.position, True, True) for x in s.states[root].beams
        )
        self.p.support_port = s
        correction = types.ModuleType("p052_scene_fixture.scene_correction")
        correction.presence = lambda parent, i, visible: setattr(parent.prim(i), "visible", visible)
        self.mods = patch.dict(
            sys.modules,
            {
                "p052_scene_fixture": types.ModuleType("p052_scene_fixture"),
                "p052_scene_fixture.scene_correction": correction,
            },
        )
        self.mods.start()
        self.addCleanup(self.mods.stop)

    def append_to(self, c, ids, n):
        return self.append(self.p, c, ids, n)

    def append_four(self):
        self.append_to(self.three, self.added, 1)
        self.append_to(self.four, self.last, 2)

    def command(self):
        ident = "SUPPORT-MEP-RECEIVE-PRODUCT-4.GROUP-COAT-PRODUCT"
        layout = next(x for x in self.four.support_layouts if x.id == ident)
        op = support.change_operation(self.four, layout, "PRODUCT-4", "FIXTURE-SUPPORT")
        self.p.ops[op.id] = op
        return NS(id="FIXTURE-COMMAND", operation_id=op.id, resume_of=None), layout

    def test_two_additions_expose_exact_new_layout_and_config(self):
        self.append_four()
        s = self.p.support_port
        self.assertIs(s.config, self.four)
        self.assertEqual(s.layouts, {x.id: x for x in self.four.support_layouts})
        self.assertIn(self.command()[1].id, s.layouts)

    def test_existing_beams_states_history_and_samples_unchanged(self):
        s = self.p.support_port
        refs = (s.states, s.previous, s.sampled, s.layouts)
        values = copy.deepcopy(refs[:3])
        position = self.p.position("existing")
        self.append_four()
        for a, b in zip(refs, (s.states, s.previous, s.sampled, s.layouts)):
            self.assertIs(a, b)
        self.assertEqual((s.states, s.previous, s.sampled), values)
        self.assertEqual(self.p.position("existing"), position)

    def test_successful_added_loads_remain_hidden_empty(self):
        rows = self.append_to(self.three, self.added, 1)
        self.assertTrue(rows)
        self.assertTrue(
            all(not r["visible"] and r["actual_position_m"] == [-30, 0, 0] for r in rows)
        )
        self.assertTrue(all(r["quantity"] in (None, 0) for r in rows))

    def test_failed_preparation_does_not_publish_new_support_catalog(self):
        s = self.p.support_port
        old = dict(s.layouts)
        original = self.p.scene.shape
        self.p.scene.shape = lambda *a, **kw: (_ for _ in ()).throw(
            ValueError("INJECTED_PREPARATION_FAILURE")
        )
        with self.assertRaisesRegex(ValueError, "INJECTED_PREPARATION_FAILURE"):
            self.append_to(self.three, self.added, 1)
        self.assertIs(s.config, self.initial)
        self.assertIs(self.p.config, self.initial)
        self.assertEqual(s.layouts, old)
        self.assertEqual(set(self.p.mapping), {"existing"})
        self.p.scene.shape = original

    def test_new_layout_reaches_original_path_checks(self):
        self.append_four()
        cmd, layout = self.command()
        self.p.support_port.check_paths(cmd)
        self.assertTrue(support.movements(self.four, None, layout))

    def test_collision_still_rejected(self):
        self.append_four()
        cmd, layout = self.command()
        move = support.movements(self.four, None, layout)[0]
        self.p.scene.obstacles = [Box("INJECTED_OBSTACLE", move.paths[0][0], (0.2, 0.6, 0.2))]
        with self.assertRaisesRegex(ValueError, "COLLISION"):
            self.p.support_port.check_paths(cmd)

    def test_actual_position_drift_still_rejected(self):
        self.append_four()
        cmd, layout = self.command()
        s = self.p.support_port
        prior = s.states[layout.root]
        s.states[layout.root] = replace(
            prior, beams=(replace(prior.beams[0], position=(999, 999, 999)), *prior.beams[1:])
        )
        with self.assertRaisesRegex(ValueError, "ACTUAL_SUPPORT_PROGRESS_DRIFT"):
            s.check_paths(cmd)


if __name__ == "__main__":
    unittest.main()
