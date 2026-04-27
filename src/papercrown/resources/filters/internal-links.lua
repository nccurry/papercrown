-- internal-links.lua
--
-- Turn cross-document references into clickable in-PDF anchors when the
-- target lives in the same build. Two source forms are handled:
--
--   (a) Markdown links produced by obsidian-export, e.g.
--          [Berserker Description](Classes\Berserker\Berserker%20Description.md)
--          [Gravwell Native](Heavyworlder Native.md#gravwell-native)
--       These come in as Pandoc `Link` elements.
--
--   (b) Raw `[[X]]` / `[[X|display]]` wikilink text that obsidian-export
--       LEFT ALONE because it couldn't find a matching .md file. (Common
--       case: catalog/list pages link to `[[Bonded]]` but the class is
--       built from many sub-files, with no top-level `Bonded.md`.) These
--       arrive as `Str` tokens inside an `Inlines` list, and we promote
--       them to real `Link` elements when the slug matches a heading id
--       we've collected from the document.
--
-- Resolution order for any link target `path[.md][#frag]`:
--   1. `#frag` matches a known heading id     -> #frag
--   2. slugify(stem(path)) matches an id      -> #<slug>
--   3. slugify(stem(path)) is a chapter slug
--      from the `valid-anchors` metadata      -> #<slug>
--   4. otherwise: leave the link alone (strip-links.lua will scrub it
--      to plain text downstream).
--
-- Filter passes are ordered so heading ids are collected BEFORE either
-- the inline wikilink promoter or the existing-link rewriter run.

local valid_anchors = {}    -- chapter-level slugs from --metadata valid-anchors
local heading_ids = {}      -- every Header.identifier seen in this doc

local function url_decode(s)
  if not s then return "" end
  -- Decode `%XX` escapes (URL encoding). Bare `+` is left alone (markdown
  -- paths don't conventionally encode spaces as `+`).
  s = s:gsub("%%(%x%x)", function(hex) return string.char(tonumber(hex, 16)) end)
  return s
end

local function slugify(s)
  -- KEEP IN SYNC with `slugify` in papercrown/manifest.py.
  -- Same rule: lowercase; runs of non-(letter/digit/underscore/hyphen)
  -- collapse to a single hyphen; strip leading/trailing hyphens.
  if not s then return "" end
  s = url_decode(s)
  s = s:lower()
  s = s:gsub("[^%w%-_]+", "-")
  s = s:gsub("^-+", ""):gsub("-+$", "")
  return s
end

local function strip_md_extension(s)
  return (s:gsub("%.md$", ""))
end

local function path_basename(s)
  -- Handles forward AND back slashes (obsidian-export on Windows emits
  -- backslashes in URLs).
  local last = s:match("([^/\\]+)$")
  return last or s
end

local function has_url_scheme(url)
  if not url or url == "" then return false end
  if url:match("^[%w+%-.]+:") then return true end   -- http://, file://, mailto:
  if url:match("^#") then return true end             -- already a fragment
  if url:match("^/") then return true end             -- absolute path
  return false
end

local function split_fragment(target)
  local hash = target:find("#", 1, true)
  if not hash then return target, nil end
  return target:sub(1, hash - 1), target:sub(hash + 1)
end

local function resolve_target(target)
  -- Returns the in-document anchor (without the leading '#') if `target`
  -- can be resolved against the collected heading ids / chapter slugs;
  -- otherwise nil.
  if not target or target == "" then return nil end
  local path, frag = split_fragment(target)
  if frag and frag ~= "" then
    local f = url_decode(frag)
    if heading_ids[f] or valid_anchors[f] then
      return f
    end
  end
  local stem = strip_md_extension(path_basename(path or ""))
  local slug = slugify(stem)
  if slug ~= "" and (heading_ids[slug] or valid_anchors[slug]) then
    return slug
  end
  return nil
end

-- Pass 0: pick up the metadata list of chapter-level slugs.
local function read_meta(meta)
  local raw = meta["valid-anchors"]
  if not raw then return nil end
  local text = pandoc.utils.stringify(raw)
  for slug in text:gmatch("[^,%s]+") do
    valid_anchors[slug] = true
  end
  return nil
end

-- Pass 1: collect every heading id Pandoc will emit. Includes auto-generated
-- ids (from `### Heading Title`) AND explicit ones (`### Title {#custom-id}`).
local function collect_header(el)
  if el.identifier and el.identifier ~= "" then
    heading_ids[el.identifier] = true
  end
  return nil
end

local function append_plain_text(out, text)
  if not text or text == "" then return end
  local cursor = 1
  while cursor <= #text do
    local s, e = text:find("%s+", cursor)
    if not s then
      out:insert(pandoc.Str(text:sub(cursor)))
      break
    end
    if s > cursor then
      out:insert(pandoc.Str(text:sub(cursor, s - 1)))
    end
    out:insert(pandoc.Space())
    cursor = e + 1
  end
end

-- Pass 2a: walk Inlines lists looking for raw `[[Target]]` / `[[Target|Display]]`
-- patterns that obsidian-export didn't convert. Pandoc may split wikilinks
-- with spaces across several Str/Space tokens (`[[Combat`, `Encounter`,
-- `Guidelines]]`), so this pass stringifies the inline run when it sees raw
-- wikilink brackets and re-emits a simple inline sequence.
--
-- This is needed because Obsidian wikilinks pointing at notes that DON'T
-- exist as standalone .md files (e.g. `[[Bonded]]` in Classes List.md
-- when there's no `Bonded.md`, only `Bonded Description.md` etc.) are
-- emitted by obsidian-export as italicized fallback text rather than
-- markdown links. Those still want to be clickable in the PDF, since the
-- corresponding heading ("# Bonded") DOES exist in the rendered build.
local function wikilink_to_link(inlines)
  local all_text = pandoc.utils.stringify(inlines)
  if not all_text:find("[[", 1, true) then
    return nil
  end

  local out = pandoc.List()
  local changed = false

  local cursor = 1
  while cursor <= #all_text do
    local s, e, body = all_text:find("%[%[([^%]]+)%]%]", cursor)
    if not s then
      append_plain_text(out, all_text:sub(cursor))
      break
    end

    if s > cursor then
      append_plain_text(out, all_text:sub(cursor, s - 1))
    end

    -- Split `target|display` if present.
    local target, display = body:match("^(.-)|(.+)$")
    if not target then
      target = body
      display = body
    end

    -- And `target#frag` if present (Obsidian section link style).
    local anchor = resolve_target(target)
    if anchor then
      local link = pandoc.Link({pandoc.Str(display)}, "#" .. anchor)
      link.classes:insert("internal-ref")
      out:insert(link)
      changed = true
    else
      -- Couldn't resolve -- emit just the display text (drop brackets so it
      -- doesn't render as `[[Foo]]` in the final PDF).
      append_plain_text(out, display)
      changed = true
    end
    cursor = e + 1
  end

  if changed then return out end
  return nil
end

-- Pass 2b: rewrite already-parsed Links to in-document anchors.
local function rewrite_link(el)
  if has_url_scheme(el.target) then return nil end
  local anchor = resolve_target(el.target)
  if not anchor then return nil end
  el.target = "#" .. anchor
  if not el.classes:includes("internal-ref") then
    el.classes:insert("internal-ref")
  end
  return el
end

-- Pass 2c: when obsidian-export can't find a target file for a wikilink,
-- it falls back to ITALICIZED display text rather than producing a markdown
-- link. So `[[Artificer]]` (when there's no Artificer.md) comes through to
-- us as `*Artificer*` -- an Emph node, not a Link. If the italicized text
-- slugifies to a heading id we know about, promote the Emph to a real
-- internal Link so the catalog tables actually link.
--
-- This is safe in practice because:
--   * legitimate stylistic italics (e.g. "*13 classes total.*") won't
--     slugify to a heading id, so they stay as Emph;
--   * the conversion is one-directional: we never demote a Link;
--   * if a user really wants italic text that happens to match a heading
--     name (rare), they can use raw HTML `<em>...</em>` to bypass us.
local function emph_to_link(el)
  local text = pandoc.utils.stringify(el.content)
  local slug = slugify(text)
  if slug == "" then return nil end
  if not (heading_ids[slug] or valid_anchors[slug]) then return nil end
  -- Wrap the original italic content in a Link so the styling is kept
  -- (italics PLUS clickable). Most catalog tables prefer plain link text;
  -- if you'd rather drop the italics, replace `el.content` with
  -- `pandoc.Inlines{pandoc.Str(text)}` here.
  local link = pandoc.Link(el.content, "#" .. slug)
  link.classes:insert("internal-ref")
  return link
end

-- Pass 2d: collapse headings that would otherwise render as
-- "Academy Dropout (Academy Dropout)" when the parenthetical is only a
-- same-name source link. Different-name pairs are kept as written.
local function collapse_duplicate_original_heading(el)
  local links = pandoc.List()
  for _, inl in ipairs(el.content) do
    if inl.t == "Link" then
      links:insert(inl)
    end
  end
  if #links ~= 1 then return nil end
  local link = links[1]
  if not link.target:match("^#original%-") then return nil end

  local full_text = pandoc.utils.stringify(el.content)
  local link_text = pandoc.utils.stringify(link.content)
  local prefix = full_text:match("^(.-)%s+%(" .. link_text:gsub("([^%w])", "%%%1") .. "%)$")
  if not prefix or prefix ~= link_text then return nil end

  if not link.classes:includes("internal-ref") then
    link.classes:insert("internal-ref")
  end
  el.content = pandoc.List({ link })
  return el
end

return {
  { Meta = read_meta },
  { Header = collect_header },
  { Inlines = wikilink_to_link },
  { Link = rewrite_link },
  { Emph = emph_to_link },
  { Header = collapse_duplicate_original_heading },
}
