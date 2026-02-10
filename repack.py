import subprocess
import os
import shutil
import argparse
import xml.etree.ElementTree as ET
import zipfile
import sys
import glob


def detect_split_apk(apk_path):
    """Detect if the input is a split APK (directory with base.apk + split_*.apk)"""
    if os.path.isdir(apk_path):
        base = os.path.join(apk_path, "base.apk")
        if os.path.exists(base):
            splits = sorted(glob.glob(os.path.join(apk_path, "split_*.apk")))
            return base, splits
        # Maybe directory contains APK files without base.apk naming
        apks = sorted(glob.glob(os.path.join(apk_path, "*.apk")))
        if apks:
            return apks[0], apks[1:]
    elif os.path.isfile(apk_path):
        # Check if there are split APKs alongside this file
        parent_dir = os.path.dirname(os.path.abspath(apk_path))
        basename = os.path.basename(apk_path)
        if basename == "base.apk":
            splits = sorted(glob.glob(os.path.join(parent_dir, "split_*.apk")))
            if splits:
                return apk_path, splits
    return apk_path, []


def inject_so_into_split_apk(split_apk_path, binary_path, output_path):
    """Inject .so into a split APK (e.g., split_config.arm64_v8a.apk) by adding the library to it"""
    print(f"📦 Injecting .so into split APK: {os.path.basename(split_apk_path)}")
    binary_name = os.path.basename(binary_path)

    with zipfile.ZipFile(split_apk_path, 'r') as zin:
        # Detect architecture from existing entries
        arch = None
        for name in zin.namelist():
            if name.startswith("lib/") and name.endswith(".so"):
                parts = name.split("/")
                if len(parts) >= 3:
                    arch = parts[1]
                    break

        if not arch:
            print(f"⚠️  No architecture detected in {os.path.basename(split_apk_path)}, skipping injection")
            shutil.copy(split_apk_path, output_path)
            return False

        print(f"   Architecture detected: {arch}")
        target_entry = f"lib/{arch}/{binary_name}"

        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                # Preserve compression type for .so files (usually STORED)
                if item.filename.endswith('.so') or item.filename == 'resources.arsc':
                    item.compress_type = zipfile.ZIP_STORED
                zout.writestr(item, data)

            # Add our implant library (stored uncompressed like other .so files)
            info = zipfile.ZipInfo(target_entry)
            info.compress_type = zipfile.ZIP_STORED
            with open(binary_path, 'rb') as f:
                zout.writestr(info, f.read())
            print(f"   ✅ Added {target_entry}")

    return True


def align_and_sign_apk(input_apk, output_apk, keystore, storepass, alias):
    """Align and sign a single APK file"""
    current_dir = os.path.dirname(os.path.abspath(output_apk))
    aligned_apk = os.path.join(current_dir, f"aligned_{os.path.basename(input_apk)}")

    # Zipalign
    zipalign_path = shutil.which("zipalign")
    if zipalign_path:
        try:
            subprocess.check_call([zipalign_path, "-p", "-f", "4", input_apk, aligned_apk])
        except subprocess.CalledProcessError:
            print(f"⚠️  zipalign failed for {os.path.basename(input_apk)}, using as-is")
            shutil.copy(input_apk, aligned_apk)
    else:
        shutil.copy(input_apk, aligned_apk)

    # Sign with apksigner
    apksigner_path = shutil.which("apksigner")
    if apksigner_path:
        try:
            subprocess.check_call([
                apksigner_path, "sign",
                "--ks", keystore,
                "--ks-pass", f"pass:{storepass}",
                "--ks-key-alias", alias,
                "--key-pass", f"pass:{storepass}",
                "--out", output_apk,
                aligned_apk
            ])
        except subprocess.CalledProcessError as e:
            print(f"⚠️  apksigner failed for {os.path.basename(input_apk)}: {e}")
            # Fallback to jarsigner
            jarsigner_path = shutil.which("jarsigner")
            if jarsigner_path:
                shutil.copy(aligned_apk, output_apk)
                subprocess.check_call([
                    jarsigner_path, "-keystore", keystore, "-storepass", storepass,
                    "-keypass", storepass, output_apk, alias
                ])
            else:
                print(f"❌ Neither apksigner nor jarsigner available!")
                sys.exit(1)
    else:
        jarsigner_path = shutil.which("jarsigner")
        if jarsigner_path:
            shutil.copy(aligned_apk, output_apk)
            subprocess.check_call([
                jarsigner_path, "-keystore", keystore, "-storepass", storepass,
                "-keypass", storepass, output_apk, alias
            ])
        else:
            print(f"❌ Neither apksigner nor jarsigner available!")
            sys.exit(1)

    # Cleanup
    if os.path.exists(aligned_apk):
        os.remove(aligned_apk)
    # apksigner may create .idsig files
    idsig = output_apk + ".idsig"
    if os.path.exists(idsig):
        os.remove(idsig)


def main():
    parser = argparse.ArgumentParser(description="Inject a native library (.so) into an APK for Android app analysis.")
    parser.add_argument("apk_path", help="Path to the input APK file or directory with split APKs")
    parser.add_argument("binary_path", help="Path to the compiled native library (.so) for Android")
    parser.add_argument("output_apk", help="Path to the output repackaged APK (or output directory for split APKs)")
    parser.add_argument("--storepass", default="password", help="Keystore password (default: password)")
    parser.add_argument("--alias", default="alias", help="Keystore alias (default: alias)")
    parser.add_argument("--additional-apks", nargs='*', help="Additional APK files to sign with the same keystore")
    args = parser.parse_args()

    current_dir = os.getcwd()
    keystore = os.path.join(os.path.dirname(os.path.abspath(__file__)), "custom.keystore")

    # Detect split APK
    base_apk, split_apks = detect_split_apk(args.apk_path)
    is_split = len(split_apks) > 0

    if is_split:
        print(f"🔀 Split APK detected!")
        print(f"   Base APK: {os.path.basename(base_apk)}")
        for s in split_apks:
            print(f"   Split: {os.path.basename(s)}")
        print()

        # For split APKs, output_apk is treated as an output directory
        output_dir = args.output_apk
        if output_dir.endswith(".apk"):
            output_dir = os.path.splitext(output_dir)[0] + "_split"
        os.makedirs(output_dir, exist_ok=True)

        # Process base.apk (decompile, inject smali, rebuild, sign)
        print("=" * 60)
        print("Step 1: Processing base.apk (smali injection + permissions)")
        print("=" * 60)
        injected_base = os.path.join(output_dir, "base.apk")
        process_single_apk(base_apk, args.binary_path, injected_base, keystore,
                           args.storepass, args.alias, inject_so_into_base=False)

        # Process split APKs - inject .so into the native lib split, re-sign all
        print()
        print("=" * 60)
        print("Step 2: Processing split APKs")
        print("=" * 60)

        for split_path in split_apks:
            split_name = os.path.basename(split_path)
            output_split = os.path.join(output_dir, split_name)

            # Inject .so into the arm64 split (or whichever contains native libs)
            if "arm64" in split_name or "armeabi" in split_name or "x86" in split_name:
                temp_injected = os.path.join(current_dir, f"temp_{split_name}")
                injected = inject_so_into_split_apk(split_path, args.binary_path, temp_injected)
                if injected:
                    # Ensure resources.arsc is uncompressed, align and sign
                    align_and_sign_apk(temp_injected, output_split, keystore, args.storepass, args.alias)
                    os.remove(temp_injected)
                    print(f"   ✅ {split_name} - injected and signed")
                else:
                    align_and_sign_apk(split_path, output_split, keystore, args.storepass, args.alias)
                    print(f"   ✅ {split_name} - signed (no injection needed)")
            else:
                # Just re-sign the split with the same key
                align_and_sign_apk(split_path, output_split, keystore, args.storepass, args.alias)
                print(f"   ✅ {split_name} - signed")

        print()
        print("=" * 60)
        print("✅ Split APK injection complete!")
        print(f"📁 Output directory: {output_dir}")
        print()
        print("To install on device:")
        output_apks = sorted(glob.glob(os.path.join(output_dir, "*.apk")))
        apk_list = " ".join(output_apks)
        print(f"   adb install-multiple {apk_list}")
        print()
        print("Or shorter:")
        print(f"   adb install-multiple {output_dir}/*.apk")

    else:
        # Single APK mode (original behavior)
        process_single_apk(base_apk, args.binary_path, args.output_apk, keystore,
                           args.storepass, args.alias, inject_so_into_base=True)


def process_single_apk(apk_path, binary_path, output_apk, keystore, storepass, alias, inject_so_into_base=True):
    """Process a single APK: decompile, inject smali + optionally .so, rebuild, sign"""
    current_dir = os.getcwd()
    extracted_dir = os.path.join(current_dir, "extracted")
    unsigned_apk = os.path.join(current_dir, "unsigned.apk")

    # Clean up extracted directory to avoid version conflicts
    if os.path.exists(extracted_dir):
        shutil.rmtree(extracted_dir)

    # Step 1: Decode the APK
    print("📂 Decompiling APK...")
    subprocess.check_call(["apktool", "d", "-f", apk_path, "-o", extracted_dir])

    # Step 2: Detect available architectures and add the native library (only for single APK mode)
    binary_name = os.path.basename(binary_path)
    if inject_so_into_base:
        lib_dir = os.path.join(extracted_dir, "lib")
        if os.path.exists(lib_dir):
            available_archs = [d for d in os.listdir(lib_dir) if os.path.isdir(os.path.join(lib_dir, d))]
            if "arm64-v8a" in available_archs:
                arch = "arm64-v8a"
            elif "armeabi-v7a" in available_archs:
                arch = "armeabi-v7a"
            elif available_archs:
                arch = available_archs[0]
            else:
                arch = "arm64-v8a"
        else:
            arch = "arm64-v8a"
            lib_dir = os.path.join(extracted_dir, "lib")

        print(f"   Using architecture: {arch}")
        lib_arch_dir = os.path.join(lib_dir, arch)
        os.makedirs(lib_arch_dir, exist_ok=True)
        target_lib_path = os.path.join(lib_arch_dir, binary_name)
        shutil.copy(binary_path, target_lib_path)

    # Determine the load name for System.loadLibrary (strip 'lib' prefix and '.so' suffix)
    load_name = binary_name
    if load_name.startswith("lib"):
        load_name = load_name[3:]
    if load_name.endswith(".so"):
        load_name = load_name[:-3]

    # Step 3: Parse AndroidManifest.xml and add permissions
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
        root.append(perm)

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
        for i in range(2, 10):
            alt_path = os.path.join(extracted_dir, f"smali_classes{i}", smali_class_path)
            if os.path.exists(alt_path):
                smali_path = alt_path
                found = True
                break
        if not found:
            raise FileNotFoundError(f"Smali file not found for {application_name}")

    # Step 4: Inject System.loadLibrary into the smali file (in onCreate method)
    print(f"   Injecting loadLibrary into: {os.path.basename(smali_path)}")
    with open(smali_path, "r") as f:
        lines = f.readlines()

    inserted = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Match onCreate with any modifiers (public, public final, etc.)
        if stripped.startswith(".method") and "onCreate()V" in stripped:
            # Determine the register to use based on .locals
            reg_index = 0
            locals_line_idx = -1
            for j in range(i + 1, len(lines)):
                if lines[j].strip().startswith(".locals"):
                    current_locals = int(lines[j].strip().split()[1])
                    reg_index = current_locals  # Use next available register
                    locals_line_idx = j
                    # Increase .locals to accommodate our new register
                    lines[j] = f"    .locals {current_locals + 1}\n"
                    break

            insert_lines = [
                f'    const-string v{reg_index}, "{load_name}"\n',
                f'    invoke-static {{v{reg_index}}}, Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V\n',
                '\n'
            ]

            # Insert right after invoke-super in onCreate (so it always executes)
            # Look for invoke-super or invoke-direct calling onCreate on parent
            inject_point = -1
            for j in range(i + 1, len(lines)):
                if lines[j].strip() == ".end method":
                    break
                if "invoke-super" in lines[j] or "invoke-direct" in lines[j]:
                    if "onCreate" in lines[j]:
                        inject_point = j + 1
                        break
            
            # Fallback: insert right after .locals line if no super call found
            if inject_point == -1 and locals_line_idx != -1:
                inject_point = locals_line_idx + 1

            if inject_point != -1:
                lines = lines[:inject_point] + insert_lines + lines[inject_point:]
                inserted = True
                break

    if not inserted:
        print("   ⚠️  Could not find onCreate method to inject library loading")

    with open(smali_path, "w") as f:
        f.writelines(lines)

    # Step 5: Modify apktool.yml for aapt2
    apktool_yml = os.path.join(extracted_dir, "apktool.yml")
    if os.path.exists(apktool_yml):
        with open(apktool_yml, "r") as f:
            yml_content = f.read()

        if "aapt2Version" not in yml_content:
            yml_content = yml_content.replace("version:", "version:\naapt2Version: '8.0.0-10921571'", 1)

        yml_content = yml_content.replace("resourcesAreCompressed: true", "resourcesAreCompressed: false")

        with open(apktool_yml, "w") as f:
            f.write(yml_content)
        print("   ✅ Modified apktool.yml for aapt2")

    # Step 6: Repackage the APK
    print("   Repackaging APK...")
    temp_build_apk = os.path.join(current_dir, "temp_build.apk")
    try:
        # apktool 2.12+ uses aapt2 by default; use --use-aapt1 flag to fall back
        subprocess.check_call(["apktool", "b", extracted_dir, "-o", temp_build_apk])
    except subprocess.CalledProcessError:
        print("   Build failed, trying with --use-aapt1...")
        try:
            subprocess.check_call(["apktool", "b", "--use-aapt1", extracted_dir, "-o", temp_build_apk])
        except subprocess.CalledProcessError:
            print("   aapt1 build failed, trying with --no-res flag...")
            subprocess.check_call(["apktool", "b", extracted_dir, "-o", temp_build_apk, "--no-res"])

    # Step 6.5: Ensure resources.arsc is stored uncompressed (Android 11+)
    print("   Ensuring resources.arsc is uncompressed...")
    ensure_resources_uncompressed(temp_build_apk, unsigned_apk)
    os.remove(temp_build_apk)

    # Step 7+8: Align and sign
    print("   Aligning and signing APK...")
    align_and_sign_apk(unsigned_apk, output_apk, keystore, storepass, alias)

    # Clean up
    if os.path.exists(unsigned_apk):
        os.remove(unsigned_apk)

    print(f"   ✅ APK saved to {output_apk}")

def ensure_resources_uncompressed(input_apk, output_apk):
    """Ensure resources.arsc is stored uncompressed in the APK (Android 11+ requirement)"""
    temp_dir = os.path.join(os.path.dirname(input_apk), "temp_apk_repack")
    os.makedirs(temp_dir, exist_ok=True)
    
    try:
        # Extract the APK
        with zipfile.ZipFile(input_apk, 'r') as zip_in:
            zip_in.extractall(temp_dir)
        
        # Repack with resources.arsc uncompressed
        with zipfile.ZipFile(output_apk, 'w', zipfile.ZIP_DEFLATED) as zip_out:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    
                    # Store resources.arsc uncompressed (compression_type=STORED)
                    if arcname == 'resources.arsc':
                        with open(file_path, 'rb') as f:
                            data = f.read()
                        zip_info = zipfile.ZipInfo(arcname)
                        zip_info.compress_type = zipfile.ZIP_STORED
                        zip_out.writestr(zip_info, data)
                        print(f"✅ Stored {arcname} uncompressed")
                    else:
                        zip_out.write(file_path, arcname, compress_type=zipfile.ZIP_DEFLATED)
        
        print("✅ APK repacked with uncompressed resources.arsc")
    finally:
        # Clean up temp directory
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

if __name__ == "__main__":
    main()