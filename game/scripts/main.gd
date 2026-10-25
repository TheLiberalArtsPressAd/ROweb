extends Node3D

## Ragnarok Offline — web client entry point.
##
## Loads a pre-baked asset pack over HTTP (see tools/build_assets.py), builds the
## map, and runs a small walkable vertical slice: click to move, orbit camera,
## a few wandering monsters and the town BGM.

const MAP := "prontera"
const SCREENSHOT_DIR := "user://shots"

var fetcher: Fetcher
var world: World
var player: Player
var cam: OrbitCamera
var bgm: AudioStreamPlayer

var _manifest: Dictionary = {}
var _entities: Array = []
var _dragging := false
var _started := false
var _autoplay_tried := false

var _status: Label
var _bar: ProgressBar
var _fade: ColorRect
var _help: Label
var _title: Label
var _loading_box: VBoxContainer


func _ready() -> void:
	_setup_environment()
	_setup_ui()
	fetcher = Fetcher.new()
	add_child(fetcher)
	fetcher.progress.connect(_on_progress)
	await _load_world()


func _setup_environment() -> void:
	var we := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.045, 0.05, 0.075)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_DISABLED
	env.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	env.glow_enabled = false
	we.environment = env
	add_child(we)
	cam = OrbitCamera.new()
	add_child(cam)


func _setup_ui() -> void:
	var layer := CanvasLayer.new()
	layer.layer = 10
	add_child(layer)

	_fade = ColorRect.new()
	_fade.color = Color(0.05, 0.045, 0.075)
	_fade.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_fade.mouse_filter = Control.MOUSE_FILTER_IGNORE
	layer.add_child(_fade)

	_loading_box = VBoxContainer.new()
	_loading_box.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	_loading_box.custom_minimum_size = Vector2(360, 0)
	_loading_box.position = Vector2(-180, -40)
	_loading_box.add_theme_constant_override("separation", 12)
	layer.add_child(_loading_box)

	_title = Label.new()
	_title.text = "RAGNAROK OFFLINE"
	_title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_title.add_theme_font_size_override("font_size", 22)
	_title.add_theme_color_override("font_color", Color(0.95, 0.86, 0.66))
	_loading_box.add_child(_title)

	_bar = ProgressBar.new()
	_bar.min_value = 0
	_bar.max_value = 100
	_bar.value = 0
	_bar.show_percentage = false
	_bar.custom_minimum_size = Vector2(360, 8)
	_loading_box.add_child(_bar)

	_status = Label.new()
	_status.text = "loading"
	_status.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_status.add_theme_color_override("font_color", Color(0.7, 0.7, 0.78))
	_loading_box.add_child(_status)

	_help = Label.new()
	_help.text = "click to walk   ·   right drag to orbit   ·   wheel to zoom   ·   H for help"
	_help.add_theme_color_override("font_color", Color(1, 1, 1, 0.75))
	_help.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.8))
	_help.add_theme_constant_override("shadow_offset_x", 1)
	_help.add_theme_constant_override("shadow_offset_y", 1)
	_help.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_LEFT)
	_help.position = Vector2(16, -44)
	_help.visible = false
	layer.add_child(_help)


func _set_status(text: String) -> void:
	if _status != null:
		_status.text = text
	print(text)


func _on_progress(done: int, total: int) -> void:
	if _bar != null and total > 0:
		_bar.value = clampf(float(done) / float(total) * 100.0, 0.0, 100.0)


func _load_world() -> void:
	_set_status("loading manifest")
	var manifest: Variant = await fetcher.fetch_json("assets/manifest.json")
	if manifest == null:
		_fail("could not load assets/manifest.json")
		return
	# The manifest stores paths relative to assets/ (e.g. "map/prontera/...").
	# Normalise them once so the rest of the client can use them directly.
	manifest.terrain = _asset_path(str(manifest.terrain))
	manifest.walk = _asset_path(str(manifest.walk))
	if manifest.props != null:
		manifest.props = _asset_path(str(manifest.props))
	_manifest = manifest

	var paths: Array[String] = [
		manifest.terrain,
		"assets/map/%s/terrain.bin" % MAP,
		"assets/map/%s/atlas.webp" % MAP,
		"assets/map/%s/lightmap.png" % MAP,
		manifest.walk,
	]
	if manifest.props != null:
		paths.append(manifest.props)
		paths.append("assets/map/%s/props.bin" % MAP)

	var terrain_json: Dictionary = await fetcher.fetch_json(manifest.terrain)
	if terrain_json.is_empty():
		_fail("terrain json missing")
		return
	var props_json: Dictionary = {}
	if manifest.props != null:
		props_json = await fetcher.fetch_json(manifest.props)

	var prop_tex_paths: Array[String] = []
	for g in props_json.get("groups", []):
		var t := "assets/" + str(g.texture)
		if not prop_tex_paths.has(t):
			prop_tex_paths.append(t)

	var sprite_entries: Array = manifest.get("sprites", [])
	var sprite_paths: Array[String] = []
	for s in sprite_entries:
		sprite_paths.append("assets/%s.webp" % str(s.file))

	var all_paths: Array[String] = []
	all_paths.append_array(paths)
	for p in prop_tex_paths:
		all_paths.append(p)
	for p in sprite_paths:
		all_paths.append(p)

	_set_status("fetching %d files" % all_paths.size())
	fetcher.set_total(all_paths.size())
	var blobs: Dictionary = await fetcher.fetch_many(all_paths)

	_set_status("building terrain")
	var terrain_bin: PackedByteArray = blobs.get("assets/map/%s/terrain.bin" % MAP, PackedByteArray())
	var atlas := Fetcher.image_from_bytes(blobs.get("assets/map/%s/atlas.webp" % MAP, PackedByteArray()))
	var lightmap := Fetcher.image_from_bytes(blobs.get("assets/map/%s/lightmap.png" % MAP, PackedByteArray()))
	var parsed_terrain := MeshIO.parse_terrain(terrain_bin)
	if parsed_terrain.is_empty() or atlas == null or lightmap == null:
		_fail("terrain assets are broken")
		return

	world = World.new()
	world.name = "World"
	add_child(world)
	world.setup_terrain(terrain_json, parsed_terrain, atlas, lightmap)
	world.setup_walk(blobs.get(manifest.walk, PackedByteArray()), terrain_json.walk)

	if not props_json.is_empty():
		_set_status("building props")
		var textures := {}
		for p in prop_tex_paths:
			var tex := Fetcher.image_from_bytes(blobs.get(p, PackedByteArray()))
			if tex != null:
				textures[p.trim_prefix("assets/")] = tex
		var props_bin: PackedByteArray = blobs.get("assets/map/%s/props.bin" % MAP, PackedByteArray())
		var parsed_props := MeshIO.parse_props(props_bin)
		if not parsed_props.is_empty():
			world.build_props(props_json.get("groups", []), parsed_props, textures)

	_set_status("spawning")
	_spawn_player(sprite_entries, blobs, sprite_paths, manifest)
	_spawn_monsters(sprite_entries, blobs, sprite_paths)

	cam.target = player

	_start_music(manifest)

	_loading_box.visible = false
	_help.visible = true
	var tween := create_tween()
	tween.tween_property(_fade, "color:a", 0.0, 0.6)
	tween.tween_callback(_fade.hide)
	_started = true
	_set_status("ready")

	if OS.get_cmdline_user_args().has("--selftest"):
		print("selftest: player at ", player.position, " entities=", _entities.size())
		await get_tree().create_timer(0.2).timeout
		get_tree().quit(0)


func _fail(msg: String) -> void:
	push_error(msg)
	if _status != null:
		_status.text = msg
	if OS.get_cmdline_user_args().has("--selftest"):
		get_tree().quit(1)


static func _asset_path(path: String) -> String:
	if path.begins_with("assets/") or path.begins_with("res://") or path.begins_with("http"):
		return path
	return "assets/" + path


func _find_sprite(id: String, entries: Array) -> Dictionary:
	for s in entries:
		if str(s.id) == id:
			return s
	return {}


func _make_entity(entry: Dictionary, tex: Texture2D) -> SpriteEntity:
	var e := SpriteEntity.new()
	e.setup(entry, tex)
	return e


func _spawn_player(entries: Array, blobs: Dictionary, sprite_paths: Array[String], manifest: Dictionary) -> void:
	var entry := _find_sprite("novice_m", entries)
	if entry.is_empty():
		return
	var path := "assets/%s.webp" % str(entry.file)
	var tex := Fetcher.image_from_bytes(blobs.get(path, PackedByteArray()))
	player = Player.new()
	player.setup(entry, tex)
	player.world = world
	var sp: Array = manifest.get("spawn", [156.0, 196.0])
	# The GND spawn point can sit on unwalkable geometry (the fountain); snap it
	# to the closest walkable cell so the player never starts inside a prop.
	var cell := world.nearest_walkable(Vector2i(int(sp[0]), int(sp[1])))
	var x := float(cell.x) + 0.5
	var z := float(cell.y) + 0.5
	player.position = Vector3(x, world.ground_height(x, z), z)
	player.facing = PI
	add_child(player)
	_entities.append(player)


func _spawn_monsters(entries: Array, blobs: Dictionary, sprite_paths: Array[String]) -> void:
	var rng := RandomNumberGenerator.new()
	rng.seed = 7
	var kinds := ["poring", "poring", "poring", "lunatic", "fabre", "poporing"]
	for i in kinds.size():
		var entry := _find_sprite(kinds[i], entries)
		if entry.is_empty():
			continue
		var tex := Fetcher.image_from_bytes(blobs.get("assets/%s.webp" % str(entry.file), PackedByteArray()))
		var npc := Wanderer.new()
		npc.setup(entry, tex)
		var spot := world.random_walkable_near(Vector2(player.position.x, player.position.z), 26.0, rng)
		npc.position = Vector3(spot.x, world.ground_height(spot.x, spot.z), spot.z)
		npc.facing = rng.randf() * TAU
		npc.leash = rng.randf_range(10.0, 22.0)
		add_child(npc)
		npc.setup_world(world)
		_entities.append(npc)


func _start_music(manifest: Dictionary) -> void:
	var audio_path := "assets/audio/prontera.mp3"
	bgm = AudioStreamPlayer.new()
	bgm.volume_db = -6.0
	add_child(bgm)
	var bytes := await fetcher.fetch(audio_path)
	if bytes.is_empty():
		return
	var stream := AudioStreamMP3.new()
	stream.data = bytes
	stream.loop = true
	bgm.stream = stream


func _play_music_once() -> void:
	if _autoplay_tried or bgm == null or bgm.stream == null:
		return
	_autoplay_tried = true
	bgm.play()


func _screen_to_ground(screen_pos: Vector2) -> Vector3:
	var camera := get_viewport().get_camera_3d()
	if camera == null:
		return Vector3.ZERO
	var origin := camera.project_ray_origin(screen_pos)
	var dir := camera.project_ray_normal(screen_pos)
	var t := 0.0
	while t < 700.0:
		var p := origin + dir * t
		var g := world.ground_height(p.x, p.z)
		if p.y <= g + 0.3:
			return Vector3(p.x, g, p.z)
		t += 0.75
	return Vector3.ZERO


func _unhandled_input(event: InputEvent) -> void:
	if not _started:
		return
	if event is InputEventMouseButton:
		var mb := event as InputEventMouseButton
		if mb.button_index == MOUSE_BUTTON_LEFT and mb.pressed:
			_play_music_once()
			var hit := _screen_to_ground(mb.position)
			if hit != Vector3.ZERO and world.is_walkable(hit.x, hit.z):
				player.move_to(world.find_path(player.position, hit))
		elif mb.button_index == MOUSE_BUTTON_RIGHT:
			_dragging = mb.pressed
		elif mb.pressed and mb.button_index == MOUSE_BUTTON_WHEEL_UP:
			cam.zoom_by(-1.0)
		elif mb.pressed and mb.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			cam.zoom_by(1.0)
	elif event is InputEventMouseMotion and _dragging:
		var mm := event as InputEventMouseMotion
		cam.rotate_by(mm.relative.x, mm.relative.y)
	elif event is InputEventKey and event.pressed:
		var key := event as InputEventKey
		if key.keycode == KEY_H:
			_help.visible = not _help.visible


func _process(_delta: float) -> void:
	if player != null:
		player.cam_yaw = deg_to_rad(cam.yaw_deg)
		for e in _entities:
			if e != player:
				e.camera_yaw = player.cam_yaw
