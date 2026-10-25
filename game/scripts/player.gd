class_name Player
extends SpriteEntity

## Click-to-move player: follows an A* path over the altitude grid.

var world: World
var speed := 7.5
var path: Array = []
var moving := false
var cam_yaw := 0.0


func move_to(points: Array) -> void:
	path = points
	moving = not path.is_empty()


func stop() -> void:
	path.clear()
	moving = false


func is_moving() -> bool:
	return moving


func _process(delta: float) -> void:
	super._process(delta)
	if moving:
		var step := speed * delta
		while step > 0.0 and not path.is_empty():
			var wp: Vector3 = path[0]
			var dx := wp.x - position.x
			var dz := wp.z - position.z
			var dist := sqrt(dx * dx + dz * dz)
			if dist <= step:
				if dist > 0.001:
					facing = atan2(dx, dz)
				position.x = wp.x
				position.z = wp.z
				step -= dist
				path.pop_front()
				if path.is_empty():
					moving = false
			else:
				position.x += dx / dist * step
				position.z += dz / dist * step
				facing = atan2(dx, dz)
				step = 0.0
	if world != null:
		position.y = world.ground_height(position.x, position.z)
	update_facing(facing, cam_yaw)
