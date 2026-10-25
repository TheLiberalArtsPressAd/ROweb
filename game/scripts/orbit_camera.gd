class_name OrbitCamera
extends Node3D

## Ragnarok-style isometric orbit camera.

var target: Node3D
var yaw_deg := 0.0
var pitch_deg := 45.0
var distance := 52.0
var target_distance := 52.0
var min_distance := 16.0
var max_distance := 130.0
var follow_speed := 10.0

var camera: Camera3D


func _ready() -> void:
	camera = Camera3D.new()
	camera.fov = 32.0
	camera.near = 1.0
	camera.far = 900.0
	camera.current = true
	add_child(camera)


func rotate_by(delta_x: float, delta_y: float) -> void:
	yaw_deg = fmod(yaw_deg - delta_x * 0.35, 360.0)
	pitch_deg = clampf(pitch_deg + delta_y * 0.25, 18.0, 78.0)


func zoom_by(steps: float) -> void:
	target_distance = clampf(target_distance * pow(1.12, steps), min_distance, max_distance)


func _process(delta: float) -> void:
	distance = lerpf(distance, target_distance, clampf(delta * 8.0, 0.0, 1.0))
	var focus := Vector3.ZERO
	if target != null:
		focus = target.global_position + Vector3(0, 1.6, 0)
	var y := deg_to_rad(yaw_deg)
	var p := deg_to_rad(pitch_deg)
	var offset := Vector3(sin(y) * cos(p), sin(p), cos(y) * cos(p)) * distance
	global_position = global_position.lerp(focus + offset, clampf(delta * follow_speed, 0.0, 1.0))
	if global_position.distance_to(focus) > 0.01:
		look_at(focus, Vector3.UP)
