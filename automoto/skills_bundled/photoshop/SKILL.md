---
name: photoshop
description: Automate Adobe Photoshop with ExtendScript (.jsx) - batch resize/export, layers, text - via its official scripting route.
category: design
tools: write_file, run_app_script, open_in_app
apps: photoshop
status: untested
---
# Photoshop (ExtendScript)

Needs a licensed Photoshop on **Windows** (COM `Photoshop.Application.DoJavaScriptFile`) or **macOS**
(AppleScript `do javascript file`). Not tested by AutoMoto's authors (no Photoshop on the test machines).

1. `write_file` `scripts/resize.jsx`, using absolute paths built from `File($.fileName).parent`:
   ```js
   #target photoshop
   app.displayDialogs = DialogModes.NO;
   var folder = new Folder(File($.fileName).parent + "/../images");
   var files = folder.getFiles(/\.(jpg|png)$/i);
   for (var i = 0; i < files.length; i++) {
     var doc = app.open(files[i]);
     doc.resizeImage(UnitValue(1200, "px"), null, 72, ResampleMethod.BICUBIC);
     var out = new File(folder + "/out_" + doc.name.replace(/\.[^.]+$/, ".jpg"));
     var o = new JPEGSaveOptions(); o.quality = 10;
     doc.saveAs(out, o, true); doc.close(SaveOptions.DONOTSAVECHANGES);
   }
   ```
2. Show the user the script, then `run_app_script` `photoshop` `scripts/resize.jsx` (approval).
3. Simple viewing/editing by hand: `open_in_app` `photoshop` `images/photo.psd`.
4. No Photoshop? Do the same with ImageMagick (`graphic-design` skill).
