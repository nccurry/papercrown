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

local function has_url_scheme(url)
  if not url or url == "" then return false end
  -- http://, https://, mailto:, etc
  if url:match("^[%w+%-.]+:") then return true end
  if url:match("^#") then return true end   -- internal anchor
  if url:match("^/") then return true end   -- absolute path
  return false
end

function Link(el)
  if has_url_scheme(el.target) then
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
  if has_url_scheme(src) then return nil end
  -- Real file paths (ending in common image extensions) are kept
  local lower = src:lower()
  if lower:match("%.png$") or lower:match("%.jpg$") or lower:match("%.jpeg$")
     or lower:match("%.gif$") or lower:match("%.webp$") or lower:match("%.svg$") then
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
