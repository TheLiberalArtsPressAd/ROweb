class_name World
extends Node3D

## Terrain, walkability and baked static props for one map.

const GROUND_SHADER := preload("res://shaders/ground.gdshader")

var meta: Dictionary = {}
var props_meta: Dictionary = {}
var spawn := Vector2(156.0, 196.0)

var _heights := PackedInt32Array()
var _grid_w := 0
var _grid_h := 0
var _walk := PackedByteArray()
var _walk_w := 0
var _walk_h := 0

var astar := AStarGrid2D.new()
var ground_mesh: MeshInstance3D
var props_mesh: MeshInstance3D


func setup_terrain(terrain: Dictionary, parsed: Dictionary, atlas: Texture2D, lightmap: Texture2D) -> void:
	meta = terrain
	_grid_w = int(terrain.width)
	_grid_h = int(terrain.height)
	_heights = PackedInt32Array(terrain.heights.data)

	ground_mesh = MeshInstance3D.new()
	ground_mesh.name = "Ground"
	ground_mesh.mesh = MeshIO.terrain_mesh(parsed)
	ground_mesh.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF

	var mat := ShaderMaterial.new()
	mat.shader = GROUND_SHADER
	mat.set_shader_parameter("albedo_tex", atlas)
	mat.set_shader_parameter("lightmap_tex", lightmap)
	mat.set_shader_parameter("brightness", 1.0)
	ground_mesh.material_override = mat
	add_child(ground_mesh)

	if terrain.has("spawn"):
		spawn = Vector2(float(terrain.spawn[0]), float(terrain.spawn[1]))


func setup_walk(raw: PackedByteArray, walk: Dictionary) -> void:
	_walk = raw
	_walk_w = int(walk.width)
	_walk_h = int(walk.height)
	astar.region = Rect2i(0, 0, _walk_w, _walk_h)
	astar.cell_size = Vector2(1, 1)
	astar.diagonal_mode = AStarGrid2D.DIAGONAL_MODE_ONLY_IF_NO_OBSTACLES
	astar.default_compute_heuristic = AStarGrid2D.HEURISTIC_OCTILE
	astar.update()
	var solid := 0
	for y in _walk_h:
		var row := y * _walk_w
		for x in _walk_w:
			if _walk[row + x] == 0:
				astar.set_point_solid(Vector2i(x, y), true)
				solid += 1
	print("world: %d x %d cells, %d blocked" % [_walk_w, _walk_h, solid])


func build_props(groups: Array, parsed: Dictionary, textures: Dictionary) -> void:
	props_meta = {"groups": groups}
	var verts: PackedVector3Array = parsed.verts
	var uvs: PackedVector2Array = parsed.uvs
	var colors: PackedColorArray = parsed.colors
	var indices: PackedInt32Array = parsed.indices

	var mesh := ArrayMesh.new()
	for i in groups.size():
		var g: Dictionary = groups[i]
		var v0 := int(g.vstart)
		var vc := int(g.vcount)
		var i0 := int(g.istart)
		var ic := int(g.icount)
		if vc <= 0 or ic <= 0:
			continue

		var idx := PackedInt32Array()
		idx.resize(ic)
		for k in ic:
			idx[k] = indices[i0 + k] - v0

		var arrays := []
		arrays.resize(Mesh.ARRAY_MAX)
		arrays[Mesh.ARRAY_VERTEX] = verts.slice(v0, v0 + vc)
		arrays[Mesh.ARRAY_TEX_UV] = uvs.slice(v0, v0 + vc)
		arrays[Mesh.ARRAY_COLOR] = colors.slice(v0, v0 + vc)
		arrays[Mesh.ARRAY_INDEX] = idx
		var surface := mesh.get_surface_count()
		mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)

		var mat := StandardMaterial3D.new()
		var tex_path := str(g.get("texture", ""))
		var tex: Texture2D = textures.get(tex_path)
		if tex != null:
			mat.albedo_texture = tex
			mat.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS
		mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		mat.vertex_color_use_as_albedo = true
		mat.vertex_color_is_srgb = true
		mat.cull_mode = BaseMaterial3D.CULL_DISABLED
		if bool(g.get("alpha", false)):
			mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR
			mat.alpha_scissor_threshold = 0.4
			mat.alpha_antialiasing_mode = BaseMaterial3D.ALPHA_ANTIALIASING_OFF
		mesh.surface_set_material(surface, mat)

	props_mesh = MeshInstance3D.new()
	props_mesh.name = "Props"
	props_mesh.mesh = mesh
	props_mesh.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(props_mesh)
	print("world: %d prop materials" % mesh.get_surface_count())


func ground_height(x: float, z: float) -> float:
	var gx := int(clampf(x * 0.5, 0.0, _grid_w - 1))
	var gz := int(clampf(z * 0.5, 0.0, _grid_h - 1))
	if _heights.is_empty():
		return 0.0
	return -float(_heights[gz * _grid_w + gx]) * 0.1


func is_walkable(x: float, z: float) -> bool:
	var cx := int(x)
	var cz := int(z)
	if cx < 0 or cz < 0 or cx >= _walk_w or cz >= _walk_h:
		return false
	return _walk[cz * _walk_w + cx] != 0


func nearest_walkable(cell: Vector2i) -> Vector2i:
	if cell.x >= 0 and cell.y >= 0 and cell.x < _walk_w and cell.y < _walk_h:
		if _walk[cell.y * _walk_w + cell.x] != 0:
			return cell
	for radius in range(1, 24):
		for dy in range(-radius, radius + 1):
			for dx in range(-radius, radius + 1):
				if maxi(absi(dx), absi(dy)) != radius:
					continue
				var x := cell.x + dx
				var y := cell.y + dy
				if x < 0 or y < 0 or x >= _walk_w or y >= _walk_h:
					continue
				if _walk[y * _walk_w + x] != 0:
					return Vector2i(x, y)
	return cell


## True when a cell and all eight neighbours are walkable, i.e. it is part of
## an open plaza rather than a one-tile gap inside a prop (the fountain bowl).
func is_open_area(cell: Vector2i) -> bool:
	for dy in range(-1, 2):
		for dx in range(-1, 2):
			var x := cell.x + dx
			var y := cell.y + dy
			if x < 0 or y < 0 or x >= _walk_w or y >= _walk_h:
				return false
			if _walk[y * _walk_w + x] == 0:
				return false
	return true


func nearest_open_cell(cell: Vector2i) -> Vector2i:
	for radius in range(0, 32):
		for dy in range(-radius, radius + 1):
			for dx in range(-radius, radius + 1):
				if maxi(absi(dx), absi(dy)) != radius:
					continue
				var c := cell + Vector2i(dx, dy)
				if is_open_area(c):
					return c
	return nearest_walkable(cell)


func find_path(from: Vector3, to: Vector3) -> Array:
	var a := nearest_walkable(Vector2i(int(from.x), int(from.z)))
	var b := nearest_walkable(Vector2i(int(to.x), int(to.z)))
	if a == b:
		return [to]
	var cells := astar.get_id_path(a, b, true)
	var points := []
	for c in cells:
		points.append(Vector3(float(c.x) + 0.5, 0.0, float(c.y) + 0.5))
	if points.size() > 1:
		points.remove_at(0)
	if points.is_empty():
		return []
	return points


func random_walkable_near(center: Vector2, radius: float, rng: RandomNumberGenerator) -> Vector3:
	for _i in 40:
		var x := center.x + rng.randf_range(-radius, radius)
		var z := center.y + rng.randf_range(-radius, radius)
		if is_walkable(x, z):
			return Vector3(x, 0.0, z)
	return Vector3(center.x, 0.0, center.y)
