# Kasugai

## TODO:

- [] Chat Server
    - [X] Listener
    - [X] Broadcaster
    - [] List of connected users (Via ip)
    - [] Timestamps and History
    - [] SSL certificate
    - [] Server Management system
    - [] Google Auth?
    - [] Unique Key for authentication
- [] Screen sharing
    - [] Listener
    - [] Front end
    - [] List  of broadcasting users
    - [] Only broadcast when user is connected
    - [] Multi-Threaded
- [] File Transfer
    - [] Multi-Threaded
    - [] P2P 
    - [] Pull info from the server (user info)
    - [X] File storage location
    - [] History (filename, size, who it came from)
- [] Chat History
    - [] Database
    - [] who, when, what
- [] Dynamic Transfer rate
    - Starting at 1024 increase bytes transfered based on time to transfer

<<<<<<< Updated upstream
python -m grpc_tools.protoc -IC:/projects/dashboard/protos --python_out=. --grpc_python_out=. C:/projects/dashboard/protos/kasugai.proto
=======
python -m grpc_tools.protoc -I. --python_out=./output --grpc_python_out=./output kasugai.proto


protoc --proto_path=. --go_out=. --go-grpc_out=. kasugai.proto
>>>>>>> Stashed changes
