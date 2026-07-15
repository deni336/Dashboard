package server

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net"
	"time"

	"chat/pkg/datastore"
	"chat/pkg/kasugai"
	"chat/pkg/stdlog"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/reflection"
	"google.golang.org/grpc/status"
)

const (
	// fileChunkSize is the size, in bytes, of each chunk streamed between clients and the server.
	fileChunkSize        = 64 * 1024
	maxFileTransferBytes = 100 * 1024 * 1024
)

type FileTransferServer struct {
	kasugai.UnimplementedFileTransferServiceServer
	dataStore  *datastore.DataStore
	grpcServer *grpc.Server
	logger     *stdlog.Logger
}

func NewFileTransferServer(logger *stdlog.Logger, ds *datastore.DataStore) *FileTransferServer {
	server := &FileTransferServer{
		dataStore: ds,
		logger:    logger,
	}
	server.grpcServer = grpc.NewServer()
	kasugai.RegisterFileTransferServiceServer(server.grpcServer, server)
	reflection.Register(server.grpcServer)
	return server
}

func (s *FileTransferServer) Start(address string) error {
	lis, err := net.Listen("tcp", address)
	if err != nil {
		return fmt.Errorf("failed to listen: %v", err)
	}

	s.logger.Info(fmt.Sprintf("File Transfer gRPC server started on: %s", address))
	return s.grpcServer.Serve(lis)
}

func (s *FileTransferServer) Stop() {
	s.logger.Info("Stopping File Transfer server...")
	if s.grpcServer == nil {
		s.logger.Warning("File Transfer server was not started")
		return
	}
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
	if req == nil || req.Id == nil || req.Id.Uuid == "" {
		return &kasugai.Ack{Success: false, Message: "Invalid file ID"}, status.Error(codes.InvalidArgument, "invalid file ID")
	}
	if req.Name == "" {
		return &kasugai.Ack{Success: false, Message: "Invalid file name"}, status.Error(codes.InvalidArgument, "invalid file name")
	}
	if req.Size < 0 || req.Size > maxFileTransferBytes {
		return &kasugai.Ack{Success: false, Message: "Invalid file size"}, status.Error(codes.InvalidArgument, "invalid file size")
	}
	if req.SenderId == nil || req.SenderId.Uuid == "" || req.RecipientId == nil || req.RecipientId.Uuid == "" {
		return &kasugai.Ack{Success: false, Message: "Invalid sender or recipient"}, status.Error(codes.InvalidArgument, "invalid sender or recipient")
	}
	if _, exists := s.dataStore.GetFileTransfer(req.Id.Uuid); exists {
		return &kasugai.Ack{Success: false, Message: "File transfer already exists"}, status.Error(codes.AlreadyExists, "file transfer already exists")
	}

	s.logger.Info(fmt.Sprintf("Initiating file transfer: %s (ID: %s, Size: %d)", req.Name, req.Id.Uuid, req.Size))
	s.dataStore.AddFileTransfer(req)
	return &kasugai.Ack{Success: true, Message: "File transfer initiated"}, nil
}

func (s *FileTransferServer) TransferFileChunk(stream kasugai.FileTransferService_TransferFileChunkServer) error {
	var fileID string
	var chunkCount int32
	var expectedChunkNumber int32
	var bytesReceived int64
	var metadata *kasugai.FileMetadata

	for {
		chunk, err := stream.Recv()
		if err == io.EOF {
			if metadata == nil {
				return status.Error(codes.InvalidArgument, "no file chunks received")
			}
			return status.Error(codes.InvalidArgument, "file transfer ended before final chunk")
		}
		if err != nil {
			s.logger.Error(fmt.Sprintf("Error receiving file chunk: %v", err))
			return err
		}

		if chunk.FileId == nil || chunk.FileId.Uuid == "" {
			return status.Error(codes.InvalidArgument, "chunk missing file ID")
		}
		if fileID == "" {
			fileID = chunk.FileId.Uuid
			var exists bool
			metadata, exists = s.dataStore.GetFileTransfer(fileID)
			if !exists {
				return status.Error(codes.NotFound, "file metadata not found")
			}
		} else if fileID != chunk.FileId.Uuid {
			return status.Error(codes.InvalidArgument, "chunk file ID changed during transfer")
		}
		if len(chunk.Data) > fileChunkSize {
			return status.Error(codes.InvalidArgument, "file chunk is too large")
		}
		if chunk.ChunkNumber != expectedChunkNumber {
			return status.Errorf(codes.InvalidArgument, "unexpected chunk number: got %d, want %d", chunk.ChunkNumber, expectedChunkNumber)
		}

		if chunk.Checksum != "" {
			sum := sha256.Sum256(chunk.Data)
			if hex.EncodeToString(sum[:]) != chunk.Checksum {
				s.logger.Error(fmt.Sprintf("Checksum mismatch for file %s, chunk %d", fileID, chunk.ChunkNumber))
				return status.Error(codes.DataLoss, "checksum mismatch")
			}
		}

		bytesReceived += int64(len(chunk.Data))
		if bytesReceived > metadata.Size {
			return status.Error(codes.InvalidArgument, "received more bytes than metadata declared")
		}

		s.dataStore.AppendFileChunk(fileID, chunk.Data)
		chunkCount++
		expectedChunkNumber++
		s.logger.Info(fmt.Sprintf("Received chunk %d for file %s", chunk.ChunkNumber, fileID))

		if chunk.IsLastChunk {
			if bytesReceived != metadata.Size {
				return status.Errorf(codes.InvalidArgument, "final byte count mismatch: got %d, want %d", bytesReceived, metadata.Size)
			}
			s.logger.Info(fmt.Sprintf("File transfer completed for file %s", fileID))
			return stream.SendAndClose(&kasugai.Ack{Success: true, Message: "File transfer completed"})
		}
	}
}

func (s *FileTransferServer) ReceiveFileMetadata(ctx context.Context, req *kasugai.Id) (*kasugai.FileMetadata, error) {
	s.logger.Info(fmt.Sprintf("Retrieving file metadata for file %s", req.Uuid))

	metadata, exists := s.dataStore.GetFileTransfer(req.Uuid)
	if !exists {
		return nil, status.Error(codes.NotFound, "file metadata not found")
	}
	return metadata, nil
}

func (s *FileTransferServer) ReceiveFileChunks(req *kasugai.Id, stream kasugai.FileTransferService_ReceiveFileChunksServer) error {
	s.logger.Info(fmt.Sprintf("Sending file chunks for file %s", req.Uuid))

	if _, exists := s.dataStore.GetFileTransfer(req.Uuid); !exists {
		return status.Error(codes.NotFound, "file metadata not found")
	}

	data, exists := s.dataStore.GetFileData(req.Uuid)
	if !exists {
		return status.Error(codes.NotFound, "file data not found")
	}

	total := len(data)
	if total == 0 {
		sum := sha256.Sum256(nil)
		return stream.Send(&kasugai.FileChunk{
			FileId:      req,
			Data:        nil,
			ChunkNumber: 0,
			IsLastChunk: true,
			Checksum:    hex.EncodeToString(sum[:]),
		})
	}

	chunkNumber := int32(0)
	for offset := 0; offset < total; offset += fileChunkSize {
		end := offset + fileChunkSize
		if end > total {
			end = total
		}

		chunkData := data[offset:end]
		sum := sha256.Sum256(chunkData)
		chunk := &kasugai.FileChunk{
			FileId:      req,
			Data:        chunkData,
			ChunkNumber: chunkNumber,
			IsLastChunk: end == total,
			Checksum:    hex.EncodeToString(sum[:]),
		}

		if err := stream.Send(chunk); err != nil {
			s.logger.Error(fmt.Sprintf("Error sending chunk %d for file %s: %v", chunkNumber, req.Uuid, err))
			return err
		}
		chunkNumber++
	}

	return nil
}
