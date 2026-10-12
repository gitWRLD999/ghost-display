# Third-party notices

These notices apply to third-party components, not to the project's original source.
No license for Ghost's original source has been selected.

## Shizuku API 13.1.5

The Android app uses `dev.rikka.shizuku:api` and `provider`, with the associated
`aidl` and `shared` modules. Their Maven metadata identifies the MIT license.
Copyright (c) 2021 RikkaW.

The complete [MIT notice](app/src/main/assets/licenses/shizuku-api-MIT.txt) is
included in the app's assets for subsequent builds. The historical preview release
also includes a separate notice file alongside its unchanged APK.

Source: [RikkaApps/Shizuku-API](https://github.com/RikkaApps/Shizuku-API).
License: [upstream LICENSE](https://github.com/RikkaApps/Shizuku-API/blob/master/LICENSE).

## Gradle wrapper

The generated `gradlew` / `gradlew.bat` scripts retain their original copyright
and Apache-2.0 headers. The wrapper JAR contains its license resource.
Gradle is build tooling; it is not embedded in Ghost's Android runtime.

## Other referenced software and content

Artemis is checked out separately for tests. No Artemis distribution is vendored
here; the tests load the pinned upstream files from a sibling checkout. Python
dependencies are installed from the test requirements and retain their own licenses.

Wikipedia showcase attribution and content licensing are recorded in
[SHOWCASE.md](docs/SHOWCASE.md). Android framework and Shizuku applications are
provided separately on the device.
