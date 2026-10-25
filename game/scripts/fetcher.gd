class_name Fetcher
extends Node

## Small HTTP helper: relative-path fetches against the folder that serves the
## game, with a concurrency limit so a map full of textures does not open 200
## sockets at once.
##
## GitHub Pages serves everything with `Cache-Control: max-age=600`, so a fresh
## deployment can hand a browser an old `index.pck` for up to ten minutes.  To
## keep the asset pack in sync with the client, every request carries the
## `RO_ASSET_BUILD` stamp that `tools/build_web.py` bakes into `index.html`.
## Failed requests are retried with a unique query so a stale CDN/browser copy
## is skipped instead of failing the whole load.

signal progress(done: int, total: int)

const MAX_ATTEMPTS := 3
const RETRY_DELAY := 0.4

var base_url := ""
var build_id := ""
var max_parallel := 12
var last_error := ""

var _inflight := 0
var _done := 0
var _total := 0
var _nonce := 0


func _ready() -> void:
	if base_url == "":
		base_url = detect_base()
	if build_id == "":
		build_id = detect_build()
	print("fetcher: base=%s build=%s" % [base_url, build_id if build_id != "" else "(local)"])


static func detect_base() -> String:
	if OS.has_feature("web"):
		var href := str(JavaScriptBridge.eval("location.href.split('?')[0].split('#')[0]", true))
		var slash := href.rfind("/")
		if slash >= 0:
			return href.substr(0, slash + 1)
	return "http://127.0.0.1:8080/"


## Build stamp of the asset pack, injected by tools/build_web.py.  Empty for
## desktop runs, which read the pack straight from the local folder.
static func detect_build() -> String:
	if OS.has_feature("web"):
		var value: Variant = JavaScriptBridge.eval("window.RO_ASSET_BUILD || ''", true)
		if value != null:
			var text: String = str(value)
			if text != "" and text != "null" and text != "undefined":
				return text
	return ""


func set_total(n: int) -> void:
	_total = n
	_done = 0


func _next_nonce() -> int:
	_nonce += 1
	return int(Time.get_ticks_msec()) + _nonce


func url_for(rel: String, bust: bool = false) -> String:
	var url := base_url + rel
	var sep := "&" if url.contains("?") else "?"
	if build_id != "":
		url += sep + "v=" + build_id
		sep = "&"
	if bust:
		url += sep + "t=" + str(_next_nonce())
	return url


## One HTTP GET.  Returns {code, body, error}; never throws.
func _request(url: String) -> Dictionary:
	var req := HTTPRequest.new()
	req.timeout = 60.0
	# Browsers already decompress gzip/br responses for the fetch() that backs
	# HTTPRequest on the web. Letting Godot decompress again makes it fail with
	# a StreamPeerGZIP error on GitHub Pages (which gzips JSON).
	req.accept_gzip = false
	add_child(req)
	var err := req.request(url)
	if err != OK:
		req.queue_free()
		return {"code": -err, "body": PackedByteArray(), "error": "request() failed (%d)" % err}
	var res: Array = await req.request_completed
	req.queue_free()
	var result := int(res[0])
	var code := int(res[1])
	var body: PackedByteArray = res[3]
	if result != HTTPRequest.RESULT_SUCCESS:
		return {"code": code, "body": PackedByteArray(), "error": "transport error %d" % result}
	return {"code": code, "body": body, "error": ""}


func _describe(rel: String, res: Dictionary) -> String:
	var code := int(res.get("code", 0))
	var error := str(res.get("error", ""))
	var body: PackedByteArray = res.get("body", PackedByteArray())
	if code > 0 and code != 200:
		return "%s: HTTP %d" % [rel, code]
	if error != "":
		return "%s: %s" % [rel, error]
	if body.is_empty():
		return "%s: empty response" % rel
	return rel


func _fetch_with_retry(rel: String) -> PackedByteArray:
	var attempt := 1
	while true:
		var res := await _request(url_for(rel, attempt > 1))
		var body: PackedByteArray = res.get("body", PackedByteArray())
		if int(res.get("code", 0)) == 200 and not body.is_empty():
			last_error = ""
			return body
		last_error = _describe(rel, res)
		if attempt >= MAX_ATTEMPTS:
			push_error("fetch failed after %d attempts: %s" % [attempt, last_error])
			return PackedByteArray()
		await get_tree().create_timer(RETRY_DELAY * attempt).timeout
		attempt += 1
	return PackedByteArray()


func fetch(rel: String) -> PackedByteArray:
	while _inflight >= max_parallel:
		await get_tree().create_timer(0.004).timeout
	_inflight += 1
	var body := await _fetch_with_retry(rel)
	_inflight -= 1
	_done += 1
	progress.emit(_done, _total)
	return body


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
			_start_batch(str(_batch_queue.pop_front()), 1)
		await get_tree().process_frame
	return _batch_results


func _start_batch(path: String, attempt: int) -> void:
	var req := HTTPRequest.new()
	req.timeout = 60.0
	req.accept_gzip = false
	add_child(req)
	req.request_completed.connect(_on_batch_response.bind(path, req, attempt), CONNECT_ONE_SHOT)
	var err := req.request(url_for(path, attempt > 1))
	if err != OK:
		req.queue_free()
		_finish_batch(path, attempt, {"code": -err, "body": PackedByteArray(), "error": "request() failed (%d)" % err})
		return
	_batch_active.append(req)


func _on_batch_response(_result: int, code: int, _headers: PackedStringArray, body: PackedByteArray, path: String, req: HTTPRequest, attempt: int) -> void:
	_batch_active.erase(req)
	req.queue_free()
	_finish_batch(path, attempt, {"code": code, "body": body, "error": "" if code > 0 else "transport error"})


func _finish_batch(path: String, attempt: int, res: Dictionary) -> void:
	var body: PackedByteArray = res.get("body", PackedByteArray())
	if int(res.get("code", 0)) == 200 and not body.is_empty():
		_batch_results[path] = body
		last_error = ""
		_batch_pending -= 1
		_done += 1
		progress.emit(_done, _total)
		return
	last_error = _describe(path, res)
	if attempt < MAX_ATTEMPTS:
		await get_tree().create_timer(RETRY_DELAY * attempt).timeout
		_start_batch(path, attempt + 1)
		return
	push_error("fetch failed after %d attempts: %s" % [attempt, last_error])
	_batch_results[path] = PackedByteArray()
	_batch_pending -= 1
	_done += 1
	progress.emit(_done, _total)


func fetch_text(rel: String) -> String:
	var data := await fetch(rel)
	return data.get_string_from_utf8()


func fetch_json(rel: String) -> Variant:
	var text := await fetch_text(rel)
	if text.is_empty():
		return null
	var parser := JSON.new()
	if parser.parse(text) != OK:
		last_error = "%s: bad JSON (%s)" % [rel, parser.get_error_message()]
		push_error(last_error)
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
