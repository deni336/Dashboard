package main

import (
	"bufio"
	pb "chat/pkg/kasugai"
	"context"
	"flag"
	"fmt"
	"io"
	"log"
	"os"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

const (
	defaultName = "gerald"
)

var (
	addr = flag.String("addr", "localhost:6969", "the address to connect to")
	name = flag.String("name", defaultName, "Name to greet")
)

func main() {
	name := flag.String("N", "Anonymous", "")
	flag.Parse()

	conn, err := grpc.Dial(*addr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		log.Fatalf("did not connect: %v", err)
	}
	defer conn.Close()

	c := pb.NewBroadcastClient(conn)
	ctx := context.Background()

	stream, err := c.ChatService(ctx)
	if err != nil {
		fmt.Println(err)
	}

	stream.Send(&pb.MessageResponse{
		Message: *name,
	})

	waitc := make(chan struct{})
	go func() {
		for {
			msg, err := stream.Recv()
			if err == io.EOF {
				close(waitc)
				return
			} else if err != nil {
				panic(err)
			}
			fmt.Println(": " + msg.Message)
		}
	}()

	fmt.Println("Connection established, type \"quit\" or use ctrl+c to exit")
	scanner := bufio.NewScanner(os.Stdin)
	for scanner.Scan() {
		msg := scanner.Text()
		if msg == "quit" {
			err := stream.CloseSend()
			if err != nil {
				panic(err)
			}
			break
		}

		err := stream.Send(&pb.MessageResponse{
			Message: msg,
		})
		if err != nil {
			panic(err)
		}
	}

	<-waitc
}
