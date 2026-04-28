-- minor-sections.lua
--
-- Wrap short minor sections so paged-media CSS can keep a heading and its
-- immediate body together when possible. We target h3/h4 because the combined
-- book hierarchy is:
--
--   h1 chapter divider
--   h2 major-section divider
--   h3 minor section
--   h4 minor sub-section
--
-- Long sections may still split naturally; `break-inside: avoid` is only a
-- preference when the content can fit.

local script_path = PANDOC_SCRIPT_FILE or debug.getinfo(1, "S").source:sub(2)
local filter_dir = script_path:match("^(.*)[/\\][^/\\]+$") or "."
local pc = dofile(filter_dir .. "/lib/papercrown.lua")

local function is_minor_header(block)
  if block.t ~= "Header" then return false end
  if block.level < 3 or block.level > 4 then return false end
  if pc.class.has(block, "section-divider-title") then return false end
  return true
end

local function minor_classes(block)
  return {
    "pc-section",
    "pc-section-minor",
    "pc-section-level-" .. tostring(block.level),
  }
end

function Div(el)
  if pc.class.has(el, "pc-section-minor") then return nil end
  el.content = pc.section.wrap(el.content, is_minor_header, minor_classes)
  return el
end

function Pandoc(doc)
  doc.blocks = pc.section.wrap(doc.blocks, is_minor_header, minor_classes)
  return doc
end
