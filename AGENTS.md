# Working on Qualeidoscope

Qualeidoscope makes multi-qubit quantum states visible and explorable. Read
[DESIGN.md](DESIGN.md) before making architectural or product decisions.

## Product principles

- Treat enjoyment as a core requirement. A good product lives or dies by whether
  people enjoy using it. Favor responsive interaction, clear controls, sensible
  defaults, and a consistent visual style.
- Consider the end user's experience in every decision: setup, first render,
  everyday exploration, customization, and recovery from errors.
- Make simple tasks easy while allowing advanced users to control the rendering.
  Expose complexity progressively, where it helps the user accomplish something.
- Preserve scientific meaning. Make basis ordering, layout, normalization, and
  color mappings explicit and reproducible.

## Engineering principles

- Minimize external dependencies. Prefer a small, understandable implementation
  when practical. Justify dependencies by the capability, reliability, or
  maintenance burden they address; do not reinvent substantial infrastructure
  merely to avoid a dependency.
- Before introducing any external dependency, explain its purpose and why it is
  needed, then obtain the prompter's approval. This includes development and test
  tooling. Do not install Playwright; browser behavior is reviewed manually by
  the prompter for this prototype.
- Keep the architecture simple, modular, and proportionate to demonstrated needs.
  Separate state input, GPU rendering, and user interaction so that each can evolve
  without entangling the others.
- Consider performance from the start. State size grows exponentially with qubit
  count. Account for CPU and GPU memory, copies, transfers, shader work, and latency.
  Measure representative workloads before making performance claims or optimizing.
- Keep the interface responsive during uploads, shader compilation, and animation.
  Provide understandable feedback and actionable errors when resource limits or
  invalid inputs prevent rendering.
- Verify changes in proportion to their impact. Test mathematical conventions and
  data handling; inspect visual and interaction changes; measure changes that affect
  performance. Report what was checked and any remaining limitations.

## Collaboration and design decisions

- Ensure the prompter understands meaningful software engineering decisions.
  Explain the problem, viable alternatives, the chosen approach, and its effects
  on performance, ease of use, dependencies, and maintainability in plain language.
- Surface consequential tradeoffs early. Ask for direction when a decision depends
  on an unresolved product preference; use judgment for routine, reversible work.
- Record lasting decisions and their rationale in the design documentation. Keep
  proposals, settled decisions, and measured results clearly distinguishable.
- Do not silently expand scope or turn an exploratory idea into a fixed requirement.
  Keep the product vision and implementation documentation aligned as the project
  develops.
