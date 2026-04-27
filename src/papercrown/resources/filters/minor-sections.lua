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

local function has_class(el, class_name)
  if not el.classes then return false end
  for _, c in ipairs(el.classes) do
    if c == class_name then return true end
  end
  return false
end

local function is_minor_header(block)
  if block.t ~= "Header" then return false end
  if block.level < 3 or block.level > 4 then return false end
  if has_class(block, "section-divider-title") then return false end
  return true
end

local function wrap_minor_sections(blocks)
  local out = pandoc.List()
  local i = 1

  while i <= #blocks do
    local block = blocks[i]

    if is_minor_header(block) then
      local level = block.level
      local section_blocks = pandoc.List()
      section_blocks:insert(block)
      i = i + 1

      while i <= #blocks do
        local next_block = blocks[i]
        if next_block.t == "Header" and next_block.level <= level then
          break
        end
        section_blocks:insert(next_block)
        i = i + 1
      end

      out:insert(pandoc.Div(
        section_blocks,
        pandoc.Attr("", { "minor-section", "minor-section-level-" .. tostring(level) })
      ))
    else
      out:insert(block)
      i = i + 1
    end
  end

  return out
end

function Div(el)
  if has_class(el, "minor-section") then return nil end
  el.content = wrap_minor_sections(el.content)
  return el
end

function Pandoc(doc)
  doc.blocks = wrap_minor_sections(doc.blocks)
  return doc
end
