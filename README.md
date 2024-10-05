# Kasugai

Kasugai is a distributed chat network that supports messaging, screen sharing, and dynamic file transfer. This project aims to provide a flexible and scalable communication system with additional features such as SSL, chat history, and data management.

![Kasugai Logo](images.png)

![GitHub license](https://img.shields.io/github/license/yourusername/yourrepo)
![GitHub stars](https://img.shields.io/github/stars/yourusername/yourrepo)
![GitHub issues](https://img.shields.io/github/issues/yourusername/yourrepo)

## Table of Contents
- [Features](#features)
  - [Web Client](#web-client)
  - [Chat Server](#chat-server)
  - [File Transfer](#file-transfer)
  - [Chat History](#chat-history)
  - [gRPC Code Generation](#grpc-code-generation)
  - [Python (Web Client)](#python-web-client)
  - [Go (Server)](#go-server)


## 🚀 Quickstart

1. **Clone the repository:**
    ```bash
    git clone https://github.com/deni336/Dashboard.git
    cd Dashboard
    ```

2. **Install dependencies:**
    - For Go (server):
    ```bash
    go mod tidy
    ```
    - For Python (web client)
    ```bash
    pip install -r requriements.txt
    ```

3. **Run the server:**
    ```bash
    go run main.go
    ```
4. **Start the web client:**
    ```bash
    python src/main.py
    ```
5. **Access the app:** Open your browser and navigate to `http://localhost:8008`.

## 🔥 Features
### Web Client
The client is a web-based application managed by a Python Flask server. The web interface allows users to:

- 🖱️ **Add Button Macros:** Dynamically create and manage button macros for quick actions.
- 📊 **Visualize Dynamic File Transfers:** View and track the progress of file transfers in real-time.
- 💬 **View Chat Broadcasts:** Monitor chat broadcasts based on the room you are in.
- 🛠️ **Manage Configuration:** Modify the server's configuration settings through the front-end interface.
- 🔄 **Room Management:** Switch between different rooms and view room-specific messages and broadcasts.
- 📁 **Data Management:** Allows the user to easily store large amounts of data on the fly
- 🖥️ **Screen Sharing:** Provides a way for users to view shared screens.

### Chat Server
- **Listener:** The server listens for incoming connections and manages multiple clients.
- **Broadcaster:** Broadcasts messages to all connected clients in real time.
- **Connected Users:** Displays a list of currently connected users via their IP addresses.
- **Timestamps and History:** Tracks message timestamps and stores chat history.
- 🔒 **SSL Certificate:** Secure communication with SSL certificates.
- **Server Management:** Features for managing the server, including authentication and user management.
- 🔑 **Unique Key for Authentication:** Provides unique keys for secure user authentication.

### File Transfer
- **Multi-Threaded:** Supports multiple file transfers simultaneously.
- **Peer-to-Peer (P2P):** Direct file sharing between users.
- 📂 **File Storage Location:** Allows setting a dedicated storage location for received files.
- 📜 **File History:** Tracks file transfers, including filename, size, and the sender’s identity.
#### Dynamic Transfer Rate
- ⚡ **Adaptive Transfers:** The system starts transfers at 1024 bytes and adjusts the transfer rate dynamically based on network performance.

### Chat History
- **Database Support:** Stores chat history in a database.
- 🗂️ **Detailed Tracking:** Logs who sent the message, when it was sent, and what was said.

## gRPC Code Generation
### Python (Web Client):
Generate Python gRPC code from `.proto` files:

```bash
python -m grpc_tools.protoc -I. --python_out=./output --grpc_python_out=./output kasugai.proto
```
This script is used for the web client, which communicates with the chat network backend via gRPC.

### Go (Server):
Generate Go gRPC code from `.proto` files:
```bash

protoc --proto_path=. --go_out=. --go-grpc_out=. kasugai.proto
```

## TODO:

- [] Chat Server
    - [X] Listener
    - [X] Broadcaster
    - [X] List of connected users
    - [] SSL certificate
    - [] Server Management system
    - [] Auth
    - [] Unique Key for authentication
    - [] Chat History
    - [] Database
    - [] who, when, what
- [] Screen sharing
    - [X] Listener
    - [] Front end work needs to be done for this also
    - [] List  of broadcasting users
    - [] Only broadcast when user is connected
    - [] bi-directional stream
- [] File Transfer
    - [X] bi-directional stream for dynamic file sharing
    - [] P2P 
    - [] Pull info from the server (user info)
    - [X] File storage location
    - [] History (filename, size, who it came from)

- [] Dynamic Transfer rate
    - Starting at 1024 increase bytes transfered based on time to transfer

python -m grpc_tools.protoc -I. --python_out=./output --grpc_python_out=./output kasugai.proto


protoc --proto_path=. --go_out=. --go-grpc_out=. kasugai.proto