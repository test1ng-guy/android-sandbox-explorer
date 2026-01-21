import subprocess
import os
import shutil
import argparse
import xml.etree.ElementTree as ET

def main():
    parser = argparse.ArgumentParser(description="Inject a native library (.so) into an APK for Android app analysis.")
    parser.add_argument("apk_path", help="Path to the input APK file")
    parser.add_argument("binary_path", help="Path to the compiled native library (.so) for Android")
    parser.add_argument("output_apk", help="Path to the output repackaged APK")
    parser.add_argument("--storepass", default="password", help="Keystore password (default: password)")
    parser.add_argument("--alias", default="alias", help="Keystore alias (default: alias)")
    parser.add_argument("--additional-apks", nargs='*', help="Additional APK files to sign with the same keystore")
    args = parser.parse_args()

    extracted_dir = "extracted"
    unsigned_apk = "unsigned.apk"
    keystore = "custom.keystore"

    # Step 1: Decode the APK
    subprocess.check_call(["apktool", "d", "-f", args.apk_path, "-o", extracted_dir])

    # Step 2: Detect available architectures and add the native library
    lib_dir = os.path.join(extracted_dir, "lib")
    if os.path.exists(lib_dir):
        available_archs = [d for d in os.listdir(lib_dir) if os.path.isdir(os.path.join(lib_dir, d))]
        if "arm64-v8a" in available_archs:
            arch = "arm64-v8a"
            print(f"Using architecture: {arch}")
        elif "armeabi-v7a" in available_archs:
            arch = "armeabi-v7a"
            print(f"Using architecture: {arch}")
        elif available_archs:
            arch = available_archs[0]  # Use the first available architecture
            print(f"Using architecture: {arch}")
        else:
            arch = "armeabi-v7a"  # Default fallback
            print(f"No architectures found, using default: {arch}")
    else:
        arch = "armeabi-v7a"  # Default fallback
        print(f"No lib directory found, using default: {arch}")
    
    lib_arch_dir = os.path.join(lib_dir, arch)
    os.makedirs(lib_arch_dir, exist_ok=True)
    binary_name = os.path.basename(args.binary_path)
    target_lib_path = os.path.join(lib_arch_dir, binary_name)
    shutil.copy(args.binary_path, target_lib_path)

    # Determine the load name for System.loadLibrary (strip 'lib' prefix and '.so' suffix if present)
    load_name = binary_name
    if load_name.startswith("lib"):
        load_name = load_name[3:]
    if load_name.endswith(".so"):
        load_name = load_name[:-3]

    # Step 3: Parse AndroidManifest.xml to find the launcher activity and add INTERNET permission if needed
    manifest_path = os.path.join(extracted_dir, "AndroidManifest.xml")
    ET.register_namespace("android", "http://schemas.android.com/apk/res/android")
    tree = ET.parse(manifest_path)
    root = tree.getroot()
    ns = {"android": "http://schemas.android.com/apk/res/android"}

    # Remove permission declarations to avoid conflicts
    for perm in root.findall("permission", ns):
        root.remove(perm)

    # Check and add INTERNET permission if not present
    if not root.findall(".//uses-permission[@android:name='android.permission.INTERNET']", ns):
        perm = ET.Element("uses-permission")
        perm.set("{http://schemas.android.com/apk/res/android}name", "android.permission.INTERNET")
        root.append(perm)  # Append to the end
        tree.write(manifest_path, xml_declaration=True, encoding="utf-8")

    # Add storage permissions if not present
    storage_perms = [
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.WRITE_EXTERNAL_STORAGE"
    ]
    for perm_name in storage_perms:
        if not root.findall(f".//uses-permission[@android:name='{perm_name}']", ns):
            perm = ET.Element("uses-permission")
            perm.set("{http://schemas.android.com/apk/res/android}name", perm_name)
            root.append(perm)
    tree.write(manifest_path, xml_declaration=True, encoding="utf-8")

    # Find the application class
    application = root.find(".//application", ns)
    if application is None:
        raise ValueError("Could not find application in AndroidManifest.xml")
    application_name = application.get("{http://schemas.android.com/apk/res/android}name")

    if application_name is None:
        raise ValueError("Application has no name")

    # Handle relative package names
    if application_name.startswith("."):
        package = root.get("package")
        application_name = package + application_name

    # Convert to smali path
    smali_class_path = application_name.replace(".", "/") + ".smali"
    smali_path = os.path.join(extracted_dir, "smali", smali_class_path)
    if not os.path.exists(smali_path):
        # Check for multi-dex (smali_classesX)
        found = False
        for i in range(2, 10):  # Assuming up to smali_classes9
            alt_path = os.path.join(extracted_dir, f"smali_classes{i}", smali_class_path)
            if os.path.exists(alt_path):
                smali_path = alt_path
                found = True
                break
        if not found:
            raise FileNotFoundError(f"Smali file not found for {application_name}")

    # Step 4: Inject System.loadLibrary into the smali file (in onCreate method)
    with open(smali_path, "r") as f:
        lines = f.readlines()

    insert_lines = [
        '    const-string v4, "implant"\n',
        '    invoke-static {v4}, Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V\n'
    ]

    inserted = False
    for i, line in enumerate(lines):
        if line.strip() == ".method public onCreate()V":
            # Update .locals if needed
            for j in range(i + 1, len(lines)):
                if lines[j].strip().startswith(".locals"):
                    current_locals = int(lines[j].strip().split()[1])
                    if current_locals < 8:
                        lines[j] = "    .locals 8\n"
                break
            
            # Find the return-void in onCreate and insert before it
            in_oncreate = False
            for j in range(i + 1, len(lines)):
                if lines[j].strip() == ".end method":
                    # We've reached the end of the method
                    break
                if lines[j].strip() == "return-void":
                    # Insert before the return-void
                    lines = lines[:j] + insert_lines + lines[j:]
                    inserted = True
                    break

    if not inserted:
        print("Warning: Could not find onCreate method to inject library loading")

    with open(smali_path, "w") as f:
        f.writelines(lines)

    # Step 5: Repackage the APK
    subprocess.check_call(["apktool", "b", extracted_dir, "-o", unsigned_apk])

    # Step 6: Sign the APK
    print("Signing APK...")
    # Try to find apksigner in common locations
    apksigner_paths = [
        "/Users/jacklondon/Library/Android/sdk/build-tools/36.0.0/apksigner",
        "apksigner"  # In PATH
    ]
    
    apksigner_path = None
    for path in apksigner_paths:
        if os.path.exists(path) or shutil.which(path):
            apksigner_path = path
            break
    
    if not apksigner_path:
        print("Warning: apksigner not found, trying uber-apk-signer.jar")
        # Fallback to uber-apk-signer.jar
        subprocess.check_call([
            "java", "-jar", "uber-apk-signer.jar", "--apks", unsigned_apk,
            "--ks", keystore, "--ksAlias", args.alias, "--ksPass", args.storepass,
            "--ksKeyPass", args.storepass
        ])
        shutil.move(unsigned_apk.replace('.apk', '-aligned-signed.apk'), args.output_apk)
    else:
        subprocess.check_call([
            apksigner_path, "sign", "--ks", keystore, "--ks-pass", f"pass:{args.storepass}",
            "--ks-key-alias", args.alias, "--out", args.output_apk, unsigned_apk
        ])
    
    print("APK signed successfully.")
    print(f"Repackaged APK saved to {args.output_apk}")

if __name__ == "__main__":
    main()