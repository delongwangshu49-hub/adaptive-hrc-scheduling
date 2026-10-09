"""Surface-only finish for the existing factory; no geometry or capability changes."""

from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdShade

from .appearance_styles import COLOURS
from .floor_finish import apply_floor_finish


def apply_scene_appearance(scene):
    materials = {}

    def bind(prim, colour):
        if colour not in materials:
            material = UsdShade.Material.Define(scene.stage, "/World/Looks/S19A_machine_" + colour)
            shader = UsdShade.Shader.Define(scene.stage, material.GetPath().AppendChild("Surface"))
            shader.CreateIdAttr("UsdPreviewSurface")
            finishes = {"work_area": (0.22, 0.27, 0.30), "contact_orange": (0.8, 0.28, 0.025)}
            shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(
                Gf.Vec3f(*finishes.get(colour, COLOURS.get(colour)))
            )
            shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(
                0.44 if colour in ("steel", "silver") else 0.72
            )
            shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(
                0.6 if colour in ("steel", "silver") else 0
            )
            material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
            materials[colour] = material
        UsdShade.MaterialBindingAPI.Apply(prim).Bind(materials[colour])

    bodies = {
        "CUT1": "cobalt",
        "R1": "orange",
        "SCN-WELD-J2": "orange",
        "SCN-WELD-J3": "cobalt",
        "SCN-FORK-01": "amber",
        "SCN-CART-01": "teal",
        "TEST1": "white",
        "FIX-J2": "teal",
        "FIX-J3": "cobalt",
        "CR1": "amber",
        "CR1-HOOK": "amber",
    }
    for identity, body in bodies.items():
        root = scene.stage.GetPrimAtPath(scene.mapping[identity])
        for prim in Usd.PrimRange(root):
            if not prim.IsA(UsdGeom.Boundable):
                continue
            name = prim.GetName()
            if (
                name in ("Label", "Mode", "Axis", "Tip")
                or "ReachBound" in str(prim.GetPath())
                or UsdGeom.Imageable(prim).ComputeVisibility() == "invisible"
            ):
                continue
            colour = body
            if name.startswith(("Wheel", "Cable", "Rope", "Bridle", "Sling")):
                colour = "rubber"
            elif name.startswith(("Roller", "Tine", "Mast", "Handle")) or name in (
                "FeedExtension",
                "Tray",
                "TransferTray",
                "Base",
                "Controller",
                "DedicatedPower",
            ):
                colour = "steel"
            elif name in ("Controls", "Control", "Panel", "Display"):
                colour = "ink"
            elif name.startswith("Clamp") or name == "Guard":
                colour = "amber"
            elif name in ("Bottle", "Meter"):
                colour = "teal" if name == "Bottle" else "cobalt"
            # Preserve joint/body contrast and give contact surfaces distinct paint.
            if identity == "CUT1" and name.startswith("Roller"):
                colour = "contact_orange"
            elif identity == "CUT1" and name == "FeedExtension":
                colour = "navy"
            elif identity == "R1":
                if name == "Housing" and "/Joint" in str(prim.GetPath()):
                    colour = "rubber"
                elif name in ("Base", "DedicatedPower"):
                    colour = "cobalt"
                elif name == "Controller":
                    colour = "ivory"
                elif name == "Link" and "/Joint6/" in str(prim.GetPath()):
                    colour = "silver"
            elif identity == "SCN-FORK-01":
                if name == "Guard":
                    colour = "cobalt"
                elif name.startswith("Tine"):
                    colour = "contact_orange"
                elif name.startswith("Mast"):
                    colour = "silver"
            elif identity == "SCN-CART-01":
                if name in ("Tray", "TransferTray"):
                    colour = "cobalt"
                elif name.startswith("Handle"):
                    colour = "contact_orange"
            elif identity == "TEST1" and name == "Tray":
                colour = "teal"
            bind(prim, colour)
    for prim in Usd.PrimRange(scene.stage.GetPrimAtPath("/World/Pads")):
        if prim.GetName() == "Pad":
            bind(prim, "work_area")
    apply_floor_finish(scene)
    # Reduce both existing lights; position and cameras stay at their originals.
    UsdLux.DomeLight(scene.stage.GetPrimAtPath("/World/Lighting/Fill")).GetIntensityAttr().Set(650)
    UsdLux.DistantLight(scene.stage.GetPrimAtPath("/World/Lighting/Sun")).GetIntensityAttr().Set(
        1250
    )
