const FRAMEWORK = `
struct Params { view: vec4<f32>, color: vec4<f32> }
@group(0) @binding(0) var<storage, read> amplitudes: array<vec2<f32>>;
@group(0) @binding(1) var<uniform> params: Params;

@vertex fn vertex_main(@builtin(vertex_index) index: u32) -> @builtin(position) vec4<f32> {
    let positions = array<vec2<f32>, 3>(vec2<f32>(-1.0, -1.0), vec2<f32>(3.0, -1.0), vec2<f32>(-1.0, 3.0));
    return vec4<f32>(positions[index], 0.0, 1.0);
}

@fragment fn fragment_main(@builtin(position) position: vec4<f32>) -> @location(0) vec4<f32> {
    var amplitude: vec2<f32>;
    var coverage = 1.0;
    if (params.color.y > 0.5) {
        // Legend: radius is |a| / norm; phase increases counterclockwise from +Re.
        let point = (position.xy / params.view.yz * 2.0 - 1.0) * vec2<f32>(1.0, -1.0);
        let radius = length(point);
        if (radius > 1.0) { return vec4<f32>(0.0); }
        coverage = 1.0 - smoothstep(1.0 - 2.0 / params.view.y, 1.0, radius);
        amplitude = point * params.view.w;
    } else {
        let side = u32(params.view.x);
        let cell = min(vec2<u32>(position.xy / params.view.yz * params.view.x), vec2<u32>(side - 1u));
        amplitude = amplitudes[cell.y * side + cell.x];
    }
    let value = amplitude_color(amplitude, params.view.w, params.color.x, params.color.z);
    let rgba = clamp(value, vec4<f32>(0.0), vec4<f32>(1.0));
    return vec4<f32>(rgba.rgb * rgba.a, rgba.a) * coverage;
}
`;

export class Renderer {
  static async create(canvas, legendCanvas, onError) {
    if (!navigator.gpu) throw new Error("WebGPU is unavailable. Open localhost or HTTPS in a browser with WebGPU enabled.");
    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) throw new Error("No WebGPU adapter is available. Check your browser's GPU settings and graphics driver.");
    const device = await adapter.requestDevice();
    device.lost.then(info => onError(`GPU connection lost: ${info.message || info.reason}. Reload to reconnect.`));
    device.addEventListener("uncapturederror", event => onError(event.error.message));
    return new Renderer(canvas, legendCanvas, device);
  }

  constructor(canvas, legendCanvas, device) {
    this.canvas = canvas;
    this.legendCanvas = legendCanvas;
    this.device = device;
    this.context = canvas.getContext("webgpu");
    this.legendContext = legendCanvas.getContext("webgpu");
    this.format = navigator.gpu.getPreferredCanvasFormat();
    this.context.configure({ device, format: this.format, alphaMode: "premultiplied", colorSpace: "srgb" });
    this.legendContext.configure({ device, format: this.format, alphaMode: "premultiplied", colorSpace: "srgb" });
    this.uniforms = device.createBuffer({ size: 32, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
    this.legendUniforms = device.createBuffer({ size: 32, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
    this.layout = device.createBindGroupLayout({ entries: [
      { binding: 0, visibility: GPUShaderStage.FRAGMENT, buffer: { type: "read-only-storage" } },
      { binding: 1, visibility: GPUShaderStage.FRAGMENT, buffer: { type: "uniform" } },
    ] });
    this.pipelineLayout = device.createPipelineLayout({ bindGroupLayouts: [this.layout] });
    this.parameters = new Float32Array(8);
    this.legendParameters = new Float32Array(8);
  }

  async setShader(source) {
    this.device.pushErrorScope("validation");
    let pipeline, failure;
    try {
      const module = this.device.createShaderModule({ code: source + "\n" + FRAMEWORK });
      const info = await module.getCompilationInfo();
      const errors = info.messages.filter(message => message.type === "error");
      if (errors.length) throw new Error(errors.map(e => `Line ${e.lineNum}: ${e.message}`).join("\n"));
      pipeline = await this.device.createRenderPipelineAsync({
        layout: this.pipelineLayout,
        vertex: { module, entryPoint: "vertex_main" },
        fragment: { module, entryPoint: "fragment_main", targets: [{ format: this.format }] },
        primitive: { topology: "triangle-list" },
      });
    } catch (error) { failure = error; }
    const validation = await this.device.popErrorScope();
    if (failure || validation) throw failure || new Error(validation.message);
    this.pipeline = pipeline; // Only replace the working pipeline after successful compilation.
  }

  upload(values, side) {
    if (values.byteLength > this.device.limits.maxStorageBufferBindingSize) {
      throw new Error("This state exceeds the device's storage buffer limit.");
    }
    if (!this.storage || this.storage.size !== values.byteLength) {
      this.storage?.destroy();
      this.storage = this.device.createBuffer({ size: values.byteLength, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST });
      this.bindGroup = this.device.createBindGroup({ layout: this.layout, entries: [
        { binding: 0, resource: { buffer: this.storage } },
        { binding: 1, resource: { buffer: this.uniforms } },
      ] });
      this.legendBindGroup = this.device.createBindGroup({ layout: this.layout, entries: [
        { binding: 0, resource: { buffer: this.storage } },
        { binding: 1, resource: { buffer: this.legendUniforms } },
      ] });
    }
    this.device.queue.writeBuffer(this.storage, 0, values);
    this.side = side;
  }

  draw(norm, phase, steepness) {
    if (!this.pipeline || !this.bindGroup) return;
    this.parameters.set([this.side, this.canvas.width, this.canvas.height, norm, phase, 0, steepness, 0]);
    this.device.queue.writeBuffer(this.uniforms, 0, this.parameters);
    this.legendParameters.set([1, this.legendCanvas.width, this.legendCanvas.height, norm, phase, 1, steepness, 0]);
    this.device.queue.writeBuffer(this.legendUniforms, 0, this.legendParameters);
    const encoder = this.device.createCommandEncoder();
    // Both views share the same pipeline and color controls.
    for (const [context, bindGroup] of [[this.context, this.bindGroup], [this.legendContext, this.legendBindGroup]]) {
      const pass = encoder.beginRenderPass({ colorAttachments: [{
        view: context.getCurrentTexture().createView(),
        clearValue: [0, 0, 0, 0], loadOp: "clear", storeOp: "store",
      }] });
      pass.setPipeline(this.pipeline);
      pass.setBindGroup(0, bindGroup);
      pass.draw(3);
      pass.end();
    }
    this.device.queue.submit([encoder.finish()]);
  }
}
