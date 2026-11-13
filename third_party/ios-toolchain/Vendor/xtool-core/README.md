# xtool-core

xtool core libraries in a Swift Package.

## About

This is a Swift Package that provides a set of utilities for Supercharge/[xtool](http://github.com/ymmiah/xtool) and vends a number of third-party dependencies (primarily, the [libimobiledevice](https://github.com/libimobiledevice/libimobiledevice) constellation).

The third-party dependencies are built via [xtool-libs](https://github.com/ymmiah/xtool-libs).

See the submodules of xtool-libs for individual licenses. Note that several dependencies are LGPL licensed, which means clients must link them dynamically (this is the default behavior if you depend on xtool-core.)
