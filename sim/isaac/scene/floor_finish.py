"""Paint the existing floor through UV colour only, without adding geometry."""

from pathlib import Path

from pxr import Gf, Sdf, UsdGeom, UsdShade


def apply_floor_finish(scene):
    floor = scene.stage.GetPrimAtPath("/World/Factory/Ground")
    # OpenUSD cuboid's top face indices are 0,1,2,3: +X+Y,-X+Y,-X-Y,+X-Y.
    # The remaining faces sample a dark corner of the same colour map.
    uv = [(1, 1), (0, 1), (0, 0), (1, 0)] + [(0, 0)] * 20
    UsdGeom.PrimvarsAPI(floor).CreatePrimvar(
        "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying
    ).Set([Gf.Vec2f(*p) for p in uv])
    material = UsdShade.Material.Define(scene.stage, "/World/Looks/S19A_floor_paint_r2")
    shader = UsdShade.Shader.Define(scene.stage, material.GetPath().AppendChild("Surface"))
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.92)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0)
    reader = UsdShade.Shader.Define(scene.stage, material.GetPath().AppendChild("UV"))
    reader.CreateIdAttr("UsdPrimvarReader_float2")
    reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
    reader.CreateOutput("result", Sdf.ValueTypeNames.Float2)
    texture = UsdShade.Shader.Define(scene.stage, material.GetPath().AppendChild("Paint"))
    texture.CreateIdAttr("UsdUVTexture")
    texture.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(
        str(Path(__file__).with_name("assets") / "s19a_floor_paint_r2.png")
    )
    texture.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set("sRGB")
    texture.CreateInput("wrapS", Sdf.ValueTypeNames.Token).Set("clamp")
    texture.CreateInput("wrapT", Sdf.ValueTypeNames.Token).Set("clamp")
    texture.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(
        reader.ConnectableAPI(), "result"
    )
    texture.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(
        texture.ConnectableAPI(), "rgb"
    )
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    UsdShade.MaterialBindingAPI.Apply(floor).Bind(material)
