"""Native scene selection and acknowledged view commands, outside business mutation."""

import hashlib
import math
import time

from s19b_desktop.model import atomic_json, read_json


def focus_distance(diagonal, focal_length, horizontal_aperture, vertical_aperture, aspect):
    """Fit a bounding sphere inside the narrower rendered camera angle."""
    values = (focal_length, horizontal_aperture, vertical_aperture, aspect)
    if any(not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError("CAMERA_PROJECTION_UNAVAILABLE")
    tangent = min(
        horizontal_aperture / (2 * focal_length),
        vertical_aperture / (2 * focal_length),
        horizontal_aperture / (2 * focal_length * aspect),
    )
    return max(0.5, diagonal / 2) / math.sin(math.atan(tangent)) * 1.2


def selection_only_viewport(viewport_window):
    """Consume transform selection using Kit's public manipulator interface."""
    import carb
    import omni.kit.app
    from omni.kit.manipulator.selector import ManipulatorBase
    from omni.kit.viewport.utility import disable_context_menu

    # The minimal viewport experience includes camera gestures, but selection
    # is an optional extension. USD programmatic selection alone does not make
    # clicks or selection rectangles work in the native viewport.
    carb.settings.get_settings().set(
        "/exts/omni.kit.viewport.window/startup/selectionManipulator/enabled", True
    )
    manager = omni.kit.app.get_app().get_extension_manager()
    if not manager.set_extension_enabled_immediate("omni.kit.manipulator.selection", True):
        raise RuntimeError("SCENE_SELECTION_EXTENSION_UNAVAILABLE")
    name = "hrc_selection_only"
    carb.settings.get_settings().set(
        "/persistent/exts/omni.kit.manipulator.selector/orders/" + name, -100000
    )

    class SelectionOnly(ManipulatorBase):
        def __init__(self):
            self._enabled = False
            self.context_menu_guard = disable_context_menu(viewport_window)
            super().__init__(name, "")

        def on_selection_changed(self, stage, selection, *args, **kwargs):
            return selection is not None

        @property
        def enabled(self):
            return self._enabled

        @enabled.setter
        def enabled(self, value):
            self._enabled = value

    return SelectionOnly()


def mapped_selection(paths, entities):
    matches = []
    for selected in paths:
        candidates = [
            (len(p), row["id"])
            for row in entities
            if row["kind"] != "operation"
            for p in row.get("paths", [])
            if selected == p or selected.startswith(p + "/")
        ]
        if candidates:
            length = max(n for n, _ in candidates)
            matches.extend(ident for n, ident in candidates if n == length)
    return sorted(set(matches))


def visible_paths(stage, paths):
    """A registered future object can have a USD path while remaining invisible."""
    from pxr import UsdGeom

    return [
        path
        for path in paths
        if (prim := stage.GetPrimAtPath(path)).IsValid()
        and UsdGeom.Imageable(prim)
        and UsdGeom.Imageable(prim).ComputeVisibility() != UsdGeom.Tokens.invisible
    ]


class SceneLink:
    def __init__(
        self, output, request, stage, viewport, camera, catalog, world, digest, capture, pump
    ):
        self.output, self.request, self.stage = output, request, stage
        self.viewport, self.camera, self.catalog, self.world = viewport, camera, catalog, world
        self.digest, self.capture, self.pump = digest, capture, pump
        self.sequence = 0
        self.selection_sequence = 0
        self.last_selection = None
        self.history = []
        self.last_publish = 0

    def identity(self):
        return dict(run_id=self.request["run_id"], request_id=self.request["request_id"], epoch=0)

    def selection(self):
        import omni.usd

        return omni.usd.get_context().get_selection()

    def publish(self, force=False):
        now = time.monotonic()
        if not force and now - self.last_publish < 0.3:
            return
        self.last_publish = now
        entities = self.catalog()
        paths_in_scene = {p for row in entities for p in row.get("paths", [])}
        visible = set(visible_paths(self.stage, paths_in_scene))
        entities = [
            dict(row, visible=any(p in visible for p in row.get("paths", []))) for row in entities
        ]
        paths = self.selection().get_selected_prim_paths()
        ids = mapped_selection(paths, entities)
        if (paths, ids) != self.last_selection:
            self.selection_sequence += 1
            self.last_selection = paths, ids
        atomic_json(
            self.output / "p051-scene-context.json",
            dict(
                **self.identity(),
                sampled_sim_h=self.world.s.time_h,
                source_state_revision=self.world.s.revision,
                published_monotonic_s=now,
                entities=entities,
                selection=dict(sequence=self.selection_sequence, entity_ids=ids, paths=paths),
                scope="DISPLAY_ONLY_NOT_BUSINESS_CONFIRMATION",
            ),
        )

    def camera_state(self):
        return {
            a.GetName(): a.Get()
            for a in self.stage.GetPrimAtPath(self.camera).GetAttributes()
            if a.HasAuthoredValueOpinion()
        }

    def set_camera(self, values):
        from pxr import Sdf

        prim = self.stage.GetPrimAtPath(self.camera)
        for name, value in values.items():
            attr = prim.GetAttribute(name)
            if not attr and name == "xformOp:transform":
                attr = prim.CreateAttribute(name, Sdf.ValueTypeNames.Matrix4d)
            if attr:
                attr.Set(value)

    def camera_confirm(self):
        from pxr import UsdGeom

        expected = (
            UsdGeom.Xformable(self.stage.GetPrimAtPath(self.camera))
            .ComputeLocalToWorldTransform(0)
            .GetInverse()
        )
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            self.pump()
            actual = self.viewport.frame_info.get("view")
            if actual is not None:
                error = max(
                    abs(actual[i * 4 + j] - expected[i][j]) for i in range(4) for j in range(4)
                )
                if error < 1e-4:
                    return error
        raise ValueError("CAMERA_FRAME_NOT_CONFIRMED")

    def poll(self):
        self.publish()
        inbox = self.output / "p051-view-inbox"
        for path in sorted(inbox.glob("*.json")):
            if not path.stem.isdecimal() or int(path.stem) <= self.sequence:
                continue
            data = read_json(path)
            if any(data.get(k) != v for k, v in self.identity().items()) or data.get(
                "sequence"
            ) != int(path.stem):
                continue
            self.sequence = data["sequence"]
            result = dict(**data, accepted=False, scope="DISPLAY_ONLY")
            state_before = self.digest(self.world.s)
            try:
                action = data["action"]
                entities = self.catalog()
                row = next((r for r in entities if r["id"] == data.get("entity_id")), None)
                paths = row["paths"] if row else []
                if action in ("locate", "focus"):
                    if not paths or not all(self.stage.GetPrimAtPath(p).IsValid() for p in paths):
                        raise ValueError("ENTITY_NOT_IN_SCENE")
                    if not visible_paths(self.stage, paths):
                        raise ValueError("ENTITY_NOT_VISIBLE")
                    before = hashlib.sha256(
                        self.stage.GetRootLayer().ExportToString().encode()
                    ).hexdigest()
                    self.selection().set_selected_prim_paths(paths, False)
                    result.update(
                        paths=paths, selected_paths=self.selection().get_selected_prim_paths()
                    )
                    if set(result["selected_paths"]) != set(paths):
                        raise ValueError("SELECTION_NOT_CONFIRMED")
                    after = hashlib.sha256(
                        self.stage.GetRootLayer().ExportToString().encode()
                    ).hexdigest()
                    if before != after:
                        raise ValueError("SELECTION_MUTATED_USD")
                    if action == "focus":
                        from pxr import Gf, Usd, UsdGeom

                        cache = UsdGeom.BBoxCache(
                            Usd.TimeCode.Default(),
                            [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy],
                        )
                        bounds = Gf.Range3d()
                        for p in paths:
                            bounds.UnionWith(
                                cache.ComputeWorldBound(
                                    self.stage.GetPrimAtPath(p)
                                ).ComputeAlignedRange()
                            )
                        if bounds.IsEmpty():
                            raise ValueError("ENTITY_BOUNDS_UNAVAILABLE")
                        self.history.append(self.camera_state())
                        self.history = self.history[-12:]
                        center = bounds.GetMidpoint()
                        camera = UsdGeom.Camera(self.stage.GetPrimAtPath(self.camera))
                        width, height = self.viewport.resolution
                        distance = focus_distance(
                            bounds.GetSize().GetLength(),
                            camera.GetFocalLengthAttr().Get(),
                            camera.GetHorizontalApertureAttr().Get(),
                            camera.GetVerticalApertureAttr().Get(),
                            width / max(1, height),
                        )
                        eye = center + Gf.Vec3d(1, -1, 0.8).GetNormalized() * distance
                        transform = (
                            Gf.Matrix4d().SetLookAt(eye, center, Gf.Vec3d(0, 0, 1)).GetInverse()
                        )
                        UsdGeom.Xformable(
                            self.stage.GetPrimAtPath(self.camera)
                        ).MakeMatrixXform().Set(transform)
                        result["view_matrix_max_error"] = self.camera_confirm()
                elif action == "camera":
                    from s19b_desktop.model import CAMERAS

                    if data.get("camera") not in CAMERAS:
                        raise ValueError("CAMERA_UNKNOWN")
                    self.history.append(self.camera_state())
                    self.history = self.history[-12:]
                    values = {
                        a.GetName(): a.Get()
                        for a in self.stage.GetPrimAtPath(
                            "/World/Cameras/" + data["camera"]
                        ).GetAttributes()
                        if a.HasAuthoredValueOpinion()
                    }
                    self.set_camera(values)
                    result["view_matrix_max_error"] = self.camera_confirm()
                elif action == "camera_back":
                    if not self.history:
                        raise ValueError("CAMERA_HISTORY_EMPTY")
                    self.set_camera(self.history.pop())
                    result["view_matrix_max_error"] = self.camera_confirm()
                elif action == "snapshot":
                    name = f"scene-snapshot-{self.sequence:012d}.png"
                    self.capture(name)
                    result.update(
                        image=name,
                        image_sha256=hashlib.sha256((self.output / name).read_bytes()).hexdigest(),
                        sampled_sim_h=self.world.s.time_h,
                        source_state_revision=self.world.s.revision,
                        frame_number=self.viewport.frame_info.get("frame_number"),
                        camera_path=str(self.viewport.camera_path),
                    )
                else:
                    raise ValueError("DISPLAY_ACTION_UNSUPPORTED")
                result.update(accepted=True, reason="CONFIRMED")
            except (ValueError, RuntimeError) as error:
                result["reason"] = str(error)
            result.update(
                state_before_sha256=state_before, state_after_sha256=self.digest(self.world.s)
            )
            if result["state_after_sha256"] != state_before:
                raise RuntimeError("DISPLAY_CHANGED_PRODUCTION_STATE")
            result["published_monotonic_s"] = time.monotonic()
            dest = self.output / "p051-view-results"
            dest.mkdir(exist_ok=True)
            atomic_json(dest / path.name, result)
            atomic_json(self.output / "p051-view-status.json", result)
            self.publish(force=True)
            return result
