# Paper Crown Styles

Paper Crown's shared book foundation lives in ordered modules under `core/`.
The renderer layers these files before the active theme's CSS, and web export
writes a generated `styles/book.css` bundle for the final artifact.

1. tokens and fonts
2. paged media
3. document typography
4. reference elements
5. art placement
6. TTRPG components
7. book structure
8. generated matter
9. web and print fixes

Theme packs should usually override custom properties in `tokens.css`, then add
a small number of component rules in `components.css`. A compact custom theme
can use one declared file like `theme.css` instead. The `theme.yaml` `css` list
is the source of truth, and `book.css` is reserved for generated web output, not
source theme authoring.
