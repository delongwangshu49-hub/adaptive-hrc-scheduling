"""Role-specific appearance; visual details never own collision or motion."""

from pxr import Gf, Sdf, UsdShade

from .appearance_styles import COLOURS, PERSON_STYLES


def apply_person_appearance(scene, path, identity):
    """Colour an existing person without changing original geometry or pose."""
    _, clothing, vest, helmet = PERSON_STYLES[identity]

    def material(name, rgb, roughness=0.72, metallic=0.0):
        result = UsdShade.Material.Define(scene.stage, "/World/Looks/S19A_" + name)
        shader = UsdShade.Shader.Define(scene.stage, result.GetPath().AppendChild("Surface"))
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*rgb))
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
        shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(metallic)
        result.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
        return result

    materials = {}
    for colour in {clothing, vest, helmet, "skin", "rubber", "silver", "ink", "white", "navy"}:
        roughness, metallic = (0.48, 0.15) if colour == "silver" else (0.72, 0.0)
        if colour == "rubber":
            roughness = 0.9
        materials[colour] = material(colour, COLOURS[colour], roughness, metallic)
    for part, color in {
        "Torso": clothing,
        "Arm0": clothing,
        "Arm1": clothing,
        "Leg0": clothing,
        "Leg1": clothing,
        "Boot0": "rubber",
        "Boot1": "rubber",
        "Head": "skin",
        "Helmet": helmet,
        "Vest": vest,
    }.items():
        UsdShade.MaterialBindingAPI.Apply(scene.stage.GetPrimAtPath(path + "/" + part)).Bind(
            materials[color]
        )

    def detail(name, position, size, color, kind="cube"):
        obj = scene.shape(path + "/Detail_" + name, position, size, "white", kind)
        UsdShade.MaterialBindingAPI.Apply(obj.GetPrim()).Bind(materials[color])

    for i, x in enumerate((-0.12, 0.12)):
        detail("VestVertical" + str(i), (x, 0.159, 1.19), (0.042, 0.003, 0.30), "silver")
    detail("VestHorizontal", (0, 0.16, 1.055), (0.415, 0.003, 0.037), "silver")
    detail("Zip", (0, 0.161, 1.18), (0.012, 0.003, 0.29), "navy")
    detail("Badge", (-0.055, 0.162, 1.265), (0.068, 0.004, 0.05), "white")
    for i, x in enumerate((-0.046, 0.046)):
        detail("Eye" + str(i), (x, 0.109, 1.687), (0.025, 0.023, 0.018), "ink", "sphere")
        detail("Brow" + str(i), (x, 0.108, 1.71), (0.032, 0.022, 0.01), "ink", "sphere")
    detail("Mouth", (0, 0.115, 1.61), (0.037, 0.015, 0.009), "ink", "sphere")
    # The small chest ID fits inside the existing body extents and supplements
    # colour for same-role colleagues and colour-vision differences.
    label = scene.group(path + "/Detail_Identity", (-0.025, 0.166, 1.252))
    label.AddRotateXYZOp().Set(Gf.Vec3f(90, 0, 180))
    scene.label(path + "/Detail_Identity/Text", identity, (0, 0, 0), 0.021, "dark")
    UsdShade.MaterialBindingAPI.Apply(
        scene.stage.GetPrimAtPath(path + "/Detail_Identity/Text")
    ).Bind(materials["ink"])


def apply_w1_appearance(scene, path):
    """Retain the earlier callable for local preview clients."""
    apply_person_appearance(scene, path, "W1")
