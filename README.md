# Android APK Injection Tool for Non-Root Devices

This project provides a complete solution for injecting a custom native library (.so) into Android apps on non-root devices. The injected library runs a TCP server on port 50052, allowing remote shell-like commands and file operations within the app's sandbox.

## Features

- TCP server on port 50052 for remote command execution
- Shell-like commands: `ls`, `cd`, `cp` for file system navigation and copying
- Recursive file/directory upload/download
- Works within app sandbox on non-root Android devices
- Automatic APK decompilation, injection, and repackaging
- Support for multiple architectures (arm64-v8a, armeabi-v7a)

## Prerequisites

- Linux/macOS with Python 3
- Android SDK with `apktool` installed: `brew install apktool` (macOS) or `apt install apktool` (Ubuntu)
- Android NDK for cross-compilation (included in `android-ndk-r26d/`)
- Java JDK for APK signing
- Android device connected via USB (for testing)

## Building the Implant

The implant is a native C library that gets injected into the APK:

```bash
# Compile the implant for Android
# The project includes pre-compiled libimplant.so
# To recompile, use Android NDK:
$ANDROID_NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/aarch64-linux-android21-clang \
  -shared -fPIC implant.c -o libimplant.so
```

## Injecting into APK

Use the provided Python script to inject the implant into any APK:

```bash
python3 repack.py <apk_path> <so_path> [output_apk] [--storepass password] [--alias alias]
```

### Example

```bash
# Inject implant into an APK
python3 repack.py target.apk libimplant.so injected.apk

# The script will:
# - Decompile the APK using apktool
# - Copy libimplant.so to lib/arm64-v8a/ (or detected architecture)
# - Modify AndroidManifest.xml to add INTERNET permission
# - Rebuild and sign the APK
```

## Installing on Device

Install the injected APK using ADB:

```bash
# Install the patched APK
adb install injected.apk

# Grant permissions if needed
adb shell pm grant <package_name> android.permission.READ_EXTERNAL_STORAGE
adb shell pm grant <package_name> android.permission.WRITE_EXTERNAL_STORAGE
```

## Connecting and Usage

1. Launch the patched app on your Android device
2. Forward the port via ADB:

```bash
adb forward tcp:50052 tcp:50052
```

3. In another terminal, connect using the Python client:

```bash
python3 implant_client.py
```

### Available Commands

- `ls [path]` - List directory contents
- `cd <path>` - Change current directory
- `cp <src> <dst> <upload|download>` - Copy files between device and host
- `exit` - Close connection

### Examples

```bash
# Connect to implant
python3 implant_client.py

# List root directory
> ls /

# Change to app data directory
> cd /data/data/com.example.app

# List app data directory
> ls

# Download a file from device
> cp /data/data/com.example.app/shared_prefs/prefs.xml ./prefs.xml download

# Upload a file to device
> cp ./local_file.txt /data/data/com.example.app/local_file.txt upload

# Download entire directory recursively
> cp /data/data/com.example.app/Documents ./downloads download
```

## Architecture

- `repack.py` - APK injection script that decompiles, modifies, and repackages APKs
- `implant.c` - Native C library with TCP server for command execution
- `implant_client.py` - Python client for remote shell access
- `libimplant.so` - Compiled native library for Android
- `android-ndk-r26d/` - Android NDK for cross-compilation

## Security Notes

- This tool is for testing and development purposes only
- Respect app store policies and legal requirements
- The injected code runs with the app's sandbox permissions
- Network traffic is forwarded via ADB (secure local connection)

## Troubleshooting

### Implant Not Loading

- Check device logs: `adb logcat | grep Implant`
- Look for "JNI_OnLoad called" and "Server listening" messages
- Ensure the APK is properly signed and installed
- Verify architecture compatibility (arm64-v8a vs armeabi-v7a)

### Connection Refused

- Verify app is running on device: `adb shell ps | grep <package_name>`
- Check port forwarding: `adb forward --list`
- Ensure port 50052 is not blocked

### File Access Issues

- Check app permissions in AndroidManifest.xml
- Verify file paths exist and are accessible
- Some directories require special permissions

### Injection Fails

- Ensure apktool is installed and working
- Check that input APK is valid and not corrupted
- Verify keystore exists and passwords are correct

## Building from Source

```bash
# Clone the repository
git clone <repository_url>
cd android-implant

# The project is ready to use - all components included
# To recompile the implant:
# Use Android NDK to compile implant.c for target architecture
```

## License

This project is for educational and research purposes only.