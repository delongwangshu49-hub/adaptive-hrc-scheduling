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


def label_visible(path, distance, selected_paths):
    """Keep zone/safety labels; object labels appear nearby or for selected objects."""
    if path.startswith(("/World/Pads/", "/World/Safety/")):
        return True
    parent = path.rsplit("/", 1)[0]
    return distance <= 22 or any(
        p == parent or p.startswith(parent + "/") or parent.startswith(p + "/")
        for p in selected_paths
    )


class ScenePresentation:
    def __init__(self, stage, camera):
        self.stage, self.camera = stage, camera
        self.last_view = None
        self.labels = []
        self.next_scan = 0

    def update(self, selected_paths):
        from pxr import UsdGeom

        now = time.monotonic()
        if now >= self.next_scan:
            # Only decorative text meshes participate; physical prims remain untouched.
            self.labels = [
                p
                for p in self.stage.Traverse()
                if p.IsA(UsdGeom.Mesh) and p.GetName() in ("Label", "Role", "Capacity", "Mode")
            ]
            self.next_scan = now + 3
            self.last_view = None
        camera = UsdGeom.Xformable(self.stage.GetPrimAtPath(self.camera))
        position = camera.ComputeLocalToWorldTransform(0).ExtractTranslation()
        key = tuple(position), tuple(selected_paths), len(self.labels)
        if key == self.last_view:
            return
        self.last_view = key
        for prim in self.labels:
            if not prim.IsValid():
                continue
            location = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(0).ExtractTranslation()
            visible = label_visible(
                str(prim.GetPath()), (location - position).GetLength(), selected_paths
            )
            UsdGeom.Imageable(prim).GetVisibilityAttr().Set(
                UsdGeom.Tokens.inherited if visible else UsdGeom.Tokens.invisible
            )


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
    # Pin documented selection bindings for this presentation-only viewport.
    settings = carb.settings.get_settings()
    for gesture in ("SelectionClickGesture", "SelectionDragGesture"):
        settings.set(
            "/exts/omni.kit.viewport.window/bindings/selection/" + gesture, "Any LeftButton"
        )
    import json
    from pathlib import Path

    import omni.usd

    accent = json.loads(
        (Path(__file__).resolve().parents[1] / "desktop/p051/web/src/design-tokens.json").read_text(
            "utf-8"
        )
    )["accent"]
    rgb = [int(accent[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    settings.set("/exts/omni.kit.manipulator.selection/style/color", [*rgb, 1.0])
    settings.set("/exts/omni.kit.manipulator.selection/style/inner_color", [*rgb, 0.10])
    omni.usd.get_context().set_selection_group_outline_color(0, (*rgb, 1.0))
    from pxr import Gf, UsdGeom

    # A higher overview exposes work areas behind the gantry without moving production objects.
    stage = omni.usd.get_context().get_stage()
    overview = stage.GetPrimAtPath("/World/Cameras/Overview")
    if overview.IsValid():
        view = Gf.Matrix4d().SetLookAt(
            Gf.Vec3d(73, -47, 94), Gf.Vec3d(29, 21, 0), Gf.Vec3d(0, 0, 1)
        )
        UsdGeom.Xformable(overview).MakeMatrixXform().Set(view.GetInverse())
    name = "hrc_selection_only"
    carb.settings.get_settings().set(
        "/persistent/exts/omni.kit.manipulator.selector/orders/" + name, -100000
    )

    class SelectionOnly(ManipulatorBase):
        def __init__(self):
            self._enabled = False
            self.context_menu_guard = disable_context_menu(viewport_window)
            self.input_probe = SceneInputProbe(viewport_window)
            super().__init__(name, "")

        def on_selection_changed(self, stage, selection, *args, **kwargs):
            return selection is not None

        @property
        def enabled(self):
            return self._enabled

        @enabled.setter
        def enabled(self, value):
            self._enabled = value

        def destroy(self):
            self.input_probe.close()
            super().destroy()

    return SelectionOnly()


class SceneInputProbe:
    """Observe only this Kit process's window mice; never consume or synthesize input."""

    def __init__(self, viewport_window):
        import carb.input
        import omni.appwindow

        self.viewport_window = viewport_window
        self.input = carb.input.acquire_input_interface()
        self.factory = omni.appwindow.acquire_app_window_factory_interface()
        self.subscriptions = {}

    def report(self):
        import carb.input

        rows = []
        try:
            for window in self.factory.get_windows():
                mouse = window.get_mouse()
                if mouse is None:
                    continue
                key = hash(mouse)
                if key not in self.subscriptions:
                    counts = {}

                    def observe(event, counts=counts):
                        name = str(event.type).split(".")[-1]
                        counts[name] = counts.get(name, 0) + 1
                        return True

                    token = self.input.subscribe_to_mouse_events(mouse, observe)
                    self.subscriptions[key] = (mouse, token, counts)
                rows.append(
                    dict(
                        title=window.get_title(),
                        window_key=str(window.get_event_key()),
                        width=window.get_width(),
                        height=window.get_height(),
                        dpi_scale=window.get_dpi_scale(),
                        ui_scale=window.get_ui_scale(),
                        mouse_blocked=bool(
                            window.get_input_blocking_state(carb.input.DeviceType.MOUSE)
                        ),
                        counts=dict(self.subscriptions[key][2]),
                    )
                )
            finder = getattr(self.viewport_window, "_find_viewport_layer", None)
            present = finder("Selection", "manipulator") is not None if finder else None
            return dict(
                windows=rows,
                selection_layer_present=present,
                scope="OWN_KIT_WINDOW_MOUSE_COUNTS_NOT_GLOBAL_INPUT",
            )
        except (RuntimeError, AttributeError, TypeError) as error:
            return dict(windows=rows, error=str(error), selection_layer_present=None)

    def close(self):
        for mouse, token, _ in self.subscriptions.values():
            self.input.unsubscribe_to_mouse_events(mouse, token)
        self.subscriptions.clear()


def related_work_ids(ids, entities):
    """Physical parts link through declared operation targets, never guessed names."""
    selected = set(ids)
    return sorted(
        selected
        | {
            row["id"]
            for row in entities
            if row.get("kind") == "operation" and selected.intersection(row.get("targets", ()))
        }
    )


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
        self,
        output,
        request,
        stage,
        viewport,
        camera,
        catalog,
        world,
        digest,
        capture,
        pump,
        input_probe=None,
    ):
        self.output, self.request, self.stage = output, request, stage
        self.viewport, self.camera, self.catalog, self.world = viewport, camera, catalog, world
        self.digest, self.capture, self.pump = digest, capture, pump
        self.sequence = 0
        self.selection_sequence = 0
        self.last_selection = None
        self.history = []
        self.last_publish = 0
        self.input_probe = input_probe
        self.presentation = ScenePresentation(stage, camera)

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
        self.presentation.update(paths)
        ids = mapped_selection(paths, entities)
        related = related_work_ids(ids, entities)
        signature = (tuple(paths), tuple(ids), tuple(related))
        if signature != self.last_selection:
            self.selection_sequence += 1
            self.last_selection = signature
        atomic_json(
            self.output / "p051-scene-context.json",
            dict(
                **self.identity(),
                sampled_sim_h=self.world.s.time_h,
                source_state_revision=self.world.s.revision,
                published_monotonic_s=now,
                entities=entities,
                selection=dict(
                    sequence=self.selection_sequence,
                    entity_ids=ids,
                    related_ids=related,
                    paths=paths,
                ),
                input=self.input_probe.report() if self.input_probe else None,
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
                if action in ("locate", "focus", "clear_selection"):
                    if action == "clear_selection":
                        paths = []
                    elif not paths or not all(self.stage.GetPrimAtPath(p).IsValid() for p in paths):
                        raise ValueError("ENTITY_NOT_IN_SCENE")
                    if action != "clear_selection" and not visible_paths(self.stage, paths):
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
