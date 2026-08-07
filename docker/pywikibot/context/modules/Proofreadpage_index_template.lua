--[=[
This is a module to implement logic for [[MediaWiki:Proofreadpage index template]]
]=]

local getArgs = require('Module:Arguments').getArgs
local messageBox = require('Module:Message box')
local ISO_639 = require('Module:ISO 639')
local error_text = require('Module:Error')['error']
local category_handler = require('Module:Category handler')._main

local p = {} -- p stands for package

local cfg = require('Module:Proofreadpage index template/config')
local attribution_data = require('Module:Header/attribution data')

local function process_args(args)
	-- Set any defaults
	for k, v in pairs(cfg.defaults) do
		if args[k] == nil then
			args[k] = cfg.defaults[k]
		end
	end

	args.source_type = cfg['cover_cats']['file_types'][args['Source']]

	args.pageTitle = (args.pageTitle and mw.title.new(args.pageTitle)) or mw.title.getCurrentTitle()
	args.fileTitle = mw.title.makeTitle('File', args.pageTitle.rootText)
	args.talkPageTitle = args.pageTitle.talkPageTitle

	args.file_exists = args.fileTitle.file.exists -- Expensive, so only compute once
	return args
end

local function construct_cat(cat)
	return '[[Category:' .. cat .. ']]'
end

local function construct_cat_link(cat, text)
	return '[[:Category:' .. cat .. '|' .. (text or cat) .. ']]'
end

-- Construct a basic "field" row
local function construct_field(id, content)
	if id == nil or content == nil then
		return nil
	elseif not cfg.headings[id] then
		error(cfg.missing_heading_id(id))
	end

	local tr = mw.html.create('tr')
		:attr('id', 'ws-index-' .. id .. '-row')
		:addClass('ws-index-row')
		:tag('th')
			:attr('scope', 'row')
			:attr('id', 'ws-index-' .. id .. '-label')
			:addClass('ws-index-label')
			:wikitext(cfg.headings[id]['txt'])
			:done()
		:tag('td')
			:attr('id', 'ws-index-' .. id .. '-value')
			:addClass('ws-index-value')
			:wikitext(content)
			:allDone()
	return tr
end

local function construct_status_field(args, statusArgs)
	local key = statusArgs.key
	local lower_key = string.lower(key)
	local config_key = statusArgs.config_key or lower_key

	local index_status = args[key] or '_missing'
	local sd = cfg[config_key][index_status] or cfg[config_key]['_default']

	local index_status_message = sd['txt']
	if type(index_status_message) == 'function' then
		index_status_message = index_status_message(index_status)
	end
	if sd['error'] then
		index_status_message = error_text({['message'] = index_status_message, ['tag'] = 'span'})
	else
		index_status_message = construct_cat_link(sd['cat'], index_status_message)
	end

	return {row = construct_field(lower_key, index_status_message), cat = construct_cat(sd['cat'])}
end

--[=[
Create indicator markup based on config

Loads the config module and creates indicator extension tags after pattern
	<indicator name="foo">[[File:Foo.svg|20px|link=bar|caption|alt=Alt text.]]</indcator>
]=]
local function construct_indicator(args, iArgs)
	if not (iArgs.include or cfg.indicator_defaults.include)(args) then
		return nil
	end

	local indicator_parts = {
		iArgs.image or cfg.indicator_defaults.image,
		iArgs.width or cfg.indicator_defaults.width
	}

	local alt = iArgs.alt or cfg.indicator_defaults.alt
	table.insert(indicator_parts, alt and 'alt=' .. alt)

	local link = iArgs.link or cfg.indicator_defaults.link
	if type(link) == 'function' then
		link = link(args)
	end
	table.insert(indicator_parts, link and 'link=' .. link)

	local caption = iArgs.caption or cfg.indicator_defaults.caption
	if type(caption) == 'function' then
		caption = caption(args)
	end
	table.insert(indicator_parts, caption)

	return mw.getCurrentFrame():extensionTag{
		['name'] = 'indicator',
		['content'] = '[[' .. table.concat(indicator_parts, '|') .. ']]',
		['args'] = {
			['name'] = iArgs.name or cfg.indicator_defaults.name
		}
	}
end

local function _metadata(args)
	local metadatatable = mw.html.create('table')
		:attr('id', 'ws-index-metadata')

	local cats = {}
	local indicators = {}

	if args['Title'] then
		metadatatable:node(construct_field('title', table.concat({args['Title'], args['Volume']}, ', ')))
	else
		metadatatable:node(construct_field('title', args['Volume'] or ''))
	end

	local simple_args = {}
	for i, v in ipairs(attribution_data) do
		local noun = v.noun
		table.insert(simple_args, {string.upper(string.sub(noun, 1, 1)) .. string.sub(noun, 2)})
	end
	table.insert(simple_args, {'Year'})
	table.insert(simple_args, {'Publisher'})
	table.insert(simple_args, {'Address', 'place'})

	for i, v in ipairs(simple_args) do
		metadatatable:node(construct_field(v[2] or string.lower(v[1]), args[v[1]]))
	end

	-- Categorize image-based indexes
	if args.source_type and cfg['cover_cats'][args.source_type] then
		table.insert(cats, construct_cat(cfg['cover_cats'][args.source_type]))
	elseif not args.source_type then
		table.insert(cats, construct_cat(cfg['cover_cats']['unknown']))
	end

	local source = args['Source']
	if args.file_exists then
		source = '[[:' .. args.fileTitle.fullText .. '|' .. source .. ']]'
	else
		-- Add a tracking category
		table.insert(cats, construct_cat(cfg.cover_cats.missing))
	end
	metadatatable:node(construct_field('source', source))

	-- Progress
	local progress_data = construct_status_field(args, {['key'] = 'Progress', ['config_key'] = 'status'})
	metadatatable:node(progress_data.row)
	table.insert(cats, progress_data.cat)

	-- Transclusion status
	local transclusion_data = construct_status_field(args, {['key'] = 'Transclusion'})
	metadatatable:node(transclusion_data.row)
	table.insert(cats, transclusion_data.cat)

	local vdate = args['Validation_date']
	if vdate then
		local vcat = cfg['validation_cats']['dated'](vdate)
		metadatatable:node(construct_field('validation_date', construct_cat_link(vcat, vdate)))
		table.insert(cats, construct_cat(vcat))
	elseif args['Progress'] == 'T' then
		table.insert(cats, construct_cat(cfg['validation_cats']['undated']))
	end

	local info_args = {'ISBN', 'OCLC', 'LCCN', 'ARK', --[=['National Archives',]=] 'DOI'}
	for i, v in ipairs(info_args) do
		local val = args[v]
		if val then
			local lower_key = string.lower(v)
			local link_fn = cfg.url_gens[lower_key]
			if link_fn then
				metadatatable:node(construct_field(lower_key, link_fn(val, val)))
			end
		end
	end

	metadatatable:node(construct_field('volumes', args['Volumes']))

	-- Language categorisations
	if args.Language then
		local langs = mw.text.split(args.Language, ',%s*', false)
		for _, l in ipairs(langs) do
			local lang = mw.text.trim(l)
			if lang ~= '' then
				table.insert(cats, construct_cat(cfg['language_cats']['single'](ISO_639.language_name(lang))))
			end
		end
		if #langs > 1 then
			table.insert(cats, construct_cat(cfg['language_cats']['multi']))
		end
	end

	return {['table'] = metadatatable, cats = table.concat(cats), indicators = table.concat(indicators)}
end

--[=[
Get the image to use as the cover image for this index

If the Image parameter contains an integer, it refers to a page in a DjVu/PDF and can be used directly
Otherwise, it may be a full image specification that we can use directly,
or just an image filename that we can construct an image specification for
]=]

local function default_cover_image(link)
	return '[[' .. cfg.cover.image .. '|' .. cfg.cover.width .. '|link=' .. link .. '|class=ws-cover]]'
end

local function _cover(args)
	local image_number = tonumber(args['Image'])

	-- check for timestamps
	if args['Image'] and not image_number and args.source_type == 'audiovisual' and mw.ustring.match(args['Image'], '^%d+[%d:]*$') then
		image_number = args['Image']
	end

	local image_spec

	local cats = {}

	if not image_number and args['Image'] and mw.ustring.find(args['Image'], '^%[%[') then
		-- Image param is not a (page) number and looks like a full image specification
		image_spec = args['Image']
		if args.source_type ~= 'image' then
			-- Add a tracking category
			table.insert(cats, construct_cat(cfg.cover_cats.fullspec))
		end
	elseif not image_number and args['Image'] and mw.ustring.find(args['Image'], '%.%w+$') then
		-- Image param is not a (page) number and is probably a filename with or without File: prefix
		image_spec = args['Image']
		local image_prefixes = {
			mw.site.namespaces.File.name,
			mw.site.namespaces.File.canonicalName
		}
		for i, alias in ipairs(mw.site.namespaces.File.aliases) do
			table.insert(image_prefixes, alias)
		end
		for i, prefix in ipairs(image_prefixes) do
			image_spec = mw.ustring.gsub(image_spec, '^' .. prefix .. ':', '')
			image_spec = mw.ustring.gsub(image_spec, '^' .. string.lower(prefix) .. ':', '')
		end
		image_spec = '[[File:' .. image_spec .. '|' .. cfg.cover.width .. '|class=ws-cover]]'

		if args.source_type ~= 'image' then
			-- Add a tracking category
			table.insert(cats, construct_cat(cfg.cover_cats.fullspec))
		end
	elseif args.source_type == 'multipage' and args.file_exists then
		-- It's a DjVu/PDF-backed index, so we fetch the cover image from a page in the (multipage) file
		image_spec = '[[' .. args.fileTitle.prefixedText .. '|' .. cfg.cover.width .. '|page=' .. (image_number or 1) .. '|class=ws-cover]]'
	elseif args.source_type == 'audiovisual' and args.file_exists then
		-- It's an audio/video-backed index, so we fetch the cover image from a thumbnail time
		image_spec = '[[' .. args.fileTitle.prefixedText .. '|' .. cfg.cover.width .. '|thumbtime=' .. (image_number or 0) .. '|class=ws-cover]]'
	elseif args.file_exists then
		-- It's either an image-based index or some unknown type, so we use the file
		image_spec = '[[' .. args.fileTitle.prefixedText .. '|' .. cfg.cover.width .. '|class=ws-cover]]'
	else
		-- Our associated file doesn't exist, so we use a placeholder
		local image_link = args.fileTitle.prefixedText
		if mw.ustring.find(args.fileTitle.rootText, '^.*%.%w+') == nil then
			image_link = 'Special:Upload'
		end
		image_spec = default_cover_image(image_link)
	end

	return image_spec .. table.concat(cats)
end

-- Also implements [[Template:Index talk remarks]]

function p._index_talk_remarks(args)
	if not args.talkPageTitle then
		args.pageTitle = (args.pageTitle and mw.title.new(args.pageTitle)) or mw.title.getCurrentTitle()
		args.talkPageTitle = args.pageTitle.talkPageTitle
	end

	local text = cfg['talkremarks']['text'](args)
	local cat = category_handler({construct_cat(cfg['talkremarks']['cat'])}) or ''

	local notes = ''
	if args.notes then
		-- 5.5em is small enough, and has the convenience of probably showing the top of a line when there are too many

		notes = mw.html.create('div')
			:addClass('ombox-content')
			:css({
				['text-align'] = 'left',
				['max-height'] = '5.5em',
				['overflow'] = 'scroll',
				['padding'] = '0.25em',
				['margin'] = '0.25em',
				['border-style'] = 'dashed'
			})
			:newline()
			:wikitext(args.notes .. cat)
			:newline()
			:allDone()
	end

	return messageBox.main('ombox', {
		['type'] = 'content',
		['image'] = '[[File:Ambox important.svg|24px]]',
		['style'] = 'box-sizing:border-box;margin:-0.93em auto 0.0em;text-align:center;width:100%;',
		['textstyle'] = 'font-size:93%;text-decoration:none;',
		['text'] = text .. tostring(notes)
	})
end

function p.index_talk_remarks(frame)
	return p._index_talk_remarks(getArgs(frame))
end

-- Main function
local function _main(args)
	args = process_args(args)

	local talkremarks = ''
	local talk_page_exists = args.talkPageTitle.exists -- Expensive
	if talk_page_exists and not args.notes then
		local content = args.talkPageTitle.content
		for _, keyword in ipairs(cfg.talkremarks.keywords) do
			local pattern
			if keyword.alone then -- Only whitespace around
				pattern = '==( *' .. keyword.pattern .. ' *)=='
			else -- Allow for other content besides the keyword
				pattern = '==([^=%n]*' .. keyword.pattern .. '[^=%n]*)=='
			end
			-- Capture section header
			local section = mw.ustring.match(content, pattern)
			if section then
				-- Specifically transclude the section
				local section_text = mw.getCurrentFrame():callParserFunction('#lsth', args.talkPageTitle.prefixedText, mw.text.trim(section))

				args.notes = section_text
				break
			end
		end
	end
	if talk_page_exists then
		talkremarks = p._index_talk_remarks(args)
	end

	local metadata_data = _metadata(args)
	local sortkey = mw.getCurrentFrame():callParserFunction('DEFAULTSORT', {args['Key'] or args.pageTitle.text})

	local is = {}
	for _, v in pairs(cfg.indicators) do
		table.insert(is, construct_indicator(args, v))
	end
	table.insert(is, metadata_data.indicators)
	local indicators = table.concat(is)

	local outertable = mw.html.create('table')
		:attr('id', 'ws-index-container')

	local outertable_tr = outertable:tag('tr')

	outertable_tr
		:tag('td')
			:attr('id', 'ws-index-main-cell')
			:tag('table')
				:attr('id', 'ws-index-main-table')
				:tag('tr'):tag('td')
					:tag('div')
						:attr('id', 'ws-index-cover-container')
						:wikitext(_cover(args))
						:done()
					:node(metadata_data['table'])
					:done()
				:tag('tr'):tag('td'):tag('div')
					:attr('id', 'ws-index-pagelist-container')
					:addClass('mw-collapsible')
					:tag('em'):wikitext(cfg.pagelist.pages.txt):done()
					:wikitext(' ')
					:tag('span')
						:attr('id', 'ws-index-pagelist-legend')
						:wikitext(cfg.pagelist.legend.txt)
						:done()
					:tag('div')
						:attr('id', 'ws-index-pagelist')
						:addClass('index-pagelist mw-collapsible-content')
						:newline()
						:wikitext(args['Pages'] and mw.text.trim(args['Pages']))
						:newline()

	if args['Remarks'] then
		outertable_tr:tag('td')
			:attr('id', 'ws-index-remarks')
			:newline()
			:wikitext(mw.getCurrentFrame():preprocess(args['Remarks']))
	else
		outertable_tr:tag('td')
			:attr('id', 'ws-index-remarks-empty')
	end

	return talkremarks .. indicators .. tostring(outertable) .. metadata_data.cats .. sortkey
end

function p.main(frame)
	return _main(getArgs(frame))
end

return p
