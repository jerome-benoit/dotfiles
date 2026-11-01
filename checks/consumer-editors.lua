local function check()
  local selector = dofile(vim.env.CONSUMER_SELECTOR)
  local function escape()
    vim.cmd.normal({ args = { '\027' }, bang = true })
  end
  local function selected()
    vim.cmd.normal({ args = { '"zy' }, bang = true })
    local text = vim.fn.getreg('z')
    vim.cmd.normal({ args = { 'gv' }, bang = true })
    return text
  end
  local function buffer(filetype, lines)
    escape()
    vim.cmd.enew()
    vim.api.nvim_buf_set_lines(0, 0, -1, true, lines)
    vim.bo.filetype = filetype
    vim.treesitter.get_parser():parse()
    assert(vim.treesitter.highlighter.active[vim.api.nvim_get_current_buf()], filetype .. ' highlighter inactive')
    assert(vim.bo.indentexpr:find('nvim%-treesitter'), 'Treesitter indentation inactive')
  end
  buffer('python', {
    'def outer():', '    def inner():', '        café = "hello"',
    '        return café', '    return inner()', '',
  })
  for _, selection in ipairs({ 'inclusive', 'exclusive' }) do
    vim.o.selection = selection
    escape()
    vim.api.nvim_win_set_cursor(0, { 3, 8 })
    selector.select('init')
    assert(selected() == 'café', selection .. ': UTF8 identifier selection')
    selector.select('node')
    local grown = selected()
    assert(#grown > #'café')
    selector.select('previous')
    assert(selected() == 'café', selection .. ': history restoration')
    selector.select('node')
    assert(selected() == grown, 'grow after decrement skipped ancestor')
    selector.select('scope')
    local inner = selected()
    assert(inner:find('def inner', 1, true) and not inner:find('def outer', 1, true))
    selector.select('scope')
    assert(selected():find('def outer', 1, true))
    selector.select('previous')
    assert(selected() == inner, 'scope decrement did not restore actual prior selection')
    -- A manual visual move resets the old history before shrinking.
    vim.api.nvim_win_set_cursor(0, { 3, 8 })
    selector.select('previous')
    assert(selected() == 'café', 'manual selection retained stale history')
    escape()
  end
  vim.o.selection = 'inclusive'
  -- A changed buffer invalidates all previous TSNode/range history.
  vim.api.nvim_buf_set_lines(0, 2, 3, true, { '        other = "changed"' })
  vim.api.nvim_win_set_cursor(0, { 3, 8 })
  selector.select('previous')
  assert(selected() == 'other', 'edit retained stale selection')
  escape()
  vim.api.nvim_buf_set_lines(0, 2, 3, true, { '        def fresh():', '            return 7' })
  vim.api.nvim_win_set_cursor(0, { 4, 19 })
  selector.select('init')
  assert(selected() == '7', 'selection used stale syntax after structural edit')
  selector.select('scope')
  assert(selected():find('def fresh', 1, true), 'scope used stale syntax after structural edit')

  buffer('lua', { 'local function first(a, b)', '  return a + b', 'end', '', 'local function second(x)', '  return x', 'end' })
  vim.api.nvim_win_set_cursor(0, { 1, 22 })
  require('nvim-treesitter-textobjects.select').select_textobject('@function.outer', 'textobjects')
  assert(selected():find('return a + b', 1, true), 'function textobject did not select body')
  escape()
  vim.api.nvim_win_set_cursor(0, { 2, 0 })
  require('nvim-treesitter-textobjects.move').goto_next_start('@function.outer', 'textobjects')
  assert(vim.api.nvim_win_get_cursor(0)[1] == 5, 'function movement did not reach second function')
  vim.api.nvim_win_set_cursor(0, { 1, 21 })
  require('nvim-treesitter-textobjects.swap').swap_next('@parameter.inner')
  -- Current swap API queues g@l for dot-repeat; execute its actual typeahead.
  vim.api.nvim_feedkeys('', 'x', false)
  assert(vim.api.nvim_get_current_line():find('first(b, a)', 1, true), 'parameter swap failed')
  require('nvim-treesitter-textobjects.swap').swap_previous('@parameter.inner')
  vim.api.nvim_feedkeys('', 'x', false)
  assert(vim.api.nvim_get_current_line():find('first(a, b)', 1, true), 'reverse parameter swap failed')
  for _, selection in ipairs({ 'inclusive', 'exclusive' }) do
    vim.o.selection = selection
    buffer('markdown', { '```python', 'value = 1', '```' })
    vim.api.nvim_win_set_cursor(0, { 2, 8 })
    selector.select('init')
    local previous_text = selected()
    assert(previous_text == '1', 'initial selection did not enter freshly parsed injection')
    for _ = 1, 20 do
      selector.select('node')
      local text = selected()
      if text == previous_text then break end
      previous_text = text
    end
    assert(previous_text == '```python\nvalue = 1\n```\n', selection .. ': injected-root/EOF selection mismatch: ' .. vim.inspect(previous_text))
    escape()
  end
  vim.o.selection = 'inclusive'
  buffer('markdown', { '```python', 'value = 1', '```' })
  vim.api.nvim_buf_set_lines(0, 1, 2, true, { 'def injected():', '    return 7' })
  vim.api.nvim_win_set_cursor(0, { 3, 11 })
  selector.select('init')
  assert(selected() == '7', 'injected selection used stale tree after immediate structural edit')
  selector.select('scope')
  assert(selected():find('def injected', 1, true), 'injected scope used stale tree after edit')
  escape()
  local project = vim.fn.tempname()
  vim.fn.mkdir(project, 'p')
  vim.fn.writefile({ '[project]', 'name = "consumer-fixture"', 'version = "0.0.0"' }, project .. '/pyproject.toml')
  vim.fn.writefile({ 'value: int = 42', 'print(value)' }, project .. '/main.py')
  local lsp_buffer
  local attached, attach_error = xpcall(function()
    vim.cmd.edit(vim.fn.fnameescape(project .. '/main.py'))
    lsp_buffer = vim.api.nvim_get_current_buf()
    assert(vim.wait(30000, function()
      for _, client in ipairs(vim.lsp.get_clients({ bufnr = lsp_buffer })) do
        if client.name == 'pyright' and client.initialized then
          return true
        end
      end
      return false
    end, 50), 'real Pyright client did not initialize and attach')
    local client = vim.lsp.get_clients({ bufnr = lsp_buffer, name = 'pyright' })[1]
    assert(client.server_capabilities.hoverProvider, 'real Pyright hover capability missing')
  end, debug.traceback)
  if lsp_buffer then
    for _, client in ipairs(vim.lsp.get_clients({ bufnr = lsp_buffer, name = 'pyright' })) do
      client:stop(true)
    end
  end
  vim.fn.delete(project, 'rf')
  assert(attached, attach_error)
  escape()
  vim.cmd.enew()
  vim.bo.filetype = 'consumer_unknown'
  local cursor = vim.api.nvim_win_get_cursor(0)
  selector.select('init')
  assert(vim.deep_equal(cursor, vim.api.nvim_win_get_cursor(0)), 'unknown parser moved cursor')

  local status = require('opencode.events.status')
  local notices = {}
  local notify = vim.notify
  vim.notify = function(message) notices[#notices + 1] = message end
  local function emit(kind, data)
    vim.api.nvim_exec_autocmds('User', {
      pattern = 'OpencodeEvent:' .. kind,
      data = { event = { type = kind, data = data or {} }, url = 'http://127.0.0.1:1' },
    })
  end
  emit('server.connected')
  local idle = status.icon()
  emit('session.execution.started')
  local busy = status.icon()
  assert(busy ~= idle, 'started event never reached status listener')
  emit('session.execution.failed', { error = 'fixture failure' })
  local failure = status.icon()
  assert(failure ~= busy and failure ~= idle)
  emit('session.execution.started')
  assert(status.icon() == busy)
  emit('session.execution.succeeded')
  assert(status.icon() == idle, 'success did not clear error')
  emit('session.execution.started')
  emit('session.execution.interrupted')
  assert(status.icon() == idle)
  assert(vim.tbl_contains(notices, 'OpenCode ready'))
  assert(vim.tbl_contains(notices, 'OpenCode error: "fixture failure"'))
  emit('global.disposed')
  assert(status.icon() ~= idle and status.icon() ~= busy and status.icon() ~= failure)
  vim.notify = notify
end
local ok, error = xpcall(check, debug.traceback)
if not ok then
  io.stderr:write(error .. '\n')
  vim.cmd.cquit(1)
else
  vim.cmd.qa({ bang = true })
end
