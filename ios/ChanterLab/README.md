# ChanterLab iOS shell

Thin WKWebView host for https://chanterlab.com (see docs/IOS-EVALUATION-2026-07.md §4 for what a
wrapper does and does not fix: it does NOT fix the VPIO mic+speaker crackle). Needs XcodeGen
(`xcodegen generate`) then open/build `ChanterLab.xcodeproj`. For a device build, set the
signing team in Xcode first.
