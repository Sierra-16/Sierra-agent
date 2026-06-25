# SVG Layout Reference

## Coordinate System

- Use a `1200 x 760` viewBox for the default landscape diagram.
- Reserve 48 px around the canvas and 88 px at the bottom for the legend.
- Use a 12-column logical grid with 24 px gutters.
- Keep nodes at least 32 px apart and keep labels 16 px away from connectors.

## Drawing Order

1. Trust and deployment boundaries.
2. Synchronous and asynchronous connectors.
3. Nodes and data stores.
4. Labels, protocol badges, and uncertainty marks.
5. Legend.

## Connector Rules

- Give every arrow marker a unique ID derived from the diagram subject.
- Route connectors orthogonally where possible.
- Do not terminate an arrow under a label or inside a node.
- Use solid lines for request/response paths and dashed lines for asynchronous events.
- Add a short protocol label only when it helps explain the boundary.

## Final Check

- Every visible edge has a source and target.
- No edge crosses node text.
- Inferred components or links include a `?` marker.
- The legend sits outside all system boundaries.
- Text remains readable at a browser width of 720 px.
