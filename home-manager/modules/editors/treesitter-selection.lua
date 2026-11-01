-- Owned incremental selection for the current Treesitter API.
local M = {}
local states = {}
local function before(a, b)
  return a[1] < b[1] or (a[1] == b[1] and a[2] < b[2])
end
local function range(node)
  local sr, sc, er, ec = node:range()
  return { { sr, sc }, { er, ec } }
end
local function selectable_range(buf, node)
  local selected = range(node)
  local count = vim.api.nvim_buf_line_count(buf)
  if selected[1][2] > 0 and selected[2][1] >= count and selected[2][2] == 0 then
    -- Neovim cannot include the final newline in a partial-line charwise range.
    -- Record the actual selectable bytes so growth/history never duplicate a range.
    selected[2] = { count - 1, #vim.api.nvim_buf_get_lines(buf, count - 1, count, true)[1] }
  end
  return selected
end
local function contains(outer, inner)
  return not before(inner[1], outer[1]) and not before(outer[2], inner[2])
end
local function equal(a, b)
  return a[1][1] == b[1][1] and a[1][2] == b[1][2]
    and a[2][1] == b[2][1] and a[2][2] == b[2][2]
end
local function visual()
  local anchor = vim.fn.getpos('v')
  local cursor = vim.api.nvim_win_get_cursor(0)
  local a, b = { anchor[2] - 1, anchor[3] - 1 }, { cursor[1] - 1, cursor[2] }
  if vim.fn.mode() == 'V' then a[2], b[2] = 0, 0 end
  if before(b, a) then a, b = b, a end
  return { a, b }
end
local function previous(buf, pos)
  local row, col = pos[1], pos[2]
  if col == 0 then
    if row == 0 then return { 0, 0 } end
    row = row - 1
    return { row, #vim.api.nvim_buf_get_lines(buf, row, row + 1, true)[1] }
  end
  local line = vim.api.nvim_buf_get_lines(buf, row, row + 1, true)[1]
  col = math.max(0, col - 1)
  while col > 0 do
    local byte = line:byte(col + 1)
    if not byte or byte < 128 or byte >= 192 then break end
    col = col - 1
  end
  return { row, col }
end
local function select_range(buf, state, selected)
  if vim.fn.mode():sub(1, 1) == 'v' or vim.fn.mode() == 'V' or vim.fn.mode() == '\022' then
    vim.cmd.normal({ args = { '\027' }, bang = true })
  end
  local line_count = vim.api.nvim_buf_line_count(buf)
  local whole_lines_at_eof = selected[1][2] == 0 and selected[2][2] == 0
    and selected[2][1] >= line_count
  local mode = whole_lines_at_eof and 'V' or 'v'
  vim.api.nvim_win_set_cursor(0, { selected[1][1] + 1, selected[1][2] })
  vim.cmd.normal({ args = { mode }, bang = true })
  local finish = mode == 'v' and vim.o.selection == 'exclusive' and selected[2]
    or previous(buf, selected[2])
  vim.api.nvim_win_set_cursor(0, { finish[1] + 1, finish[2] })
  state.mode = mode
  state.visual = visual()
  state.tick = vim.api.nvim_buf_get_changedtick(buf)
  states[buf] = state
end
function M.select(action)
  local buf = vim.api.nvim_get_current_buf()
  local available, parser = pcall(vim.treesitter.get_parser, buf)
  if not available or not pcall(function() parser:parse(true) end) then return end
  local state = states[buf]
  if action == 'init' or not state or state.tick ~= vim.api.nvim_buf_get_changedtick(buf)
    or vim.fn.mode() ~= state.mode or not equal(state.visual, visual()) then
    local ok, node = pcall(vim.treesitter.get_node, { bufnr = buf, ignore_injections = false })
    if not ok then return end
    while node and not node:named() do node = node:parent() end
    if not node then return end
    state = { history = { selectable_range(buf, node) } }
    select_range(buf, state, state.history[1])
    return
  end
  if action == 'previous' then
    if #state.history > 1 then table.remove(state.history) end
    select_range(buf, state, state.history[#state.history])
    return
  end
  local current = state.history[#state.history]
  local selected
  -- Search containing trees too: injected roots have no TSNode parent in the host.
  parser:for_each_tree(function(syntax, language_tree)
    local root = syntax:root()
    local function consider(node)
      local candidate = selectable_range(buf, node)
      if contains(candidate, current) and not equal(candidate, current)
        and (not selected or contains(selected, candidate)) then
        selected = candidate
      end
    end
    if action == 'scope' then
      local query = vim.treesitter.query.get(language_tree:lang(), 'locals')
      if query then
        for id, node in query:iter_captures(root, buf) do
          if query.captures[id] == 'local.scope' then consider(node) end
        end
      end
    elseif contains(range(root), current) then
      local node = root:named_descendant_for_range(
        current[1][1], current[1][2], current[1][1], current[1][2]
      )
      while node do
        consider(node)
        node = node:parent()
      end
    end
  end)
  if selected then
    state.history[#state.history + 1] = selected
    select_range(buf, state, selected)
  end
end
function M.setup()
  vim.keymap.set('n', 'gnn', function() M.select('init') end)
  for key, action in pairs({ grn = 'node', grc = 'scope', grm = 'previous' }) do
    vim.keymap.set('x', key, function() M.select(action) end)
  end
  vim.api.nvim_create_autocmd('BufWipeout', {
    group = vim.api.nvim_create_augroup('TreesitterSelection', { clear = true }),
    callback = function(args) states[args.buf] = nil end,
  })
end
return M
