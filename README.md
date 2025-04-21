# Kasugai

Kasugai is a distributed chat network that supports messaging, screen sharing, and dynamic file transfer. This project provides a flexible, scalable, and secure communication system featuring OAuth-based authentication, encrypted chat history, and asynchronous message processing.

## Table of Contents
- [Features](#features)
  - [Web Client](#web-client)
  - [Chat Server](#chat-server)
  - [File Transfer](#file-transfer)
  - [Chat History](#chat-history)
  - [Authentication](#authentication)
  - [Asynchronous Processing](#asynchronous-processing)
- [Configuration](#configuration)
- [🚀 Quickstart](#%F0%9F%9A%80-quickstart)
- [gRPC Code Generation](#grpc-code-generation)
- [Testing](#testing)
- [Roadmap](#roadmap)

## 🔥 Features

### Web Client
The client is a Python Flask application providing a responsive web interface. It includes:
- 🖱️ **Dynamic Button Macros:** Create and manage quick‑action buttons via the UI.  
- 📊 **Real‑Time File Transfer Visualization:** Track progress of file uploads/downloads.  
- 💬 **Live Chat Broadcast:** View and send messages to current rooms.  
- 🛠️ **Configuration Management:** Update server settings through the front end.  
- 🔄 **Room & Session Management:** Create, join, and switch between chat rooms.  
- 🖥️ **Screen Sharing:** Peer‑to‑peer bi‑directional streaming of desktop sessions.

### Chat Server
- **Multi‑Threaded Listener & Broadcaster:** Handles gRPC streams for text and media in parallel.  
- **Connected Users Directory:** Displays active participants.  
- 🔒 **SSL/TLS Support:** Secure transport for gRPC (TLS) and HTTPS (Flask).  
- 💼 **Factory Pattern Initialization:** Modular startup of server components.  
- 🔑 **OAuth Authentication:** Google OAuth via `AuthManager` for secure user login.

### File Transfer
- **Bi‑Directional Streaming:** Efficient chunked transfers over gRPC.  
- 📂 **Custom Storage Paths:** Configure file storage location via `config.ini`.  
- 🏷️ **Transfer History:** Logs file metadata and transfer rates dynamically.

### Chat History
- **MongoDB Persistence:** NoSQL storage for encrypted message documents.  
- 🔐 **Fernet Encryption:** Messages encrypted at rest with per‑instance key.  
- 📈 **Indexed Timestamps:** Fast, time‑ordered retrievals via MongoDB indexes.

### Authentication
- **AuthManager Module:** Centralizes OAuth client setup and route protection.  
- **Session Management:** Secure session cookies with Flask secret key.

### Asynchronous Processing
- **MessageProcessor Class:** Batches and queues incoming messages via `asyncio.Queue`.  
- ⚡ **Batch Streaming:** `receive_text_message_batches()` reduces network overhead and latency.

## Configuration
All settings are stored in `~/<home>/Kasugai/config.ini`. Key sections include:
```ini
[WebServer]
port = 8000
address = localhost

[Database]
mongo_uri = mongodb://localhost:27017
mongo_db = kasugai
mongo_collection = chat_history
encryption_key =  # auto‑generated on first run

[Logging]
path = kasugai/logs/
loglevel = INFO

[FileTransfer]
avail =
uploadfolder = kasugai/resources/

[Application]
clientid = YOUR_GOOGLE_CLIENT_ID
clientsecret = YOUR_GOOGLE_CLIENT_SECRET
```

## 🚀 Quickstart

1. **Clone the repository**
   ```bash
    git clone https://github.com/yourusername/yourrepo.git
    cd yourrepo
    ```  
2. **Install prerequisites**
   - Python 3.8+ & pip:  
    ```bash
    pip install -r requirements.txt  # includes Flask, Flask‑SocketIO, PyMongo, cryptography, authlib, gRPC
    ```  
   - Go (for server):  
    ```bash
    go mod tidy  # fetches dependencies for the gRPC server
    ```  
3. **Configure**
   - Copy `config.ini` to `~/<home>/Kasugai/` (auto‑created on first run).  
   - Fill in Google OAuth credentials under `[Application]`.
4. **Run the server** (gRPC + health):  
   ```bash
    go run main_server.go  # or equivalent entry point
    ```  
5. **Start the web client**:  
   ```bash
    python src/main.py
    ```  
6. **Access**: Open `http://localhost:8000` in your browser.

## gRPC Code Generation

### Python (Web Client)
```bash
python -m grpc_tools.protoc -I. --python_out=./src --grpc_python_out=./src kasugai.proto
```  
### Go (Server)
```bash
protoc --proto_path=. --go_out=. --go-grpc_out=. kasugai.proto
```

## Testing
- **Unit Tests**: Run Python tests with:
  ```bash
    pytest tests/  # includes test_factory.py, test_auth_manager.py, etc.
    ```
- **Integration Tests**: Use Docker Compose (future).

## Roadmap
- [ ] Complete SSL/TLS server certificate support.  
- [ ] Add user management dashboard.  
- [ ] P2P file transfer enhancements.  
- [ ] Automated deployment via Docker & Kubernetes.

---

*Kasugai © 2025 – deni336*


