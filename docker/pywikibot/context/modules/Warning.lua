local libraryUtil = require('libraryUtil')

local wrapper = "%s" -- wikitext formatting
local msg_loc = "Lua warning in %s at line %d: %s."
local msg = "Lua warning: %s."

return function (message, level)
	libraryUtil.checkType('warn', 2, level, 'number', true)
	level = level or 1
	if level > 0 then
		local _, location = pcall(error, '', level+2)
		if location ~= '' then
			location = mw.text.split(location:sub(1,-3), ':%f[%d]')
			message = msg_loc:format(location[1], location[2], message)
		else
			message = msg:format(message)
		end
	else
		message = msg:format(message)
	end
	mw.addWarning(wrapper:format(message))
end
