---
name: illustrator
description: Automate Adobe Illustrator with ExtendScript (.jsx) - export artboards to PNG/SVG/PDF, batch edits.
category: design
tools: write_file, run_app_script, open_in_app
apps: illustrator
status: untested
---
# Illustrator (ExtendScript)

Windows: COM `Illustrator.Application.DoJavaScriptFile`; macOS: AppleScript `do javascript file`. Untested by AutoMoto's authors.

1. `write_file` `scripts/export.jsx`:
   ```js
   #target illustrator
   var src = new File(File($.fileName).parent + "/../art/logo.ai");
   var doc = app.open(src);
   var opts = new ExportOptionsPNG24(); opts.artBoardClipping = true; opts.transparency = true;
   opts.horizontalScale = opts.verticalScale = 200;
   doc.exportFile(new File(src.parent + "/logo@2x.png"), ExportType.PNG24, opts);
   doc.close(SaveOptions.DONOTSAVECHANGES);
   ```
2. `run_app_script` `illustrator` `scripts/export.jsx` (approval). SVG export: `ExportType.SVG` with `ExportOptionsSVG`.
3. Without Illustrator, write SVG directly and export with Inkscape/ImageMagick (`graphic-design`).
