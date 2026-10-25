class_name MeshIO

## Binary readers for the asset pipeline output (see tools/build_assets.py).

const TERRAIN_MAGIC := 0x324D4F52  # "ROM2"
const PROPS_MAGIC := 0x52504F52  # "ROPR"


static func _u32(data: PackedByteArray, off: int) -> int:
	return data.decode_u32(off)


static func parse_terrain(data: PackedByteArray) -> Dictionary:
	if data.size() < 12 or _u32(data, 0) != TERRAIN_MAGIC:
		push_error("terrain.bin: bad header")
		return {}
	var nv := _u32(data, 4)
	var ni := _u32(data, 8)
	var off := 12

	var raw_pos := data.slice(off, off + nv * 12).to_float32_array()
	off += nv * 12
	var raw_uv := data.slice(off, off + nv * 8).to_float32_array()
	off += nv * 8
	var raw_uv2 := data.slice(off, off + nv * 8).to_float32_array()
	off += nv * 8
	var raw_col := data.slice(off, off + nv * 4)
	off += nv * 4
	var indices := data.slice(off, off + ni * 4).to_int32_array()

	var verts := PackedVector3Array()
	var uvs := PackedVector2Array()
	var uv2s := PackedVector2Array()
	var colors := PackedColorArray()
	verts.resize(nv)
	uvs.resize(nv)
	uv2s.resize(nv)
	colors.resize(nv)
	for i in nv:
		verts[i] = Vector3(raw_pos[i * 3], raw_pos[i * 3 + 1], raw_pos[i * 3 + 2])
		uvs[i] = Vector2(raw_uv[i * 2], raw_uv[i * 2 + 1])
		uv2s[i] = Vector2(raw_uv2[i * 2], raw_uv2[i * 2 + 1])
		colors[i] = Color8(raw_col[i * 4], raw_col[i * 4 + 1], raw_col[i * 4 + 2], raw_col[i * 4 + 3])
	return {"verts": verts, "uvs": uvs, "uv2s": uv2s, "colors": colors, "indices": indices}


static func parse_props(data: PackedByteArray) -> Dictionary:
	if data.size() < 16 or _u32(data, 0) != PROPS_MAGIC:
		push_error("props.bin: bad header")
		return {}
	var ng := _u32(data, 4)
	var nv := _u32(data, 8)
	var ni := _u32(data, 12)
	var off := 16

	var raw_pos := data.slice(off, off + nv * 12).to_float32_array()
	off += nv * 12
	off += nv * 12  # normals (unused: lighting is baked into vertex colours)
	var raw_uv := data.slice(off, off + nv * 8).to_float32_array()
	off += nv * 8
	var raw_col := data.slice(off, off + nv * 4)
	off += nv * 4
	var indices := data.slice(off, off + ni * 4).to_int32_array()

	var verts := PackedVector3Array()
	var uvs := PackedVector2Array()
	var colors := PackedColorArray()
	verts.resize(nv)
	uvs.resize(nv)
	colors.resize(nv)
	for i in nv:
		verts[i] = Vector3(raw_pos[i * 3], raw_pos[i * 3 + 1], raw_pos[i * 3 + 2])
		uvs[i] = Vector2(raw_uv[i * 2], raw_uv[i * 2 + 1])
		colors[i] = Color8(raw_col[i * 4], raw_col[i * 4 + 1], raw_col[i * 4 + 2], raw_col[i * 4 + 3])
	return {"groups": ng, "verts": verts, "uvs": uvs, "colors": colors, "indices": indices}


static func terrain_mesh(parsed: Dictionary) -> ArrayMesh:
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = parsed.verts
	arrays[Mesh.ARRAY_TEX_UV] = parsed.uvs
	arrays[Mesh.ARRAY_TEX_UV2] = parsed.uv2s
	arrays[Mesh.ARRAY_COLOR] = parsed.colors
	arrays[Mesh.ARRAY_INDEX] = parsed.indices
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh
