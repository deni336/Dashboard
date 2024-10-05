package server

import (
	"context"
	"fmt"
	"net"
	"time"

	"chat/pkg/datastore"
	"chat/pkg/kasugai"
	"chat/pkg/stdlog"

	"google.golang.org/grpc"
	"google.golang.org/grpc/reflection"
)

type FileTransferServer struct {
	kasugai.UnimplementedFileTransferServiceServer
	dataStore  *datastore.DataStore
	grpcServer *grpc.Server
	logger     *stdlog.Logger
}

func NewFileTransferServer(logger *stdlog.Logger, ds *datastore.DataStore) *FileTransferServer {
	return &FileTransferServer{
		dataStore: ds,
		logger:    logger,
	}
}

func (s *FileTransferServer) Start(address string) error {
	lis, err := net.Listen("tcp", address)
	if err != nil {
		return fmt.Errorf("failed to listen: %v", err)
	}

	s.grpcServer = grpc.NewServer()
	kasugai.RegisterFileTransferServiceServer(s.grpcServer, s)
	reflection.Register(s.grpcServer)

	s.logger.Info(fmt.Sprintf("File Transfer gRPC server started on: %s", address))
	return s.grpcServer.Serve(lis)
}

func (s *FileTransferServer) Stop() {
	s.logger.Info("Stopping File Transfer server...")
	stopped := make(chan struct{})
	go func() {
		s.grpcServer.GracefulStop()
		close(stopped)
	}()

	t := time.NewTimer(10 * time.Second)
	select {
	case <-stopped:
		s.logger.Info("File Transfer server stopped gracefully")
	case <-t.C:
		s.logger.Warning("File Transfer server stop timeout, forcing shutdown")
		s.grpcServer.Stop()
	}
	t.Stop()
}

func (s *FileTransferServer) InitiateFileTransfer(ctx context.Context, req *kasugai.FileMetadata) (*kasugai.Ack, error) {
	// Implement file transfer initiation logic
	s.logger.Info(fmt.Sprintf("Initiating file transfer: %s", req.Name))
	// Add your implementation here
	return &kasugai.Ack{Success: true, Message: "File transfer initiated"}, nil
}

func (s *FileTransferServer) TransferFileChunk(stream kasugai.FileTransferService_TransferFileChunkServer) error {
	// Implement file chunk transfer logic
	for {
		chunk, err := stream.Recv()
		if err != nil {
			s.logger.Error(fmt.Sprintf("Error receiving file chunk: %v", err))
			return err
		}

		// Process the received chunk
		s.logger.Info(fmt.Sprintf("Received chunk %d for file %s", chunk.ChunkNumber, chunk.FileId.Uuid))

		if chunk.IsLastChunk {
			s.logger.Info(fmt.Sprintf("File transfer completed for file %s", chunk.FileId.Uuid))
			return stream.SendAndClose(&kasugai.Ack{Success: true, Message: "File transfer completed"})
		}
	}
}

func (s *FileTransferServer) ReceiveFileMetadata(ctx context.Context, req *kasugai.Id) (*kasugai.FileMetadata, error) {
	// Implement logic to retrieve file metadata
	s.logger.Info(fmt.Sprintf("Retrieving file metadata for file %s", req.Uuid))
	// Add your implementation here
	return &kasugai.FileMetadata{}, nil
}

func (s *FileTransferServer) ReceiveFileChunks(req *kasugai.Id, stream kasugai.FileTransferService_ReceiveFileChunksServer) error {
	// Implement logic to send file chunks to the client
	s.logger.Info(fmt.Sprintf("Sending file chunks for file %s", req.Uuid))
	// Add your implementation here
	return nil
}
