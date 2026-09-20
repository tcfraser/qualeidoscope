// Built-in amplitude-to-color mapping.
// norm is the positive magnitude that reaches full brightness, not the state L2 norm.
// phase_offset is in radians. Return straight-alpha display RGB in [0, 1].
// steepness is the positive "Amplitude threshold" exponent; default 4, linear at 1.
// OKLab conversion: https://bottosson.github.io/posts/oklab/ (public-domain reference).
fn oklab_to_linear_srgb(lab: vec3<f32>) -> vec3<f32> {
    let roots = vec3<f32>(
        lab.x + 0.3963377774 * lab.y + 0.2158037573 * lab.z,
        lab.x - 0.1055613458 * lab.y - 0.0638541728 * lab.z,
        lab.x - 0.0894841775 * lab.y - 1.2914855480 * lab.z);
    let lms = roots * roots * roots;
    return vec3<f32>(
         4.0767416621 * lms.x - 3.3077115913 * lms.y + 0.2309699292 * lms.z,
        -1.2684380046 * lms.x + 2.6097574011 * lms.y - 0.3413193965 * lms.z,
        -0.0041960863 * lms.x - 0.7034186147 * lms.y + 1.7076147010 * lms.z);
}

fn linear_to_display_srgb(linear: vec3<f32>) -> vec3<f32> {
    let rgb = clamp(linear, vec3<f32>(0.0), vec3<f32>(1.0));
    return select(1.055 * pow(rgb, vec3<f32>(1.0 / 2.4)) - 0.055,
                  12.92 * rgb, rgb <= vec3<f32>(0.0031308));
}

// Find the available C/L ratio for this OKLab hue. At L=1, the first negative
// RGB component marks the saturation boundary; overall intensity is set below.
// A fixed iteration count bounds the work. No lookup table or library is needed.
fn hue_saturation_limit(direction: vec2<f32>) -> f32 {
    var low = 0.0;
    var high = 1.0;
    for (var step = 0u; step < 12u; step += 1u) {
        let ratio = (low + high) * 0.5;
        let rgb = oklab_to_linear_srgb(vec3<f32>(1.0, ratio * direction));
        if (min(rgb.r, min(rgb.g, rgb.b)) >= 0.0) {
            low = ratio;
        } else {
            high = ratio;
        }
    }
    return low;
}

fn amplitude_color(amplitude: vec2<f32>, norm: f32, phase_offset: f32, steepness: f32) -> vec4<f32> {
    // Scaled length avoids squaring very small or very large input components.
    let scale = max(abs(amplitude.x), abs(amplitude.y));
    if (scale == 0.0) { return vec4<f32>(0.0, 0.0, 0.0, 1.0); }
    let magnitude = scale * length(amplitude / scale);
    let hue = atan2(amplitude.y, amplitude.x) + phase_offset;
    let relative_magnitude = min(magnitude, norm) / norm;
    // Guard ratios that underflow to zero before pow; exact zeros stay black.
    if (relative_magnitude == 0.0) { return vec4<f32>(0.0, 0.0, 0.0, 1.0); }
    let brightness = pow(relative_magnitude, steepness);
    let direction = vec2<f32>(cos(hue), sin(hue));
    // Use 95% of this hue's available saturation for vivid, slightly softened color.
    let saturation = 0.95 * hue_saturation_limit(direction);
    let rgb = oklab_to_linear_srgb(vec3<f32>(1.0, saturation * direction));
    // A full-scale amplitude reaches a display channel value of 1 for every hue.
    let peak_rgb = rgb / max(rgb.r, max(rgb.g, rgb.b));
    // The power curve scales linear-light intensity: larger exponents suppress
    // smaller amplitudes, while the normalization endpoint stays fully bright.
    // Scaling all channels equally preserves OKLab hue and saturation.
    return vec4<f32>(linear_to_display_srgb(peak_rgb * brightness), 1.0);
}
