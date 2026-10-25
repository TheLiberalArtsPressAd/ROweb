class_name Wanderer
extends SpriteEntity

## Idle monster that now and then strolls to a nearby walkable cell.

var world: World
var speed := 2.2
var path: Array = []
var wait := 0.0
var rng := RandomNumberGenerator.new()
var home := Vector2.ZERO
var leash := 16.0


func setup_world(world_ref: World) -> void:
	world = world_ref
	home = Vector2(position.x, position.z)
	rng.randomize()
	wait = rng.randf_range(0.5, 4.0)


func is_moving() -> bool:
	return not path.is_empty()


func _process(delta: float) -> void:
	super._process(delta)
	if world == null:
		return
	if path.is_empty():
		wait -= delta
		if wait <= 0.0:
			var target := world.random_walkable_near(home, leash, rng)
			path = world.find_path(position, target)
			wait = rng.randf_range(2.0, 7.0)
	else:
		var step := speed * delta
		while step > 0.0 and not path.is_empty():
			var wp: Vector3 = path[0]
			var dx := wp.x - position.x
			var dz := wp.z - position.z
			var dist := sqrt(dx * dx + dz * dz)
			if dist <= step:
				position.x = wp.x
				position.z = wp.z
				step -= dist
				path.pop_front()
			else:
				position.x += dx / dist * step
				position.z += dz / dist * step
				facing = atan2(dx, dz)
				step = 0.0
	position.y = world.ground_height(position.x, position.z)
	update_facing(facing, camera_yaw)
