-- highlight-level-headings.lua
--
-- Tag any heading whose text starts with "Level <N>" (e.g. "Level 1",
-- "Level 12 Capstone") with a `level-heading` class, so CSS can give
-- them prominent styling (bigger, accent rule, more whitespace).
--
-- These markers appear throughout each class Levels.md file and in
-- subclass files. Their natural depth in the source is h3, but in the
-- combined book they're demoted -- once for being inside a wrapper,
-- once more when child_divider strips the chapter title. So matching
-- on `el.level == 3` only worked in single-chapter PDFs. We now match
-- any heading level so the styling survives any nesting depth.

function Header(el)
  local text = pandoc.utils.stringify(el.content)
  if text:match("^[Ll]evel%s+%d+") then
    if not el.classes:includes("level-heading") then
      el.classes:insert("level-heading")
    end
    return el
  end
  return nil
end
