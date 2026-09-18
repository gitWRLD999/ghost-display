# Development

## Toolchain

| Component | Version |
| --- | --- |
| Android compile / target SDK | 36 / 36 |
| Minimum manifest SDK | 34; device verification is on Android 16 only |
| Android Gradle Plugin | 8.13.0 |
| Gradle wrapper | 8.13 |
| Build tools | 36.0.0 |
| Java language level | 17 |
| Verified build JDK | 21 |
| Shizuku API / provider | 13.1.5 |

The checked-in Java source is formatted with google-java-format 1.36.1. No generated AIDL Java class is checked in; Gradle generates it from `IGhostDisplayService.aidl`.

## Build

```sh
./gradlew clean assembleDebug
```

```powershell
./scripts/build.ps1 -JavaHome /path/to/jdk -AndroidSdk /path/to/sdk
```

The PowerShell build helper discovers standard local installations when explicit paths are omitted. It verifies the APK with `apksigner` and can verify its signing certificate against `-ExpectedCertificateSha256`.

## Signing updates

Keep the release signing key outside the repository. An Android update must match the certificate already installed on the phone.

| Environment variable | Meaning |
| --- | --- |
| `GHOST_KEYSTORE` | Absolute path to the existing signing keystore. |
| `GHOST_STORE_PASSWORD` | Store password; default is Android debug convention. |
| `GHOST_KEY_ALIAS` | Alias; default `androiddebugkey`. |
| `GHOST_KEY_PASSWORD` | Key password; default is Android debug convention. |
| `GHOST_SIGNING_CERT_SHA256` | Expected certificate digest for the Windows helper. |

The personal preview APK is a debug build. Its certificate SHA-256 is `2f1079729bc379f7eba0298cf61875d8a4c7d5dadf8ab67d0b8edb67db387991`. This public digest is not the private key. CI uses a fresh debug key and therefore cannot install over the personal release.

## Device verification

`scripts/smoke.ps1` exercises the real CLI, starts Chrome on Ghost, checks WindowManager and InputDispatcher focus, compares independent text fields, and verifies test-fixture tap/long-press/swipe/key state and valid images. The fixture writes its own state under app-private storage; the debug test harness reads it using `run-as`. Production control does not depend on that fixture or Accessibility.

Viewer and lock/off tests also require visual inspection, power/keyguard diagnostics, and elapsed-time measurements. A valid PNG or advancing frame counter alone is insufficient: a black frame must not be mistaken for functioning capture.

## Privacy of development artifacts

Only synthetic test screenshots and summarized measurements belong in Git. Raw `dumpsys` output can contain unrelated app state. APK backups, keystores, phone serials, local paths, Termux history, and framework decompilation artifacts stay outside the repository.
