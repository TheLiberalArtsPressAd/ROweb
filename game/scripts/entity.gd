class_name SpriteEntity
extends Node3D

## Camera-facing billboard driven by a pre-composited sprite atlas.

static var _shadow_texture: Texture2D

var meta: Dictionary = {}
var canvas := Vector2(160, 160)
var pivot := Vector2(80, 140)
var pixel := 1.0 / 35.0
var atlas: Texture2D

var row := 0
var frame := 0
var anim_time := 0.0
var playing := true

var _mesh: MeshInstance3D
var _material: StandardMaterial3D
var _atlas_cache := {}
var _shadow: MeshInstance3D

var facing := 0.0  # world yaw of the entity, radians, 0 = +Z (south)
var camera_yaw := 0.0


static func make_shadow_texture() -> Texture2D:
	if _shadow_texture != null:
		return _shadow_texture
	var size := 64
	var img := Image.create(size, size, false, Image.FORMAT_RGBA8)
	for y in size:
		for x in size:
			var d := Vector2(x - size * 0.5 + 0.5, y - size * 0.5 + 0.5).length() / (size * 0.5)
			var a := clampf(1.0 - d, 0.0, 1.0)
			a = a * a * 0.55
			img.set_pixel(x, y, Color(0, 0, 0, a))
	_shadow_texture = ImageTexture.create_from_image(img)
	return _shadow_texture


func setup(sprite_meta: Dictionary, texture: Texture2D) -> void:
	meta = sprite_meta
	atlas = texture
	if meta.has("canvas"):
		canvas = Vector2(float(meta.canvas[0]), float(meta.canvas[1]))
	else:
		# Older asset packs omit "canvas": every frame in an action shares the
		# same cell size, so the largest frame is the sprite canvas.
		var cw := 1
		var ch := 1
		for action in meta.get("actions", []):
			for r in action.get("frames", []):
				cw = maxi(cw, int(r[2]))
				ch = maxi(ch, int(r[3]))
		canvas = Vector2(cw, ch)
	pivot = Vector2(float(meta.pivot[0]), float(meta.pivot[1]))
	pixel = float(meta.get("pixel", 1.0 / 35.0))

	_material = StandardMaterial3D.new()
	_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	_material.billboard_mode = BaseMaterial3D.BILLBOARD_FIXED_Y
	_material.billboard_keep_scale = true
	_material.cull_mode = BaseMaterial3D.CULL_DISABLED
	_material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR
	_material.alpha_scissor_threshold = 0.5
	_material.texture_filter = BaseMaterial3D.TEXTURE_FILTER_NEAREST_WITH_MIPMAPS

	_mesh = MeshInstance3D.new()
	_mesh.mesh = _build_quad()
	_mesh.material_override = _material
	_mesh.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(_mesh)

	_shadow = MeshInstance3D.new()
	var quad := PlaneMesh.new()
	quad.size = Vector2(1.6, 1.6)
	_shadow.mesh = quad
	var smat := StandardMaterial3D.new()
	smat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	smat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	smat.albedo_texture = make_shadow_texture()
	smat.cull_mode = BaseMaterial3D.CULL_DISABLED
	smat.depth_draw_mode = BaseMaterial3D.DEPTH_DRAW_DISABLED
	_shadow.material_override = smat
	_shadow.position = Vector3(0, 0.02, 0)
	add_child(_shadow)

	set_row(0, 0)


func _build_quad() -> ArrayMesh:
	var x0 := -pivot.x * pixel
	var x1 := (canvas.x - pivot.x) * pixel
	var y0 := 0.0
	var y1 := canvas.y * pixel
	var verts := PackedVector3Array([
		Vector3(x0, y0, 0.0),
		Vector3(x0, y1, 0.0),
		Vector3(x1, y1, 0.0),
		Vector3(x1, y0, 0.0),
	])
	var uvs := PackedVector2Array([
		Vector2(0, 1), Vector2(0, 0), Vector2(1, 0), Vector2(1, 1),
	])
	var idx := PackedInt32Array([0, 1, 2, 0, 2, 3])
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = verts
	arrays[Mesh.ARRAY_TEX_UV] = uvs
	arrays[Mesh.ARRAY_INDEX] = idx
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh


func row_for(kind: String, direction: int) -> int:
	var names: Array = meta.get("action_names", [])
	var want := "%s_%d" % [kind, direction]
	var i := names.find(want)
	if i >= 0:
		return i
	for j in names.size():
		if str(names[j]).begins_with(kind):
			return j
	return 0


func set_row(new_row: int, start_frame: int = 0) -> void:
	if new_row == row and start_frame == 0:
		return
	row = clampi(new_row, 0, maxi(0, meta.actions.size() - 1))
	frame = start_frame
	anim_time = 0.0
	_apply_frame()


func _frame_rect() -> Rect2:
	var action: Dictionary = meta.actions[row]
	var rects: Array = action.frames
	var r: Array = rects[mini(frame, rects.size() - 1)]
	return Rect2(float(r[0]), float(r[1]), float(r[2]), float(r[3]))


func _apply_frame() -> void:
	if _material == null:
		return
	var rect := _frame_rect()
	var key := "%d_%d_%d_%d" % [int(rect.position.x), int(rect.position.y), int(rect.size.x), int(rect.size.y)]
	var tex: AtlasTexture = _atlas_cache.get(key)
	if tex == null:
		tex = AtlasTexture.new()
		tex.atlas = atlas
		tex.region = rect
		tex.filter_clip = true
		_atlas_cache[key] = tex
	_material.albedo_texture = tex


func _process(delta: float) -> void:
	if not playing or meta.is_empty():
		return
	var action: Dictionary = meta.actions[row]
	var frames: Array = action.frames
	if frames.size() <= 1:
		return
	anim_time += delta * 1000.0
	var delay := maxf(24.0, float(action.delay))
	while anim_time >= delay:
		anim_time -= delay
		frame = (frame + 1) % frames.size()
		_apply_frame()


func update_facing(world_yaw: float, cam_yaw: float) -> void:
	facing = world_yaw
	camera_yaw = cam_yaw
	var rel := world_yaw - cam_yaw
	var dir := posmod(int(round(-rel / (PI / 4.0))), 8)
	if is_moving():
		set_row(row_for("walk", dir))
	else:
		set_row(row_for("idle", dir))


func is_moving() -> bool:
	return false
