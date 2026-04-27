--[[
  stat-blocks.lua

  Wraps consecutive stat-line paragraphs into a single <div class="stat-block">.
  If a bullet/ordered list is made entirely of stat-line items, unwraps the
  list and emits the same stat block without list markers.

  A "stat line" is narrowly defined as a paragraph whose FIRST inline is a
  Strong (bold) element whose text ends with a colon, e.g.:

      **Key Stats:** STR, DEX
      **Starting HP:** 20
      **Key Save:** STR

  This avoids false-positives on ordinary bold feature names like
  `**The Cycle (Rage)**` which are normal body text, not stat lines.

  Consecutive stat-line paragraphs (with no other content between them) are
  grouped into one div. A run of 2+ stat lines becomes a stat block; single
  isolated stat lines also get wrapped so CSS can style the label uniformly.
  Pure stat-line lists become stat blocks too, because the stat boxes already
  read as a list visually and should not also carry bullet markers.
]]

local function strong_label_ends_with_colon(strong_el)
  if not strong_el or strong_el.t ~= "Strong" then return false end
  -- Collect strong's text
  local text = ""
  for _, inl in ipairs(strong_el.content) do
    if inl.t == "Str" then text = text .. inl.text
    elseif inl.t == "Space" then text = text .. " "
    end
  end
  -- Trailing ":" (with optional trailing whitespace which shouldn't happen
  -- inside Strong, but be defensive)
  return text:match(":%s*$") ~= nil
end

local function stat_line_div(block)
  return pandoc.Div({ block }, pandoc.Attr("", { "stat-line" }))
end

local function stat_block_div(lines)
  return pandoc.Div(lines, pandoc.Attr("", { "stat-block" }))
end

local function same_kind_text_block(original, inlines)
  if original.t == "Plain" then
    return pandoc.Plain(inlines)
  end
  return pandoc.Para(inlines)
end

local function stat_line_divs(block)
  if block.t ~= "Para" and block.t ~= "Plain" then return nil end

  local chunks = pandoc.List()
  local current = pandoc.List()
  for i, inl in ipairs(block.content) do
    local next_inl = block.content[i + 1]
    if
      (inl.t == "SoftBreak" or inl.t == "LineBreak")
      and strong_label_ends_with_colon(next_inl)
    then
      if #current == 0 then return nil end
      chunks:insert(current)
      current = pandoc.List()
    else
      current:insert(inl)
    end
  end
  if #current > 0 then chunks:insert(current) end
  if #chunks == 0 then return nil end

  local lines = pandoc.List()
  for _, chunk in ipairs(chunks) do
    if #chunk == 0 or not strong_label_ends_with_colon(chunk[1]) then
      return nil
    end
    lines:insert(stat_line_div(same_kind_text_block(block, chunk)))
  end
  return lines
end

local function has_class(div, class_name)
  if not div or div.t ~= "Div" then return false end
  for _, cls in ipairs(div.classes) do
    if cls == class_name then return true end
  end
  return false
end

local function append_stat_item_lines(item, lines)
  if #item ~= 1 then return false end

  local block = item[1]
  local split_lines = stat_line_divs(block)
  if split_lines then
    for _, line in ipairs(split_lines) do
      lines:insert(line)
    end
    return true
  end

  if has_class(block, "stat-line") then
    lines:insert(block)
    return true
  end

  if has_class(block, "stat-block") then
    for _, child in ipairs(block.content) do
      if not has_class(child, "stat-line") then return false end
      lines:insert(child)
    end
    return true
  end

  return false
end

local function stat_list_to_block(block)
  if block.t ~= "BulletList" and block.t ~= "OrderedList" then return nil end
  local lines = pandoc.List()
  for _, item in ipairs(block.content) do
    if not append_stat_item_lines(item, lines) then
      return nil
    end
  end
  if #lines == 0 then return nil end
  return stat_block_div(lines)
end

function Blocks(blocks)
  local out = pandoc.List()
  local buffer = pandoc.List()

  local function flush_buffer()
    if #buffer == 0 then return end
    out:insert(stat_block_div(buffer))
    buffer = pandoc.List()
  end

  for _, blk in ipairs(blocks) do
    local stat_list = stat_list_to_block(blk)
    if stat_list then
      flush_buffer()
      out:insert(stat_list)
    else
      local split_lines = stat_line_divs(blk)
      if split_lines then
        -- Tag the inner para so CSS can target stat-line individually.
        for _, line in ipairs(split_lines) do
          buffer:insert(line)
        end
      else
        flush_buffer()
        out:insert(blk)
      end
    end
  end
  flush_buffer()

  return out
end
