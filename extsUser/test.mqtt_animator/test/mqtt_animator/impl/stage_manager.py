"""
USD Stage Manager for Omniverse MQTT Animator.
Handles dynamic creation, transform updates, materials, waypoint beacons,
and motion trails for walker prims in the USD stage.
Supports both Y-up and Z-up stage coordinates.
"""

import math
from typing import Dict, Any, List, Optional, Tuple

try:
    from pxr import Usd, UsdGeom, Gf, Sdf, Vt
except ImportError:
    Usd = None
    UsdGeom = None
    Gf = None
    Sdf = None
    Vt = None

try:
    import omni.usd as omni_usd
except ImportError:
    omni_usd = None


def hex_to_rgb(hex_str: str) -> Tuple[float, float, float]:
    """Convert hex color string (#rrggbb) to normalized RGB floats (0.0 - 1.0)."""
    h = hex_str.lstrip("#")
    if len(h) != 6:
        return (0.22, 0.74, 0.97)  # default sky blue
    try:
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
        return (r, g, b)
    except ValueError:
        return (0.22, 0.74, 0.97)


class DeviceVisuals:
    """Holds references to USD prims and trail history for a single walker."""

    def __init__(self, device_id: str, root_path: str):
        self.device_id = device_id
        self.root_path = root_path
        self.beacon_path = f"{root_path}_target"
        self.trail_path = f"{root_path}_trail"
        self.color_rgb = (0.22, 0.74, 0.97)
        self.color_hex = "#38bdf8"
        self.model_type = "target_waypoints"
        self.trail_points: List[Tuple[float, float]] = []
        self.max_trail_points: int = 60
        self.last_trail_sample_time: float = 0.0


class UsdStageManager:
    """Manages the USD Stage prims representing simulated walkers."""

    def __init__(self, base_root_path: str = "/World/Walkers"):
        self.base_root_path = base_root_path
        self._devices: Dict[str, DeviceVisuals] = {}
        self._show_trails: bool = True

    def get_stage(self) -> Optional[Any]:
        """Retrieve current USD stage."""
        if omni_usd is not None and hasattr(omni_usd, "get_context"):
            return omni_usd.get_context().get_stage()
        return None

    def is_y_up(self, stage) -> bool:
        """Check if stage is configured with Y as Up-Axis."""
        if UsdGeom is not None and stage is not None:
            return UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y
        return True

    def set_show_trails(self, show: bool):
        """Toggle motion trails globally."""
        self._show_trails = show
        stage = self.get_stage()
        if not stage or UsdGeom is None:
            return

        for dev in self._devices.values():
            trail_prim = stage.GetPrimAtPath(dev.trail_path)
            if trail_prim and trail_prim.IsValid():
                imageable = UsdGeom.Imageable(trail_prim)
                if show:
                    imageable.MakeVisible()
                else:
                    imageable.MakeInvisible()

    def ensure_root_prim(self, stage):
        """Ensure the base root group /World/Walkers exists."""
        if not stage or UsdGeom is None:
            return
        root_prim = stage.GetPrimAtPath(self.base_root_path)
        if not root_prim or not root_prim.IsValid():
            UsdGeom.Xform.Define(stage, self.base_root_path)

    def register_device(
        self,
        device_id: str,
        color_hex: str = "#38bdf8",
        model_type: str = "target_waypoints"
    ) -> DeviceVisuals:
        """Creates or retrieves visual prims for a walker device."""
        if device_id in self._devices:
            dev = self._devices[device_id]
            dev.color_hex = color_hex
            dev.color_rgb = hex_to_rgb(color_hex)
            dev.model_type = model_type
            self._update_colors(dev)
            return dev

        dev_path = f"{self.base_root_path}/{device_id.replace('-', '_')}"
        dev = DeviceVisuals(device_id, dev_path)
        dev.color_hex = color_hex
        dev.color_rgb = hex_to_rgb(color_hex)
        dev.model_type = model_type
        self._devices[device_id] = dev

        stage = self.get_stage()
        if stage and UsdGeom is not None:
            self.ensure_root_prim(stage)
            self._create_walker_prims(stage, dev)
            self._create_beacon_prims(stage, dev)
            self._create_trail_prim(stage, dev)

        return dev

    def _create_walker_prims(self, stage, dev: DeviceVisuals):
        """Create body mesh and heading cone for the walker."""
        xform = UsdGeom.Xform.Define(stage, dev.root_path)

        # Body: Cylinder chassis
        body_path = f"{dev.root_path}/Chassis"
        cyl = UsdGeom.Cylinder.Define(stage, body_path)
        cyl.GetRadiusAttr().Set(0.55)
        cyl.GetHeightAttr().Set(0.35)
        cyl.GetAxisAttr().Set("Y" if self.is_y_up(stage) else "Z")
        cyl.GetDisplayColorAttr().Set([Gf.Vec3f(*dev.color_rgb)])

        # Nose/Heading indicator: Small forward cone
        nose_path = f"{dev.root_path}/HeadingNose"
        cone = UsdGeom.Cone.Define(stage, nose_path)
        cone.GetRadiusAttr().Set(0.2)
        cone.GetHeightAttr().Set(0.4)
        cone.GetAxisAttr().Set("Z" if self.is_y_up(stage) else "Y")
        cone.GetDisplayColorAttr().Set([Gf.Vec3f(1.0, 1.0, 1.0)])

        # Offset nose towards front of body (+Z in standard 3D)
        nose_xform = UsdGeom.Xformable(cone.GetPrim())
        translate_op = nose_xform.AddTranslateOp()
        if self.is_y_up(stage):
            translate_op.Set(Gf.Vec3d(0.0, 0.1, 0.6))
        else:
            translate_op.Set(Gf.Vec3d(0.0, 0.6, 0.1))

    def _create_beacon_prims(self, stage, dev: DeviceVisuals):
        """Create target waypoint beacon (sphere + thin beam)."""
        beacon_xform = UsdGeom.Xform.Define(stage, dev.beacon_path)

        sphere_path = f"{dev.beacon_path}/Sphere"
        sphere = UsdGeom.Sphere.Define(stage, sphere_path)
        sphere.GetRadiusAttr().Set(0.3)
        sphere.GetDisplayColorAttr().Set([Gf.Vec3f(*dev.color_rgb)])

        beam_path = f"{dev.beacon_path}/Beam"
        beam = UsdGeom.Cylinder.Define(stage, beam_path)
        beam.GetRadiusAttr().Set(0.05)
        beam.GetHeightAttr().Set(6.0)
        beam.GetAxisAttr().Set("Y" if self.is_y_up(stage) else "Z")
        beam.GetDisplayColorAttr().Set([Gf.Vec3f(*dev.color_rgb)])

        # Offset beam so base rests on ground
        beam_xform = UsdGeom.Xformable(beam.GetPrim())
        if self.is_y_up(stage):
            beam_xform.AddTranslateOp().Set(Gf.Vec3d(0.0, 3.0, 0.0))
        else:
            beam_xform.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, 3.0))

        if dev.model_type != "target_waypoints":
            UsdGeom.Imageable(beacon_xform.GetPrim()).MakeInvisible()

    def _create_trail_prim(self, stage, dev: DeviceVisuals):
        """Create dynamic BasisCurves prim to visualize motion trail."""
        curves = UsdGeom.BasisCurves.Define(stage, dev.trail_path)
        curves.GetTypeAttr().Set(UsdGeom.Tokens.linear)
        try:
            curves.SetWidthsInterpolation(UsdGeom.Tokens.constant)
        except Exception:
            pass
        curves.GetWidthsAttr().Set([0.08])
        curves.GetDisplayColorAttr().Set([Gf.Vec3f(*dev.color_rgb)])

    def _update_colors(self, dev: DeviceVisuals):
        """Update display color of chassis and beacon if changed."""
        stage = self.get_stage()
        if not stage or Gf is None:
            return

        body_prim = stage.GetPrimAtPath(f"{dev.root_path}/Chassis")
        if body_prim and body_prim.IsValid():
            UsdGeom.Gprim(body_prim).GetDisplayColorAttr().Set([Gf.Vec3f(*dev.color_rgb)])

        sphere_prim = stage.GetPrimAtPath(f"{dev.beacon_path}/Sphere")
        if sphere_prim and sphere_prim.IsValid():
            UsdGeom.Gprim(sphere_prim).GetDisplayColorAttr().Set([Gf.Vec3f(*dev.color_rgb)])

    def update_pose(
        self,
        device_id: str,
        x: float,
        z: float,
        yaw_rad: float,
        target_x: float = 0.0,
        target_z: float = 0.0,
        model_type: Optional[str] = None,
        now_time: float = 0.0
    ):
        """Applies evaluated position and rotation to USD prims in stage."""
        if device_id not in self._devices:
            return

        dev = self._devices[device_id]
        if model_type:
            dev.model_type = model_type

        stage = self.get_stage()
        if not stage or UsdGeom is None or Gf is None:
            return

        # Ensure prims are created if stage was reloaded
        prim = stage.GetPrimAtPath(dev.root_path)
        if not prim or not prim.IsValid():
            self._create_walker_prims(stage, dev)
            self._create_beacon_prims(stage, dev)
            self._create_trail_prim(stage, dev)
            prim = stage.GetPrimAtPath(dev.root_path)

        is_y = self.is_y_up(stage)

        # 1. Update Walker Xform
        xformable = UsdGeom.Xformable(prim)
        xform_ops = xformable.GetOrderedXformOps()
        trans_op = None
        rot_op = None
        target_rot_type = UsdGeom.XformOp.TypeRotateY if is_y else UsdGeom.XformOp.TypeRotateZ

        # If existing ops have an incompatible rotation type from a different up-axis, reset order
        if any(
            op.GetOpType() in (UsdGeom.XformOp.TypeRotateY, UsdGeom.XformOp.TypeRotateZ)
            and op.GetOpType() != target_rot_type
            for op in xform_ops
        ):
            xformable.ClearXformOpOrder()
            xform_ops = []

        for op in xform_ops:
            if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
                trans_op = op
            elif op.GetOpType() == target_rot_type:
                rot_op = op

        if not trans_op:
            trans_op = xformable.AddTranslateOp()

        elevation = 0.25
        if is_y:
            trans_op.Set(Gf.Vec3d(x, elevation, z))
        else:
            trans_op.Set(Gf.Vec3d(x, z, elevation))

        yaw_deg = math.degrees(yaw_rad)
        if is_y:
            if not rot_op:
                rot_op = xformable.AddRotateYOp()
            rot_op.Set(yaw_deg)
        else:
            if not rot_op:
                rot_op = xformable.AddRotateZOp()
            # In Z-up stage, rotation around +Z from +Y to +X requires negative angle
            rot_op.Set(-yaw_deg)

        # 2. Update Waypoint Beacon
        beacon_prim = stage.GetPrimAtPath(dev.beacon_path)
        if beacon_prim and beacon_prim.IsValid():
            beacon_imageable = UsdGeom.Imageable(beacon_prim)
            if dev.model_type == "target_waypoints":
                beacon_imageable.MakeVisible()
                b_xform = UsdGeom.Xformable(beacon_prim)
                b_trans_op = b_xform.GetTranslateOp()
                if not b_trans_op:
                    b_trans_op = b_xform.AddTranslateOp()
                if is_y:
                    b_trans_op.Set(Gf.Vec3d(target_x, 0.3, target_z))
                else:
                    b_trans_op.Set(Gf.Vec3d(target_x, target_z, 0.3))
            else:
                beacon_imageable.MakeInvisible()

        # 3. Update Motion Trail
        if self._show_trails and (now_time - dev.last_trail_sample_time >= 0.08):
            dev.last_trail_sample_time = now_time
            dev.trail_points.append((x, z))
            if len(dev.trail_points) > dev.max_trail_points:
                dev.trail_points.pop(0)

            if len(dev.trail_points) >= 2:
                trail_prim = stage.GetPrimAtPath(dev.trail_path)
                if trail_prim and trail_prim.IsValid():
                    curves = UsdGeom.BasisCurves(trail_prim)
                    pts = []
                    for px, pz in dev.trail_points:
                        if is_y:
                            pts.append(Gf.Vec3f(px, 0.08, pz))
                        else:
                            pts.append(Gf.Vec3f(px, pz, 0.08))
                    curves.GetPointsAttr().Set(Vt.Vec3fArray(pts))
                    curves.GetCurveVertexCountsAttr().Set(Vt.IntArray([len(pts)]))

    def remove_device(self, device_id: str):
        """Remove device and its associated prims from the USD stage."""
        if device_id not in self._devices:
            return

        dev = self._devices.pop(device_id)
        stage = self.get_stage()
        if not stage or Sdf is None:
            return

        for p in [dev.root_path, dev.beacon_path, dev.trail_path]:
            if stage.GetPrimAtPath(p).IsValid():
                stage.RemovePrim(Sdf.Path(p))

    def clear_all(self):
        """Clear all walker prims on shutdown or stage reset."""
        stage = self.get_stage()
        if stage and Sdf is None:
            pass
        elif stage:
            for dev in list(self._devices.values()):
                self.remove_device(dev.device_id)
            if stage.GetPrimAtPath(self.base_root_path).IsValid():
                stage.RemovePrim(Sdf.Path(self.base_root_path))
        self._devices.clear()
