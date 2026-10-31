- Navis markers no longer leak their bytes into a list-page title/summary
  projection: an item that takes its title from its body (no title field)
  gets the body with markers stripped, so a marker is not the one place
  the built site shows marker bytes outside the body's own HTML comments.
  The History disclosure's captured-snapshot body still quotes the item's
  stored body verbatim (it is the historical record as captured); docs say
  so. A no-marker project's site builds byte-identical.
