package main

// import (
// 	pb "chat/pkg/grpc"
// 	"context"
// 	"flag"
// 	"fmt"
// 	"log"

// 	"google.golang.org/grpc"
// 	"google.golang.org/grpc/credentials/insecure"
// )

// const (
// 	defaultName = "gerald"
// )

// var (
// 	addr = flag.String("addr", "localhost:6969", "the address to connect to")
// 	name = flag.String("name", defaultName, "Name to greet")
// )

// func main() {
// 	//name := flag.String("N", "Anonymous", "")
// 	flag.Parse()
// 	//m := []*pb.MsgPayload{}
// 	conn, err := grpc.Dial(*addr, grpc.WithTransportCredentials(insecure.NewCredentials()))
// 	if err != nil {
// 		log.Fatalf("did not connect: %v", err)
// 	}
// 	defer conn.Close()

// 	c := pb.NewBroadcastClient(conn)
// 	ctx := context.Background()
// 	handleChat(ctx, c)

// 	log.Printf("Grabbing chat stream\n")
// 	stream, err := c.ChatStream(ctx, &pb.MsgPayload{Message: "Hello World"})
// 	if err != nil {
// 		log.Fatalf("client.ListFeatures failed: %v", err)
// 	}

//a := stream.RecvMsg(&pb.MsgPayload{Message: "Hello World"})
// if err != nil {
// 	fmt.Println(err)
// }
// fmt.Println(a)
// fmt.Println(stream)

// waitc := make(chan struct{})
// go func() {
// 	for {
// 		msg, err := stream.Recv()
// 		if err == io.EOF {
// 			close(waitc)
// 			return
// 		} else if err != nil {
// 			panic(err)
// 		}
// 		m = append(m, msg)
// 		fmt.Println(": " + msg.Message)
// 	}
// }()

// for _, note := range m {
// 	if err := stream.SendMsg(note); err != nil {
// 		log.Fatalf("client.RouteChat: stream.Send(%v) failed: %v", note, err)
// 	}
// }

//fmt.Println("Connection established, type \"quit\" or use ctrl+c to exit")
//scanner := bufio.NewScanner(os.Stdin)
// for scanner.Scan() {
// 	msg := scanner.Text()
// 	if msg == "quit" {
// 		err := stream.CloseSend()
// 		if err != nil {
// 			fmt.Println(err)
// 		}
// 		break
// 	}

// 	err := stream.SendMsg(&pb.MsgPayload{
// 		Name:      "Bob",
// 		Message:   msg,
// 		Timestamp: time.Now().Format("02-02-1992"),
// 	})
// 	if err != nil {
// 		fmt.Println(err)
// 	}
// }

//stream.CloseSend()
//<-waitc
//}

// func handleChat(ctx context.Context, c pb.BroadcastClient) {
// 	atvusrs, err := c.ChatService(ctx, &pb.MsgPayloadRequest{})
// 	if err != nil {
// 		fmt.Println(err)
// 	}
// 	fmt.Println(atvusrs)
// }
