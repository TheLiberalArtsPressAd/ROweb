class_name Fetcher
extends Node

## Small HTTP helper: relative-path fetches against the folder that serves the
## game, with a concurrency limit so a map full of textures does not open 200
## sockets at once.

signal progress(done: int, total: int)

var base_url := ""
var max_parallel := 12

var _inflight := 0
var _done := 0
var _total := 0


func _ready() -> void:
	if base_url == "":
		base_url = detect_base()


static func detect_base() -> String:
	if OS.has_feature("web"):
		var href := str(JavaScriptBridge.eval("location.href.split('?')[0].split('#')[0]", true))
		var slash := href.rfind("/")
		if slash >= 0:
			return href.substr(0, slash + 1)
	return "http://127.0.0.1:8080/"


func set_total(n: int) -> void:
	_total = n
	_done = 0


func _load_url(url: String) -> PackedByteArray:
	var req := HTTPRequest.new()
	req.timeout = 60.0
	# Browsers already decompress gzip/br responses for the fetch() that backs
	# HTTPRequest on the web. Letting Godot decompress again makes it fail with
	# a StreamPeerGZIP error on GitHub Pages (which gzips JSON).
	req.accept_gzip = false
	add_child(req)
	var err := req.request(url)
	if err != OK:
		_inflight -= 1
		req.queue_free()
		push_error("request failed: %s (%d)" % [url, err])
		return PackedByteArray()
	var res: Array = await req.request_completed
	req.queue_free()
	_inflight -= 1
	_done += 1
	progress.emit(_done, _total)
	if res[1] != 200:
		push_error("HTTP %d: %s" % [res[1], url])
		return PackedByteArray()
	return res[3]


func fetch(rel: String) -> PackedByteArray:
	while _inflight >= max_parallel:
		await get_tree().create_timer(0.004).timeout
	_inflight += 1
	return await _load_url(base_url + rel)


# --- batched fetching -------------------------------------------------------
# Coroutines cannot be stored in GDScript, so parallel downloads are driven by
# HTTPRequest nodes and a completion handler instead of awaiting each call.

var _batch_results := {}
var _batch_queue: Array = []
var _batch_active: Array = []
var _batch_pending := 0


func fetch_many(paths: Array) -> Dictionary:
	_batch_results = {}
	_batch_queue = paths.duplicate()
	_batch_pending = paths.size()
	_batch_active.clear()
	while _batch_pending > 0:
		while _batch_active.size() < max_parallel and not _batch_queue.is_empty():
			var p: String = _batch_queue.pop_front()
			var req := HTTPRequest.new()
			req.timeout = 60.0
			req.accept_gzip = false
			add_child(req)
			req.request_completed.connect(_on_batch_response.bind(p, req), CONNECT_ONE_SHOT)
			var err := req.request(base_url + p)
			if err != OK:
				push_error("request failed: %s (%d)" % [p, err])
				_batch_results[p] = PackedByteArray()
				_batch_pending -= 1
				req.queue_free()
				continue
			_batch_active.append(req)
		await get_tree().process_frame
	return _batch_results


func _on_batch_response(_result: int, code: int, _headers: PackedStringArray, body: PackedByteArray, path: String, req: HTTPRequest) -> void:
	if code == 200:
		_batch_results[path] = body
	else:
		push_error("HTTP %d: %s" % [code, path])
		_batch_results[path] = PackedByteArray()
	_batch_active.erase(req)
	_batch_pending -= 1
	_done += 1
	progress.emit(_done, _total)
	req.queue_free()


func fetch_text(rel: String) -> String:
	var data := await fetch(rel)
	return data.get_string_from_utf8()


func fetch_json(rel: String) -> Variant:
	var text := await fetch_text(rel)
	if text.is_empty():
		return null
	var parser := JSON.new()
	if parser.parse(text) != OK:
		push_error("json error in %s: %s" % [rel, parser.get_error_message()])
		return null
	return parser.data


func fetch_image(rel: String) -> ImageTexture:
	var data := await fetch(rel)
	return image_from_bytes(data)


static func image_from_bytes(data: PackedByteArray) -> ImageTexture:
	if data.is_empty():
		return null
	var img := Image.new()
	var err := ERR_FILE_UNRECOGNIZED
	if data.size() > 12 and data[0] == 0x89 and data[1] == 0x50:
		err = img.load_png_from_buffer(data)
	else:
		err = img.load_webp_from_buffer(data)
	if err != OK:
		push_error("cannot decode texture (%d bytes)" % data.size())
		return null
	return ImageTexture.create_from_image(img)
