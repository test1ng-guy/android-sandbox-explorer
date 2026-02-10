# Android Sandbox Explorer

A universal tool for injecting a native library into any Android APK (single or split) on non-root devices. The injected library runs a TCP server inside the app's sandbox, enabling remote file system exploration via simple shell-like commands.

## Features

- Works with **single APK** and **split APK** (base + split\_config.\*)
- Auto-detects architecture (arm64-v8a, armeabi-v7a, etc.)
- Auto-detects Application class and `onCreate` method (any modifiers)
- Multi-dex support (smali\_classes2..N)
- TCP server on port 50052 for remote command execution
- Commands: `ls`, `cd`, `cp` (upload / download, recursive)
- Adds INTERNET + storage permissions automatically
- APK Signature Scheme v2 signing (apksigner)

## Prerequisites

- Python 3
- [apktool](https://apktool.org/) — `brew install apktool` (macOS) / `apt install apktool` (Linux)
- Android SDK Build Tools (`zipalign`, `apksigner`) — from Android Studio or standalone SDK
- Java JDK (for APK signing)
- ADB + Android device with USB debugging enabled

## Quick Start

### 1. Build the implant (optional — pre-compiled `libimplant.so` included)

```bash
# Using Android NDK:
$ANDROID_NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/aarch64-linux-android21-clang \
  -shared -fPIC -o libimplant.so implant.c -llog
```

### 2. Inject into APK

**Single APK:**
```bash
python3 repack.py app.apk libimplant.so injected.apk
```

**Split APK (directory with base.apk + split\_\*.apk):**
```bash
python3 repack.py /path/to/split_dir/ libimplant.so output.apk
# Output → output_split/ directory with all signed splits
```

The script will automatically:
- Decompile the APK with apktool
- Inject `System.loadLibrary("implant")` into Application.onCreate()
- Add the .so to the correct architecture directory
- Add INTERNET and storage permissions
- Rebuild, align (zipalign), and sign (apksigner v2)

### 3. Install on device

```bash
# Single APK
adb install injected.apk

# Split APK
adb install-multiple output_split/*.apk
```

### 4. Connect to the implant

```bash
# Launch the app on device, then:
adb forward tcp:50052 tcp:50052
python3 implant_client.py
```

### Available commands

| Command | Description |
|---|---|
| `ls [path]` | List directory contents |
| `cd <path>` | Change directory |
| `cp <src> <dst> download` | Download file/directory from device |
| `cp <src> <dst> upload` | Upload file to device |
| `exit` | Close connection |

### Usage examples

```bash
> ls /data/data/com.example.app
cache
files
shared_prefs
databases

> cd /data/data/com.example.app

> cp /data/data/com.example.app/shared_prefs/prefs.xml ./prefs.xml download
Downloaded file 1234 bytes to ./prefs.xml

> cp ./payload.txt /data/data/com.example.app/files/payload.txt upload
OK
```

## Project Structure

| File | Description |
|---|---|
| `implant.c` | Native C library — TCP server, runs inside the app sandbox |
| `libimplant.so` | Pre-compiled implant (arm64-v8a) |
| `repack.py` | APK injection script (decompile → patch → rebuild → sign) |
| `implant_client.py` | Python TCP client for connecting to the implant |

## repack.py Parameters

```
python3 repack.py <apk_path> <so_path> <output> [--storepass PASS] [--alias ALIAS]
```

| Parameter | Default | Description |
|---|---|---|
| `apk_path` | — | APK file or directory with split APKs |
| `so_path` | — | Path to the .so library to inject |
| `output` | — | Output APK path (or base name for split output dir) |
| `--storepass` | `password` | Keystore password |
| `--alias` | `alias` | Key alias in the keystore |

## Troubleshooting

**Implant not loading:**
```bash
adb logcat -s Implant
# Should see: "JNI_OnLoad called", "Server listening"
```

**Connection refused:**
```bash
adb forward --list          # Check port forwarding
adb shell ps | grep <pkg>   # Check app is running
```

**Installation fails (INSTALL\_PARSE\_FAILED\_NO\_CERTIFICATES):**
- Make sure `apksigner` from Android SDK build-tools is in PATH (not a broken wrapper)
- All split APKs must be signed with the same key

**Injection fails:**
- Verify `apktool` is installed and up to date
- Check that `custom.keystore` exists next to `repack.py`

## Security Notes

- This tool is intended for security research and testing only
- The injected code runs within the app's sandbox permissions
- Network traffic is forwarded via ADB (local connection only — binds to localhost)
- Respect applicable laws and app store policies

## License

For educational and research purposes only.