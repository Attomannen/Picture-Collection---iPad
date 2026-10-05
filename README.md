# PicBoard

A PureRef-style reference board for iPad: an infinite canvas where you drop in images and move, scale, rotate, flip and layer them.

## Run it
- **Mac:** open this folder in Xcode (File > Open), pick an iPad simulator or device, press Run.
- **iPad:** open the folder in Swift Playgrounds (4.4+).

## Controls
- Drag an image to move it; drag empty space to pan.
- Pinch: scales the selected image, or zooms the canvas when nothing is selected.
- Two-finger twist rotates the selected image.
- Toolbar: add from Photos / Files / clipboard (or drag & drop from another app), fit all, undo.
- Bottom bar (when an image is selected): flip, duplicate, to front/back, delete.

## Files
Boards are saved automatically in the app's `Documents/Boards` as `.picboard`
(a single file: JSON scene + original image bytes; see `Sources/Core/BoardArchive.swift`).
Long-press a board in the list to export it; use Import to bring one in.

## Layout
- `Sources/Core` – model and file format (Foundation only)
- `Sources/App` – SwiftUI app
- `Tests/CoreTests` – unit tests for the above

`.pur` import/export is planned; it should plug in beside `BoardArchive`.
