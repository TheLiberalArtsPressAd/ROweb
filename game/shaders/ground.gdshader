shader_type spatial;

// Ragnarok ground: tiled atlas texture multiplied by the per-cell lightmap.
// RoBrowser multiplies colour and lightmap in sRGB space, so the lightmap is
// imported as sRGB and the vertex colour (tile tint * directional light) is
// linearised here to keep the same result in Godot's linear pipeline.
render_mode unshaded, cull_disabled, depth_draw_opaque;

uniform sampler2D albedo_tex : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D lightmap_tex : source_color, filter_linear, repeat_disable;
uniform float brightness = 1.0;

void fragment() {
	vec4 tex = texture(albedo_tex, UV);
	float lm = texture(lightmap_tex, UV2).r;
	vec3 tint = pow(COLOR.rgb, vec3(2.2));
	ALBEDO = tex.rgb * lm * tint * brightness;
	ALPHA = tex.a;
}
