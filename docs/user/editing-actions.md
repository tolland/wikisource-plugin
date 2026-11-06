# Editing actions

These actions come with the Wikitext Language plugin. They edit only the
document text, so they behave the same in local `.wt` files and in pages opened
from a wiki.

## Surround With (`Ctrl+Alt+T`)

Select some text, press `Ctrl+Alt+T` (**Code → Surround With…**) and choose a
construct. The list, in order:

| Entry | Inserts |
|---|---|
| Bold | `'''…'''` |
| Italic | `''…''` |
| `<code>`, `<math>`, `<nowiki>`, `<ref>`, `<small>`, `<sup>`, `<sub>` | the tag around the selection, inline |
| `<pre>`, `<poem>`, `<blockquote>`, `<noinclude>`, `<includeonly>`, `<onlyinclude>` | the tags on their own lines around the selection |
| `<section begin/end>` | `<section begin="name" />` before and `<section end="name" />` after, on their own lines |

For `<section begin/end>` you type the section name once and both markers
update together. Platform surrounders (your own live templates with
`$SELECTION$`) still appear in the same popup.

## Bold and Italic (`Ctrl+B`, `Ctrl+I`)

In a wikitext file, `Ctrl+B` toggles `'''bold'''` and `Ctrl+I` toggles
`''italic''` around the selection. Both are also on the editor's right-click
menu.

- With an empty selection the markers are inserted with the caret between them.
- If the selection is already bold (or italic), the markers are removed.
- Bold-italic (`'''''x'''''`) is handled per style: un-bolding leaves `''x''`,
  un-italicising leaves `'''x'''`.
- A selection spanning several lines is toggled line by line, because
  MediaWiki quote formatting never crosses a line break.

In every other file type these shortcuts keep their usual meaning
(`Ctrl+B` Go to Declaration, `Ctrl+I` Implement Methods).

## Switches

Each feature has a switch in **Help → Find Action → Registry…**. They are
registry keys rather than settings because the interaction styles are still
being evaluated.

| Key | Default | Effect |
|---|---|---|
| `wikitext.editing.surround.enabled` | `true` | Offer wikitext constructs in Surround With. |
| `wikitext.editing.surround.strategy` | `template` | `template` inserts as a live template (section names are typed in place); `document` makes one plain edit. |
| `wikitext.editing.variablePrompt` | `inline` | Used by the `document` strategy only: `dialog` asks for a section name in a modal; any other value leaves the placeholder selected for you to type over. |
| `wikitext.editing.toggle.enabled` | `true` | Enable the Bold/Italic actions. When off, `Ctrl+B`/`Ctrl+I` revert to the platform actions. |
| `wikitext.editing.toggle.promote` | `true` | Let the wikitext actions win `Ctrl+B`/`Ctrl+I` in wikitext files. |
