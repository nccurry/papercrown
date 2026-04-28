-- Shared helpers for Paper Crown Pandoc Lua filters.
--
-- Keep this file dependency-free. Filters load it with `dofile` using the
-- current filter's `PANDOC_SCRIPT_FILE`, which is reliable for packaged
-- resources and Windows paths.

local pc = {}

pc.text = {}
pc.class = {}
pc.block = {}
pc.link = {}
pc.section = {}
pc.component = {}

-- ---------------------------------------------------------------------------
-- Text helpers
-- ---------------------------------------------------------------------------

function pc.text.stringify(value)
  return pandoc.utils.stringify(value or "")
end

function pc.text.append_plain_text(out, text)
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

function pc.text.strong_text(strong_el)
  if not strong_el or strong_el.t ~= "Strong" then return "" end
  local text = ""
  for _, inl in ipairs(strong_el.content) do
    if inl.t == "Str" then
      text = text .. inl.text
    elseif inl.t == "Space" then
      text = text .. " "
    elseif inl.t == "Code" then
      text = text .. inl.text
    end
  end
  return text
end

function pc.text.first_line_text_and_rest(inlines)
  local header_text = ""
  local break_at = nil

  for i, el in ipairs(inlines) do
    if el.t == "SoftBreak" or el.t == "LineBreak" then
      break_at = i
      break
    end
    if el.t == "Str" then
      header_text = header_text .. el.text
    elseif el.t == "Space" then
      header_text = header_text .. " "
    elseif el.t == "Code" then
      header_text = header_text .. el.text
    end
  end

  local start = break_at and (break_at + 1) or (#inlines + 1)
  while
    inlines[start]
    and (
      inlines[start].t == "Space"
      or inlines[start].t == "SoftBreak"
      or inlines[start].t == "LineBreak"
    )
  do
    start = start + 1
  end

  local rest = pandoc.List()
  for i = start, #inlines do
    rest:insert(inlines[i])
  end

  return header_text, rest
end

-- ---------------------------------------------------------------------------
-- Class helpers
-- ---------------------------------------------------------------------------

function pc.class.has(el, class_name)
  if not el or not el.classes then return false end
  for _, cls in ipairs(el.classes) do
    if cls == class_name then return true end
  end
  return false
end

function pc.class.add(el, class_name)
  if not el or not class_name or class_name == "" then return el end
  if not pc.class.has(el, class_name) then
    el.classes:insert(class_name)
  end
  return el
end

function pc.class.add_all(el, class_names)
  for _, class_name in ipairs(class_names or {}) do
    pc.class.add(el, class_name)
  end
  return el
end

function pc.class.unique(class_names)
  local seen = {}
  local out = pandoc.List()
  for _, class_name in ipairs(class_names or {}) do
    if class_name and class_name ~= "" and not seen[class_name] then
      out:insert(class_name)
      seen[class_name] = true
    end
  end
  return out
end

function pc.class.without(class_names, excluded)
  local blocked = {}
  for _, class_name in ipairs(excluded or {}) do
    blocked[class_name] = true
  end
  local out = pandoc.List()
  for _, class_name in ipairs(class_names or {}) do
    if not blocked[class_name] then
      out:insert(class_name)
    end
  end
  return out
end

-- ---------------------------------------------------------------------------
-- Block/component helpers
-- ---------------------------------------------------------------------------

function pc.block.attr(identifier, class_names, attributes)
  return pandoc.Attr(identifier or "", pc.class.unique(class_names), attributes or {})
end

function pc.block.div(blocks, class_names, identifier, attributes)
  return pandoc.Div(blocks or pandoc.List(), pc.block.attr(identifier, class_names, attributes))
end

function pc.block.is_text_block(block)
  return block and (block.t == "Para" or block.t == "Plain")
end

function pc.block.same_kind_text_block(original, inlines)
  if original.t == "Plain" then
    return pandoc.Plain(inlines)
  end
  return pandoc.Para(inlines)
end

function pc.component.div(kind, blocks, extra_classes, identifier, attributes)
  local classes = pandoc.List({ "pc-component", kind })
  for _, class_name in ipairs(extra_classes or {}) do
    classes:insert(class_name)
  end
  return pc.block.div(blocks, classes, identifier, attributes)
end

function pc.component.part(name, blocks, extra_classes)
  local classes = pandoc.List({ "pc-component-" .. name })
  for _, class_name in ipairs(extra_classes or {}) do
    classes:insert(class_name)
  end
  return pc.block.div(blocks, classes)
end

-- ---------------------------------------------------------------------------
-- Link/path helpers
-- ---------------------------------------------------------------------------

function pc.link.url_decode(s)
  if not s then return "" end
  return (s:gsub("%%(%x%x)", function(hex)
    return string.char(tonumber(hex, 16))
  end))
end

function pc.link.slugify(s)
  -- Keep behavior aligned with papercrown.manifest.slugify for ordinary
  -- headings, while preserving the previous filter behavior of returning an
  -- empty string for empty/unresolvable input.
  if not s then return "" end
  s = pc.link.url_decode(s)
  s = s:lower()
  s = s:gsub("[^%w%-_]+", "-")
  s = s:gsub("^-+", ""):gsub("-+$", "")
  return s
end

function pc.link.strip_md_extension(s)
  return (s:gsub("%.md$", ""))
end

function pc.link.path_basename(s)
  local last = s:match("([^/\\]+)$")
  return last or s
end

function pc.link.has_url_scheme(url)
  if not url or url == "" then return false end
  if url:match("^[%w+%-.]+:") then return true end
  if url:match("^#") then return true end
  if url:match("^/") then return true end
  return false
end

function pc.link.split_fragment(target)
  local hash = target:find("#", 1, true)
  if not hash then return target, nil end
  return target:sub(1, hash - 1), target:sub(hash + 1)
end

function pc.link.is_image_path(src)
  local lower = (src or ""):lower()
  return lower:match("%.png$")
    or lower:match("%.jpg$")
    or lower:match("%.jpeg$")
    or lower:match("%.gif$")
    or lower:match("%.webp$")
    or lower:match("%.svg$")
end

function pc.link.mark_internal(link)
  pc.class.add_all(link, { "pc-ref", "pc-ref-internal" })
  return link
end

-- ---------------------------------------------------------------------------
-- Section helpers
-- ---------------------------------------------------------------------------

function pc.section.wrap(blocks, is_section_header, classes_for_header)
  local out = pandoc.List()
  local i = 1

  while i <= #blocks do
    local block = blocks[i]

    if is_section_header(block) then
      local level = block.level
      local section_blocks = pandoc.List({ block })
      i = i + 1

      while i <= #blocks do
        local next_block = blocks[i]
        if next_block.t == "Header" and next_block.level <= level then
          break
        end
        section_blocks:insert(next_block)
        i = i + 1
      end

      out:insert(pc.block.div(section_blocks, classes_for_header(block)))
    else
      out:insert(block)
      i = i + 1
    end
  end

  return out
end

return pc
