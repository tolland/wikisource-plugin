require('strict')

local p = {}

local getArgs = require('Module:Arguments').getArgs
local warn = require('Module:Warning')

local languageNameOverrides = mw.loadData('Module:ISO 639/overrides')

--[=[
Get the language name, in English, for a given ISO 639 (-1, -2 or -3) code

Returns nil if the language is not in the lookup tables.
]=]
function p.language_name(code, failValue)
	-- Only continue if we get passed a non-empty string for the code param
	if code == nil or code == '' then
		warn('No ISO code provided to [[Module:ISO 639]]')
		return failValue
	elseif type(code) ~= 'string' then
		warn('ISO code \"' .. tostring(code) .. '\" is not a string')
		return failValue
	end

	-- If we have a local override, apply it
	local language = languageNameOverrides[code]

	-- Otherwise, ask MediaWiki for the language name in English for this code
	if language == nil or language == '' then
		language = mw.language.fetchLanguageName(code, 'en')
	end

	-- If we got no name from MediaWiki and have no override for this code,
	-- load the big honkin' local lookup table and check there.
	if language == nil or language == '' then
		local localLanguageNames = mw.loadData('Module:ISO 639/local')
		language = localLanguageNames[code]
	end

	-- If we found a non-empty lang name we return it.
	if language ~= nil and language ~= '' then
		return language
	end

	-- otherwise we return the failure value
	warn('ISO code \"' .. code .. '\" not recognized by [[Module:ISO 639]]')
	return failValue
end

--[=[
Implements [[Template:ISO 639 name]]
]=]

function p.ISO_639_name(frame)
	local args = getArgs(frame)

	return p.language_name(args[1] or args.code, '[[Category:' .. 'ISO 639 name template errors' .. ']]')
end

return p
