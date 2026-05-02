-- art-labels.lua
--
-- Apply CSS-declared art labels to matching Markdown images.

local function metadata_text(meta, key)
  local value = meta[key]
  if not value then return "" end
  return pandoc.utils.stringify(value)
end

local function split_labels(text)
  local labels = {}
  for raw in string.gmatch(text or "", "([^,]+)") do
    local label = raw:match("^%s*(.-)%s*$")
    if label ~= "" then
      table.insert(labels, label)
    end
  end
  table.sort(labels, function(a, b) return #a > #b end)
  return labels
end

local function basename(path)
  local clean = path:gsub("[?#].*$", ""):gsub("\\", "/")
  return clean:match("([^/]+)$") or clean
end

local function stem(path)
  local name = basename(path)
  return (name:gsub("%.[^.]*$", "")):lower()
end

local function matching_label(src, labels)
  local image_stem = stem(src)
  for _, label in ipairs(labels) do
    if image_stem == label or image_stem:sub(1, #label + 1) == label .. "-" then
      return label
    end
  end
  return nil
end

local function has_class(classes, class_name)
  for _, existing in ipairs(classes) do
    if existing == class_name then return true end
  end
  return false
end

local function add_class(classes, class_name)
  if not has_class(classes, class_name) then
    table.insert(classes, class_name)
  end
end

local function label_image(image, labels)
  local label = matching_label(image.src, labels)
  if not label then return nil end
  add_class(image.classes, label)
  add_class(image.classes, "art-role-" .. label)
  return label
end

local function standalone_image(block)
  if block.t ~= "Para" and block.t ~= "Plain" then return nil end
  if #block.content ~= 1 then return nil end
  local inline = block.content[1]
  if inline.t == "Image" then return inline end
  return nil
end

local function label_figure(block, labels)
  if block.t ~= "Figure" then return nil end
  local label = nil
  local image_classes = pandoc.List()
  local figure = block:walk({
    Image = function(img)
      local image_label = label_image(img, labels)
      if image_label and not label then
        label = image_label
        for _, class_name in ipairs(img.classes) do
          add_class(image_classes, class_name)
        end
      end
      return img
    end,
  })
  if not label then return nil end
  return label, image_classes, figure
end

local function wrapper_for(label, image_classes, blocks)
  local wrapper_classes = pandoc.List({
    "art-image",
    label,
    "art-role-" .. label,
  })
  for _, class_name in ipairs(image_classes) do
    add_class(wrapper_classes, class_name)
  end
  return pandoc.Div(blocks, pandoc.Attr("", wrapper_classes))
end

local labeled_blocks

local function labeled_block(block, labels)
  local image = standalone_image(block)
  if image then
    local label = label_image(image, labels)
    if label then
      return wrapper_for(label, image.classes, { pandoc.Para({ image }) })
    end
  end
  local figure_label, figure_classes, figure = label_figure(block, labels)
  if figure_label then
    return wrapper_for(figure_label, figure_classes, { figure })
  end
  if block.t == "Div" or block.t == "BlockQuote" then
    block.content = labeled_blocks(block.content, labels)
    return block
  end
  if block.t == "BulletList" or block.t == "OrderedList" then
    for i, item in ipairs(block.content) do
      block.content[i] = labeled_blocks(item, labels)
    end
    return block
  end
  return block:walk({
    Image = function(img)
      label_image(img, labels)
      return img
    end,
  })
end

labeled_blocks = function(blocks, labels)
  local out = pandoc.List()
  for _, block in ipairs(blocks) do
    out:insert(labeled_block(block, labels))
  end
  return out
end

function Pandoc(doc)
  local labels = split_labels(metadata_text(doc.meta, "art-labels"))
  if #labels == 0 then return doc end
  doc.blocks = labeled_blocks(doc.blocks, labels)
  return doc
end
