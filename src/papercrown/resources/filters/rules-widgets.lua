-- rules-widgets.lua
--
-- Normalize fenced-div rules widgets into a shared component structure.
--
-- Authoring:
--   :::: {.pc-feature title="Sneak Attack" level="1" tags="rogue,damage"}
--   Once per turn, add extra damage when conditions are met.
--   ::::
--
-- Output:
--   <div class="pc-component pc-feature">
--     <div class="pc-component-header">
--       <div class="pc-component-title">Sneak Attack</div>
--       <div class="pc-component-meta">...</div>
--     </div>
--     <div class="pc-component-body">...</div>
--   </div>

local script_path = PANDOC_SCRIPT_FILE or debug.getinfo(1, "S").source:sub(2)
local filter_dir = script_path:match("^(.*)[/\\][^/\\]+$") or "."
local pc = dofile(filter_dir .. "/lib/papercrown.lua")

local WIDGETS = {
  ["pc-feature"] = true,
  ["pc-ability"] = true,
  ["pc-procedure"] = true,
}

local META_FIELDS = {
  { key = "level", label = "Level" },
  { key = "cost", label = "Cost" },
  { key = "trigger", label = "Trigger" },
  { key = "duration", label = "Duration" },
  { key = "usage", label = "Usage" },
  { key = "recharge", label = "Recharge" },
  { key = "tags", label = "Tags" },
}

local RESERVED_ATTRS = {
  ["title"] = true,
  ["data-title"] = true,
  ["level"] = true,
  ["cost"] = true,
  ["trigger"] = true,
  ["duration"] = true,
  ["usage"] = true,
  ["recharge"] = true,
  ["tags"] = true,
}

local function widget_kind(el)
  for _, class_name in ipairs(el.classes) do
    if WIDGETS[class_name] then
      return class_name
    end
  end
  return nil
end

local function display_label(key, label, value)
  if key == "level" then
    return label .. " " .. value
  end
  return label .. ": " .. value
end

local function meta_inlines(attributes)
  local inlines = pandoc.List()

  for _, field in ipairs(META_FIELDS) do
    local value = attributes[field.key]
    if value and value ~= "" then
      if #inlines > 0 then
        inlines:insert(pandoc.Space())
      end
      inlines:insert(pandoc.Span(
        { pandoc.Str(display_label(field.key, field.label, value)) },
        pc.block.attr("", {
          "pc-component-meta-item",
          "pc-component-meta-" .. field.key,
        })
      ))
    end
  end

  return inlines
end

local function cleaned_attributes(attributes)
  local out = {}
  for key, value in pairs(attributes or {}) do
    if not RESERVED_ATTRS[key] then
      out[key] = value
    end
  end
  return out
end

local function body_without_title_heading(blocks)
  if #blocks == 0 then return nil, blocks end
  local first = blocks[1]
  if first.t ~= "Header" then return nil, blocks end

  local body = pandoc.List()
  for i = 2, #blocks do
    body:insert(blocks[i])
  end
  return pc.text.stringify(first.content), body
end

function Div(el)
  local kind = widget_kind(el)
  if not kind then return nil end
  if pc.class.has(el, "pc-component") then return nil end

  local title = el.attributes["title"] or el.attributes["data-title"]
  local heading_title = nil
  local body_blocks = el.content
  if not title or title == "" then
    heading_title, body_blocks = body_without_title_heading(el.content)
    title = heading_title
  end

  local header_parts = pandoc.List()
  if title and title ~= "" then
    header_parts:insert(pc.component.part(
      "title",
      { pandoc.Plain({ pandoc.Str(title) }) }
    ))
  end

  local meta = meta_inlines(el.attributes)
  if #meta > 0 then
    header_parts:insert(pc.component.part("meta", { pandoc.Plain(meta) }))
  end

  local content = pandoc.List()
  if #header_parts > 0 then
    content:insert(pc.component.part("header", header_parts))
  end
  content:insert(pc.component.part("body", body_blocks))

  local extra_classes = pc.class.without(el.classes, { kind, "pc-component" })
  return pc.component.div(
    kind,
    content,
    extra_classes,
    el.identifier,
    cleaned_attributes(el.attributes)
  )
end
