-- strip-links.lua
--
-- After obsidian-export resolves wikilinks to plain markdown links, some
-- links may still point to notes that aren't included in this PDF. Those
-- dead links would render as underlined blue text going nowhere in the
-- output.
--
-- Strategy: any Link whose target is not a real URL (no scheme, not
-- starting with '#') gets converted to its display text. Internal section
-- anchors (starting with '#') are preserved so Pandoc can generate working
-- internal links in digital mode.
--
-- Also strips any residual raw wikilink text that obsidian-export didn't
-- touch (e.g. when pointing to nonexistent notes).

local script_path = PANDOC_SCRIPT_FILE or debug.getinfo(1, "S").source:sub(2)
local filter_dir = script_path:match("^(.*)[/\\][^/\\]+$") or "."
local pc = dofile(filter_dir .. "/lib/papercrown.lua")

function Link(el)
  if pc.link.has_url_scheme(el.target) then
    return nil
  end
  -- obsidian-export emits links like [Text](Other Note.md) -- drop the link
  -- wrapper, keep the display text
  return el.content
end

function Image(el)
  -- Keep real images; drop images whose src is clearly a non-resolvable note
  local src = el.src or ""
  if src == "" then return nil end
  if pc.link.has_url_scheme(src) then return nil end
  -- Real file paths (ending in common image extensions) are kept
  if pc.link.is_image_path(src) then
    return nil
  end
  -- Otherwise: drop the image (likely a note reference Obsidian rendered as embed)
  return pandoc.Null()
end

-- NOTE: stripping of raw `[[...]]` wikilink text used to live here, but
-- internal-links.lua now handles that pass (it has access to the heading-id
-- table and can promote resolvable wikilinks into clickable internal Links
-- before falling back to plain text). Anything still left as a `[[...]]`
-- string after both filters is intentionally untouched.
