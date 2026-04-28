--[[
  callouts.lua

  Converts Obsidian callouts into styled <div> blocks for HTML/PDF output.

  Obsidian syntax (inside a BlockQuote):
      > [!tip]- Optional Title
      > Body line 1
      > Body line 2

  Output:
      <div class="pc-callout pc-callout-tip is-foldable">
        <div class="pc-callout-title">Optional Title</div>
        <div class="pc-callout-body">
          <p>Body line 1</p>
          <p>Body line 2</p>
        </div>
      </div>

  Types recognized: note, tip, info, example, faq, question, warning, caution,
  danger, success, summary, abstract, todo, quote, cue, angle, pressure.
  Unknown types fall back to a matching "pc-callout-<type>" style.

  The `-` suffix on `[!tip]-` means foldable in Obsidian; we preserve that as
  a class marker in case the CSS wants to style it differently.
]]

local script_path = PANDOC_SCRIPT_FILE or debug.getinfo(1, "S").source:sub(2)
local filter_dir = script_path:match("^(.*)[/\\][^/\\]+$") or "."
local pc = dofile(filter_dir .. "/lib/papercrown.lua")

local CALLOUT_ALIASES = {
  ["note"]     = "note",
  ["abstract"] = "abstract",
  ["summary"]  = "abstract",
  ["tldr"]     = "abstract",
  ["info"]     = "info",
  ["todo"]     = "todo",
  ["tip"]      = "tip",
  ["hint"]     = "tip",
  ["important"]= "tip",
  ["success"]  = "success",
  ["check"]    = "success",
  ["done"]     = "success",
  ["question"] = "question",
  ["faq"]      = "question",
  ["help"]     = "question",
  ["warning"]  = "warning",
  ["caution"]  = "warning",
  ["attention"]= "warning",
  ["failure"]  = "danger",
  ["fail"]     = "danger",
  ["missing"]  = "danger",
  ["danger"]   = "danger",
  ["error"]    = "danger",
  ["bug"]      = "danger",
  ["example"]  = "example",
  ["quote"]    = "quote",
  ["cite"]     = "quote",
  ["cue"]      = "cue",
  ["angle"]    = "angle",
  ["pressure"] = "pressure",
}

local function normalize_type(raw)
  if not raw then return "note" end
  local lower = raw:lower()
  return CALLOUT_ALIASES[lower] or lower or "note"
end

-- Extract the plain-text header of a callout from the first paragraph of the
-- blockquote. Returns (kind, foldable, title_inlines, rest_of_first_para) or
-- nil if this blockquote is not an Obsidian callout.
local function parse_header(first_block)
  if not pc.block.is_text_block(first_block) then
    return nil
  end
  local inlines = first_block.content
  if #inlines == 0 then return nil end

  local header_text, rest = pc.text.first_line_text_and_rest(inlines)

  local kind, foldable, title = header_text:match("^%s*%[!([%w_-]+)%]([%+%-]?)%s*(.-)%s*$")
  if not kind then return nil end

  return kind, foldable, title, rest
end

function BlockQuote(el)
  if #el.content == 0 then return nil end
  local first = el.content[1]
  local parsed_kind, foldable, title_text, rest_inlines = parse_header(first)
  if not parsed_kind then return nil end

  local kind = normalize_type(parsed_kind)
  local classes = { "pc-callout", "pc-callout-" .. kind }
  if foldable == "-" then
    table.insert(classes, "is-foldable")
  elseif foldable == "+" then
    table.insert(classes, "is-foldable-open")
  end

  -- Build body: everything after the header inlines, plus remaining blocks
  local body_blocks = pandoc.List()

  if rest_inlines and #rest_inlines > 0 then
    -- Strip leading whitespace
    while #rest_inlines > 0 and (rest_inlines[1].t == "Space" or rest_inlines[1].t == "SoftBreak") do
      table.remove(rest_inlines, 1)
    end
    if #rest_inlines > 0 then
      body_blocks:insert(pandoc.Para(rest_inlines))
    end
  end

  for i = 2, #el.content do
    body_blocks:insert(el.content[i])
  end

  local result = pandoc.List()

  -- Title div (only if we have one, or always for styling consistency)
  local display_title = title_text
  if not display_title or display_title == "" then
    -- Capitalize kind as fallback title
    display_title = kind:sub(1,1):upper() .. kind:sub(2)
  end
  local title_div = pandoc.Div(
    { pandoc.Plain({ pandoc.Str(display_title) }) },
    pandoc.Attr("", { "pc-callout-title" })
  )
  result:insert(title_div)

  if #body_blocks > 0 then
    local body_div = pandoc.Div(body_blocks, pandoc.Attr("", { "pc-callout-body" }))
    result:insert(body_div)
  end

  return pandoc.Div(result, pandoc.Attr("", classes))
end
