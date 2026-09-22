"""
Omniverse UI Window for MQTT Animator & Container Fleet Manager.
Constructed using native omni.ui components with real-time telemetry updates.
"""

from typing import Dict, Any, Optional, Callable

try:
    import omni.kit.ui
    import omni.ui as ui
except ImportError:
    ui = None
    omni_kit_ui = None


ALGORITHM_CHOICES = [
    ("v5_catmull_rom", "v5: Centripetal Catmull-Rom (Recommended)"),
    ("v4_continuous_seamless", "v4: Continuous Extrapolation"),
    ("v3_hermite_spline", "v3: Cubic Hermite Spline"),
    ("v2_simple_lerp", "v2: Simple Exp LERP"),
    ("v1_raw_snap", "v1: Raw 0-Lag Snap")
]

MODEL_CHOICES = [
    ("target_waypoints", "Target Waypoints"),
    ("edge_repulsion", "Edge-Repulsion Cruise"),
    ("langevin_brownian", "Langevin Brownian")
]


class UIBuilder:
    """Manages the Omniverse UI window, telemetry widgets, and container fleet controls."""

    def __init__(
        self,
        window_title: str = "MQTT Random Walk Animator & Fleet",
        menu_path: str = "Window/MQTT Random Walk Animator",
        extension_instance: Optional[Any] = None
    ):
        self._window = None
        self._menu = None
        self._window_title = window_title
        self._menu_path = menu_path
        self.ext = extension_instance

        # Telemetry Labels
        self._lbl_mqtt_status = None
        self._lbl_active_count = None
        self._lbl_fps = None
        self._lbl_algo_desc = None
        self._slider_buffer_delay = None
        self._cb_trails = None

        # Container Cards Widget Cache: device_id -> dict of UI elements
        self._device_cards: Dict[str, Dict[str, Any]] = {}
        self._cards_container = None

        if ui is not None:
            try:
                import omni.kit.ui
                self._menu = omni.kit.ui.get_editor_menu().add_item(
                    self._menu_path, self.on_toggle, toggle=True, value=True
                )
            except Exception as e:
                print(f"[UIBuilder Notice] Menu item registration: {e}")

            # Automatically build and show window
            self.build_ui()
            if self._window:
                self._window.visible = True

    def on_toggle(self, *args, **kwargs):
        """Toggle window visibility."""
        if not self._window:
            self.build_ui()
        if self._window is not None:
            self._window.visible = not self._window.visible

    def build_ui(self):
        """Construct the Omniverse UI Window."""
        if ui is None:
            return

        if not self._window:
            self._window = ui.Window(
                title=self._window_title,
                visible=True,
                width=420,
                height=650
            )

            with self._window.frame:
                with ui.ScrollingFrame(
                    horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
                    vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED
                ):
                    with ui.VStack(spacing=10, style={"margin": 10}):
                        self._build_header_section()
                        ui.Spacer(height=4)
                        self._build_smoothing_section()
                        ui.Spacer(height=4)
                        self._build_fleet_section()

    def _build_header_section(self):
        """Header and live connection status."""
        with ui.ZStack(height=70):
            ui.Rectangle(style={"background_color": 0xFF1E2433, "border_radius": 6})
            with ui.VStack(spacing=4, style={"margin": 8}):
                with ui.HStack():
                    ui.Label("📡 MQTT 3D Telemetry Fleet", style={"font_size": 16, "color": 0xFF38BDF8})
                with ui.HStack():
                    ui.Label("Broker: ", width=50, style={"color": 0xFF8E99B0})
                    self._lbl_mqtt_status = ui.Label("Connecting...", style={"color": 0xFFFBBF24})
                with ui.HStack():
                    ui.Label("Active Walkers: ", width=100, style={"color": 0xFF8E99B0})
                    self._lbl_active_count = ui.Label("0", style={"color": 0xFF34D399})
                    ui.Spacer(width=20)
                    ui.Label("FPS: ", width=35, style={"color": 0xFF8E99B0})
                    self._lbl_fps = ui.Label("60", style={"color": 0xFFE2E8F0})

    def _build_smoothing_section(self):
        """Interpolation algorithm selector and delay sliders."""
        with ui.CollapsableFrame("Smoothing & Interpolation", collapsed=False):
            with ui.VStack(spacing=8, style={"margin": 6}):
                with ui.HStack(height=24):
                    ui.Label("Algorithm:", width=90)
                    combo = ui.ComboBox(
                        0,
                        *[label for _, label in ALGORITHM_CHOICES],
                        width=ui.Fraction(1)
                    )

                    def on_combo_changed(model, val):
                        idx = model.get_item_value_model().as_int
                        mode_key = ALGORITHM_CHOICES[idx][0]
                        if self.ext:
                            self.ext.current_interpolation_mode = mode_key
                        descriptions = {
                            "v5_catmull_rom": "Centripetal spline (alpha=0.5) with 2-frame history. Zero overshoots.",
                            "v4_continuous_seamless": "Continuous extrapolation with velocity dead-reckoning.",
                            "v3_hermite_spline": "Cubic Hermite polynomial with filtered unique keyframes.",
                            "v2_simple_lerp": "Standard exponential LERP smoothing.",
                            "v1_raw_snap": "Instantaneous snap to latest keyframe (no smoothing)."
                        }
                        if self._lbl_algo_desc:
                            self._lbl_algo_desc.text = descriptions.get(mode_key, "")

                    combo.model.add_item_changed_fn(on_combo_changed)

                self._lbl_algo_desc = ui.Label(
                    "Centripetal spline (alpha=0.5) with 2-frame history. Zero overshoots.",
                    style={"color": 0xFF94A3B8, "font_size": 11},
                    word_wrap=True
                )

                with ui.HStack(height=24):
                    ui.Label("Buffer Delay:", width=90)
                    self._slider_buffer_delay = ui.IntSlider(min=0, max=200, step=5)
                    self._slider_buffer_delay.model.set_value(40)

                    def on_delay_changed(model):
                        val = model.as_int
                        if self.ext:
                            self.ext.buffer_offset_ms = float(val)

                    self._slider_buffer_delay.model.add_value_changed_fn(on_delay_changed)

                # Quick presets
                with ui.HStack(height=22, spacing=6):
                    ui.Label("Presets:", width=90, style={"color": 0xFF8E99B0})
                    for preset_ms in [0, 20, 40, 100]:
                        btn = ui.Button(f"{preset_ms}ms", height=20)

                        def make_preset_cb(p_val):
                            return lambda: self._slider_buffer_delay.model.set_value(p_val)

                        btn.set_clicked_fn(make_preset_cb(preset_ms))

                with ui.HStack(height=24):
                    self._cb_trails = ui.CheckBox()
                    self._cb_trails.model.set_value(True)
                    ui.Label("Show 3D Motion Trails in Viewport")

                    def on_trails_changed(model):
                        val = model.as_bool
                        if self.ext and hasattr(self.ext, "stage_manager"):
                            self.ext.stage_manager.set_show_trails(val)

                    self._cb_trails.model.add_value_changed_fn(on_trails_changed)

    def _build_fleet_section(self):
        """Container spawn modal and list of active containers."""
        with ui.CollapsableFrame("Container Fleet Controller", collapsed=False):
            with ui.VStack(spacing=8, style={"margin": 6}):
                # Spawn subframe
                with ui.CollapsableFrame("➕ Spawn New Walker Container", collapsed=True):
                    with ui.VStack(spacing=6, style={"margin": 6}):
                        with ui.HStack(height=24):
                            ui.Label("Name:", width=80)
                            in_name = ui.StringField()
                            in_name.model.set_value("Walker #Alpha")

                        with ui.HStack(height=24):
                            ui.Label("Model:", width=80)
                            in_model = ui.ComboBox(0, *[m[1] for m in MODEL_CHOICES])

                        with ui.HStack(height=24):
                            ui.Label("Publish Hz:", width=80)
                            in_hz = ui.IntSlider(min=1, max=60, step=1)
                            in_hz.model.set_value(24)

                        with ui.HStack(height=24):
                            ui.Label("Color Hex:", width=80)
                            in_color = ui.StringField()
                            in_color.model.set_value("#38bdf8")

                        spawn_btn = ui.Button("🚀 Launch Container", height=28)

                        def on_spawn_clicked():
                            name = in_name.model.as_string
                            model_idx = in_model.model.get_item_value_model().as_int
                            model_val = MODEL_CHOICES[model_idx][0]
                            hz = float(in_hz.model.as_int)
                            col = in_color.model.as_string

                            if self.ext and hasattr(self.ext, "fleet_client"):
                                self.ext.fleet_client.dispatch_async(
                                    self.ext.fleet_client.spawn_container,
                                    device_name=name,
                                    model_type=model_val,
                                    write_hz=hz,
                                    color=col,
                                    on_success=lambda r: print(f"[UI] Spawned container: {r}"),
                                    on_error=lambda err: print(f"[UI Error] Spawn failed: {err}")
                                )

                        spawn_btn.set_clicked_fn(on_spawn_clicked)

                # Active devices container
                ui.Label("Active Fleet Walkers:", style={"color": 0xFF8E99B0, "font_size": 12})
                self._cards_container = ui.VStack(spacing=6)

    def update_telemetry(self, is_connected: bool, device_count: int, fps: int):
        """Update global header indicators."""
        if self._lbl_mqtt_status:
            if is_connected:
                self._lbl_mqtt_status.text = "🟢 Connected (localhost:1883)"
                self._lbl_mqtt_status.style = {"color": 0xFF34D399}
            else:
                self._lbl_mqtt_status.text = "🔴 Disconnected"
                self._lbl_mqtt_status.style = {"color": 0xFFF43F5E}

        if self._lbl_active_count:
            self._lbl_active_count.text = str(device_count)

        if self._lbl_fps:
            self._lbl_fps.text = str(fps)

    def sync_device_card(
        self,
        device_id: str,
        name: str,
        color_hex: str,
        model_type: str,
        write_hz: float,
        x: float,
        z: float,
        yaw_rad: float
    ):
        """Creates or updates an active container card in the UI."""
        if not self._cards_container or ui is None:
            return

        if device_id not in self._device_cards:
            self._create_card(device_id, name, color_hex, model_type, write_hz)

        card = self._device_cards.get(device_id)
        if card:
            # Update position text
            yaw_deg = int((yaw_rad * 180.0 / 3.14159) % 360)
            card["lbl_pose"].text = f"X: {x:.2f}  Z: {z:.2f}  Yaw: {yaw_deg}°"

    def _create_card(self, device_id: str, name: str, color_hex: str, model_type: str, write_hz: float):
        """Create UI card frame for a newly discovered walker container."""
        with self._cards_container:
            card_frame = ui.CollapsableFrame(f"🤖 {name} ({device_id})", collapsed=False)
            with card_frame:
                with ui.VStack(spacing=5, style={"margin": 6}):
                    lbl_pose = ui.Label(f"X: 0.00  Z: 0.00  Yaw: 0°", style={"color": 0xFF38BDF8})

                    with ui.HStack(height=22):
                        ui.Label("Model:", width=60)
                        model_idx = 0
                        for i, (m_val, _) in enumerate(MODEL_CHOICES):
                            if m_val == model_type:
                                model_idx = i
                                break
                        cbox_model = ui.ComboBox(model_idx, *[m[1] for m in MODEL_CHOICES])

                        def on_model_changed(model, val):
                            idx = model.get_item_value_model().as_int
                            new_m = MODEL_CHOICES[idx][0]
                            if self.ext and hasattr(self.ext, "fleet_client"):
                                self.ext.fleet_client.dispatch_async(
                                    self.ext.fleet_client.update_config,
                                    device_id=device_id,
                                    model_type=new_m
                                )

                        cbox_model.model.add_item_changed_fn(on_model_changed)

                    with ui.HStack(height=22):
                        ui.Label("Rate Hz:", width=60)
                        slider_hz = ui.IntSlider(min=1, max=60, step=1)
                        slider_hz.model.set_value(int(write_hz))

                        def on_hz_changed(model):
                            new_hz = float(model.as_int)
                            if self.ext and hasattr(self.ext, "fleet_client"):
                                self.ext.fleet_client.dispatch_async(
                                    self.ext.fleet_client.update_config,
                                    device_id=device_id,
                                    write_hz=new_hz
                                )

                        slider_hz.model.add_value_changed_fn(on_hz_changed)

                    with ui.HStack(height=24):
                        ui.Spacer()
                        kill_btn = ui.Button("❌ Kill Container", width=120, height=22)

                        def on_kill():
                            kill_btn.enabled = False
                            if self.ext and hasattr(self.ext, "fleet_client"):
                                self.ext.fleet_client.dispatch_async(
                                    self.ext.fleet_client.kill_container,
                                    device_id=device_id
                                )

                        kill_btn.set_clicked_fn(on_kill)

            self._device_cards[device_id] = {
                "frame": card_frame,
                "lbl_pose": lbl_pose
            }

    def remove_device_card(self, device_id: str):
        """Remove device card widget when walker goes offline."""
        if device_id in self._device_cards:
            card = self._device_cards.pop(device_id)
            if "frame" in card and card["frame"]:
                try:
                    card["frame"].visible = False
                except Exception:
                    pass

    def cleanup(self):
        """Clean up window and menu."""
        if self._window is not None:
            self._window.destroy()
            self._window = None

        if self._menu is not None:
            try:
                import omni.kit.ui
                omni.kit.ui.get_editor_menu().remove_item(self._menu)
            except Exception:
                pass
            self._menu = None
